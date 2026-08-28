#!/usr/bin/env python3
"""Per-episode UNRESOLVED queue — the human rung of the deterministic → LLM → human ladder,
for the subtitle path.

`glossary_acquire.py` already implements that ladder properly: candidates the deterministic
gates cannot settle become `flagged`, and `--review` walks them with their evidence attached.
The subtitle path had no equivalent. Repair increments `skipped_no_ref` and `rejected` and
continues; punctuation restoration records `restore_empty` and leaves the old text in place.
Each is a *safe* fallback, and each is invisible: `common.llm_chat()` returns "" on every
transport failure, so a dead endpoint produces a clean-looking run with a slightly higher
counter. The actual ladder was:

    rules -> bounded LLM -> keep old text / increment a counter

This module supplies the missing arrow. It records WHAT could not be settled, WHY, and the
evidence a human needs to settle it — so a model refusal, a dead endpoint and a missing
reference stop being the same silent no-op.

It also records what WAS settled without anyone checking the meaning. `repair.accept_repair`
states the acceptance bar in its own docstring and then says plainly that nothing below it
enforces that: `factory -> needle` and `VIVRA card -> Vivi card` both pass every gate. An
accepted repair is therefore a decision no code has checked, and the `repair_applied` stage
is where it waits for someone who can. Measured over 45 of them (2026-08-27): 4 outright
regressions and 5 more needing correction -- 36 of 45 clean, none of the nine reachable by
any check in this pipeline.

PER-STAGE, not one flat queue: the triage action differs by stage. A repair rejection needs
the fansub reference checked; a punctuation failure needs the run read; they are not
interchangeable, and a flat queue destroys the signal that says which to do.

Deliberately NOT covered yet: the hallucination `flag`. `maybe_silence` fires on 67% of real
cards (measured over 20,292), so queuing it would bury the operator in ~13,000 entries per
20,000 cards. A queue nobody can face is worse than no queue.

That deferral is tied to a specific future item: the liveness counters showed `music` AND
`repetition` both activate ZERO times, while `maybe_silence` activates on two thirds of
everything. All three are hallucination-gate rules that need re-thresholding together, and
the queue's hallucination stage should be added in that same pass — the right threshold is
what decides whether the entries are worth a human's attention at all.

Contract, mirroring qc.write: this is OBSERVABILITY. It must never raise and never fail an
episode that otherwise generated correctly. Every entry point returns a bool.
"""

import json
import os
import tempfile

import decisions
from common import SIDECAR_MODE, out_for

# Imported as a NAME so the CLI resolves a show exactly the way the store and the mux gate
# do. decisions.py imports only stdlib, so this cannot cycle back through here.
from decisions import show_for

SUFFIX = ".dubtitles.unresolved.jsonl"

# Reasons, per stage. Kept as a module constant so the --review CLI and the call sites cannot
# drift apart, and so a typo'd reason is visible rather than silently creating a new bucket.
REASONS = {
    "repair": (
        "no_reference",  # no fansub anchor overlapped this card's source window
        "rejected_guard",  # the model proposed an edit; accept_repair() refused it
        "rejected_name_invented",  # the model substituted a proper noun that is in
        # neither the glossary nor the original -- the phonetic name guard refused it
        "decision_unfittable",  # [S-4] a HUMAN verdict whose text cannot be displayed on
        # this card. C1 holds timing immutable, so the ASR text stands -- and the reviewer
        # is told, because a decision that disappears silently is the failure this whole
        # loop exists to prevent. The only reason here that is about the human, not the model.
        "llm_empty",
    ),  # the backend returned nothing (transport failure or timeout)
    "punctuation": (
        "llm_empty",  # ditto -- a dead endpoint looks exactly like "no change"
        "rejected_guard",
    ),  # accept_restoration() found the model rewrote words
    "repair_applied": ("accepted",),  # accept_repair ADMITTED this repair -- see the docstring
}

