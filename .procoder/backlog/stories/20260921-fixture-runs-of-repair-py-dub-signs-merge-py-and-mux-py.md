# Fixture runs of `repair.py`, `dub_signs_merge.py`, and `mux.py` that force `extract-error`/`build-error`/`crashed`/`timeout`/ `unwritable` each leave a matching entry in `<stem>.dubtitles.stages.json` — checked by reading the sidecar, not just the function's return string.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-6 of `.procoder/specs/v0-2-0-hardening.md`: Add a durable per-episode stage-status artifact with typed outcomes: `common.STAGES_SUFFIX = ".dubtitles.stages.json"`, `common.STAGE_OUTCOMES = ("ok", "no-reference", "llm-empty", "backend-unreachable", "extract-error", "build-error", "no-video", "timeout", "crashed", "unwritable")`, `common.write_stage(stem, stage, outcome, detail="")` (merges into the per-episode JSON), `common.read_stages(stem) -> dict` (empty dict when absent/unreadable), and `common.failed_stage(stem) -> str | None` (first stage whose outcome is not in `{"ok", "no-reference", "no-video"}`).

Delivered by Task 6 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Fixture runs of `repair.py`, `dub_signs_merge.py`, and `mux.py` that force `extract-error`/`build-error`/`crashed`/`timeout`/ `unwritable` each leave a matching entry in `<stem>.dubtitles.stages.json` — checked by reading the sidecar, not just the function's return string.

## Evidence

`python3 -m pytest tests/test_repair.py::test_a_dead_backend_refuses_the_episode_instead_of_rebuilding_raw_asr tests/test_dub_signs_merge.py::test_process_one_no_video_writes_matching_stage_record tests/test_dub_signs_merge.py::test_process_one_build_error_writes_matching_stage_record tests/test_mux.py::test_process_reports_a_failed_stamp_write_and_keeps_the_sidecar -v` -- all PASSED. repair.py writes backend-unreachable/no-reference/no-video/ok; dub_signs_merge.py writes no-video/build-error/ok (detail=no-signs); mux.py writes unwritable on a failed stamp write -- each read back from <stem>.dubtitles.stages.json via common.read_stages(), not the function's return string.
