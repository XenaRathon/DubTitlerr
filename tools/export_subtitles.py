#!/usr/bin/env python3
"""Export completed-dubtitle subtitles for the "unreviewed, subject to improve" public drop.

export_reviewed.py's manifest gates on decision 11 (every queued line has a human verdict).
Measured 2026-08-31 against the real library: 255 One Pace episodes carry a review queue,
7,222 queued lines have no verdict, and ZERO episodes qualify -- Season 31, the set believed
reviewed, does not either (docs/superpowers/specs/2026-08-31-public-beta-design.md,
Workstream C). Shipping under that gate means shipping nothing.

This tool gates on completion instead: a valid `.dubtitles.done` stamp (common.stamp_valid)
that matches the episode's current video is the same claim mux.py itself relies on to skip
a re-mux -- "this episode's dubtitle track is the one actually in the file". Every episode
that passes is exported with `"status": "unreviewed"` in its manifest entry, and the
repository README says so up front. Decision 11 is untouched; export_reviewed.py's stricter
manifest remains the tool for a future reviewed release.

Per episode: the dialogue-only `.srt` (regenerated from `.dubtitles.conf.json`, since
mux.py deletes the loose srt/ass sidecars on a successful mux) and the merged `.ass`
(extracted from the muxed video's own "Dubtitles"-titled subtitle stream -- the sidecar
mux.py wrote INTO the file, not a copy that can drift from it).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reflow
from common import STAMP_SUFFIX, TRACK_NAME, read_stamp, stamp_valid, ts_srt

CONF_SUFFIX = ".dubtitles.conf.json"
VIDEO_EXTS = (".mkv", ".mp4", ".m4v")


def find_video(stem: str) -> str | None:
    for ext in VIDEO_EXTS:
        video = stem + ext
        if os.path.exists(video):
            return video
    return None


def show_for(stem: str) -> str:
    """Derive the display show from the episode's grandparent directory, matching
    export_reviewed.py's own show_for."""
    return os.path.basename(os.path.dirname(os.path.dirname(stem)))


def completed_episodes(show: str, media_root: str) -> list:
    """Every stem in `show` whose muxed video currently matches a valid `.dubtitles.done`
    stamp. ONE `os.walk` of media_root -- review_server measures this walk at 297s for 989
    episodes over a network mount, so a second pass would double a five-minute operation to
    produce nothing new (same reasoning as export_reviewed.py's own single-walk test)."""
    stems = []
    for root, _dirs, files in os.walk(media_root):
        for filename in files:
            if not filename.endswith(STAMP_SUFFIX):
                continue
            stem = os.path.join(root, filename[: -len(STAMP_SUFFIX)])
            if show_for(stem) != show:
                continue
            video = find_video(stem)
            if video is None:
                continue
            if not stamp_valid(read_stamp(stem + STAMP_SUFFIX), video):
                continue
            stems.append(stem)
    stems.sort()
    return stems


def dialogue_srt(stem: str) -> str | None:
    """The dialogue-only SRT rebuilt from `.dubtitles.conf.json`. None (never raises) when
    the file is missing or unparseable -- this runs inside a loop over hundreds of real
    episodes and one bad conf.json must not abort the batch."""
    try:
        with open(stem + CONF_SUFFIX, encoding="utf-8") as f:
            cards = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        blocks = [
            f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{reflow.wrap_balance(c['text'])}\n"
            for i, c in enumerate(cards, 1)
        ]
    except (KeyError, TypeError):
        return None
    return "\n".join(blocks)


def probe_duration_seconds(video: str, run=subprocess.run) -> float | None:
    try:
        result = run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        value = float(json.loads(result.stdout)["format"]["duration"])
        return value if value > 0 else None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def dubtitles_stream_index(video: str, run=subprocess.run) -> int | None:
    """The stream index of the muxed video's own TRACK_NAME-titled subtitle stream, or
    None when it isn't there (the episode's video predates a successful mux)."""
    try:
        result = run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index:stream_tags=title",
                "-select_streams",
                "s",
                "-of",
                "json",
                video,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        streams = json.loads(result.stdout).get("streams", [])
        for s in streams:
            if (s.get("tags") or {}).get("title") == TRACK_NAME:
                return s.get("index")
        return None
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def extract_ass(video: str, stream_index: int, out_path: str, run=subprocess.run) -> bool:
    """Thin, fully mockable wrapper around the ffmpeg extraction call. Never raises."""
    try:
        result = run(
            ["ffmpeg", "-y", "-v", "error", "-i", video, "-map", f"0:{stream_index}", out_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def manifest_entry(stem: str, show: str, season: str, episode_title: str, duration: float | None) -> dict:
    return {
        "show": show,
        "season": season,
        "episode_title": episode_title,
        "duration_seconds": duration,
        "status": "unreviewed",
    }


def export_episode(
    stem: str,
    out_root: str,
    *,
    probe=probe_duration_seconds,
    stream_finder=dubtitles_stream_index,
    extractor=extract_ass,
) -> dict | None:
    """Export one episode's subtitles into `out_root/<show>/<season>/`. None when the
    video has no TRACK_NAME stream to extract -- despite a valid completion stamp, that
    means there is nothing here actually worth shipping."""
    video = find_video(stem)
    if video is None:
        return None
    show = show_for(stem)
    season = os.path.basename(os.path.dirname(stem))
    episode_title = os.path.basename(stem)

    index = stream_finder(video)
    if index is None:
        return None

    out_dir = os.path.join(out_root, show, season)
    os.makedirs(out_dir, exist_ok=True)
    ass_path = os.path.join(out_dir, episode_title + ".ass")
    if not extractor(video, index, ass_path):
        try:
            os.remove(ass_path)
        except OSError:
            pass
        return None

    srt = dialogue_srt(stem)
    if srt is not None:
        with open(os.path.join(out_dir, episode_title + ".srt"), "w", encoding="utf-8") as f:
            f.write(srt)

    return manifest_entry(stem, show, season, episode_title, probe(video))


def write_manifest(path: str, entries: list) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", required=True)
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)

    stems = completed_episodes(args.show, args.media_root)
    entries = [entry for stem in stems if (entry := export_episode(stem, args.out)) is not None]
    write_manifest(args.manifest, entries)
    print(f"exported {len(entries)} of {len(stems)} completed episodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