# The queue a reviewer opens by default. Keyed on (stage, reason), not reason alone, because
# "rejected_guard" belongs to BOTH `repair` and `punctuation`.
#
# Two different reasons for what is left out, and they must not be confused:
#
#   NOT ACTIONABLE per line. `no_reference` is mostly "this release has no fansub" -- true,
#   and one fact about the release rather than N facts about N cards. `llm_empty` is a dead
#   endpoint, likewise one fact about the run. Measured: ~25 primary entries per episode
#   against ~86 recorded, and this module already refuses to queue the hallucination flag on
#   the same grounds -- "a queue nobody can face is worse than no queue."
#
#   NO VERDICT TO GIVE. `punctuation`/`rejected_guard` records `original_text` AND
#   `proposed_text` (punctuation.py:290-296) -- the identical two-text shape as the repair
#   rejection that IS included, and just as judgeable by reading them. An earlier version of
#   this comment claimed otherwise; that was false and an adversarial review caught it. The
#   real bar is that a reviewer's verdict has nowhere to go. accept_restoration() is not a
#   judgement gate like accept_repair(): it is word-identity (punctuation.py:134-144), so a
#   rejection means the model CHANGED A WORD, and applying it anyway breaks _apply()'s stated
#   precondition that "past the guard the correspondence is exact" -- tokens would misalign
#   across the run. Of the four verdicts only `reject` is implementable; `accept`/`force`
#   are not, and `correct` only for text of identical token count. Restoration also runs on
#   the word list BEFORE reflow (generate.py:944-951) while repair runs on cards after it,
#   so [S-5]'s card write-back cannot apply a punctuation decision at all -- that needs a
#   TEXT-tier replay.
#
#   OWNER DECISION 2026-08-27: widening waits until there is a way to ACT on a punctuation
#   review, not merely display one. Until then those entries stay reachable through the
#   unfiltered walk and the --review CLI. The per-episode volume has never been measured;
#   the only sample is the 7 live rejections behind _split_dashes (punctuation.py:80-85),
#   3 of which were false rejections from a guard bug -- found from the QC event channel,
#   which already carries both texts, not from this queue.
PRIMARY = (
    ("repair_applied", "accepted"),
    ("repair", "rejected_guard"),
    ("repair", "rejected_name_invented"),
    # [S-4]. In PRIMARY because it is the reviewer's OWN decision coming back refused: left
    # out of the default view, their verdict would vanish silently, which is precisely what
    # the entry was written to prevent. Unlike the punctuation entries held out above, this
    # one is actionable per line -- the answer is shorter text.
    ("repair", "decision_unfittable"),
)


def path_for(stem: str) -> str:
    return out_for(stem + SUFFIX)


