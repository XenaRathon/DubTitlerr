#!/usr/bin/env python3
"""Timing Compare (Phase 0): dubtitle-vs-subtitle timing analysis.

Standalone, read-only analytics tool (GPU-free -- no faster_whisper import anywhere)
that compares Whisper-generated dubtitle card timing against the embedded, human-timed
English subtitle track, to measure alignment and quantify how many "kept" cards leak
past B1's hallucination gate into a subtitle gap. See specs/timing-compare/spec-v3.md
for the full spec/schema and specs/timing-compare/tasks.md for the task breakdown.

This module (U2, tasks T2-T6; U3, T7's wiring half; U4, T9-T10) builds the analytical core
and the report:
  - CLI scaffold + show-dir walking (T2)
  - conf.json load + hardening (T3)
  - English sub-stream extraction + dialogue-track selection (T4)
  - RANSAC offset+drift line fit over nearest-onset card/cue pairs (T5)
  - slack-aware on-cue/in-gap overlap classification (T6)
  - VAD split of in-gap cards (T7 wiring): extracts each in-gap card's dub-audio window at
    its ORIGINAL (un-aligned, Whisper-timebase) [start, end] via ffmpeg and calls
    tools/vad.py's vad_probe() -- see classify_in_gap_cards() below. The VAD decision core
    itself (webrtcvad/ffmpeg-silencedetect backends) lives in tools/vad.py (T7/T8).
  - NSP/LP band bucketing, the schema_version-2 per-episode/per-show/overall report, atomic
    --out write, and the printed headline summary (T9), plus edge/aggregate null-safety
    (T10) -- see build_episode_report()/aggregate_episodes()/build_report() below.

Run from the repo root (mirrors tools/bakeoff.py's sys.path convention):
  python tools/timing_compare.py <show_dir> [<show_dir> ...]

Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import argparse
import bisect
import itertools
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile

import pysubs2

sys.path.insert(0, ".")
import common  # noqa: E402
import hallucination  # noqa: E402  -- pure stdlib (see hallucination.py docstring), no GPU import
import tools.vad as vad  # noqa: E402

log = common.log

# --- Tunables (spec-v3.md "Report schema" config block; env-overridable where noted) ---

TOLERANCE_DEFAULT = 0.30
TOLERANCE_MIN, TOLERANCE_MAX = 0.0, 2.0

MIN_CUES_DEFAULT = 50
MIN_PLAIN_SHARE_DEFAULT = 0.70

PAIR_RADIUS_DEFAULT_S = 5.0                 # nearest-onset seed pairing radius

RANSAC_INLIER_THRESHOLD_S = 0.30            # post-seed-fit inlier band (fixed, not the --tolerance CLI flag)
RANSAC_MIN_INLIERS = 10                     # offset_a_s/drift_b are null below this
RANSAC_MIN_RESIDUAL_N = 2                   # residual_median_s/iqr_s are null below this
RANSAC_EXHAUSTIVE_CAP = 60                  # <= this many pairs: try every 2-point line (deterministic)
RANSAC_MAX_RANDOM_CANDIDATES = 200          # above the cap: seeded-random 2-point sample instead
RANSAC_RANDOM_SEED = 0                      # fixed seed -> reproducible results on large inputs

LOOK_FOR_DRIFT_IQR_S = 1.0
LOOK_FOR_DRIFT_SLOPE = 0.002

DEFAULT_LANG_ENV = os.environ.get("SUB_LANGS", "eng,en,und,")


# ============================================================================
# T2 -- CLI scaffold + show-dir walking
# ============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="timing_compare.py",
        description="Compare Whisper dubtitle card timing against the embedded English "
                     "subtitle track (read-only, GPU-free). See specs/timing-compare/spec-v3.md.")
    ap.add_argument("show_dir", nargs="+",
                     help="one or more show/library directories to walk for episodes")
    ap.add_argument("--tolerance", type=float, default=TOLERANCE_DEFAULT,
                     help=f"slack-aware overlap tolerance in seconds, clamped to "
                          f"[{TOLERANCE_MIN},{TOLERANCE_MAX}] (default {TOLERANCE_DEFAULT})")
    ap.add_argument("--out", default="timing-compare.report.json",
                     help="report JSON output path (report writing lands in a later unit)")
    ap.add_argument("--lang", default=DEFAULT_LANG_ENV,
                     help="comma-separated accepted subtitle languages, lowercased "
                          "(default: env SUB_LANGS)")
    ap.add_argument("--vad", choices=("webrtcvad", "ffmpeg-silencedetect"), default="webrtcvad",
                     help="VAD backend for in-gap card speech probing (accepted now, wired in a later unit)")
    ap.add_argument("--vad-aggressiveness", type=int, choices=(0, 1, 2, 3), default=2,
                     help="webrtcvad aggressiveness 0-3 (accepted now, wired in a later unit)")
    ap.add_argument("--summary-only", action="store_true",
                     help="suppress per-episode lines, print only the run summary")
    return ap


def find_episodes(show_dirs: list) -> list:
    """Walk each show_dir for common.VIDEO_EXTS files, pruning common.EXTRA_DIRS (same
    pattern as generate.py's --root walk). Does not follow symlinks (os.walk's default,
    matching repair.py's walk). A show_dir that is itself a video file is accepted as a
    single episode (handy for ad-hoc single-file runs)."""
    videos = []
    for root in show_dirs:
        if os.path.isfile(root):
            if root.lower().endswith(common.VIDEO_EXTS):
                videos.append(root)
            continue
        if not os.path.isdir(root):
            log(f"not a file or directory, skipping: {root}")
            continue
        for dp, dns, fs in os.walk(root):
            dns[:] = [d for d in dns if d.lower() not in common.EXTRA_DIRS]
            for fn in fs:
                if fn.lower().endswith(common.VIDEO_EXTS):
                    videos.append(os.path.join(dp, fn))
    return sorted(videos)


# ============================================================================
# T3 -- conf.json load + hardening
# ============================================================================

def load_conf(path: str) -> tuple:
    """Load a <stem>.dubtitles.conf.json sidecar. Returns (status, rows):
      - missing file            -> ("no-conf", [])           (not an error, just skip)
      - unreadable/malformed    -> ("bad-conf", [])
      - otherwise               -> ("ok", cleaned_rows)       (bad rows dropped, not fatal)

    Rows with start >= end or a negative start are silently dropped (edge case in
    spec-v3.md); everything else -- including unrounded floats, extra keys like `flag`/
    `word_probs` -- is passed through untouched."""
    if not os.path.exists(path):
        return "no-conf", []
    try:
        with open(path) as f:
            rows = json.load(f)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return "bad-conf", []
    if not isinstance(rows, list):
        return "bad-conf", []
    cleaned = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            start = float(r["start"])
            end = float(r["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start >= end or start < 0:
            continue
        cleaned.append(r)
    return "ok", cleaned


# ============================================================================
# T4 -- English sub-stream extraction + dialogue-track selection
# ============================================================================
# NOTE: everything in this section does real ffmpeg/ffprobe I/O and has no ffmpeg/real
# media available in this environment to exercise it against -- PENDING manual
# verification on the server (see report). Kept deliberately thin/obvious so that
# manual review is easy.

def resolve_track_selection_thresholds() -> tuple:
    """(min_cues, min_plain_share), env-overridable (TIMING_COMPARE_MIN_CUES /
    TIMING_COMPARE_MIN_PLAIN_SHARE). Single source of truth for select_reference_track()
    AND the report's `config` block (T9) -- so the report always reflects the thresholds
    actually applied, even when overridden via env."""
    return (int(os.environ.get("TIMING_COMPARE_MIN_CUES", MIN_CUES_DEFAULT)),
            float(os.environ.get("TIMING_COMPARE_MIN_PLAIN_SHARE", MIN_PLAIN_SHARE_DEFAULT)))


def _sub_codec_map(video: str) -> dict:
    """{stream_index: codec_name} for every subtitle stream (any language) -- used only
    to label the winning reference_track's codec; common.eng_sub_streams() already
    resolved which indices qualify by language+codec, it just doesn't return codec."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s",
                             "-show_entries", "stream=index,codec_name", "-of", "json", video],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=90)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed:", video, e)
        return {}
    return {st["index"]: st.get("codec_name") for st in streams}


