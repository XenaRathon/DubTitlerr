#!/usr/bin/env python3
"""Re-key sidecars orphaned when an external tool RENAMED the video they describe.

Why this exists
---------------
Sidecar LOOKUP is by filename stem (``mux.py``: ``os.path.splitext(video)`` +
``STAMP_SUFFIX``), but sidecar VALIDATION is by content (``common._stamp_matches_file``:
size equality plus an mtime tolerance). So when an external transcoder renames a video,
its stamp still describes that video perfectly -- it is simply no longer being looked
for. The episode reads as never-processed and is queued for a full re-transcription.

Measured on the live library 2026-08-24: 3,889 videos, 813 stamps, **67 orphaned**, of
which 46 match a video by size and 31 by size and mtime together.

What it will not do
-------------------
It never deletes. An orphan with no match is REPORTED, because its stamp is the only
record that the episode was ever processed, and a stamp is far cheaper to keep than a
re-transcription is to redo.

It never moves ``.dubtitles.fail`` (a poison marker naming THAT stem), ``*.stale``
(parked output from a superseded run) or ``*.muxtmp.mkv`` (an in-flight mux). Carrying
any of those onto a live stem would corrupt state rather than recover it.

It refuses to ``--apply`` while the pipeline is running. generate and mux write and
delete exactly the files this renames; a re-key racing a live mux would produce the
silent corruption this project keeps finding.

Matching, and the limit of the available evidence
-------------------------------------------------
A stamp records ``size`` and ``mtime`` and nothing else. There is NO recorded digest of
the original video, so a content hash has nothing to compare against: hashing the
candidate proves only that it is readable. That means "confirm by content before
re-keying" is not implementable on the stamps this library already has, and pretending
otherwise would be a confident wrong answer of exactly the kind this project keeps
finding. Verdicts are graded by the evidence that does exist:

    size + mtime agree     RECLAIMABLE  -- a plain rename; the pipeline's own
                                          _stamp_matches_file would accept this pairing
    size agrees, mtime not PROBABLE     -- consistent with a copy that lost its
                                          timestamp, but also with a coincidence. NOT
                                          re-keyed unless --include-probable says so.
    no size match          UNRECOVERABLE
    more than one claimant AMBIGUOUS

Measured split on the live library: 31 reclaimable, 15 probable, 21 unrecoverable.

Stamps written from now on could carry a digest, which would collapse PROBABLE into a
decidable question. That is deliberately NOT done here: it helps only episodes stamped
after the change, and this tool exists for the 67 that already are.

An orphan matching two videos, or two orphans matching one video, is AMBIGUOUS and
neither is touched. Guessing by name similarity is exactly the kind of inference that
produces a confident wrong answer.

Usage
-----
    reclaim_orphans.py <library-root>              # dry run: report, change nothing
    reclaim_orphans.py --apply <library-root>
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common  # noqa: E402

VIDEO_EXTS = (".mkv", ".mp4", ".m4v")

# Everything that belongs to an episode and should follow its rename. Deliberately
# explicit: a glob would sweep up the markers below.
REKEY_SUFFIXES = (
    common.STAMP_SUFFIX,
    common.WORDS_SUFFIX,
    ".dubtitles.conf.json",
    ".dubtitles.qc.json",
    ".dubtitles.repair-summary.json",
    ".dubtitles.unresolved.jsonl",
    ".dubtitles.mux.log",
    ".eng.dubtitles.srt",
    ".eng.dubtitles.ass",
)

# Never re-keyed, and the reason each one must stay put:
#   .dubtitles.fail   poison marker naming the stem generate crashed on
#   .stale            parked output from a superseded pipeline version
#   .muxtmp.mkv       an in-flight mux; moving it races the process writing it
NEVER_REKEY = (".dubtitles.fail", ".stale", ".muxtmp.mkv")

HASH_WINDOW = 4 * 1024 * 1024  # head + tail bytes compared before a re-key


@dataclass
class Match:
    stem: str
    video: str | None
    mtime_agrees: bool
    content_identical: bool | None
    verdict: str  # reclaimable | ambiguous | unrecoverable


def pipeline_is_live() -> bool:
    """True if a pipeline process is running on this host.

    Reads /proc rather than shelling out to pgrep, so it works in the slim container
    image. Unreadable /proc (or a non-Linux host) is treated as LIVE: refusing to run is
    the safe answer when the question cannot be answered."""
    names = ("generate.py", "mux.py", "repair.py", "dub_signs_merge.py", "gen_loop.sh", "merge_pass.sh")
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return True
    me = str(os.getpid())
    for pid in pids:
        if pid == me:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "replace")
        except OSError:
            continue  # the process exited between listdir and open
        # Compare basenames of the argv tokens, not a substring of the whole command
        # line: "pytest tests/test_generate.py" contains "generate.py" and would report
        # a live pipeline on any developer machine running the suite.
        if any(os.path.basename(tok) in names for tok in cmd.split("\x00") if tok):
            return True
    return False


def _edge_digest(path: str) -> str | None:
    """sha256 over the head and tail of a file. Reading whole episodes over NFS to
    compare 46 candidates would cost hours; the edges catch a different encode."""
    try:
        size = os.path.getsize(path)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            h.update(f.read(HASH_WINDOW))
            if size > HASH_WINDOW * 2:
                f.seek(-HASH_WINDOW, os.SEEK_END)
                h.update(f.read(HASH_WINDOW))
        return h.hexdigest()
    except OSError:
        return None


def find_matches(root: str) -> list[Match]:
    """Every orphaned stamp under `root`, with a verdict. Reads only; never writes."""
    videos: dict[int, list[str]] = collections.defaultdict(list)
    stamps: list[str] = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            if fn.endswith(VIDEO_EXTS):
                try:
                    videos[os.path.getsize(p)].append(p)
                except OSError:
                    pass
            elif fn.endswith(common.STAMP_SUFFIX):
                stamps.append(p)

    orphans: list[tuple[str, dict]] = []
    for s in stamps:
        stem = s[: -len(common.STAMP_SUFFIX)]
        if any(os.path.exists(stem + e) for e in VIDEO_EXTS):
            continue  # its video is still there under this name
        doc = common.read_stamp(s)
        if doc:
            orphans.append((stem, doc))

    # A video claimed by more than one orphan is evidence for none of them.
    claims: collections.Counter = collections.Counter()
    for _, doc in orphans:
        for v in videos.get(doc.get("size"), []):
            claims[v] += 1

    out: list[Match] = []
    for stem, doc in orphans:
        cands = videos.get(doc.get("size"), [])
        if len(cands) != 1 or claims[cands[0]] > 1:
            out.append(Match(stem, None, False, None, "ambiguous" if cands else "unrecoverable"))
            continue
        video = cands[0]
        try:
            mtime_agrees = abs(doc.get("mtime", 0) - os.path.getmtime(video)) < 1.0
        except OSError:
            mtime_agrees = False
        readable = _edge_digest(video) is not None
        if not readable:
            verdict = "unrecoverable"
        else:
            verdict = "reclaimable" if mtime_agrees else "probable"
        out.append(Match(stem, video, mtime_agrees, readable, verdict))
    return out


def reclaim(root: str, apply: bool = False, include_probable: bool = False) -> list[Match]:
    matches = find_matches(root)
    if apply and pipeline_is_live():
        print("REFUSING: a pipeline process is running -- generate and mux write the very")
        print("files this renames. Stop the container, then re-run.")
        return matches
    for m in matches:
        allowed = {"reclaimable"} | ({"probable"} if include_probable else set())
        if not apply or m.verdict not in allowed or not m.video:
            continue
        new_stem = os.path.splitext(m.video)[0]
        for suff in REKEY_SUFFIXES:
            src = m.stem + suff
            if not os.path.exists(src) or any(n in suff for n in NEVER_REKEY):
                continue
            dst = new_stem + suff
            if os.path.exists(dst):
                continue  # never overwrite live output
            try:
                os.replace(src, dst)
            except OSError as e:
                print("  rename failed:", src, e)
    return matches


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("root", help="library root to walk")
    ap.add_argument("--apply", action="store_true", help="re-key (default: report only)")
    ap.add_argument(
        "--include-probable",
        action="store_true",
        help="also re-key size-only matches whose mtime disagrees (a copy, not a rename)",
    )
    args = ap.parse_args()

    matches = reclaim(args.root, apply=args.apply, include_probable=args.include_probable)
    by = collections.Counter(m.verdict for m in matches)
    print(f"{'APPLIED' if args.apply else 'DRY RUN'} — {len(matches)} orphaned stamp(s)")
    print(f"  reclaimable    : {by['reclaimable']}   (size + mtime agree)")
    print(f"  probable       : {by['probable']}   (size only -- needs --include-probable)")
    print(f"  ambiguous      : {by['ambiguous']}   (left untouched on purpose)")
    print(f"  unrecoverable  : {by['unrecoverable']}   (reported, never deleted)")
    for m in matches:
        print(f"  [{m.verdict:<13}] {os.path.basename(m.stem)[:52]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
