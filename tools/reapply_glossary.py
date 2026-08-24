#!/usr/bin/env python3
"""Re-apply the CURRENT glossary to episodes that were already generated and muxed.

Why this exists
---------------
``glossary.correct()`` runs at generation time (``generate.py:636``) and, for repaired
cards only, inside ``repair.py``. Nothing re-applies a glossary to an episode that is
already finished. So a ``hard_fixes`` entry added today reaches only work done after it
-- 112 ``hockey``-for-``Haki`` mishears sat in already-stamped One Pace episodes with no
path to fix them short of re-transcribing the season.

This tool closes that gap by rebuilding the subtitle from the surviving
``.dubtitles.conf.json``, which is the pipeline's own record of every card. No GPU, no
LLM, no re-transcription.

What it CANNOT do, and why
--------------------------
Card boundaries are fixed. ``conf.json`` stores ``word_probs`` -- a list of floats -- not
the word list with timings, so ``reflow()`` and ``punctuation.restore()`` cannot be
re-run from it. Both operate on the word list BEFORE cards are split (see
``docs/superpowers/specs/2026-08-20-punctuation-restoration-design.md``: "Splitting must
be DOWNSTREAM of the fix"). Anything that changes how text is DIVIDED needs a full
regenerate; this tool only changes what the text SAYS.

Flow per episode
----------------
1. read ``<stem>.dubtitles.conf.json``
2. ``glossary.correct()`` every card
3. if nothing changed -> leave the episode completely untouched
4. ``--apply``: rewrite conf.json, render ``<stem>.eng.dubtitles.srt``, drop the
   ``.dubtitles.done`` stamp

Step 4 stops there on purpose. Dropping the stamp with a sidecar present is exactly the
state ``merge_pass.sh`` is built to consume: it assembles signs into a ``.ass`` and
re-muxes, replacing the old Dubtitles track and writing a fresh stamp. ``generate.py``
skips episodes that already have a sidecar, so the re-transcribe path is not triggered.
Reusing that machinery beats reimplementing mux here.

Usage
-----
    reapply_glossary.py <dir-or-conf.json> [...]         # dry run, reports the diff
    reapply_glossary.py --apply <dir-or-conf.json> [...]
    reapply_glossary.py --show-lines 40 <dir>            # more sample diffs

Env: GLOSSARY_DIR (same meaning as the rest of the pipeline).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glossary  # noqa: E402
from common import MEDIA_GID, MEDIA_UID, STAMP_SUFFIX, read_words, ts_srt  # noqa: E402

CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"
GLOSSARY_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")


def show_for(stem: str) -> str:
    """The show directory name owning `stem` (``<show>/<Season NN>/<episode>``).

    This is the SAME string gen_loop.sh passes as SHOW_NAME when it runs generate, which
    is what makes prompt comparison meaningful: derive a different name here and
    prompt_for() would build a prompt whisper never saw, marking every episode
    transcription-stale forever."""
    return os.path.basename(os.path.dirname(os.path.dirname(stem)))


def glossary_for(stem: str) -> dict:
    """Load the glossary for the show that owns `stem`. Mirrors repair.py's lookup."""
    return glossary.load(os.path.join(GLOSSARY_DIR, show_for(stem) + ".json"))


def find_confs(target: str) -> list[str]:
    """A conf.json path, or every conf.json under a directory, sorted."""
    if os.path.isfile(target):
        return [target]
    out = []
    for dp, _, fns in os.walk(target):
        out += [os.path.join(dp, f) for f in fns if f.endswith(CONF_SUFFIX)]
    return sorted(out)