def select_reference_track(video: str, lang: set) -> tuple | None:
    """Pick the dialogue-dense English subtitle track for `video`. Extracts each
    candidate stream (common.eng_sub_streams) to its own tempfile.TemporaryDirectory
    (cleaned up immediately, nothing left on media), scores it with
    common.dialogue_density_score, and keeps the highest-scoring track that clears
    min_cues/min_plain_share (env-overridable via TIMING_COMPARE_MIN_CUES /
    TIMING_COMPARE_MIN_PLAIN_SHARE). Ties -> lower stream index (guaranteed by iterating
    indices ascending and only replacing on a strictly higher score).

    Returns (reference_track, cue_intervals) or None if no stream qualifies
    (`no-reference`). `reference_track` is the spec-shaped dict (stream_index, codec,
    cue_count, density_score); `cue_intervals` is the winning track's
    [(start_s, end_s, text), ...] (sorted), for T5/T6 to pair/classify against."""
    indices = common.eng_sub_streams(video, lang)
    if not indices:
        return None

    min_cues, min_plain_share = resolve_track_selection_thresholds()
    codecs = _sub_codec_map(video)

    best_track, best_cues = None, None
    for idx in indices:
        with tempfile.TemporaryDirectory() as td:
            ex = os.path.join(td, "s.ass")
            if not common.extract_sub(video, idx, ex):
                continue
            try:
                events = pysubs2.load(ex).events
            except Exception:
                continue
        cue_count, plain_share = common.dialogue_density_score(events)
        if cue_count < min_cues or plain_share < min_plain_share:
            continue
        if best_track is None or plain_share > best_track["density_score"]:
            cues = sorted((ev.start / 1000.0, ev.end / 1000.0, ev.plaintext.strip())
                          for ev in events if common.is_dialogue_event(ev))
            best_track = {"stream_index": idx, "codec": codecs.get(idx),
                          "cue_count": cue_count, "density_score": plain_share}
            best_cues = cues

    if best_track is None:
        return None
    return best_track, best_cues


# ============================================================================
# T5 -- RANSAC offset+drift fit (pure functions, no I/O, no numpy)
# ============================================================================
# numpy check: not a declared dependency (pyproject.toml lists pysubs2/faster-whisper/
# jellyfish only; numpy is present transitively via faster-whisper's stack, not ours to
# rely on). This is a 1-variable linear fit -- pure-Python closed-form least squares.

