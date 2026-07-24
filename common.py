#!/usr/bin/env python3
"""Shared stdlib-only helpers for the DubTitlerr pipeline stages (generate.py, mux.py,
repair.py, dub_signs_merge.py, mine_glossary.py, recreate_srt.py).

Single source of truth for the helpers that used to be duplicated per-module (see
specs/v1-polish/spec.md, Phase 1 — Foundation). Pure stdlib: no imports from other
project modules, so any pipeline stage can import this without dragging in the rest
of the pipeline (and without risking a circular import).
"""
import json
import os
import subprocess

MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))

# OUTPUT_ROOT: write sidecars/output files to this branch path instead of next to the
# source media, so writes land on a disk with space (mergerfs unifies branches, so the
# file still shows next to the source in the pool view). READS still use MEDIA_ROOT.
# Empty OUTPUT_ROOT = write in place.
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "")

VIDEO_EXTS = (".mkv", ".mp4", ".m4v")

def load_extras(path="data/extras.txt"):
    """Load the EXTRA_DIRS set (Plex "local extras" subfolders + creditless/scene clips --
    never real episodes, often mismatched junk from the scraper -- pruned from library
    walks) from the single-source-of-truth data file (see specs/v2-models-ops/spec.md,
    "EXTRA_DIRS consolidation"). Falls back to the pre-consolidation hardcoded set if the
    file is missing/unreadable, so the pipeline still runs correctly without it (e.g. a
    dev checkout, or an image built before the data file existed)."""
    try:
        with open(path) as f:
            return {ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")}
    except OSError:
        return {"behind the scenes", "deleted scenes", "featurettes", "interviews",
                "scenes", "shorts", "trailers", "other", "extras"}


# Plex "local extras" subfolders + creditless/scene clips — never real episodes, often
# mismatched junk from the scraper. Pruned from library walks.
EXTRA_DIRS = load_extras()

STAMP_SUFFIX = ".dubtitles.done"


def log(*a): print(*a, flush=True)


def out_for(p):
    """Redirect a write path onto OUTPUT_ROOT (if configured) so writes land on a disk
    with space; creates intermediate directories (safe superset of the non-creating
    variant — callers that write to an already-existing dir are unaffected)."""
    if OUTPUT_ROOT and p.startswith(MEDIA_ROOT):
        q = OUTPUT_ROOT + p[len(MEDIA_ROOT):]
        os.makedirs(os.path.dirname(q), exist_ok=True)
        return q
    return p


def ts_srt(t):
    """Format a float number-of-seconds as an SRT timestamp (HH:MM:SS,mmm)."""
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def write_stamp(path: str, video: str) -> None:
    """Write the .dubtitles.done idempotency stamp recording the muxed file's size+mtime."""
    st = os.stat(video)
    with open(path, "w") as f:
        json.dump({"size": st.st_size, "mtime": st.st_mtime, "muxed": True}, f)


def read_stamp(path: str) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def stamp_valid(stamp: dict | None, video: str) -> bool:
    """True if the stamp matches the current file (size+mtime) — i.e. still muxed, not replaced."""
    if not stamp or not stamp.get("muxed"):
        return False
    try:
        st = os.stat(video)
    except OSError:
        return False
    return stamp.get("size") == st.st_size and abs(stamp.get("mtime", 0) - st.st_mtime) < 1.0


def find_video(stem):
    for e in VIDEO_EXTS:
        if os.path.exists(stem + e):
            return stem + e
    return None


def eng_sub_streams(video, sub_langs):
    """Indices of ASS/SSA subtitle streams in an accepted language. ``sub_langs`` is a
    set of lowercased language codes (each consumer keeps its own SUB_LANGS env-derived
    set — not unified here, since the two current callers already read the same env var
    to the same default and there's no behavior change from passing it explicitly)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s",
                            "-show_entries", "stream=index,codec_name:stream_tags=language",
                            "-of", "json", video], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=90)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed:", video, e)
        return []
    out = []
    for st in streams:
        if st.get("codec_name") not in ("ass", "ssa"):
            continue
        if ((st.get("tags") or {}).get("language", "") or "").lower() in sub_langs:
            out.append(st["index"])
    return out


def extract_sub(video, idx, out):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}",
                    "-c:s", "copy", out], capture_output=True, stdin=subprocess.DEVNULL, timeout=180)
    if not (os.path.exists(out) and os.path.getsize(out) > 0):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", video, "-map", f"0:{idx}", out],
                       capture_output=True, stdin=subprocess.DEVNULL, timeout=180)
    return os.path.exists(out) and os.path.getsize(out) > 0
