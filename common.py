#!/usr/bin/env python3
"""Shared stdlib-only helpers for the DubTitlerr pipeline stages (generate.py, mux.py,
repair.py, dub_signs_merge.py, mine_glossary.py, recreate_srt.py).

Single source of truth for the helpers that used to be duplicated per-module (see
specs/v1-polish/spec.md, Phase 1 — Foundation). Stdlib + pysubs2: no imports from other
project modules, so any pipeline stage can import this without dragging in the rest
of the pipeline (and without risking a circular import).
"""
import json
import os
import re
import subprocess
import tempfile

import pysubs2

MEDIA_UID = int(os.environ.get("MEDIA_UID", "1000"))
MEDIA_GID = int(os.environ.get("MEDIA_GID", "100"))

# OUTPUT_ROOT: write sidecars/output files to this branch path instead of next to the
# source media, so writes land on a disk with space (mergerfs unifies branches, so the
# file still shows next to the source in the pool view). READS still use MEDIA_ROOT.
# Empty OUTPUT_ROOT = write in place.
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/media")
OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "")

VIDEO_EXTS = (".mkv", ".mp4", ".m4v")

# SUB_LANGS: accepted embedded-sub languages for dialogue_intervals()'s default (all-stream)
# path -- same env var/default repair.py has always read (T1 hoist: single source of truth).
SUB_LANGS = set(os.environ.get("SUB_LANGS", "eng,en,und,").split(","))

# Dialogue-vs-sign/karaoke predicate (hoisted verbatim from repair.py's pre-refactor
# dialogue_intervals -- do not tweak without checking dub_signs_merge.py's classifier too,
# which uses a related but NOT identical KEEP_STYLE/DROP_STYLE pair for its own purpose).
KARAOKE = re.compile(r"\\[kK][fo]?\d")
POSITIONED = re.compile(r"\\(?:pos|move)\(|\\an[134567 89]")
DROP_STYLE = re.compile(r"warning", re.I)        # junk, never a dialogue reference
DIALOGUE_EXCLUDE_STYLE = re.compile(
    r"karaoke|translat|sign|song|caption|title|credit|note|lyric|romaji|kashi|insert", re.I)

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


def is_dialogue_event(ev: "pysubs2.SSAEvent", txt: str | None = None) -> bool:
    """True if a pysubs2 event is a *plain dialogue* line -- not a comment, not a
    positioned/animated sign, not karaoke, and not on an excluded (sign/song/karaoke/etc.)
    style -- and has non-empty rendered text. This is the exact predicate T1 hoisted out of
    repair.py's pre-refactor dialogue_intervals(); reused by dialogue_intervals(),
    dialogue_event_count(), and the pure dialogue_density_score() scorer below.

    ``txt``, if given, is the caller's already-computed ``ev.plaintext.strip()`` -- lets a
    caller that also needs the stripped text (dialogue_intervals) avoid recomputing it here.
    Default (None) computes it internally, so every other call site is unaffected."""
    if ev.is_comment:
        return False
    t = ev.text
    if KARAOKE.search(t) or POSITIONED.search(t):        # sign/song, not dialogue
        return False
    style = ev.style or ""
    if DIALOGUE_EXCLUDE_STYLE.search(style) or DROP_STYLE.search(style):
        return False
    return bool(txt if txt is not None else ev.plaintext.strip())


def _load_stream_events(video, idx):
    """Extract subtitle stream ``idx`` to a scratch .ass and return its pysubs2 events, or
    ``[]`` on any extraction/parse failure (never raises) -- matches the original
    repair.dialogue_intervals try/except-and-skip behavior exactly."""
    with tempfile.TemporaryDirectory() as td:
        ex = os.path.join(td, "s.ass")
        if not extract_sub(video, idx, ex):
            return []
        try:
            return pysubs2.load(ex).events
        except Exception:
            return []


def dialogue_intervals(video, stream_indices=None):
    """Embedded DIALOGUE lines (the translation track) as (start_s, end_s, text), sorted.

    ``stream_indices=None`` (default) reproduces the exact pre-hoist repair.py behavior:
    every English subtitle stream (``eng_sub_streams(video, SUB_LANGS)``) is scanned and
    the results merged/sorted together. Pass an explicit iterable of stream indices to
    score/scan just those streams (e.g. one candidate track at a time, for per-track
    density scoring) -- the byte-identical default path is what repair.py's live callers
    (``process``/``overlap_ref``) depend on."""
    indices = eng_sub_streams(video, SUB_LANGS) if stream_indices is None else stream_indices
    ivals = []
    for idx in indices:
        for ev in _load_stream_events(video, idx):
            txt = ev.plaintext.strip()
            if is_dialogue_event(ev, txt):
                ivals.append((ev.start / 1000.0, ev.end / 1000.0, txt))
    ivals.sort()
    return ivals


def dialogue_event_count(video, stream_index: int) -> int:
    """Count of plain-dialogue cues on a single subtitle stream (see is_dialogue_event)."""
    return sum(1 for ev in _load_stream_events(video, stream_index) if is_dialogue_event(ev))


def dialogue_density_score(events: list) -> tuple:
    """Pure scorer over a pre-loaded list of pysubs2.SSAEvent (no I/O): returns
    ``(dialogue_cue_count, plain_event_share)`` where ``dialogue_cue_count`` is the number
    of plain-dialogue events (is_dialogue_event) and ``plain_event_share`` is that count
    divided by the number of non-comment events on the track -- i.e. how much of the track
    is dialogue versus signs/karaoke/songs. ``(0, 0.0)`` for an empty or all-comment track."""
    non_comment = [ev for ev in events if not ev.is_comment]
    if not non_comment:
        return (0, 0.0)
    dialogue_count = sum(1 for ev in non_comment if is_dialogue_event(ev))
    return (dialogue_count, dialogue_count / len(non_comment))
