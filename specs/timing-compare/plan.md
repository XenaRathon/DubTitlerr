# Plan — Timing Compare: dubtitle-vs-subtitle timing analysis (Phase 0)

> After `spec-v3.md` approval. Approving this triggers the kickoff (branch creation).
> (v3 = spec-v2 + the multi-model panel consult: RANSAC drift fit, VAD probe, leaked-past-B1
> framing, recalibrated Phase-1 trigger.)

## Branch and delivery

- **Branch:** `feat/timing-compare` (base: `main`).
- **PR slicing:** single PR to `main`. Bounded to two new `tools/` scripts, one test file, a small
  `common.py`/`repair.py` refactor, and a `webrtcvad` dependency add.

## Technical approach

1. **Refactor first (live-pipeline blast radius — do before anything else).** Hoist
   `dialogue_intervals` from `repair.py` into `common.py` as
   `dialogue_intervals(video, stream_indices=None)` (default = current all-stream behavior), and add
   `dialogue_event_count` + `dialogue_density_score`. `repair.py` imports from `common.py`. Pin the
   `stream_indices=None` path to the exact pre-refactor `repair.py` output with a regression test, so
   the offline tool can never destabilize the repair stage.
2. **Timing model:** implement a robust linear fit `offset(t) = a + b·t` via RANSAC over
   `(card.start, cue.start)` pairs (seed = nearest-onset pairs within `±5 s`; inliers within `±0.30 s`
   of the line; refit by least-squares on inliers). Report intercept, drift slope, inlier count, and
   **post-fit** residual median/IQR + a `look_for_drift` flag. This replaces v2's constant median offset.
3. **Track selection + extraction:** per episode, extract English sub streams to a temp dir, score each
   with `dialogue_density_score`, pick the dialogue-dense track (or `no-reference`).
4. **Classify + VAD probe:** align each kept card with the fitted model, classify `on-cue`/`in-gap`
   by slack-aware overlap; for every `in-gap` card, extract its dub-audio window (original Whisper
   timebase) to 16 kHz mono and run `tools/vad.py::vad_probe` → `in_gap_silent` /`in_gap_speech`
   /`in_gap_vad_error`. `false_in_gap_rate = in_gap_speech / kept cards`.
5. **Report:** emit `timing-compare.report.json` (schema_version 2) + a printed summary headlining
   `applicability_ratio`, `pct_cards_on_cue`, `in_gap_speech`, and `false_in_gap_rate`.
6. **Test:** synthetic unit tests for the RANSAC fit, overlap classification, density scoring, band
   bucketing, nearest-onset pairing, and the VAD frame-decision (pure function over a frame-voiced list).

## Affected files (by layer)

| Layer             | File                                   | Change                                                                            |
| ----------------- | -------------------------------------- | --------------------------------------------------------------------------------- |
| Analytics (new)   | `tools/timing_compare.py`              | CLI, RANSAC fit, overlap+VAD classification, JSON report, summary.                |
| Analytics (new)   | `tools/vad.py`                         | `vad_probe()` — `webrtcvad` + `ffmpeg-silencedetect` backends.                    |
| Tests (new)       | `tests/test_timing_compare.py`         | Pure-function unit tests (incl. RANSAC + VAD frame-decision).                     |
| Common (refactor) | `common.py`                            | Hoist `dialogue_intervals`; add `dialogue_event_count`, `dialogue_density_score`. |
| Repair (refactor) | `repair.py`                            | `from common import dialogue_intervals` (no behavior change).                     |
| Deps              | `pyproject.toml`, `Dockerfile.builder` | add `webrtcvad`.                                                                  |

## Risks and mitigation

| Risk                                                     | Mitigation                                                                                                                                             |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Refactor changes `repair.py` behavior                    | Re-export via `common.py`; regression test pins `stream_indices=None` to current output; run repair tests before/after.                                |
| Constant-offset error from PAL/framerate drift           | RANSAC linear fit (intercept+slope); post-fit residual + `look_for_drift` flag surface any remaining drift.                                            |
| Sub gaps misread as hallucinations (real dub-only lines) | Independent VAD probe splits `in_gap_silent` vs `in_gap_speech`; `false_in_gap_rate` measures the real-speech-in-gap risk directly.                    |
| `webrtcvad` won't build in the image                     | `--vad ffmpeg-silencedetect` dep-free fallback; if both fail, in-gap cards → `in_gap_vad_error` and `false_in_gap_rate` reported `null` (not a crash). |
| Speech under loud music read as silent by VAD            | Documented limitation; the `by_nsp`/`by_lp` cross-tab is the second view; aggressiveness tunable; calibrate on first run.                              |
| Greedy nearest-onset mis-pairs on clustered cues         | RANSAC inlier selection discards mis-pairs the plain median would absorb.                                                                              |
| Thresholds wrong for the actual library                  | All raw counts + `applicability_ratio` + `false_in_gap_rate` exposed; thresholds env-overridable; tune after first run.                                |

## Rollback and reversibility

- Reverting the PR removes the two `tools/` scripts + the test file, rolls back the
  `common.py`/`repair.py` refactor, and drops the `webrtcvad` dep. No data/schema changes; read-only,
  only write is the report file.

## Testing strategy

- **Unit (bulk):** synthetic `card`/`cue` fixtures for RANSAC fit (constant offset, pure drift,
  drift+outliers → correct slope/inliers), slack-aware overlap, density scoring/plain filtering,
  NSP/LP/flag bucketing (boundary values), small-N/IQR `null` safety, and the VAD frame-decision
  (voiced-frame ratio → bool) over a synthetic frame list.
- **Integration (offline, manual):** run on one real show dir; inspect the report + summary; confirm
  `reference_track` is sane, `drift_b` plausible, and in-gap cards get a VAD verdict (not all errors).
- **Regression:** full pytest after the refactor; repair tests green.
- Target: ≥90% on the pure functions; 100% on bucketing + overlap + RANSAC inlier logic.

## Observability / performance

- One log line per episode with status (`analyzed`/`no-conf`/`no-reference`/`bad-conf`) + per-show
  progress with status counts.
- VAD adds per-in-gap-card ffmpeg window extraction; in-gap cards are a small minority, so cost is
  bounded. Sequential per episode; parallelize later only if a full-library run is too slow.
