#!/usr/bin/env python3
"""S&S extract-only prototype (docs/beta-feedback/2026-09-07-r-animedubs.md): pull just
the signs/songs/credits events out of a full English subtitle track, no Whisper involved.

Two independent classifiers decide KEEP, either is enough:
  - dub_signs_merge.keep_event(ev): the existing tag/style classifier (karaoke, \\pos/
    \\move, drawing, animated, or a sign/song/credit style name).
  - off_default_position(ev, play_res_y): a numeric heuristic from the beta-feedback
    thread's own description of how pirate groups build S&S tracks -- "extract what's
    not in the default location" -- checked FIRST so its hits are attributable in the
    per-reason table even when keep_event() would also have kept the same event (e.g. an
    \\an8 top-aligned line: dub_signs_merge's own POSITIONED regex already matches \\an8,
    so without checking position first every such line would be silently folded into
    keep_event's bucket and this heuristic's real hit rate -- and its false-positive
    rate on plain top-aligned dialogue -- would be invisible).

Read-only: never mutates the source .ass. Writes `<stem>.sns.ass` into --out (a
directory), never beside the source media. NOT wired into merge_pass.sh -- this is a
prototype for scoping the feature request, not a pipeline stage.

Built with help of Claude (Anthropic).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

import pysubs2

sys.path.insert(0, ".")
import dub_signs_merge as dsm

DEFAULT_PLAY_RES_Y = 288  # matches dub_signs_merge.py's no-PlayRes-declared fallback
OFF_DEFAULT_Y_FRACTION = 0.75  # top 75% of the frame is "not where dialogue sits"

_POS_RE = re.compile(r"\\pos\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)")
_MOVE_RE = re.compile(r"\\move\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,")
_AN_RE = re.compile(r"\\an(\d)")


def off_default_position(ev: pysubs2.SSAEvent, play_res_y: int) -> bool:
    """True if `ev`'s override tags place it away from the bottom-center dialogue spot:
    an explicit \\pos(x,y)/\\move(x1,y1,...) whose y sits above the bottom quarter of the
    frame (y < 0.75 * play_res_y -- ASS y grows downward, so a SMALL y is a sign near the
    top), or an explicit \\an<N> alignment override where N is not 2 (bottom-center,
    libass's default). `play_res_y` must be > 0 -- callers resolve a missing/zero
    PlayResY to DEFAULT_PLAY_RES_Y before calling this."""
    t = ev.text
    m = _POS_RE.search(t) or _MOVE_RE.search(t)
    if m and float(m.group(2)) < OFF_DEFAULT_Y_FRACTION * play_res_y:
        return True
    m2 = _AN_RE.search(t)
    return bool(m2 and m2.group(1) != "2")


def classify_event(ev: pysubs2.SSAEvent, play_res_y: int) -> str:
    """One of "position_only" (off_default_position fired -- checked first, see module
    docstring), "keep" (dub_signs_merge.keep_event fired and position did not), or
    "drop"."""
    if off_default_position(ev, play_res_y):
        return "position_only"
    if dsm.keep_event(ev):
        return "keep"
    return "drop"


def extract(path: str, out_dir: str) -> tuple[pysubs2.SSAFile, Counter]:
    """Load `path`, classify every event, build the kept-only SSAFile (styles imported
    from the source so KEEP_STYLE-matched lines still render), write
    `<stem>.sns.ass` under `out_dir`, and return (kept_subs, per (style, reason) counts)."""
    subs = pysubs2.load(path)
    play_res_y = int(subs.info.get("PlayResY") or 0) or DEFAULT_PLAY_RES_Y

    counts: Counter = Counter()
    kept = pysubs2.SSAFile()
    kept.info.update(subs.info)
    kept.import_styles(subs)
    for ev in subs.events:
        reason = classify_event(ev, play_res_y)
        counts[(ev.style or "", reason)] += 1
        if reason != "drop":
            kept.append(ev)

    stem = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, stem + ".sns.ass")
    kept.save(out_path)
    return kept, counts


def print_counts(path: str, counts: Counter) -> None:
    print(f"{path}:")
    for (style, reason), n in sorted(counts.items()):
        print(f"  {style:<20} {reason:<14} {n}")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Extract-only S&S prototype (see module docstring).")
    ap.add_argument("ass_file", nargs="+", help="one or more extracted subtitle-stream .ass files")
    ap.add_argument("--out", required=True, help="directory to write <stem>.sns.ass into (never beside the media)")
    return ap


def main(argv=None) -> int:
    a = build_arg_parser().parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for path in a.ass_file:
        _kept, counts = extract(path, a.out)
        print_counts(path, counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
