#!/usr/bin/env python3
"""DECISION STORE — a human's verdict on a repaired line, made durable and shippable.

`repair.accept_repair` states the acceptance bar in its own docstring and then says
plainly that nothing below it enforces that. It is measured, not feared: `factory ->
needle` and `VIVRA card -> Vivi card` both pass every mechanical gate, and so does
dropping a word from `the flame flame fruit`. The enforcement is a person reading the
lines. This module is where that person's answer goes.

Keyed on the normalised ``(orig, proposed)`` TEXT PAIR, never on episode or card index.
Position does not survive a ``TEXT_VERSION`` bump and means nothing in another library;
the text does. Measured in `REVIEW-2026-08-27-unanchored-repair-45-lines.md`: `"Roger's
treasure belongs to me"` occurs in E01, E02 AND E03 with an identical fix, so one verdict
settles all three.

Sibling in role to the per-show glossary — same show-keyed naming, same intent to be
committed to git so the next person does not relitigate a call that has already been made.

Env:
  DECISIONS_DIR   default /config/decisions  (per-show store, sibling in role to
                  GLOSSARY_DIR -- a mount, so a `git pull` on the host is what makes it
                  current)
"""

import json
import os
import tempfile
import time

# The four outcomes a reviewer can reach. `force` admits a repair accept_repair refused;
# it overrides the judgement gates but never fits_card, because card timing is immutable.
VERDICTS = ("accept", "reject", "correct", "force")

DECISIONS_DIR = os.environ.get("DECISIONS_DIR", "/config/decisions")
GLOSSARY_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")
STORE_VERSION = 1


def key(text: str) -> str:
    """The match key for one side of a decision pair.

    Case and runs of whitespace are folded away: the same line re-transcribed can differ
    in both without being a different line.

    PUNCTUATION IS KEPT, deliberately. Restoring punctuation is the bulk of what this
    repair stage does, so punctuation is part of a line's identity rather than noise on
    top of it. `CP-0.` and `CP?` are a real ASR/proposal pair from the 2026-08-27 review
    -- the owner rejected that repair, and folding punctuation would let the rejection
    match the very text it was rejecting in favour of.

    The ONE punctuation exception is the apostrophe. U+2019 and U+0027 are two renderings
    of one character, not two characters: Whisper and the repair LLM each emit either, and
    English dub dialogue is mostly contractions, so this is not an edge case but most
    lines. `glossary_acquire.reduce_form` folds both for the same reason (_REDUCE_RE,
    glossary_acquire.py:33) and records the trap that comes with it -- the curly glyph
    "gets silently normalised to U+0027 by editors in this toolchain", so it is written
    here as chr(0x2019) rather than literally, or the fold would quietly stop working and
    still read correctly in review."""
    return " ".join((text or "").replace(chr(0x2019), chr(0x27)).lower().split())


def record(store: dict, orig: str, proposed: str, verdict: str, text: str = "", note: str = "", promoted=None) -> dict:
    """Append one human verdict. Returns the SAME store, mutated -- callers hold it and
    hand it to save().

    Two verdicts are refused or rewritten here rather than downstream, so that lookup has
    exactly one spelling per outcome:

    * an EMPTY side of the pair is dropped. It normalises to "" and would then match every
      card the LLM returned nothing for -- a key that broad is worse than no key.
    * a `correct` whose text restores the original IS a rejection. A reviewer reaches it by
      choosing `correct` and typing the original back, which is the same decision by a
      different route; stored as-is, the [S-4] consult would have to handle two spellings
      of one outcome, and one of them would look like a repair.
    * a `correct` with no usable text is dropped. The consult reads `d["text"]` for that
      verdict, so a missing key raises mid-episode -- against this project's never-fail-an
      -episode contract -- and a whitespace-only one renders a blank card, which is worse
      than the repair it replaced.
    * a verdict outside VERDICTS is dropped. Stored verbatim, a typo matches no branch the
      consult tests, so the line falls through to accept_repair as though it were never
      reviewed while the store claims that it was."""
    o, p = key(orig), key(proposed)
    if not o or not p:
        return store
    if verdict == "correct" and key(text) == o:
        verdict, text = "reject", ""
    if verdict == "correct" and not (text or "").strip():
        return store
    if verdict not in VERDICTS:
        return store
    # `at` is what lets a sweep tell a verdict that has NOT shipped from one that has.
    # A verdict recorded after an episode's last mux never reaches the video on its own:
    # mux.py treats the .dubtitles.done stamp as its only skip guard and nothing re-opens
    # the episode (measured 2026-08-29 -- 11 of 20 One Pace corrections were still absent
    # from the shipped track). Without a time on the entry, a sweep can only ask "has this
    # line ever been ruled on", which is true forever, so it would re-open every eligible
    # episode on every pass. Epoch float, the unit common.write_stamp records `mtime` in,
    # so the comparison against a stamp is a subtraction rather than a parse.
    # Entries written before 2026-08-29 have no `at`; lookup() and for_orig() never read
    # it, so those verdicts keep applying exactly as before.
    entry = {"orig": o, "proposed": p, "verdict": verdict, "run": "review", "at": time.time()}
    if text:
        entry["text"] = text  # the human's wording, verbatim and un-normalised
    if note:
        entry["note"] = note
    if promoted:
        entry["promoted"] = promoted
    # REPLACE, never append a second verdict for one pair. lookup() returns the first
    # match, so appending would leave a reviewer's correction written to the file, shipped
    # to git, and permanently unreachable -- the human could never change their mind. This
    # mirrors the I3/C2 invariant in `glossary_acquire.apply_proposals`
    # (glossary_acquire.py:668): every verdict clears what a prior run left for the same
    # key, "exactly the both-states bug this module exists to avoid reintroducing."
    entries = store.setdefault("decisions", [])
    for i, e in enumerate(entries):
        if e.get("orig") == o and e.get("proposed") == p:
            entries[i] = entry
            return store
    entries.append(entry)
    return store