def items(stem: str) -> list:
    """Every entry, resolved and pending. Returns [] rather than raising.

    JSONL, one entry per line. A trailing partial line -- the only thing a crash mid-append
    can produce -- is skipped, so a torn write costs the last entry rather than the file."""
    out = []
    try:
        with open(path_for(stem), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue  # torn final line; everything before it is intact
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        return []
    return out


def pending(stem: str, primary_only: bool = False) -> list:
    """Unresolved entries; with ``primary_only``, only those worth a human's attention.

    The filter lives here, not in the caller, so the review UI and the --review CLI cannot
    disagree about what "the queue" means -- the same reason REASONS is a module constant."""
    out = [e for e in items(stem) if not e.get("resolved")]
    if primary_only:
        out = [e for e in out if (e.get("stage"), e.get("reason")) in PRIMARY]
    return out


CONF_SUFFIX = ".dubtitles.conf.json"


def live_only(stem: str, entries: list) -> list:
    """The entries still describing a line this episode actually contains.

    A re-transcription replaces conf.json, and every queue entry written against the old
    text is then about something that no longer exists: nothing will re-queue it, so nothing
    will ever resolve it. Measured on the live library 2026-08-27 -- 6,364 One Pace entries
    orphaned this way, against 0 that still matched.

    FAILS OPEN, and deliberately opposite to the mux gate. Without conf.json neither can
    tell an orphan from a live entry, and there the cost of guessing wrong is shipping an
    unreviewed repair, so it holds everything; here the cost is hiding a question a human
    could have answered, so it shows everything. Same ignorance, opposite safe direction.

    Shared with mux.held_for_review rather than reimplemented -- two answers to "is this
    entry still live" would drift, and the drift would be invisible until a reviewer was
    shown a queue the gate disagreed with."""
    try:
        with open(out_for(stem + CONF_SUFFIX), encoding="utf-8") as f:
            live = {decisions.key(c.get("text", "")) for c in json.load(f) if isinstance(c, dict)}
    except (OSError, ValueError, TypeError):
        return list(entries)
    return [e for e in entries if decisions.key(e.get("original_text", "")) in live]


def card_starts(stem: str) -> dict:
    """Every line this episode contains, mapped to the card start times it appears at.

    A queue entry carries no timing: repair.py records original_text and proposed_text, and
    an accepted repair records neither source_start nor source_end. So the timestamp a
    reviewer needs to scrub to the line and hear it is DERIVED here from conf.json rather
    than stored -- which is why the 682 entries already queued get one with no backfill, and
    why a re-transcription cannot leave a stale time behind.

    A LIST per line, not one time. The same sentence can be on several cards, and repair.py's
    duplicate-pair suppression makes those ONE queue entry -- so the reviewer is owed all of
    the places it is, not an arbitrary first.

    CARD start, not source_start: the reviewer is seeking to a card they will read on screen,
    not to the window the anchor logic searched.

    Keyed on decisions.key, the same identity live_only matches on, so the two cannot
    disagree about which entry describes which card. Returns {} rather than raising."""
    out: dict = {}
    try:
        with open(out_for(stem + CONF_SUFFIX), encoding="utf-8") as f:
            cards = json.load(f)
        for c in cards:
            if not isinstance(c, dict):
                continue
            out.setdefault(decisions.key(c.get("text", "")), []).append(float(c.get("start", 0.0)))
    except (OSError, ValueError, TypeError):
        return {}
    return out


def _rewrite(stem: str, doc: list) -> bool:
    """Whole-file replace, used only by resolve(). Atomic via temp + os.replace."""
    path = path_for(stem)
    d = os.path.dirname(path) or "."
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for e in doc:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.chmod(tmp, SIDECAR_MODE)
        os.replace(tmp, path)
        return True
    except (OSError, ValueError):
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def record(stem: str, stage: str, reason: str, **fields) -> bool:
    """Append one unresolved case. Extra fields are the evidence for triage — for repair that
    is original_text/proposed_text/source_start/source_end/avg_logprob; for punctuation the
    run's text. `proposed_text` matters most: today a rejected repair discards what the model
    said, which is exactly what a human needs to judge whether the guard was right."""
    entry = {"stage": stage, "reason": reason, "resolved": False}
    entry.update({k: v for k, v in fields.items() if v is not None})
    path = path_for(stem)
    try:
        # O(1) append. The array version re-read and re-wrote the whole file per card --
        # O(n^2) I/O, and one CIFS round-trip each, on a path that fires ~86x per episode.
        exists = os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if not exists:
            os.chmod(path, SIDECAR_MODE)  # only the creator sets the mode
        return True
    except (OSError, ValueError):
        return False


def resolve(stem: str, index: int, accept: bool, note: str = "") -> bool:
    """Mark one entry reviewed. The entry KEEPS its evidence: this file is the audit trail,
    not a worklist that shrinks. Mirrors glossary_acquire.record_decision, where a human
    rejection is itself durable information (it stops the next sweep re-proposing it)."""
    doc = items(stem)
    if not (0 <= index < len(doc)):
        return False
    doc[index]["resolved"] = True
    doc[index]["accepted"] = bool(accept)
    if note:
        doc[index]["note"] = note
    return _rewrite(stem, doc)


def resolve_many(stem: str, updates: list) -> bool:
    """Mark several entries reviewed in ONE rewrite. `updates` is [(index, accept, note)].

    resolve() re-reads and re-writes the whole file per call. That is fine for the --review
    CLI, which settles one line at a time, and wrong for the review page, where a reviewer
    hands back thirty verdicts at once: thirty rewrites over CIFS, and -- because the server
    is threaded -- thirty read-modify-write windows in which two open tabs lose each other's
    entries.

    ALL OR NOTHING on a bad index. A caller that miscounted would otherwise land some
    verdicts and not others, with nothing telling the reviewer which."""
    doc = items(stem)
    if any(not (0 <= i < len(doc)) for i, _a, _n in updates):
        return False
    for index, accept, note in updates:
        doc[index]["resolved"] = True
        doc[index]["accepted"] = bool(accept)
        if note:
            doc[index]["note"] = note
    return _rewrite(stem, doc)


# --- review CLI ---------------------------------------------------------------------------
# Mirrors glossary_acquire.py's --review: walk what the automation could not settle, show the
# evidence that stage's triage actually needs, record the decision. Unified walk, stage-keyed
# storage -- one pass for the operator, but a repair entry still arrives with its reference
# and a punctuation entry with its run.

_EVIDENCE = {
    # what a human needs to see to settle each reason, in the order it helps
    "no_reference": ("original_text", "source_start", "source_end", "avg_logprob"),
    "rejected_guard": ("original_text", "proposed_text", "reference", "avg_logprob", "words"),
    "rejected_name_invented": ("original_text", "proposed_text", "reference", "avg_logprob", "words"),
    "llm_empty": ("original_text", "segments", "words"),
    # The repair was APPLIED. The reviewer's whole job is comparing these two texts.
    "accepted": ("original_text", "proposed_text", "avg_logprob"),
    # The reviewer's own verdict, refused on timing. They need both texts to shorten it.
    "decision_unfittable": ("original_text", "proposed_text", "avg_logprob"),
}


def _render(i: int, e: dict) -> str:
    head = f"[{i}] {e['stage']}/{e['reason']}"
    lines = [head, "-" * len(head)]
    for k in _EVIDENCE.get(e["reason"], ()):
        if k in e:
            lines.append(f"  {k:14} {e[k]}")
    for k, v in e.items():  # anything not in the template, so nothing hides
        if k not in ("stage", "reason", "resolved", "accepted", "note") and k not in _EVIDENCE.get(e["reason"], ()):
            lines.append(f"  {k:14} {v}")
    return "\n".join(lines)


# What a CLI answer MEANS, per stage. "keep as-is" is about the CARD, not the proposal, and
# the card shows different things depending on why the entry was queued:
#
#   repair_applied/accepted -- the repair SHIPPED, so the card shows it. Keeping it as-is
#       endorses the repair (`accept`); needing fixing rejects it.
#   repair/rejected_guard, rejected_name_invented -- the repair was REFUSED, so the card
#       shows the ASR text. Keeping it as-is endorses the refusal (`reject` of the
#       proposal); needing fixing says the ASR is wrong and the refused proposal should
#       stand, which is `force`.
#
# Recording `reject` for a "needs fixing" on both stages would silently invert the
# reviewer's meaning on half of them.
_CLI_VERDICT = {
    ("repair_applied", "accepted"): {"k": "accept", "f": "reject"},
    ("repair", "rejected_guard"): {"k": "reject", "f": "force"},
    ("repair", "rejected_name_invented"): {"k": "reject", "f": "force"},
    ("repair", "decision_unfittable"): {"k": "reject", "f": "reject"},
}


def _record_verdict(stem: str, e: dict, ans: str, note: str) -> bool:
    """Persist the CLI's answer as a real verdict. True when it is safely stored.

    Returns True for an entry there is nothing to store -- `no_reference` and `llm_empty`
    carry no proposal, so they have no pair to key on and were never decisions in the first
    place. False means a verdict was WANTED and could not be written, which must stop the
    entry being marked resolved: a review that silently discards the human's decision is
    worse than one that errors, because the human believes the line is settled."""
    verdict = _CLI_VERDICT.get((str(e.get("stage", "")), str(e.get("reason", ""))), {}).get(ans)
    if not verdict or not e.get("proposed_text"):
        return True
    show = show_for(stem)
    if not show:
        print("  NOT SAVED: cannot resolve a show for this episode — check GLOSSARY_DIR")
        return False
    ddir = decisions.DECISIONS_DIR
    store = decisions.record(decisions.load(show, ddir), e.get("original_text", ""), e["proposed_text"], verdict, note=note)
    if not decisions.save(store, show, ddir):
        print(f"  NOT SAVED: the verdict for this line could not be written to {ddir}")
        return False
    print(f"  recorded {verdict} for {show}")
    return True


def main(argv=None):
    import argparse
    import glob as _glob

    ap = argparse.ArgumentParser(description="Review subtitle-quality cases the pipeline could not settle.")
    ap.add_argument("target", help="an episode stem, or a directory to walk")
    ap.add_argument("--review", action="store_true", help="interactive walk (default: list pending and exit)")
    a = ap.parse_args(argv)

    stems = (
        [a.target]
        if os.path.exists(a.target + SUFFIX)
        else [p[: -len(SUFFIX)] for p in sorted(_glob.glob(os.path.join(a.target, "**", "*" + SUFFIX), recursive=True))]
    )
    total = 0
    for stem in stems:
        todo = pending(stem)
        if not todo:
            continue
        print(f"\n=== {os.path.basename(stem)}  ({len(todo)} pending) ===")
        for e in todo:
            idx = items(stem).index(e)
            print(_render(idx, e))
            total += 1
            if not a.review:
                continue
            try:
                ans = input("  keep as-is [k] / needs fixing [f] / skip [s] ? ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  stopped.")
                return 0
            if ans in ("k", "f"):
                note = input("  note (optional): ").strip()
                # The VERDICT first, then the flag. The verdict is what repair.py consults
                # and what the mux gate treats as the hold's authority; the flag only empties
                # this queue. Marking the entry resolved on an unsaved verdict would hide the
                # loss from the next walk, which is the one place it would still be visible.
                if _record_verdict(stem, e, ans, note):
                    resolve(stem, idx, accept=(ans == "k"), note=note)
    print(f"\n{total} pending across {len(stems)} episode(s)." if total else "\nNothing pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