def render_srt(cards: list[dict]) -> str:
    """Same shape generate.py writes: 1-based index, HH:MM:SS,mmm timestamps, blank line."""
    parts = []
    for i, c in enumerate(cards, 1):
        parts.append(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{c['text']}\n\n")
    return "".join(parts)


def _chown(path: str) -> None:
    try:
        os.chown(path, MEDIA_UID, MEDIA_GID)
    except OSError:
        pass  # non-root, or a filesystem without it


def process(conf_path: str, apply: bool, samples: list) -> dict:
    stem = conf_path[: -len(CONF_SUFFIX)]
    gloss = glossary_for(stem)
    try:
        cards = json.load(open(conf_path))
    except Exception as e:
        return {"stem": stem, "error": str(e)}

    changed_cards = 0
    total_edits = 0
    for c in cards:
        old = c.get("text", "")
        if not old:
            continue
        new, n = glossary.correct(old, gloss)
        if n and new != old:
            changed_cards += 1
            total_edits += n
            if len(samples) < 400:
                samples.append((os.path.basename(stem)[:38], old, new))
            c["text"] = new

    # Which tier this episode's glossary state puts it in. The correction above is
    # applied either way -- it is CPU-cheap and it improves the output -- but an episode
    # whose stored initial_prompt no longer matches is ALSO reported as needing the
    # decoder, so a partial text fix cannot quietly hide an out-of-date transcript.
    doc = read_words(stem)
    tier = glossary.stale_tier((doc or {}).get("initial_prompt"), gloss, show_for(stem))
    res = {
        "stem": stem,
        "cards": len(cards),
        "changed": changed_cards,
        "edits": total_edits,
        "tier": tier,
    }
    if not changed_cards or not apply:
        return res

    # Write conf first: it is the record of truth. If we die between the two writes the
    # episode still has a valid stamp and its old muxed track -- consistent, just not yet
    # improved. The reverse order would leave a corrected sidecar next to a stale conf.
    tmp = conf_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cards, f)
    os.replace(tmp, conf_path)
    _chown(conf_path)

    srt = stem + SRT_SUFFIX
    tmp = srt + ".tmp"
    with open(tmp, "w") as f:
        f.write(render_srt(cards))
    os.replace(tmp, srt)
    _chown(srt)

    # Drop the stamp LAST, and only once the sidecar is on disk. mux.py treats a valid
    # stamp as its only skip guard, so this is what re-opens the episode for merge_pass;
    # doing it earlier would leave a window where neither a stamp nor a sidecar exists.
    stamp = stem + STAMP_SUFFIX
    if os.path.exists(stamp):
        os.remove(stamp)
        res["stamp_dropped"] = True
    return res


def main() -> int:
    # __doc__ is None under `python -OO`; the tool must still run there.
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("targets", nargs="+", help="conf.json files, or directories to walk")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--show-lines", type=int, default=15, help="sample diffs to print")
    # Episode filenames are full of spaces, apostrophes and "!" — shell globbing them is
    # a quoting minefield, so selection is done here on the basename instead.
    ap.add_argument("--match", help="only episodes whose filename matches this regex")
    args = ap.parse_args()

    confs = []
    for t in args.targets:
        confs += find_confs(t)
    if args.match:
        pat = re.compile(args.match)
        confs = [p for p in confs if pat.search(os.path.basename(p))]
    if not confs:
        print("no conf.json found under:", ", ".join(args.targets))
        return 1

    samples: list = []
    results = [process(p, args.apply, samples) for p in confs]

    errs = [r for r in results if r.get("error")]
    ok = [r for r in results if not r.get("error")]
    touched = [r for r in ok if r["changed"]]

    print(f"{'APPLIED' if args.apply else 'DRY RUN'} — {len(ok)} episode(s)")
    print(f"  episodes with changes : {len(touched)}")
    print(f"  cards changed         : {sum(r['changed'] for r in ok)}")
    print(f"  total edits           : {sum(r['edits'] for r in ok)}")
    print(f"  cards scanned         : {sum(r['cards'] for r in ok)}")
    stale = [r for r in ok if r.get("tier") == "transcribe"]
    print(f"  transcription-stale   : {len(stale)}   (initial_prompt changed -> needs the GPU)")
    if args.apply:
        print(f"  stamps dropped        : {sum(1 for r in ok if r.get('stamp_dropped'))}   (merge_pass will re-mux these)")
    for r in errs:
        print("  ERROR", os.path.basename(r["stem"])[:50], r["error"])

    if touched:
        print("\nper episode:")
        for r in sorted(touched, key=lambda x: -x["edits"]):
            print(f"  {os.path.basename(r['stem'])[:52]:<54} {r['edits']:>3} edit(s) in {r['changed']} card(s)")
    if samples:
        print(f"\nsample diffs (first {min(args.show_lines, len(samples))} of {len(samples)}):")
        for ep, old, new in samples[: args.show_lines]:
            print(f"  [{ep}]")
            print(f"    -  {old}")
            print(f"    +  {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