def lookup(store: dict, orig: str, proposed: str):
    """The stored verdict for this exact pair, or None.

    BOTH sides are part of the key. Matching on `orig` alone would let a rejection of one
    proposal suppress every future proposal for that line -- including the one that fixes
    it. A miss is a no-op by design: the caller falls through to `accept_repair`, which is
    today's behaviour, rather than applying a verdict that was never given for this text."""
    o, p = key(orig), key(proposed)
    for e in store.get("decisions", []):
        if e.get("orig") == o and e.get("proposed") == p:
            return e
    return None


def path_for(show: str, dir: str = DECISIONS_DIR) -> str:
    """This show's store file. Named for the show DIRECTORY, matching `glossaries/`."""
    return os.path.join(dir, show + ".json")


def for_orig(store: dict, orig: str) -> list:
    """Every verdict recorded for this ORIGINAL line, whatever was proposed against it.

    Deliberately NOT `lookup`, and the difference matters. `lookup` requires both sides
    because APPLYING a verdict on the strength of `orig` alone would let a rejection of one
    proposal suppress every future proposal for that line, including the one that fixes it.
    This function answers a different question -- "has a human ruled on this line at all?"
    -- which is what [S-5] needs to decide whether an already-muxed episode is worth
    re-opening. It decides eligibility, never what text to write.

    That restriction is unchanged: `corrected_text` below is the write-side sibling, and it
    is where the "which wording" question is answered and bounded to `correct` verdicts."""
    o = key(orig)
    return [e for e in store.get("decisions", []) if e.get("orig") == o]


def corrected_text(store: dict, orig: str):
    """The human's own wording for this ORIGINAL line, or None. The write-side sibling of
    `for_orig`, which stays eligibility-only.

    `repair.process` consults `lookup` inside the per-card loop and only AFTER a proposal
    exists, so a card it SKIPS -- no fansub anchor, or `llm()` returned "" on a transport
    failure -- never reaches the store. It then rebuilds the srt from conf.json, shipping
    raw ASR over text a reviewer typed through `review_apply`. `lookup` cannot help there:
    it needs both sides of the pair and a skipped card has no proposal.

    Answering on the orig alone is safe for `correct` AND ONLY FOR IT. The human supplied
    the wording themselves, so it stands whatever was proposed against it. Every other
    verdict is excluded deliberately: `accept` and `force` carry the MODEL's proposal, which
    a skipped card does not have, and `reject` means the ASR text stands -- reaching a
    rejection on the orig alone is precisely the "one rejection suppresses every future
    proposal" failure `lookup`'s docstring exists to prevent.

    `record` replaces per (orig, proposed) pair, so one orig can still hold two corrections
    made against different proposals. The later one wins, by `at`. Entries written before
    2026-08-29 have no `at`; a dated correction therefore beats an undated one, and when
    two undated ones disagree this returns None rather than guessing. The caller sees a
    non-empty `for_orig` with no text and counts that as owed-but-unresolved, which is the
    outcome that must never be silent."""
    hits = [e for e in for_orig(store, orig) if e.get("verdict") == "correct" and (e.get("text") or "").strip()]
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]["text"]
    dated = [e for e in hits if isinstance(e.get("at"), (int, float))]
    if not dated:
        return None
    return max(dated, key=lambda e: e["at"])["text"]