def nearest_onset_pairs(card_starts: list, cue_starts: list, max_radius_s: float = PAIR_RADIUS_DEFAULT_S) -> list:
    """Pair each card onset (index ci into card_starts) to its nearest cue onset (index
    cj into cue_starts) within max_radius_s. Tie -> earlier cue (lower cue_starts[cj]),
    then lower cue index. A card with no cue onset within radius is omitted.

    Requires cue_starts sorted ascending (as common.dialogue_intervals()/
    select_reference_track() already return them) -- nearest-neighbor-in-sorted-array
    via bisect, O(len(card_starts) * log(len(cue_starts))).

    Returns [(card_i, cue_j, delta), ...] where delta = cue_starts[cue_j] - card_starts[card_i].
    """
    pairs = []
    for ci, ct in enumerate(card_starts):
        pos = bisect.bisect_left(cue_starts, ct)
        candidates = [j for j in (pos - 1, pos) if 0 <= j < len(cue_starts)]
        best_j = best_ad = best_delta = None
        for cj in candidates:
            kt = cue_starts[cj]
            d = kt - ct
            ad = abs(d)
            if ad > max_radius_s:
                continue
            if (best_j is None or ad < best_ad
                    or (ad == best_ad and (kt < cue_starts[best_j]
                                            or (kt == cue_starts[best_j] and cj < best_j)))):
                best_j, best_ad, best_delta = cj, ad, d
        if best_j is not None:
            pairs.append((ci, best_j, best_delta))
    return pairs


def resolve_pairs(card_starts: list, cue_starts: list, index_pairs: list) -> list:
    """Trivial glue: resolve nearest_onset_pairs()'s (card_i, cue_j, delta) index output
    into the (card_start, cue_start) value pairs ransac_offset_drift() fits over. Kept as
    its own (pure) function so each stage -- pairing, resolving, fitting -- is
    independently testable without needing real card/cue lists end-to-end."""
    return [(card_starts[ci], cue_starts[cj]) for ci, cj, _delta in index_pairs]


