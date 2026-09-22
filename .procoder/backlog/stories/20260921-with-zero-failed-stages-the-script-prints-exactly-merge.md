# With zero failed stages, the script prints exactly `MERGE PASS COMPLETE`.

Status: done 2026-09-22
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-7 of `.procoder/specs/v0-2-0-hardening.md`: `merge_pass.sh` captures each stage invocation's exit code and prints `MERGE PASS COMPLETE` only when no episode has a failed stage (per `common.failed_stage`); otherwise it prints `MERGE PASS INCOMPLETE: <n> episodes with a failed stage`.

Delivered by Task 7 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] With zero failed stages, the script prints exactly `MERGE PASS COMPLETE`.

## Evidence

`python3 -m pytest tests/test_merge_pass.py::test_zero_failed_stages_prints_exactly_merge_pass_complete -v` -- PASSED. merge_pass.sh run end-to-end over one fully-passing stage fixture prints "MERGE PASS COMPLETE" and never "MERGE PASS INCOMPLETE".
