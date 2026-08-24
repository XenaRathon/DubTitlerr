#!/usr/bin/env python3
"""ONE-TIME migration — write a grandfather (v1) ``.dubtitles.done`` stamp for every
episode that already carries an embedded "Dubtitles" track but has no stamp beside it.

Why this exists: the strip-at-mux change made the version-aware stamp the ONLY "already
muxed" guard. generate.py and mux.py used to fall back on an ffprobe check ("this file
has a Dubtitles track, so it's done"); that backstop is gone, because a re-mux now
REPLACES the old track instead of refusing to touch the file — which is exactly what
lets a PIPELINE_VERSION bump regenerate an already-dubbed episode. The side effect is
that a file muxed before stamps existed (or one whose stamp was lost) reads as STALE and
would be re-transcribed + re-muxed on the next sweep. Running this first turns that
mass regeneration back into the intended no-op rollout.

The stamp it writes records ``GRANDFATHER_VERSION``, not ``PIPELINE_VERSION``: it is
recording what actually produced the file (pre-versioning output = v1). So running this
AFTER a deliberate version bump correctly leaves those files stale rather than falsely
marking last version's output as current.

DRY-RUN by default (prints the plan); pass --apply to write stamps. Never touches media
— it only creates sidecar ``.dubtitles.done`` files, so it is safe to re-run (an
existing stamp of any version is left exactly as it is).

Usage:
  python3 scripts/migrate_write_v1_stamps.py "/media/Anime Library"          # dry run
  python3 scripts/migrate_write_v1_stamps.py --apply "/media/Anime Library"
  python3 scripts/migrate_write_v1_stamps.py --apply ep1.mkv ep2.mkv         # explicit files

Requires ffprobe.  Built with help of Claude (Anthropic).
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import (  # noqa: E402
    EXTRA_DIRS,
    GRANDFATHER_VERSION,
    STAMP_SUFFIX,
    VIDEO_EXTS,
    is_our_track,
    log,
    read_stamp,
    stream_title,
)


def has_dubtitles_track(video: str) -> bool | None:
    """True/False if ffprobe answered; **None if the file could not be probed at all**
    (ffprobe missing, timed out, exited nonzero, or emitted unparseable output).

    The tri-state matters. Collapsing a probe failure into False would file every
    unreadable or corrupt file under `no-dubtitles` — "not muxed yet, the normal pipeline
    owns it" — so a run over a partly-broken library would report zero errors and read as
    clean while silently skipping exactly the files worth looking at. This is detection for
    migration, not a skip guard: the pipeline deliberately no longer decides "done" from
    the presence of the track (see the module docstring)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream_tags=title", "-of", "json", video],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None  # couldn't run it / timed out
    if r.returncode != 0:
        return None  # unreadable/truncated file
    try:
        streams = json.loads(r.stdout).get("streams", [])
    except ValueError:
        return None  # ffprobe said OK but emitted junk
    return any(is_our_track(stream_title(st)) for st in streams)


def write_v1_stamp(path: str, video: str) -> None:
    """Like common.write_stamp, but pinned to GRANDFATHER_VERSION — this file was produced
    by the pre-versioning pipeline, so that is the version to record."""
    st = os.stat(video)
    with open(path, "w") as f:
        json.dump({"size": st.st_size, "mtime": st.st_mtime, "muxed": True, "version": GRANDFATHER_VERSION}, f)


def process(video: str, apply: bool) -> str:
    """-> "has-stamp" | "no-dubtitles" | "probe-failed" | "plan" | "stamped" | "error"."""
    stamp = os.path.splitext(video)[0] + STAMP_SUFFIX
    if read_stamp(stamp) is not None:
        return "has-stamp"  # never overwrite (incl. a deliberate stale one)
    has_track = has_dubtitles_track(video)
    if has_track is None:
        log("  probe failed (unreadable?):", os.path.basename(video))
        return "probe-failed"  # counted apart from no-dubtitles, never stamped
    if not has_track:
        return "no-dubtitles"  # not muxed yet — the normal pipeline owns it
    if not apply:
        log("  PLAN stamp", os.path.basename(video))
        return "plan"
    try:
        write_v1_stamp(stamp, video)
    except OSError as e:
        log("  stamp write failed:", video, e)
        return "error"
    return "stamped"


def walk(roots: list) -> list:
    """Every video under `roots` (dirs walked, plain files passed through), with Plex
    extras subfolders pruned the same way generate.py/mux.py prune them."""
    vids = []
    for root in roots:
        if os.path.isfile(root):
            vids.append(root)
            continue
        for dp, dns, files in os.walk(root):
            dns[:] = [d for d in dns if d.lower() not in EXTRA_DIRS]
            vids += [os.path.join(dp, f) for f in files if f.lower().endswith(VIDEO_EXTS)]
    return vids


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write stamps (default: dry run)")
    ap.add_argument("paths", nargs="+", help="library roots and/or explicit video paths")
    a = ap.parse_args()
    counts = {}
    for v in walk(a.paths):
        res = process(v, a.apply)
        counts[res] = counts.get(res, 0) + 1
    log("SUMMARY", counts)
    if not a.apply and counts.get("plan"):
        log(f"{counts['plan']} file(s) would be stamped — re-run with --apply")
    if counts.get("probe-failed"):
        log(
            f"WARNING: {counts['probe-failed']} file(s) could not be probed — they are NOT "
            f"counted as 'no-dubtitles' and were NOT stamped; check them by hand"
        )


if __name__ == "__main__":
    main()