def _fit_line_ls(xs: list, ys: list):
    """Closed-form ordinary-least-squares slope/intercept for y = a + b*x (pure Python,
    no numpy). Returns (a, b), or None if there are fewer than 2 points or all x are
    identical (slope undefined)."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = mean_y - b * mean_x
    return a, b


def _residuals(xs: list, ys: list, a: float, b: float) -> list:
    return [y - (a + b * x) for x, y in zip(xs, ys)]


def _iqr(sorted_values: list):
    if len(sorted_values) < 2:
        return None
    try:
        q1, _q2, q3 = statistics.quantiles(sorted_values, n=4)
    except statistics.StatisticsError:
        return None
    return q3 - q1


def ransac_offset_drift(pairs: list, threshold_s: float = RANSAC_INLIER_THRESHOLD_S,
                         min_inliers: int = RANSAC_MIN_INLIERS, seed: int = RANSAC_RANDOM_SEED) -> dict:
    """Fit offset(t) = a + b*t over (card_start, cue_start) pairs -- t is card_start, the
    fitted quantity is (card_start - cue_start) -- robust to outliers.

    `pairs` is a list of (card_start, cue_start) value tuples: normally
    resolve_pairs(card_starts, cue_starts, nearest_onset_pairs(...)), but this function
    takes raw value pairs directly so it's independently unit-testable with synthetic data.

    Algorithm (deterministic, no numpy): consider every 2-point line through the pairs
    (exhaustive if len(pairs) <= RANSAC_EXHAUSTIVE_CAP, else a fixed-seed random sample of
    up to RANSAC_MAX_RANDOM_CANDIDATES pairs so large episodes stay fast) as a RANSAC
    candidate model; score each by its inlier count (|residual| <= threshold_s); keep the
    candidate with the most inliers; refit by ordinary least squares on that inlier set
    (spec-v3.md's "seed -> keep inliers -> refit"). Fixed seed -> reproducible results.

    Returns a dict: offset_a_s, drift_b (None if inlier_count < min_inliers),
    matched_pairs_count, inlier_count, residual_median_s, residual_iqr_s (None if
    inlier_count < RANSAC_MIN_RESIDUAL_N), look_for_drift (residual iqr > 1.0 s OR
    |drift_b| > 0.002, either half False/skipped when its input is None)."""
    matched = len(pairs)
    result = {"offset_a_s": None, "drift_b": None, "matched_pairs_count": matched,
              "inlier_count": 0, "residual_median_s": None, "residual_iqr_s": None,
              "look_for_drift": False}
    if matched < 2:
        return result

    xs = [c for c, _k in pairs]
    ys = [c - k for c, k in pairs]              # offset(t) target: card_start - cue_start
    idxs = list(range(matched))

    if matched <= RANSAC_EXHAUSTIVE_CAP:
        candidates = list(itertools.combinations(idxs, 2))
    else:
        rng = random.Random(seed)
        seen = set()
        while len(seen) < min(RANSAC_MAX_RANDOM_CANDIDATES, matched * (matched - 1) // 2):
            i, j = rng.sample(idxs, 2)
            seen.add((min(i, j), max(i, j)))
        candidates = list(seen)

    best_inliers = []
    for i, j in candidates:
        if xs[i] == xs[j]:
            continue                             # vertical/degenerate 2-point line
        b = (ys[j] - ys[i]) / (xs[j] - xs[i])
        a = ys[i] - b * xs[i]
        inliers = [k for k in idxs if abs(ys[k] - (a + b * xs[k])) <= threshold_s]
        if len(inliers) > len(best_inliers):
            best_inliers = inliers

    if len(best_inliers) < 2:
        # No usable 2-point seed line (e.g. every x identical) -- fall back to a plain
        # OLS fit over everything as the best-effort inlier set.
        fit = _fit_line_ls(xs, ys)
        if fit is None:
            return result
        a, b = fit
        resid = _residuals(xs, ys, a, b)
        inliers = [k for k in idxs if abs(resid[k]) <= threshold_s]
        if len(inliers) < 2:
            inliers = idxs                       # still nothing better -- use every point
    else:
        inliers = best_inliers

    ix = [xs[k] for k in inliers]
    iy = [ys[k] for k in inliers]
    refit = _fit_line_ls(ix, iy)
    if refit is None:
        return result
    a, b = refit

    inlier_count = len(inliers)
    result["inlier_count"] = inlier_count
    if inlier_count >= min_inliers:
        result["offset_a_s"] = a
        result["drift_b"] = b
    if inlier_count >= RANSAC_MIN_RESIDUAL_N:
        resid_sorted = sorted(_residuals(ix, iy, a, b))
        result["residual_median_s"] = statistics.median(resid_sorted)
        result["residual_iqr_s"] = _iqr(resid_sorted)
        iqr_drift = result["residual_iqr_s"] is not None and result["residual_iqr_s"] > LOOK_FOR_DRIFT_IQR_S
        slope_drift = result["drift_b"] is not None and abs(result["drift_b"]) > LOOK_FOR_DRIFT_SLOPE
        result["look_for_drift"] = bool(iqr_drift or slope_drift)
    return result


# ============================================================================
# T6 -- slack-aware on-cue/in-gap overlap classification (pure)
# ============================================================================

def classify_overlap(card_start: float, card_end: float, cue_start: float, cue_end: float,
                      tolerance: float) -> bool:
    """Slack-aware overlap test: True if [card_start, card_end] intersects
    [cue_start, cue_end] once each cue edge is loosened by `tolerance` seconds --
    max(0, min(card_end, cue_end+t) - max(card_start, cue_start-t)) > 0."""
    return max(0.0, min(card_end, cue_end + tolerance) - max(card_start, cue_start - tolerance)) > 0.0


def align_card(card_start: float, card_end: float, fit: dict) -> tuple:
    """Apply the fitted offset+drift model to a card: aligned_t = t - (a + b*t) for both
    start and end. When the fit has no confident offset (offset_a_s is None, i.e.
    inlier_count < RANSAC_MIN_INLIERS), alignment is skipped (treated as offset 0, drift 0)
    and low_confidence is reported True so callers/reports can flag it.

    Returns (aligned_start, aligned_end, low_confidence)."""
    a = fit.get("offset_a_s")
    b = fit.get("drift_b")
    low_confidence = a is None
    if a is None:
        a = 0.0
    if b is None:
        b = 0.0
    aligned_start = card_start - (a + b * card_start)
    aligned_end = card_end - (a + b * card_end)
    return aligned_start, aligned_end, low_confidence


def classify_card(aligned_start: float, aligned_end: float, cue_intervals: list, tolerance: float) -> str:
    """'on-cue' if the aligned card overlaps ANY cue in cue_intervals (slack-aware,
    classify_overlap), else 'in-gap'. cue_intervals: [(start_s, end_s, text), ...]."""
    for cue_start, cue_end, _text in cue_intervals:
        if classify_overlap(aligned_start, aligned_end, cue_start, cue_end, tolerance):
            return "on-cue"
    return "in-gap"


def covered_cue_count(cards: list, cue_intervals: list, tolerance: float) -> int:
    """Count of cue_intervals overlapped (slack-aware, classify_overlap) by at least one
    card's aligned_start/aligned_end. Feeds the report's pct_cues_covered (T9). Pure, no
    I/O; in-gap cards contribute nothing by construction (classify_card already found no
    overlap for them), so scanning every card here (not just on-cue ones) is harmless and
    keeps this function independent of classify_card's own bookkeeping.
    O(len(cards) * len(cue_intervals)) -- fine at per-episode scale (hundreds of each)."""
    if not cards or not cue_intervals:
        return 0
    count = 0
    for cue_start, cue_end, _text in cue_intervals:
        if any(classify_overlap(c["aligned_start"], c["aligned_end"], cue_start, cue_end, tolerance)
               for c in cards):
            count += 1
    return count


# ============================================================================
# T7 (wiring half) -- VAD split of in-gap cards. select_audio_stream/extract_audio_window
# do real ffmpeg/ffprobe I/O with no real media available in this environment -- PENDING
# manual verification on the server (see the report), same status as T4's
# select_reference_track/_sub_codec_map above. classify_in_gap_cards()'s orchestration
# logic (verdict mapping, on-cue cards left untouched, no-audio-stream fallback) IS
# covered by tests/test_timing_compare.py via monkeypatching, same pattern as
# process_episode()'s own tests monkeypatch select_reference_track.
# ============================================================================

VAD_AUDIO_LANG = ("eng", "en")          # the dub audio track is always English (or the
                                         # sole audio track) -- independent of --lang,
                                         # which is the *subtitle* language allowlist.

IN_GAP_VERDICT = {True: "in_gap_speech", False: "in_gap_silent", None: "in_gap_vad_error"}


def select_audio_stream(video: str):
    """Pick the dub audio stream index to VAD-probe. Mirrors generate.py's
    eng_audio_index() exactly (same eng/en tag preference, same REQUIRE_ENG-gated
    fallback to the first audio stream) so the VAD probe listens to the SAME audio Whisper
    actually transcribed -- not a guess at which track is the dub. Deliberately NOT
    imported from generate.py: generate.py does `from faster_whisper import WhisperModel`
    at module scope, and this tool's GPU-free / no-faster_whisper-import acceptance
    criterion (spec-v3.md) forbids pulling that in, even transitively.

    Returns the stream index, or None if ffprobe fails or there's no usable audio stream
    (REQUIRE_ENG=1, the default, requires an eng/en tag; REQUIRE_ENG=0 falls back to the
    first audio stream of any language, matching generate.py's own env gate)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                             "-show_entries", "stream=index:stream_tags=language",
                             "-of", "json", video], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=90)
        streams = json.loads(r.stdout).get("streams", [])
    except Exception as e:
        log("ffprobe failed (audio):", video, e)
        return None
    eng = [s for s in streams if ((s.get("tags") or {}).get("language", "") or "").lower() in VAD_AUDIO_LANG]
    if eng:
        return eng[0]["index"]
    if os.environ.get("REQUIRE_ENG", "1") == "1":
        return None
    return streams[0]["index"] if streams else None


