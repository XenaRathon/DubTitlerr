# Two new tests pass: one with an unwritable stamp path, one simulating an interruption between `_finalize` and `write_stamp` — both assert either `orig` or a validly stamped `final` survives, never neither.

Status: done 2026-09-22
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-9 of `.procoder/specs/v0-2-0-hardening.md`: For an MP4/M4V source, reorder `mux.process()` so the stamp is written BEFORE `os.remove(orig)`, not after (today's order is the reverse: `mux.py:462-467`).

Delivered by Task 9 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Two new tests pass: one with an unwritable stamp path, one simulating an interruption between `_finalize` and `write_stamp` — both assert either `orig` or a validly stamped `final` survives, never neither.

## Evidence

`python3 -m pytest tests/test_mux.py::test_process_reports_a_failed_stamp_write_and_keeps_the_sidecar tests/test_mux.py::test_mp4_stamp_write_failure_rolls_back_final_and_keeps_orig -v` -- both PASSED. The first covers an unwritable stamp path (MKV, sidecar kept for retry); the second covers the MP4 _finalize-to-write_stamp window with write_stamp raising mid-way -- both assert the surviving state is either `orig` intact or a validly stamped `final`, never neither.
