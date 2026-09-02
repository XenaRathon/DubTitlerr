#!/usr/bin/env python3
"""Re-open already-muxed episodes so a MERGE-STAGE fix reaches the shipped track.

Why this exists
---------------
``TEXT_VERSION`` covers everything downstream of the word list, and a bump re-derives the
text tier for the whole library. A fix that changes neither the words nor the text --
``dub_signs_merge``'s classification of which signs/song events survive, and which whisper
cards are dropped over a song span (166e88d) -- has nothing to trigger it. mux.py writes
the stamp and then removes BOTH sidecars, so an already-muxed episode has conf.json, a
stamp, and no subtitle sidecar at all: `merge_pass.sh` globs for
``*.eng.dubtitles.srt``/``.ass`` and finds nothing, forever.

Bumping TEXT_VERSION would work, and would also re-derive and re-mux every episode in the
library for a change that only affects releases carrying song-family styles. This is the
targeted alternative: point it at the shows that actually have an OP/ED and it puts just
those episodes back in the merge queue.

What it does, per episode
-------------------------
1. rebuilds ``<stem>.eng.dubtitles.srt`` from the surviving conf.json
   (``recreate_srt.recreate`` -- the same re-wrap, not a second copy of it),
2. removes a stale ``<stem>.eng.dubtitles.ass``. mux.sub_source prefers the ass over the
   srt and merge_pass only re-runs the merge when no ass is present, so leaving one behind
   re-muxes the OLD signs decisions and the fix never lands,
3. drops ``<stem>.dubtitles.done`` LAST. The stamp is mux's only skip guard, so this is
   what re-opens the episode -- and doing it before the sidecar exists would leave a window
   with neither, which reads to the next sweep as an episode needing the GPU.

No GPU, no LLM, no re-transcription: conf.json is the pipeline's own record of every card.

SCOPE. It reopens exactly what you point it at; it does not probe the videos to decide
which releases carry song styles (that is an ffmpeg extract per episode). The shows with a
conventional OP/ED are the ones that need it -- see the changelog entry for the fix.

Usage
-----
    reopen_for_signs.py <dir-or-conf.json> [...]            # dry run, lists the episodes
    reopen_for_signs.py --apply <dir-or-conf.json> [...]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recreate_srt  # noqa: E402
from common import MEDIA_GID, MEDIA_UID, STAMP_SUFFIX, log  # noqa: E402

CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"
ASS_SUFFIX = ".eng.dubtitles.ass"


def find_confs(target: str) -> list[str]:
    """A conf.json path, or every conf.json under a directory, sorted."""
    if os.path.isfile(target):
        return [target]
    out = []
    for dp, _, fns in os.walk(target):
        out += [os.path.join(dp, f) for f in fns if f.endswith(CONF_SUFFIX)]
    return sorted(out)


def process(conf_path: str, apply: bool) -> dict:
    """Re-open one episode. `skip` names why nothing was done, so a run that changes
    nothing says which reason applied rather than reporting a silent success."""
    stem = conf_path[: -len(CONF_SUFFIX)]
    res = {"stem": stem, "skip": None, "ass_removed": False}
    stamp = stem + STAMP_SUFFIX
    if not os.path.exists(stamp):
        # Already open: it is in the merge queue (or mid-run) and will pick the fix up on
        # its own. Rebuilding the srt under a live pass would race that pass's own writer.
        res["skip"] = "no stamp -- already open"
        return res
    if not apply:
        return res

    srt = stem + SRT_SUFFIX
    if recreate_srt.recreate(conf_path) is None and not os.path.exists(srt):
        res["skip"] = "conf.json produced no srt"
        return res
    try:
        os.chown(srt, MEDIA_UID, MEDIA_GID)
    except OSError:
        pass  # non-root, or a filesystem without it

    ass = stem + ASS_SUFFIX
    if os.path.exists(ass):
        os.remove(ass)
        res["ass_removed"] = True

    os.remove(stamp)  # LAST -- see the module docstring
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("targets", nargs="+", help="conf.json paths or directories to walk")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    a = ap.parse_args(argv)

    confs = [c for t in a.targets for c in find_confs(t)]
    if not confs:
        log("reopen_for_signs: no conf.json found under any target -- nothing to do")
        return 1

    results = [process(c, a.apply) for c in confs]
    reopened = [r for r in results if not r["skip"]]
    for r in results:
        if r["skip"]:
            log(f"  skip {os.path.basename(r['stem'])}: {r['skip']}")
    log(
        f"{'REOPENED' if a.apply else 'WOULD REOPEN'} {len(reopened)} of {len(confs)} episode(s); "
        f"{sum(1 for r in reopened if r['ass_removed'])} stale .ass removed"
    )
    if not a.apply and reopened:
        log("  (dry run -- re-run with --apply, then let merge_pass.sh sweep)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