def extract_audio_window(video: str, audio_idx: int, start_s: float, end_s: float, out_wav: str) -> bool:
    """Extract dub audio stream `audio_idx`'s [start_s, end_s) window to 16 kHz mono
    pcm_s16le -- generate.py's extract_wav() encode settings, but windowed via -ss/-to
    (both as input options: ffmpeg treats -to as an absolute timestamp on the original
    timeline in that position, so this yields exactly [start_s, end_s), not
    [start_s, start_s+end_s)). Input-side -ss is sample-accurate for audio-only extraction
    (no keyframe dependency the way video seeking has), so no re-encode-then-trim needed.

    start_s/end_s MUST be the card's ORIGINAL Whisper-timebase [start, end] -- the audio
    Whisper actually heard -- NOT the RANSAC-aligned timestamps; the offset/drift model
    exists only to compare against the *cue* timeline (T5/T6), never to shift where we
    listen on the dub audio itself (spec-v3.md's VAD acceptance criterion is explicit
    about this). Returns False (never raises) on any ffmpeg failure or empty output."""
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", str(start_s), "-to", str(end_s),
           "-i", video, "-map", f"0:{audio_idx}", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    except Exception as e:
        log("ffmpeg audio window extract failed:", video, start_s, end_s, e)
        return False
    return os.path.exists(out_wav) and os.path.getsize(out_wav) > 0


def classify_in_gap_cards(video: str, cards: list, vad_backend: str = "webrtcvad",
                           vad_aggressiveness: int = 2) -> None:
    """Mutates `cards` in place: for every card whose classify_card() result is "in-gap",
    VAD-probes its dub-audio window (card's ORIGINAL [start, end], not aligned_start/
    aligned_end -- see extract_audio_window()) and sets
    card["in_gap_vad_verdict"] = "in_gap_silent" | "in_gap_speech" | "in_gap_vad_error".

    "on-cue" cards are left completely untouched -- no `in_gap_vad_verdict` key is added --
    per spec-v3.md's constraint that the VAD path only ADDS information to in-gap cards and
    can never change T6's on-cue/in-gap classification.

    The dub audio stream is resolved ONCE per episode (select_audio_stream), not once per
    card. If no usable audio stream is found (or ffprobe fails), every in-gap card gets
    in_gap_vad_error without attempting extraction -- still no crash, still keeps going.
    All extraction happens into one per-episode tempfile.TemporaryDirectory, removed on
    return (no sidecar left on the media tree, matching T4's extraction convention)."""
    in_gap = [c for c in cards if c.get("classification") == "in-gap"]
    if not in_gap:
        return
    audio_idx = select_audio_stream(video)
    if audio_idx is None:
        for c in in_gap:
            c["in_gap_vad_verdict"] = "in_gap_vad_error"
        return
    with tempfile.TemporaryDirectory() as td:
        for i, c in enumerate(in_gap):
            wav = os.path.join(td, f"gap_{i}.wav")
            verdict = None
            if extract_audio_window(video, audio_idx, c["start"], c["end"], wav):
                verdict = vad.vad_probe(wav, aggressiveness=vad_aggressiveness, backend=vad_backend)
            c["in_gap_vad_verdict"] = IN_GAP_VERDICT[verdict]


# ============================================================================
# Per-episode orchestration -- wires T3-T7 together. Produces the per-episode data
# structure U4 (report/aggregates) will consume; see the report for the exact shape. Not
# itself unit-tested here (it's the ffmpeg/track-selection/VAD I/O seam -- PENDING manual
# verification, see the report).
# ============================================================================

