#!/usr/bin/env python3
"""Compute the qualifying-episode manifest for the subtitle release."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decisions
import unresolved

EP_SUFFIX = ".dubtitles.conf.json"
VIDEO_EXTS = (".mkv", ".mp4", ".m4v")


def media_duration(video):
    """Return a video's duration in seconds, or None when ffprobe cannot answer."""
    if not video:
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            return None
        value = float(json.loads(result.stdout)["format"]["duration"])
        return value if value > 0 else None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def find_video(stem):
    for suffix in VIDEO_EXTS:
        video = stem + suffix
        if os.path.exists(video):
            return video
    return None


def queue_for(stem):
    """Exactly the review page's queue; the full unresolved log is intentionally excluded."""
    return unresolved.live_only(stem, unresolved.pending(stem, primary_only=True))


def show_for(stem):
    """Derive the display/store show from the episode's grandparent directory."""
    return os.path.basename(os.path.dirname(os.path.dirname(stem)))


def is_target_show(stem, show):
    return show_for(stem) == show


def manifest_entry(stem, show, queue, store, duration_probe=media_duration):
    return {
        "stem": stem,
        "show": show,
        "season": os.path.basename(os.path.dirname(stem)),
        "episode_title": os.path.basename(stem),
        "duration_seconds": duration_probe(find_video(stem)),
        "queue_size": len(queue),
        "corrections": sum(
            1
            for entry in queue
            if any(
                verdict.get("verdict") == "correct" and (verdict.get("text") or "").strip()
                for verdict in decisions.for_orig(store, entry.get("original_text") or "")
            )
        ),
    }


def qualifying_episodes(show, decisions_dir, media_root, duration_probe=media_duration):
    """Return ``(qualifying entries, queue-bearing episode count, total undecided lines)``.

    All three come from ONE walk. review_server measures this walk at 297 seconds for 989
    episodes over a network mount -- "a stat costs what a read costs" there -- so counting
    queue-bearing episodes in a second pass would double a five-minute operation to produce
    a number this pass already has in hand."""
    store = decisions.load(show, decisions_dir)
    entries = []
    undecided_total = 0
    queue_episodes = 0
    for root, _dirs, files in os.walk(media_root):
        for filename in files:
            if not filename.endswith(EP_SUFFIX):
                continue
            stem = os.path.join(root, filename[: -len(EP_SUFFIX)])
            if not is_target_show(stem, show):
                continue
            queue = queue_for(stem)
            if queue:
                queue_episodes += 1
            undecided = unresolved.undecided(queue, store)
            undecided_total += len(undecided)
            if queue and not undecided:
                entries.append(manifest_entry(stem, show, queue, store, duration_probe))
    entries.sort(key=lambda entry: (entry["season"], entry["episode_title"]))
    return entries, queue_episodes, undecided_total


def write_manifest(path, entries):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")


def summarize(entries, queue_episodes, undecided_total):
    print(f"qualifying episodes: {len(entries)}")
    print(f"episodes with a queue: {queue_episodes}")
    print(f"total still-undecided lines: {undecided_total}")
    if not entries:
        print("no episodes qualify")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    entries, queue_episodes, undecided_total = qualifying_episodes(args.show, args.decisions, args.media_root)
    write_manifest(args.out, entries)
    summarize(entries, queue_episodes, undecided_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
