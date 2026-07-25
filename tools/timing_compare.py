#!/usr/bin/env python3
"""Timing Compare (Phase 0): dubtitle-vs-subtitle timing analysis.

Standalone, read-only analytics tool (GPU-free -- no faster_whisper import anywhere)
that compares Whisper-generated dubtitle card timing against the embedded, human-timed
English subtitle track, to measure alignment and quantify how many "kept" cards leak
past B1's hallucination gate into a subtitle gap. See specs/timing-compare/spec-v3.md
for the full spec/schema and specs/timing-compare/tasks.md for the task breakdown.

This module (U2, tasks T2-T6) builds the analytical core:
  - CLI scaffold + show-dir walking (T2)
  - conf.json load + hardening (T3)
  - English sub-stream extraction + dialogue-track selection (T4)
  - RANSAC offset+drift line fit over nearest-onset card/cue pairs (T5)
  - slack-aware on-cue/in-gap overlap classification (T6)

Out of scope here (later units): the VAD probe of in-gap cards (tools/vad.py, U3/T7-T8)
and the full report/aggregate/summary builder (schema_version 2, U4/T9-T10). --vad and
--vad-aggressiveness are accepted and threaded through so the CLI surface is stable, but
not yet wired to a real probe -- in-gap cards are left unsplit (see process_episode()).

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

    min_cues = int(os.environ.get("TIMING_COMPARE_MIN_CUES", MIN_CUES_DEFAULT))
    min_plain_share = float(os.environ.get("TIMING_COMPARE_MIN_PLAIN_SHARE", MIN_PLAIN_SHARE_DEFAULT))
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


# ============================================================================
# Per-episode orchestration -- wires T3-T6 together. Produces the per-episode data
# structure U3 (VAD split of in-gap cards) and U4 (report/aggregates) consume; see the
# report for the exact shape. Not itself unit-tested here (it's the ffmpeg/track-
# selection I/O seam -- PENDING manual verification, see the report).
# ============================================================================

def process_episode(video: str, lang: set, tolerance: float,
                     pair_radius_s: float = PAIR_RADIUS_DEFAULT_S) -> dict:
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
                "fit": ransac_offset_drift([]), "cue_count": len(cue_intervals), "cards": []}

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
        # U3 will split "in-gap" into in_gap_silent/in_gap_speech/in_gap_vad_error via a
        # VAD probe of the card's ORIGINAL (un-aligned) [start, end] window; left unsplit here.
        card["low_confidence_alignment"] = low_conf
        cards.append(card)

    return {"video": video, "status": "analyzed", "reference_track": reference_track,
            "fit": fit, "cue_count": len(cue_intervals), "cards": cards}


# ============================================================================
# main
# ============================================================================

def main(argv=None):
    ap = build_arg_parser()
    a = ap.parse_args(argv)
    tolerance = max(TOLERANCE_MIN, min(TOLERANCE_MAX, a.tolerance))
    # Mirror common.SUB_LANGS's construction (no `if s.strip()` filter): the default
    # "eng,en,und," must keep the blank token so untagged subtitle streams (language ==
    # "", as returned by common.eng_sub_streams for streams with no language tag) match
    # here the same way they do in the rest of the pipeline. Dropping "" here would make
    # this tool's --lang stricter than common.SUB_LANGS, wrongly marking episodes whose
    # only usable dialogue track is untagged as no-reference.
    lang = {s.strip().lower() for s in a.lang.split(",")}

    videos = find_episodes(a.show_dir)
    counts: dict = {}
    results = []
    for video in videos:
        res = process_episode(video, lang, tolerance)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        results.append(res)
        if not a.summary_only:
            log(f"{res['status']:12} {video}")

    log("SUMMARY", counts,
        f"(vad={a.vad} vad_aggressiveness={a.vad_aggressiveness} tolerance={tolerance} "
        f"-- {a.out} report writing + VAD probe land in later units)")
    return results


if __name__ == "__main__":
    main()