def process_episode(video: str, lang: set, tolerance: float, pair_radius_s: float = PAIR_RADIUS_DEFAULT_S,
                     vad_backend: str = "webrtcvad", vad_aggressiveness: int = 2) -> dict:
    stem, _ext = os.path.splitext(video)
    conf_path = stem + ".dubtitles.conf.json"
    status, rows = load_conf(conf_path)
    if status in ("no-conf", "bad-conf"):
        return {"video": video, "status": status}

    ref = select_reference_track(video, lang)
    if ref is None:
        return {"video": video, "status": "no-reference"}
    reference_track, cue_intervals = ref

    if not rows:                                  # empty conf.json: analyzed, 0 cards, no crash
        return {"video": video, "status": "analyzed", "reference_track": reference_track,
                "fit": ransac_offset_drift([]), "cue_count": len(cue_intervals), "cards": [],
                "cues_covered": 0}

    card_starts = [r["start"] for r in rows]
    cue_starts = [c[0] for c in cue_intervals]
    index_pairs = nearest_onset_pairs(card_starts, cue_starts, max_radius_s=pair_radius_s)
    value_pairs = resolve_pairs(card_starts, cue_starts, index_pairs)
    fit = ransac_offset_drift(value_pairs)

    cards = []
    for r in rows:
        aligned_start, aligned_end, low_conf = align_card(r["start"], r["end"], fit)
        classification = classify_card(aligned_start, aligned_end, cue_intervals, tolerance)
        card = dict(r)
        card["aligned_start"] = round(aligned_start, 3)
        card["aligned_end"] = round(aligned_end, 3)
        card["classification"] = classification          # "on-cue" | "in-gap"
        card["low_confidence_alignment"] = low_conf
        cards.append(card)

    # T7: split "in-gap" cards into in_gap_silent/in_gap_speech/in_gap_vad_error via an
    # independent VAD probe of each card's dub-audio window, at the card's ORIGINAL
    # (un-aligned) [r["start"], r["end"]] -- classify_in_gap_cards() reads `card["start"]`/
    # `card["end"]` (the untouched conf.json row values `dict(r)` copied above), never
    # `aligned_start`/`aligned_end`. Sets card["in_gap_vad_verdict"] in place; on-cue cards
    # are untouched (no key added). Mutates `cards`, which is already the return value.
    classify_in_gap_cards(video, cards, vad_backend=vad_backend, vad_aggressiveness=vad_aggressiveness)

    # T9: cues_covered feeds the report's pct_cues_covered. Computed from aligned_start/
    # aligned_end, same as classification -- so it reflects the fitted model, not raw
    # Whisper timestamps.
    cues_covered = covered_cue_count(cards, cue_intervals, tolerance)

    return {"video": video, "status": "analyzed", "reference_track": reference_track,
            "fit": fit, "cue_count": len(cue_intervals), "cards": cards,
            "cues_covered": cues_covered}


# ============================================================================
# T9/T10 -- band bucketing + schema_version-2 report/aggregate builder (pure functions;
# no I/O -- take process_episode()-shaped `res` dicts, real or synthetic). Cutpoints match
# hallucination.py's B1 gate exactly (imported, not re-hardcoded) so the report's bucket
# labels line up with the thresholds that actually decided drop/flag/keep upstream.
# ============================================================================

def bucket_nsp(nsp: float) -> str:
    """Bucket a kept card's no_speech_prob against hallucination.py's NSP_FLAG/NSP_DROP,
    STRICT per spec-v3.md: <=0.5 clean, >0.5 and <=0.95 flag, >0.95 drop."""
    if nsp <= hallucination.NSP_FLAG:            # <= 0.5
        return "clean_le_0.5"
    if nsp <= hallucination.NSP_DROP:             # 0.5 < nsp <= 0.95
        return "flag_gt_0.5_le_0.95"
    return "drop_gt_0.95"                         # > 0.95


def bucket_lp(lp: float) -> str:
    """Bucket a kept card's avg_logprob against hallucination.py's LP_FLAG/LP_DROP, STRICT
    per spec-v3.md: >=-0.6 clean, <-0.6 and >=-2.0 flag, <-2.0 drop."""
    if lp >= hallucination.LP_FLAG:               # >= -0.6
        return "clean_ge_-0.6"
    if lp >= hallucination.LP_DROP:               # -2.0 <= lp < -0.6
        return "flag_lt_-0.6_ge_-2.0"
    return "drop_lt_-2.0"                         # < -2.0


