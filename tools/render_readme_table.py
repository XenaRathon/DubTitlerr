#!/usr/bin/env python3
"""Regenerate the subtitle repo README's shows table from its manifests.

Rewrites ONLY the text between the lines ``<!-- shows-table:start -->`` and
``<!-- shows-table:end -->``. If the markers are absent, duplicated or out of order it warns
and changes nothing: guessing where to write into a hand-edited public README is worse than
leaving a stale table. Idempotent for the same manifests and date.

  render_readme_table.py --manifest-dir $SUBS_REPO/manifest --readme $SUBS_REPO/README.md
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import atomic_write

START = "<!-- shows-table:start -->"
END = "<!-- shows-table:end -->"
_DATE = re.compile(r"^Last updated \S+: ")
_TVDB = re.compile(r"\s*\{tvdb-\d+\}\s*$")


def _warn(msg):
    print(f"render_readme_table: {msg}", file=sys.stderr)


def _load(manifest_dir):
    """[(show name, entries)] for every readable list manifest; bad ones are skipped."""
    shows = []
    for fn in sorted(os.listdir(manifest_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(manifest_dir, fn), encoding="utf-8") as f:
                entries = json.load(f)
        except (OSError, ValueError) as e:
            _warn(f"skipping {fn}: {e}")
            continue
        if not isinstance(entries, list):
            _warn(f"skipping {fn}: not a JSON list")
            continue
        if entries:
            shows.append((_TVDB.sub("", fn[: -len(".json")]), entries))
    return shows


def _block(shows, today):
    total = sum(len(e) for _, e in shows)
    # Reviewed only on positive evidence: a missing, null, empty or non-string status, or an
    # entry that is not an object, counts as unreviewed.
    reviewed = sum(
        1
        for _, es in shows
        for e in es
        if isinstance(e, dict) and isinstance(e.get("status"), str) and e["status"].strip() and e["status"] != "unreviewed"
    )
    review = "all unreviewed" if reviewed == 0 else f"{reviewed} of {total} reviewed"
    rows = sorted(shows, key=lambda s: (-len(s[1]), s[0]))
    lines = [
        f"Last updated {today}: **{total} episodes across {len(shows)} shows**, {review}. "
        "Episodes and shows are added automatically as DubTitlerr finishes them, and this table is rebuilt from "
        "`manifest/` with each update. `manifest/` has the full per-episode list.",
        "",
        "| Show | Episodes |",
        "| --- | ---: |",
        *(f"| {name.replace('|', chr(92) + '|')} | {len(es)} |" for name, es in rows),
    ]
    return "\n".join(lines) + "\n"


def _undated(block):
    return _DATE.sub("Last updated : ", block, count=1)


def render(manifest_dir, readme_path, today):
    """Rewrite the marked region; True if the README changed, False if not (or if untouched
    because the markers are unusable)."""
    with open(readme_path, encoding="utf-8", newline="") as f:
        text = f.read()
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.strip() == START]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == END]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        _warn(f"{readme_path}: need exactly one start marker followed by one end marker; README left unchanged")
        return False
    shows = _load(manifest_dir)
    if not shows:
        _warn(f"no manifest loaded from {manifest_dir}; README left unchanged")
        return False
    block = _block(shows, today)
    # The lead line carries a date that changes daily: compare with the date blanked out, and
    # when only the date differs keep the old file (and old date) so publishing does not
    # commit a noise change every day. A legacy "As of" lead line never matches, so it is
    # rewritten once.
    old_block = "".join(lines[starts[0] + 1 : ends[0]])
    if old_block.startswith("Last updated ") and _undated(old_block) == _undated(block):
        return False
    new = "".join(lines[: starts[0] + 1]) + block + "".join(lines[ends[0] :])
    if new == text:
        return False
    atomic_write(readme_path, lambda f: f.write(new), mode=os.stat(readme_path).st_mode & 0o777, newline="")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--manifest-dir", required=True)
    ap.add_argument("--readme", required=True)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (tests); default: today, UTC")
    a = ap.parse_args(argv)
    today = a.today or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    print("README table updated" if render(a.manifest_dir, a.readme, today) else "README table unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
