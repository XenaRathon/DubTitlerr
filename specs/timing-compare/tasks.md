# Tasks — Timing Compare: dubtitle-vs-subtitle timing analysis (Phase 0)

> Persistent memory. New session: read `spec-v3.md` + this file, check out the branch first.
> (v3 spec = spec-v2 + panel consult: RANSAC drift fit, VAD probe, leaked-past-B1 framing.)
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Delivered on `main` via the commits above** — T1–T11 landed as standalone commits
(no `feat/timing-compare` branch was ever created; `git branch -a` confirms this).
Reconciled 2026-09-21 after v0.2.0 candidate item 9 found the checklist below stale
against the actual `git log`.

Rules: ≤~1h each, dependency-ordered, verifiable, test-first, gates green (ruff · pytest via
`rtk proxy`), 1 task = 1 conventional commit.

## Tasks

- [x] **T1 — Refactor `common.py`/`repair.py` (do FIRST — live blast radius).**
      Delivered in `51ead55` (`refactor(T1): hoist dialogue_intervals from repair.py
      into common.py`).
      Hoist `dialogue_intervals(video, stream_indices=None)` from `repair.py` to `common.py` (default =
      current all-stream behavior); add `dialogue_event_count`, `dialogue_density_score`; `repair.py`
      imports from `common.py`. Add a regression test pinning the `stream_indices=None` output to the
      pre-refactor result. — done when: `rtk proxy pytest tests/test_repair*.py` passes and
      `ruff check common.py repair.py` clean.