def build_episode_report(res: dict) -> dict:
    """Build the schema_version-2 per-episode report object (spec-v3.md's "Report schema"
    block) from a process_episode()-shaped `res` dict. Pure/hermetic -- takes `res` as-is
    (real or synthetic), no I/O.

    Non-"analyzed" statuses (no-conf/bad-conf/no-reference) carry no card/fit/reference
    data to report, so they collapse to a bare {"status": status}.

    Null semantics (T10, spec-v3.md Edge-cases table):
      - pct_cards_on_cue / pct_cues_covered: null when the episode has 0 kept cards (empty
        conf.json) or (for cues_covered) 0 cues -- division is undefined, not a crash.
      - false_in_gap_rate: 0.0 (via max(1, total)) in the ordinary case, but null in the
        specific case where the episode HAS in-gap cards and EVERY one of them came back
        in_gap_vad_error (both VAD backends failed/unavailable) -- reporting 0.0 there would
        misleadingly read as "no false-in-gap risk" when it's actually "unmeasured"."""
    status = res["status"]
    if status != "analyzed":
        return {"status": status}

    cards = res.get("cards", [])
    fit = res["fit"]
    total = len(cards)
    on_cue = [c for c in cards if c["classification"] == "on-cue"]
    in_gap = [c for c in cards if c["classification"] == "in-gap"]

    pct_cards_on_cue = (len(on_cue) / total) if total else None
    cue_count = res.get("cue_count", 0)
    cues_covered = res.get("cues_covered", 0)
    pct_cues_covered = (cues_covered / cue_count) if (total and cue_count) else None

    by_nsp = {"clean_le_0.5": 0, "flag_gt_0.5_le_0.95": 0, "drop_gt_0.95": 0}
    by_lp = {"clean_ge_-0.6": 0, "flag_lt_-0.6_ge_-2.0": 0, "drop_lt_-2.0": 0}
    by_flag = {"maybe_silence": 0, "low_conf": 0, "none": 0}
    in_gap_silent = in_gap_speech = in_gap_vad_error = 0
    for c in in_gap:
        by_nsp[bucket_nsp(c.get("no_speech_prob", 0.0))] += 1
        by_lp[bucket_lp(c.get("avg_logprob", 0.0))] += 1
        flag_key = c.get("flag") or "none"
        by_flag[flag_key] = by_flag.get(flag_key, 0) + 1
        verdict = c.get("in_gap_vad_verdict")
        if verdict == "in_gap_silent":
            in_gap_silent += 1
        elif verdict == "in_gap_speech":
            in_gap_speech += 1
        elif verdict == "in_gap_vad_error":            # never merged into silent/speech (T10)
            in_gap_vad_error += 1

    if in_gap and in_gap_speech == 0 and in_gap_silent == 0:
        # every in-gap card is vad_error -- both VAD backends failed/unavailable for this
        # whole episode; the true rate is unmeasured, not zero (spec-v3.md Edge-cases).
        false_in_gap_rate = None
    else:
        false_in_gap_rate = in_gap_speech / max(1, total)

    maybe_silence = [c for c in cards if c.get("flag") == "maybe_silence"]
    flag_validation = {
        "maybe_silence_in_gap": sum(1 for c in maybe_silence if c["classification"] == "in-gap"),
        "maybe_silence_on_cue": sum(1 for c in maybe_silence if c["classification"] == "on-cue"),
    }

    return {
        "status": "analyzed",
        "offset_a_s": fit["offset_a_s"], "drift_b": fit["drift_b"],
        "matched_pairs_count": fit["matched_pairs_count"], "inlier_count": fit["inlier_count"],
        "residual_median_s": fit["residual_median_s"], "residual_iqr_s": fit["residual_iqr_s"],
        "look_for_drift": fit["look_for_drift"],
        "pct_cards_on_cue": pct_cards_on_cue, "pct_cues_covered": pct_cues_covered,
        "kept_in_gap": {
            "total": len(in_gap), "in_gap_silent": in_gap_silent, "in_gap_speech": in_gap_speech,
            "in_gap_vad_error": in_gap_vad_error, "by_nsp": by_nsp, "by_lp": by_lp, "by_flag": by_flag,
        },
        "false_in_gap_rate": false_in_gap_rate,
        "flag_validation": flag_validation,
        "reference_track": res["reference_track"],
    }


STATUS_TO_COUNT_KEY = {"no-conf": "no_conf", "no-reference": "no_reference",
                        "bad-conf": "bad_conf", "analyzed": "analyzed"}


def aggregate_episodes(results: list) -> dict:
    """Aggregate a list of process_episode()-shaped `res` dicts into a schema_version-2
    aggregate object (spec-v3.md) -- used IDENTICALLY for both the per-show and the overall
    aggregate (same shape, just a different slice of `results`), so the two levels can never
    drift out of sync. Pure/hermetic -- operates on the raw `res` dicts (not the polished
    per-episode report shape), so it can pool card counts across episodes directly.

    Status counts (no_conf/no_reference/bad_conf/analyzed) are always numeric, even when
    every episode is no-reference (T10). applicability_ratio = analyzed / (analyzed +
    no_reference), null only if that denominator itself is 0 (no analyzed AND no
    no-reference episodes at all -- e.g. a show that's entirely no-conf/bad-conf).
    pct_cards_on_cue / false_in_gap_rate are pooled ratios (total on-cue / speech cards over
    total kept cards across all analyzed episodes in `results`) and null whenever that pool
    is empty (0 kept cards) -- covers both "zero analyzed episodes" (T10's headline edge
    case) and "analyzed episodes exist but every one has an empty conf.json". Mirrors
    build_episode_report's other null rule too: if the pool has in-gap cards but EVERY one
    is `in_gap_vad_error` (both VAD backends failed/unavailable across the whole pool),
    false_in_gap_rate is null (unmeasured), not a misleading 0.0 -- also surfaced via the
    in_gap_silent/in_gap_vad_error totals so a reader can see the pool was unmeasured."""
    counts = {"no_conf": 0, "no_reference": 0, "bad_conf": 0, "analyzed": 0}
    total_cards = on_cue_cards = kept_in_gap_total = 0
    in_gap_speech_total = in_gap_silent_total = in_gap_vad_error_total = 0
    for res in results:
        counts[STATUS_TO_COUNT_KEY.get(res["status"], res["status"])] += 1
        if res["status"] != "analyzed":
            continue
        cards = res.get("cards", [])
        total_cards += len(cards)
        on_cue_cards += sum(1 for c in cards if c["classification"] == "on-cue")
        in_gap = [c for c in cards if c["classification"] == "in-gap"]
        kept_in_gap_total += len(in_gap)
        in_gap_speech_total += sum(1 for c in in_gap if c.get("in_gap_vad_verdict") == "in_gap_speech")
        in_gap_silent_total += sum(1 for c in in_gap if c.get("in_gap_vad_verdict") == "in_gap_silent")
        in_gap_vad_error_total += sum(
            1 for c in in_gap if c.get("in_gap_vad_verdict") == "in_gap_vad_error")

    denom = counts["analyzed"] + counts["no_reference"]
    applicability_ratio = (counts["analyzed"] / denom) if denom else None
    pct_cards_on_cue = (on_cue_cards / total_cards) if total_cards else None
    if kept_in_gap_total > 0 and in_gap_speech_total == 0 and in_gap_silent_total == 0:
        # every in-gap card in the pool is vad_error -- both VAD backends failed/unavailable
        # for the whole pool; the true rate is unmeasured, not zero (mirrors
        # build_episode_report's per-episode rule; happens e.g. whenever webrtcvad is
        # unavailable, including the dev venv and any server run before the wheel is built).
        false_in_gap_rate = None
    else:
        false_in_gap_rate = (in_gap_speech_total / total_cards) if total_cards else None

    return {
        "no_conf": counts["no_conf"], "no_reference": counts["no_reference"],
        "bad_conf": counts["bad_conf"], "analyzed": counts["analyzed"],
        "applicability_ratio": applicability_ratio,
        "pct_cards_on_cue": pct_cards_on_cue,
        "kept_in_gap": kept_in_gap_total,
        "in_gap_speech": in_gap_speech_total,
        "in_gap_silent": in_gap_silent_total,
        "in_gap_vad_error": in_gap_vad_error_total,
        "false_in_gap_rate": false_in_gap_rate,
    }