def load(show: str, dir: str = DECISIONS_DIR) -> dict:
    """This show's store, or {} when it is absent, unreadable or corrupt.

    NEVER half-loaded. `unresolved.items()` can drop a torn final line because its format
    is one self-contained record per line; this file is a single JSON document, so a
    partial parse is not a shorter store, it is an arbitrary one. A store read as smaller
    than it is looks identical to a store with fewer verdicts, and every decision lost
    that way falls silently through to accept_repair -- the failure this module exists to
    stop. An unreadable store means today's behaviour, loudly typed as {}."""
    try:
        with open(path_for(show, dir), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def save(store: dict, show: str, dir: str = DECISIONS_DIR) -> bool:
    """Write the store atomically. Returns False rather than raising.

    Atomic via mkstemp + os.replace, mirroring `unresolved._rewrite`: a reader in
    `repair.py` sees the old file or the new one, never a partial. False is not cosmetic --
    a review that silently discards the human's verdict is worse than one that errors,
    because the human believes the line is settled and never revisits it.

    ATOMIC WRITE, NOT ATOMIC READ-MODIFY-WRITE. Two callers that both load() before either
    save()s will lose one of the two verdicts, and nothing here prevents that. The review
    server is the only writer and handles one request at a time, which is what makes this
    safe today -- if that ever stops being true this needs a lock, not a bigger docstring."""
    store["show"], store["version"] = show, STORE_VERSION
    store.setdefault("decisions", [])
    path = path_for(show, dir)
    tmp = None
    try:
        os.makedirs(dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dir, prefix=os.path.basename(path) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
        return True
    except (OSError, ValueError):
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def show_for(path: str, gloss_dir: str = GLOSSARY_DIR) -> str:
    """The show a media path belongs to, as the SAME identity the glossary file is named
    for -- the show directory's basename.

    Deliberately not `gloss["show"]`. That key is a display name: the glossary file
    `Cowboy Bebop (1998) {tvdb-76885}.json` carries `show == "Cowboy Bebop"`. Keyed on it,
    a show's decision store and its glossary would be two differently-named artifacts for
    one show, and every lookup would miss without ever erroring.

    The walk mirrors `repair.glossary_for`: an episode sits two levels below its show, so
    resolving on its own directory finds nothing. Returns "" when no ancestor has a
    glossary -- a show the pipeline does not have a dictionary for has no decisions either."""
    d = os.path.dirname(os.path.abspath(path))
    while d and d != os.path.dirname(d):
        name = os.path.basename(d)
        if os.path.exists(os.path.join(gloss_dir, name + ".json")):
            return name
        d = os.path.dirname(d)
    return ""


def decisions_for(path: str, gloss_dir: str = GLOSSARY_DIR, dir: str = DECISIONS_DIR) -> tuple:
    """``(store, show)`` for an episode path. Both are empty when nothing resolves.

    An absent DECISIONS_DIR is the pre-existing state of every install and costs nothing:
    the caller gets {} and falls through to accept_repair, which is today's behaviour."""
    show = show_for(path, gloss_dir)
    return (load(show, dir) if show else {}), show


def promote(gloss: dict, promoted: dict) -> tuple:
    """Write a term-level verdict into the show glossary. Returns ``(new_gloss, applied)``.

    Some verdicts are about a LINE and some are about a TERM. `factory -> needle` is a line
    -- it means nothing anywhere else. `Samadai -> Samurai` is a term: it belongs in
    `hard_fixes`, where `glossary.correct()` applies it show-wide and where it ships inside
    an artifact this repo already commits.

    NO RULE decides which a verdict is. The human does, at review time, and `promoted` is
    the record of what they chose -- an audit trail, never a classifier. Auto-classifying on
    a single-token difference was considered and refused: `factory -> needle` is a
    single-token difference between two ordinary English words, so the rule would promote
    show-wide the exact regression this store exists to catch.

    Deep-copies, per this repo's convention for every glossary write path
    (`glossary_acquire.apply_proposals`, `record_decision`, `revert`,
    `glossary_verify.apply_results`).

    Refuses to overwrite an entry already present, comparing keys CASE-INSENSITIVELY
    because `glossary.load_dict` lowercases every `hard_fixes` key at load -- `samadai` and
    `Samadai` are one fix downstream, and writing both leaves the file contradicting itself.
    A hand-maintained glossary outranks one reviewer's call on one line.

    `applied` is what actually landed, not what was asked for, so the decision's audit trail
    records the outcome rather than the intent."""
    g = json.loads(json.dumps(gloss))
    fixes = g.setdefault("hard_fixes", {})
    existing = {str(k).lower() for k in fixes}
    applied = {}
    for variant, canonical in (promoted or {}).get("hard_fix", {}).items():
        if not variant or not canonical or str(variant).lower() in existing:
            continue
        fixes[variant] = canonical
        # run == "review" is the marker glossary_acquire.revert refuses to delete (R4), so
        # an automated sweep can never undo what a person decided here.
        g.setdefault("acquired", {})[variant] = {"canonical": canonical, "run": "review"}
        # A human accepting a fix outranks an earlier rejection of the same spelling, the
        # same way record_decision clears it (glossary_acquire.py:800).
        if variant in g.get("known", []):
            g["known"] = [k for k in g["known"] if k != variant]
        applied[variant] = canonical
    return g, applied
