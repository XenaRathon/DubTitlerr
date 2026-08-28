#!/usr/bin/env python3
"""ADDITIVE glossary mining. For one show: load its existing dictionary (if any), mine the
NEW (not-yet-dubtitled) episodes' embedded English subtitles for recurring proper nouns
(character/place names — the official spellings), and ADD any new ones to the dictionary.
Never rebuilds from scratch: curated names, hard_fixes and a curated initial_prompt are
preserved; mining only appends. Runs BEFORE generate (in gen_loop) so the grown dictionary
applies to the very episodes being transcribed, and grows again whenever new episodes appear.

CPU only (ffmpeg + pysubs2). Env: GLOSSARY_DIR (default /config/glossaries),
MINE_MIN_COUNT (a name must recur >= this across the new episodes, default 3).
Built with help of Claude (Anthropic).
"""

import json
import os
import re
import subprocess
import sys
import tempfile

import pysubs2

from common import is_our_track, load_extras, stream_title

EXTRA_DIRS = load_extras()  # data/extras.txt is the source (see common.load_extras)

GLOSS_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")
MIN_COUNT = int(os.environ.get("MINE_MIN_COUNT", "3"))
SKIP_FILE_RE = re.compile(r"\bNC(ED|OP|BD)\b|-\s*scene\b|creditless", re.I)
# words that are capitalized for position/grammar, not proper nouns — never mine these.
# V2 C8: sourced from data/common_proper_noun_deny.txt (one word per line, # comments
# allowed) so the deny-list can be tuned without a code change; falls back to this exact
# inline set if the file is missing/unreadable (backward-compatible).
_COMMON_FALLBACK = """the a an and or but of to in on at is was are were be been being have has had do does did
will would can could should shall may might must i you he she it we they me him her us them my your his
her its our their this that these those with from for not no nor yes all out up down here there then now
what who whom whose when where why how which while because if so as than too very just only even still
oh ah hey hmm well yeah yes okay ok hello goodbye please thank thanks sorry sir madam mister missus doctor
get got go going gone come came see saw seen know knew known think thought say said tell told want need
make made take took give gave find found let look looked good bad great little big small new old one two
three four five six seven eight nine ten first last next every some any many much more most right left
wait stop help yes mom dad mother father brother sister friend everyone someone something nothing
today tomorrow yesterday day night morning time year hand way thing people man woman boy girl
master lady lord king queen captain general doctor mister""".split()