def build_report(show_results: dict, config: dict) -> dict:
    """Assemble the full schema_version-2 report (spec-v3.md) from {show_name: [res, ...]}
    (process_episode()-shaped raw results grouped by show, insertion order preserved) plus
    the resolved CLI `config` block. Pure -- no I/O; writing --out and printing the summary
    are main()'s job (write_report_atomic()/print_summary() below)."""
    shows = {}
    for show_name, results in show_results.items():
        episodes = {os.path.basename(res["video"]): build_episode_report(res) for res in results}
        shows[show_name] = {"episodes": episodes, "aggregate": aggregate_episodes(results)}
    all_results = [res for results in show_results.values() for res in results]
    return {"schema_version": 2, "config": config, "shows": shows,
            "aggregate": aggregate_episodes(all_results)}


def write_report_atomic(report: dict, out_path: str) -> None:
    """Write `report` as JSON to out_path atomically (tempfile in the same dir + os.replace)
    so a crash mid-write never leaves a truncated/partial report on disk."""
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, prefix=".timing-compare.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _fmt(x) -> str:
    if x is None:
        return "null"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def _log_aggregate_headline(label: str, agg: dict) -> None:
    log(f"[{label}] applicability_ratio={_fmt(agg['applicability_ratio'])} "
        f"pct_cards_on_cue={_fmt(agg['pct_cards_on_cue'])} "
        f"kept_in_gap.total={agg['kept_in_gap']} in_gap_speech={agg['in_gap_speech']} "
        f"false_in_gap_rate={_fmt(agg['false_in_gap_rate'])}")


def print_summary(report: dict) -> None:
    """Print the headline per-show + overall summary (spec-v3.md): applicability_ratio,
    pct_cards_on_cue, kept_in_gap.total, in_gap_speech, false_in_gap_rate."""
    for show_name, show in report["shows"].items():
        _log_aggregate_headline(show_name, show["aggregate"])
    _log_aggregate_headline("OVERALL", report["aggregate"])


def show_name_for_root(root: str) -> str:
    """Derive a show grouping key from a CLI show_dir argument: the directory's basename
    (trailing slash stripped), or -- when `root` is itself a single video file (find_episodes
    accepts that for ad-hoc single-file runs) -- its parent directory's basename."""
    root = root.rstrip(os.sep)
    if os.path.isfile(root):
        root = os.path.dirname(root) or root
    return os.path.basename(root) or root


# ============================================================================
# main
# ============================================================================

def main(argv=None):
    ap = build_arg_parser()
    a = ap.parse_args(argv)
    tolerance = max(TOLERANCE_MIN, min(TOLERANCE_MAX, a.tolerance))
    if tolerance != a.tolerance:
        log(f"--tolerance {a.tolerance} out of [{TOLERANCE_MIN},{TOLERANCE_MAX}], "
            f"clamped to {tolerance}")
    # Mirror common.SUB_LANGS's construction (no `if s.strip()` filter): the default
    # "eng,en,und," must keep the blank token so untagged subtitle streams (language ==
    # "", as returned by common.eng_sub_streams for streams with no language tag) match
    # here the same way they do in the rest of the pipeline. Dropping "" here would make
    # this tool's --lang stricter than common.SUB_LANGS, wrongly marking episodes whose
    # only usable dialogue track is untagged as no-reference.
    lang = {s.strip().lower() for s in a.lang.split(",")}
    min_cues, min_plain_share = resolve_track_selection_thresholds()

    # Group by CLI show_dir root (not a single combined find_episodes(a.show_dir) walk) so
    # the report's "shows" key can name each root -- see show_name_for_root().
    show_results: dict = {}
    results = []
    for root in a.show_dir:
        show_name = show_name_for_root(root)
        for video in find_episodes([root]):
            res = process_episode(video, lang, tolerance, vad_backend=a.vad,
                                   vad_aggressiveness=a.vad_aggressiveness)
            results.append(res)
            show_results.setdefault(show_name, []).append(res)
            if not a.summary_only:
                log(f"{res['status']:12} {video}")

    config = {"tolerance_s": tolerance, "min_cues": min_cues, "min_plain_share": min_plain_share,
              "pair_radius_s": PAIR_RADIUS_DEFAULT_S, "vad_backend": a.vad,
              "vad_aggressiveness": a.vad_aggressiveness}
    report = build_report(show_results, config)
    write_report_atomic(report, a.out)
    print_summary(report)
    log(f"wrote {a.out}")
    return results


if __name__ == "__main__":
    main()
