# Given a prior `.ass` sidecar containing at least one non-dialogue (signs) event, a forced `dub_signs_merge.py` failure (`"build-error"` or `"no-video"`) makes `mux.process()` refuse to mux the dialogue-only `.srt` and return a distinct non-muxing status instead of stamping the demoted output as done.

Status: done 2026-09-22
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-8 of `.procoder/specs/v0-2-0-hardening.md`: A transient signs extract/build failure is made distinguishable from a genuinely signs-free episode: `mux.py` refuses to mux a dialogue-only replacement as though it were the combined track when `common.read_stages` says the `signs` stage failed AND the prior `.ass` sidecar had at least one sign event — it must not silently fall through `sub_source()`'s ASS-then-SRT fallback (`mux.py:403-409`) and stamp the demoted output as done.

Delivered by Task 8 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Given a prior `.ass` sidecar containing at least one non-dialogue (signs) event, a forced `dub_signs_merge.py` failure (`"build-error"` or `"no-video"`) makes `mux.process()` refuse to mux the dialogue-only `.srt` and return a distinct non-muxing status instead of stamping the demoted output as done.

## Evidence

`python3 -m pytest tests/test_mux.py::test_signs_regression_refused_when_signs_stage_failed_and_only_srt_remains tests/test_mux.py::test_signs_regression_refused_for_no_video_outcome_too -v` -- both PASSED. With only a dialogue-only .srt present and a recorded signs stage outcome of "build-error" or "no-video", mux.process() returns "signs-regression-refused" and never stamps the file as done.
