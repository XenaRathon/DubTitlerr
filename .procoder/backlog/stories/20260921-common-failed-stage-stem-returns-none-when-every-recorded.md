# `common.failed_stage(stem)` returns `None` when every recorded outcome is in `{"ok", "no-reference", "no-video"}`, and returns the first offending stage name otherwise.

Status: done 2026-09-22
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-6 of `.procoder/specs/v0-2-0-hardening.md`: Add a durable per-episode stage-status artifact with typed outcomes: `common.STAGES_SUFFIX = ".dubtitles.stages.json"`, `common.STAGE_OUTCOMES = ("ok", "no-reference", "llm-empty", "backend-unreachable", "extract-error", "build-error", "no-video", "timeout", "crashed", "unwritable")`, `common.write_stage(stem, stage, outcome, detail="")` (merges into the per-episode JSON), `common.read_stages(stem) -> dict` (empty dict when absent/unreadable), and `common.failed_stage(stem) -> str | None` (first stage whose outcome is not in `{"ok", "no-reference", "no-video"}`).

Delivered by Task 6 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `common.failed_stage(stem)` returns `None` when every recorded outcome is in `{"ok", "no-reference", "no-video"}`, and returns the first offending stage name otherwise.

## Evidence

`python3 -m pytest tests/test_common.py::test_failed_stage_none_when_all_pass_else_first_offender -v` -- PASSED. failed_stage() returns None with repair=ok/signs=no-reference/mux=no-video, then returns "signs" after signs is rewritten to build-error.
