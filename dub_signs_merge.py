#!/usr/bin/env python3
"""Merge Whisper "dubtitles" (English-dub dialogue) with each video's internal
"Signs and Songs" subtitle track into ONE .ass file, so a player that only shows
one subtitle track at a time renders BOTH at once.

For every ``<stem>.eng.dubtitles.srt`` it finds, it:
  1. locates the matching video (.mkv/.mp4),
  2. finds the internal subtitle stream whose title looks like "Signs and Songs",
  3. extracts it and appends the dub dialogue under a bottom-aligned style,
  4. writes ``<stem>.eng.dubtitles.ass`` and removes the now-redundant ``.srt``.

If a file has no signs track, the plain ``.srt`` is left untouched. Idempotent
and safe to re-run on a schedule.

Config via env:
  MERGE_ROOTS  colon-separated folders to scan
               (default: /data/Media/Anime Library:/data/Media/Anime Movie Library)
  DUB_SUFFIX   sidecar suffix to look for (default: .eng.dubtitles.srt)
  MEDIA_UID / MEDIA_GID  ownership for the written .ass (default 1000 / 100)

Requires: ffmpeg/ffprobe on PATH, and the `pysubs2` package.
Built with help of Claude (Anthropic).
"""
import json
import os
import subprocess
import tempfile

import pysubs2

ROOTS = os.environ.get(
    "MERGE_ROOTS",
    "/data/Media/Anime Library:/data/Media/Anime Movie Library",
).split(":")
SUFFIX = os.environ.get("DUB_SUFFIX", ".eng.dubtitles.srt")
MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))
VIDEO_EXTS = (".mkv", ".mp4", ".m4v")
SIGNS_KEYWORDS = ("sign", "song")


def log(*a):
    print(*a, flush=True)


def find_video(stem):
    for ext in VIDEO_EXTS:
        if os.path.exists(stem + ext):
            return stem + ext
    return None


def find_signs_stream(video):
    """Return the absolute index of the 'Signs and Songs' subtitle stream, or None."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s",
             "-show_entries", "stream=index:stream_tags=title", "-of", "json", video],
            capture_output=True, text=True, timeout=90)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed:", video, e)
        return None
    for st in streams:
        title = ((st.get("tags") or {}).get("title", "") or "").lower()
        if any(k in title for k in SIGNS_KEYWORDS):
            return st["index"]
    return None


def extract_track(video, index, out_ass):
    # copy first (preserves ASS styling + positioning); fall back to a convert
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-map", f"0:{index}",
                    "-c:s", "copy", out_ass], capture_output=True, timeout=180)
    if not (os.path.exists(out_ass) and os.path.getsize(out_ass) > 0):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-map", f"0:{index}", out_ass],
                       capture_output=True, timeout=180)
    return os.path.exists(out_ass) and os.path.getsize(out_ass) > 0


def merge(signs_ass, dub_srt, out_ass):
    signs = pysubs2.load(signs_ass)
    dub = pysubs2.load(dub_srt)
    try:
        play_y = int(signs.info.get("PlayResY") or 0)
    except Exception:
        play_y = 0
    if not play_y:
        play_y = 720
    fs = max(32, round(play_y / 17))
    st = pysubs2.SSAStyle()
    st.fontname = "Arial"
    st.fontsize = fs
    st.bold = True
    st.primarycolor = pysubs2.Color(255, 255, 255)
    st.outlinecolor = pysubs2.Color(0, 0, 0)
    st.outline = max(1.5, fs / 22)
    st.shadow = 1.0
    st.alignment = pysubs2.Alignment.BOTTOM_CENTER
    st.marginv = max(10, round(play_y / 22))
    signs.styles["Dubtitles"] = st
    added = 0
    for ev in dub:
        if ev.is_comment:
            continue
        ev.style = "Dubtitles"
        signs.events.append(ev)
        added += 1
    signs.sort()
    signs.save(out_ass)
    return added, (os.path.exists(out_ass) and os.path.getsize(out_ass) > 0)


def process_one(srt):
    stem = srt[: -len(SUFFIX)]
    out_ass = stem + ".eng.dubtitles.ass"
    video = find_video(stem)
    if not video:
        return "no-video"
    idx = find_signs_stream(video)
    if idx is None:
        return "no-signs"
    with tempfile.TemporaryDirectory() as td:
        sgn = os.path.join(td, "signs.ass")
        if not extract_track(video, idx, sgn):
            return "extract-failed"
        try:
            added, ok = merge(sgn, srt, out_ass)
        except Exception as e:
            log("merge error:", srt, e)
            return "merge-error"
    if not ok or added == 0:
        return "merge-empty"
    try:
        os.chown(out_ass, MEDIA_UID, MEDIA_GID)
    except OSError:
        pass
    try:
        os.remove(srt)
    except OSError:
        pass
    return "merged"


def main():
    counts = {}
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, _, files in os.walk(root):
            for f in files:
                if f.endswith(SUFFIX):
                    res = process_one(os.path.join(dp, f))
                    counts[res] = counts.get(res, 0) + 1
                    if res == "merged":
                        log("merged:", f)
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