- [x] **T2 — Scaffold `tools/timing_compare.py`.** Delivered in `4163e91`
      (`feat(timing-compare/T2-T6): tool core -- CLI, conf.json, track selection,
      RANSAC fit, classification`), together with T3–T6 below (one commit covers
      all four — see each task's own tick for the cross-reference).
      CLI (`--tolerance`, `--out`, `--lang`, `--vad`,
      `--vad-aggressiveness`, `--summary-only`); load `SUB_LANGS` from env; walk show dirs (prune
      `EXTRA_DIRS`, no symlink-follow); locate `<stem>.dubtitles.conf.json`. — done when:
      `python tools/timing_compare.py --help` runs; ruff clean.
- [x] **T3 — conf.json load + hardening.** Delivered in `4163e91` (see T2's note).
      Parse rows; `FileNotFoundError`/`PermissionError`/
      `JSONDecodeError` → `bad-conf`; drop rows with `start>=end`/negative `start`. — done when:
      unit tests for `no-conf`/`bad-conf`/bad-row pass.
- [x] **T4 — Subtitle extraction + dialogue-track selection.** Delivered in `4163e91`
      (see T2's note); a lang-set correctness fix followed in `fb25397`
      (`fix(timing-compare): keep blank lang token in --lang set to match
      common.SUB_LANGS`).
      `TemporaryDirectory()`; score with `dialogue_density_score`; pick dialogue-dense track (thresholds
      `min_cues`/`min_plain_share`, env-overridable); ties → lower index; else `no-reference`. — done
      when: on a real episode returns a `reference_track` block with `cue_count>0`; density-scorer unit
      tests pass.
- [x] **T5 — RANSAC offset+drift fit.** Delivered in `4163e91` (see T2's note).
      Nearest-onset seed pairs within `±5 s`; RANSAC line fit
      (`offset(t)=a+b·t`), inliers within `±0.30 s`, least-squares refit on inliers; report
      `offset_a_s`, `drift_b`, `matched_pairs_count`, `inlier_count`, post-fit residual median/IQR,
      `look_for_drift`; `null` guards (<10 inliers → offset null, <2 → residual null). — done when:
      synthetic tests (constant offset, pure drift, drift+outliers) recover the right slope/inliers.
- [x] **T6 — Overlap classification.** Delivered in `4163e91` (see T2's note).
      Align each kept card with the fitted model; slack-aware
      `on-cue`/`in-gap` (`max(0, min(a_e,k_e+t)-max(a_s,k_s-t))>0`, `t` clamped `[0,2]`). — done when:
      classification unit tests (touching bounds, nested, offset+drift applied) pass.
- [x] **T7 — VAD probe (`tools/vad.py`).** Delivered in `6b723ad` (`feat(timing-
      compare/T7): VAD probe of in-gap cards -- tools/vad.py + wiring`).
      `vad_probe(wav, aggressiveness)` with `webrtcvad` +
      `ffmpeg-silencedetect` backends over a 16 kHz mono window; pure `frames→voiced-ratio→bool`
      decision is unit-tested; extraction of the dub-audio window (original Whisper timebase) via
      ffmpeg into the temp dir; classify in-gap cards `in_gap_silent`/`in_gap_speech`/`in_gap_vad_error`;
      graceful fallback if `webrtcvad` missing. — done when: VAD frame-decision unit tests pass; a real
      in-gap card gets a non-error verdict; `ruff` clean.
- [x] **T8 — Add `webrtcvad` dependency.** Delivered in `d339ccd` (`feat(timing-
      compare/T8): add webrtcvad dependency (analysis extra + builder image)`).
      `pyproject.toml` (analysis extra) + `Dockerfile.builder`
      pip line. — done when: `pip install -e .[analysis]` (or equivalent) succeeds; `import webrtcvad` ok.
- [x] **T9 — Band bucketing + report generation.** Delivered in `3936de9` (`feat
      (timing-compare/T9-T11): schema_version-2 report + aggregates + edge
      hardening`), together with T10/T11 below.
      Bucket `kept_in_gap` by NSP/LP/flag (boundaries
      matching `hallucination.py`); compute `false_in_gap_rate`, coverage, `applicability_ratio`; build
      per-episode/per-show/aggregate; write `timing-compare.report.json` (schema_version 2); print the
      headline summary. — done when: a full run produces a report matching `spec-v3.md`’s schema and the
      summary shows `applicability_ratio` + `false_in_gap_rate`.
- [x] **T10 — Edge/aggregate hardening.** Delivered in `3936de9` (see T9's note); a
      follow-up null-safety fix landed in `7267b64` (`fix(timing-compare): aggregate
      false_in_gap_rate null on all-vad_error + doc/strip cleanups`) — the aggregate
      level had the same bug T10 already fixed at the per-episode level.
      `all no-reference` show → `null` aggregates; empty conf →
      0-card `analyzed`; `vad_error` counted separately; `--out` atomic write. — done when: edge-case
      unit tests pass; `ruff` clean.
- [x] **T11 — Unit test file.** Delivered in `3936de9` (see T9's note; the test file
      grew again in `7267b64`'s fix).
      `tests/test_timing_compare.py` covering all pure functions (RANSAC,
      overlap, density, bucketing, pairing, VAD frame-decision) with synthetic fixtures. — done when:
      `rtk proxy pytest tests/test_timing_compare.py` passes; pure-function coverage ≥90%.
- [ ] **T12 — Integration check on a real show.** Run on one real show dir; verify report + summary
      (sane `reference_track`, plausible `drift_b`, in-gap cards get VAD verdicts, believable
      `false_in_gap_rate`). — done when: the user has reviewed the output and accepted it — see
      `docs/timing-compare/*-phase0-report.json` and `docs/timing-compare/*-phase0-go-no-go.md` (added
      by the v0.2.0 hardening plan's sprint 014, Task 18). Tick this box by hand once that go/no-go
      note records a decision. **This run's numbers calibrate the recalibrated Phase-1 trigger
      (false_in_gap_rate ≤ ~2% across ≥3 shows).**

## Closing (the _close_ phase — always keep last)

- [ ] **CI / gates:** `ruff check tools/timing_compare.py tools/vad.py tests/test_timing_compare.py` + full `rtk proxy pytest` green. — done when: pipeline green.
- [x] ~~**Push the branch:** `git push origin feat/timing-compare`.~~ N/A — no
      `feat/timing-compare` branch ever existed; T1–T11 are already on `main` as
      standalone commits (see the header above).
- [x] ~~**Draft the PR:** Summary / Notable Decisions / Test Plan; pause for approval.~~
      N/A for the same reason — nothing to open a PR against.

## Done

<move tasks marked [x] here, preserving the done criterion>
