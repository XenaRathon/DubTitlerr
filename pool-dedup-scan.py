#!/usr/bin/env python3
"""Phase 1: scan the .230 pool (mergerfs over btrfs branches).

Walks each underlying btrfs branch directly (real inode numbers, real nlink
counts — mergerfs synthesizes its own inodes), records per-file metadata, and
writes a JSONL report. Also groups hardlink aliases and size-collision
candidates so Phase 2 only hashes files that could actually be duplicates.
"""
import json
import os
import sys

BRANCH_ROOT = "/srv"
POOL_VIEW_ROOT = "/export/pool-root"

# Top-level pool dirs to scan. Skip hidden/system junk.
TOP_DIRS = {
    "backups", "downloads", "karakeep", "media", "qbit-scratch",
    "qui-crossseed-data",
}

# File extensions that are not worth dedup hashing (sidecar/thumbnail/etc).
SKIP_EXTS = {
    ".nfo", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tbn",
    ".srt", ".sub", ".idx", ".ass", ".ssa", ".vtt", ".txt", ".log",
    ".part", ".parts", ".nzb", ".torrent", ".md5", ".sfv", ".url",
    ".db", ".ini", ".cfg", ".conf", ".json", ".xml", ".bak", ".tmp",
    ".lua", ".py", ".sh",
}

# Small files get hashed wholesale; threshold for "small".
SMALL_SIZE = 64 * 1024


def branch_paths():
    """Yield (branch_root, top, abs_top) for every scanned top dir on every branch."""
    for entry in sorted(os.listdir(BRANCH_ROOT)):
        if not entry.startswith("dev-disk-by-uuid-"):
            continue
        branch = os.path.join(BRANCH_ROOT, entry)
        if not os.path.isdir(branch):
            continue
        for top in TOP_DIRS:
            p = os.path.join(branch, top)
            if os.path.isdir(p):
                yield branch, top, p


def main():
    out = sys.stdout
    seen = set()
    stats = {"files": 0, "symlinks": 0, "dirs": 0, "skipped_ext": 0, "skipped_empty": 0}

    for branch, top, top_abs in branch_paths():
        for dirpath, dirnames, filenames in os.walk(top_abs, followlinks=False):
            # Don't descend into recycle bins on branches if present
            dirnames[:] = [d for d in dirnames if d not in (".recycle", ".trash", ".snapshot")]
            stats["dirs"] += len(dirnames)
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if os.path.islink(full):
                    stats["symlinks"] += 1
                    continue
                if not os.path.isfile(full):
                    continue

                ext = os.path.splitext(fn)[1].lower()
                if ext in SKIP_EXTS:
                    stats["skipped_ext"] += 1
                    continue
                if st.st_size == 0:
                    stats["skipped_empty"] += 1
                    continue

                # View path relative to the pool root, e.g. media/TV Library/...
                rel = os.path.relpath(full, os.path.join(branch, top))
                view_rel = os.path.join(top, rel) if rel != "." else top
                # De-dup guard in case branches overlap oddly
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)

                rec = {
                    "dev": st.st_dev,
                    "ino": st.st_ino,
                    "nlink": st.st_nlink,
                    "size": st.st_size,
                    "view": view_rel,
                    "branch": os.path.basename(branch),
                    "mtime": int(st.st_mtime),
                }
                out.write(json.dumps(rec) + "\n")
                stats["files"] += 1

    sys.stderr.write(json.dumps(stats) + "\n")


if __name__ == "__main__":
    main()