# `merge_pass.sh` captures `rc=$?` immediately after each of the three `python3` invocations (repair.py, dub_signs_merge.py, mux.py) and writes a `"crashed"` stage record via `python3 -c` when `rc != 0` and no stage record exists for that stem.

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

- [x] `merge_pass.sh` captures `rc=$?` immediately after each of the three `python3` invocations (repair.py, dub_signs_merge.py, mux.py) and writes a `"crashed"` stage record via `python3 -c` when `rc != 0` and no stage record exists for that stem.

## Evidence

`python3 -m pytest tests/test_merge_pass.py::test_crashed_record_written_only_when_stage_left_none -v` -- PASSED. merge_pass.sh's three inline `python3 -c` guards (after repair.py, dub_signs_merge.py, mux.py) each capture rc=$? immediately and write a 'crashed' stage record only when the stage itself left none for that stem (verified directly, and end-to-end via test_merge_pass.py's subprocess-driven tests). Fixing this test also caught a real bug: the inline snippets had no PYTHONPATH and silently failed `import common` (fixed in merge_pass.sh, commit e29d193).