def _load_common(path: str = "data/common_proper_noun_deny.txt") -> set:
    try:
        with open(path, encoding="utf-8") as f:
            words = {ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")}
    except OSError:
        words = set()
    return words or set(_COMMON_FALLBACK)


COMMON = _load_common()


def eng_sub_text(video):
    """Return plaintext of the video's English (or und) ASS/SSA/SRT subtitle, or ''.

    Our own previously-muxed dubtitle (common.is_our_track) is excluded: this selector
    bypasses common.eng_sub_streams(), so it needs the same guard, otherwise a
    regeneration would re-mine last version's spellings out of its own output and
    reinforce its errors into the glossary. No fallback — a file whose only English sub
    is our dubtitle mines nothing."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_entries",
                "stream=index,codec_name:stream_tags=language,title",
                "-of",
                "json",
                # NO -nostdin. That is an ffmpeg option; ffprobe has no such flag and takes
                # the NEXT argument -- the video path -- as its value, then exits 1 with an
                # empty stdout. json.loads("") raised straight into the handler below, so
                # this returned "" for every file on every show, and the miner's summary
                # ("0 new ep(s), no new terms") read exactly like a normal no-op. Found
                # 2026-08-28 on Sword Art Online: two English fansub tracks per episode,
                # nothing mined, no glossary -- and with no glossary decisions.show_for
                # returns "", so the show gets no decision store and the review page refuses
                # every verdict. stdin=DEVNULL below is what actually keeps ffprobe off the
                # terminal; the flag was never doing that job.
                video,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as exc:
        # SAID, not swallowed. "" is the right answer for a release with no fansub track,
        # and that is common -- but a broken probe must not be indistinguishable from it.
        # Silence is how a wrong argument list ran against the whole library unnoticed.
        print(f"mine: could not read subtitle streams from {video}: {exc}")
        return ""
    cand = [
        s
        for s in streams
        if ((s.get("tags") or {}).get("language") or "").lower() in ("eng", "en", "und", "")
        and s.get("codec_name") in ("ass", "ssa", "subrip")
        and not is_our_track(stream_title(s))
    ]
    if not cand:
        return ""
    idx = cand[0]["index"]
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "s.ass")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", video, "-map", f"0:{idx}", out],
            capture_output=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
        if not os.path.exists(out):
            return ""
        try:
            subs = pysubs2.load(out)
        except Exception:
            return ""
        return "\n".join(ev.plaintext for ev in subs if not ev.is_comment)


REVIEW_REASON = "possessive_floor_crossing"
# A trailing possessive: ASCII apostrophe or U+2019, then "s". chr(0x2019) is BUILT, never
# typed as a literal -- a curly apostrophe pasted into this repo's source has been silently
# normalised to ASCII before, which disables the guard while leaving a passing-looking test.
_POSS_RE = re.compile("['" + chr(0x2019) + "]s$")


def _fold(w):
    """Strip a trailing possessive 's / U+2019s. Every other word comes back unchanged,
    including internal-apostrophe names (Kin'emon, D'Arby) and a bare trailing quote."""
    return _POSS_RE.sub("", w)


def mine_text(text, bare, poss, midsentence, forms=None):
    """Count capitalized proper-noun candidates into TWO lanes and track which appear
    MID-sentence (not just sentence-initial, where any word is capitalized).

    `bare` counts the plain form, `poss` the possessive one. Before D5 the ^[A-Z][a-z]{3,}$
    test ran against a core that still carried its `'s`, so `Brownbeard's`/`Vegapunk's` matched
    nothing and were counted as NEITHER form -- the evidence was split and then discarded.

    Possessives are never merged into `bare` and never added to `midsentence`. Both gates on
    the auto-append lane (the count floor and the mid-sentence requirement) therefore see
    exactly what they saw before this change, which is what makes the fold safe without an
    English-dictionary gate: possessive evidence can REINFORCE a candidate but can never
    ORIGINATE one. admit() reads the second lane.

    `forms` (optional) collects the SURFACE spellings behind each folded key --
    {folded: {surface: count}} -- so a consumer can show a reviewer the evidence a term
    was escalated on rather than a bare number. Purely observational: no admission rule
    reads it, and it exists here rather than in the caller so there is exactly one
    tokeniser and one fold in the repo (D3a needs the forms; task 13)."""
    for sent in re.split(r"[.!?…]+|\n", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]{2,}", sent)
        for i, w in enumerate(words):
            core = w.strip("'’-")
            folded = _fold(core)
            if not re.match(r"^[A-Z][a-z]{3,}$", folded):
                continue
            if forms is not None:
                seen = forms.setdefault(folded, {})
                seen[core] = seen.get(core, 0) + 1
            if folded != core:  # possessive: reinforces, never originates
                poss[folded] = poss.get(folded, 0) + 1
                continue
            bare[core] = bare.get(core, 0) + 1
            if i > 0:  # not the first word of the sentence
                midsentence.add(core)


def admit(bare, poss, midsentence, min_count=None, common=None, existing=frozenset()):
    """Two-lane admission -> (new_names, review_queue).

        bare >= min_count                              -> auto-append (unchanged behaviour)
        bare <  min_count and bare + poss >= min_count  -> review queue, REVIEW_REASON

    Possessive evidence may raise a candidate into VISIBILITY; it may never raise one into
    the glossary unattended. Deliberately NO English-dictionary gate on this path: 13 of this
    show's 81 glossary names are dictionary words (Brook, Robin and Chopper are Straw Hats),
    so a gate would make 16% of the cast permanently unmineable -- trading a false positive
    for a systematic false negative on the names that matter most.

    The mid-sentence requirement gates BOTH lanes, as it always has: without it every
    sentence-initial word would queue for review."""
    min_count = MIN_COUNT if min_count is None else min_count
    common = COMMON if common is None else common
    new, queue = [], {}
    for t in sorted(midsentence):
        if t.lower() in common or t.lower() in existing:
            continue
        b, p = bare.get(t, 0), poss.get(t, 0)
        if b >= min_count:
            new.append(t)
        elif b + p >= min_count:
            queue[t] = {"reason": REVIEW_REASON, "bare": b, "possessive": p}
    return new, queue


def mine(text, min_count=None, common=None, existing=frozenset()):
    """mine_text + admit over one block of text -> (new_names, review_queue)."""
    bare, poss, mid = {}, {}, set()
    mine_text(text, bare, poss, mid)
    return admit(bare, poss, mid, min_count, common, existing)


def queue_for_review(cfg, queue):
    """Record the crossing lane in the glossary's `flagged` review queue -> newly-added terms.

    Never overwrites an entry another producer (glossary_verify, glossary_acquire, or a human
    decision) wrote for the same term: the crossing lane is the weakest evidence in the file
    and must not displace a stronger reason already in front of a reviewer. Its own entries
    are refreshed, since each sweep re-counts only the not-yet-dubtitled episodes."""
    flagged = cfg.get("flagged") or {}
    added = []
    for term, meta in queue.items():
        cur = flagged.get(term)
        if isinstance(cur, str):
            cur = {"reason": cur}
        if cur and cur.get("reason") != REVIEW_REASON:
            continue
        if cur is None:
            added.append(term)
        flagged[term] = meta
    if flagged:
        cfg["flagged"] = flagged
    return sorted(added)


def main():
    if len(sys.argv) < 2:
        print("usage: mine_glossary.py <show_dir>")
        return
    show_dir = sys.argv[1].rstrip("/")
    show = os.path.basename(show_dir)
    gpath = os.path.join(GLOSS_DIR, show + ".json")
    cfg = {"show": show, "initial_prompt": "", "names": [], "hard_fixes": {}}
    if os.path.exists(gpath):
        try:
            cfg.update(json.load(open(gpath)))
        except Exception as e:
            print("mine: bad glossary, starting fresh:", e)
    existing = {n.lower() for n in cfg.get("names", [])}

    counter, poss, mid = {}, {}, set()
    mined_eps = 0
    for dp, dns, fs in os.walk(show_dir):
        dns[:] = [d for d in dns if d.lower() not in EXTRA_DIRS]
        for fn in fs:
            if not fn.lower().endswith((".mkv", ".mp4")) or SKIP_FILE_RE.search(fn):
                continue
            stem = os.path.splitext(os.path.join(dp, fn))[0]
            # only NEW episodes (no dubtitle yet) -> each episode mined exactly once, additively
            if os.path.exists(stem + ".eng.dubtitles.ass") or os.path.exists(stem + ".eng.dubtitles.srt"):
                continue
            txt = eng_sub_text(os.path.join(dp, fn))
            if txt:
                mine_text(txt, counter, poss, mid)
                mined_eps += 1

    new, queue = admit(counter, poss, mid, MIN_COUNT, COMMON, existing)
    queued = queue_for_review(cfg, queue)  # D5: the crossing lane goes to a human, never auto-appended
    if not new and not queued:
        print(f"mine[{show}]: {mined_eps} new ep(s), no new terms (dict has {len(existing)})")
        return
    cfg["names"] = cfg.get("names", []) + new
    # build a prompt from the top names only if there is no curated one
    if not cfg.get("initial_prompt"):
        top = sorted(cfg["names"], key=lambda n: -counter.get(n, 0))[:30]
        title = re.sub(r"\s*\{tvdb-\d+\}|\s*\(\d{4}\)", "", show)
        cfg["initial_prompt"] = f"This is {title}, a Japanese anime (English dub). Spell names correctly: " + ", ".join(top) + "."
    os.makedirs(GLOSS_DIR, exist_ok=True)
    with open(gpath, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")  # POSIX line: prettier flags a glossary without it
    review = f" | {len(queued)} queued for review: {queued[:5]}" if queued else ""
    print(f"mine[{show}]: +{len(new)} terms from {mined_eps} new ep(s) -> {new[:15]}{review}")


if __name__ == "__main__":
    main()
