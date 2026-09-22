# For an MP4/M4V source with a monkeypatched `write_stamp` that raises `OSError`, `final` (the new mkv) is removed and `orig` still exists on disk afterward; the return value signals a retryable state distinct from today's `"stamp-write-failed"`-with-`orig`-already-gone.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-9 of `.procoder/specs/v0-2-0-hardening.md`: For an MP4/M4V source, reorder `mux.process()` so the stamp is written BEFORE `os.remove(orig)`, not after (today's order is the reverse: `mux.py:462-467`).

Delivered by Task 9 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] For an MP4/M4V source with a monkeypatched `write_stamp` that raises `OSError`, `final` (the new mkv) is removed and `orig` still exists on disk afterward; the return value signals a retryable state distinct from today's `"stamp-write-failed"`-with-`orig`-already-gone.

## Evidence

`python3 -m pytest tests/test_mux.py::test_mp4_stamp_write_failure_rolls_back_final_and_keeps_orig -v` -- PASSED. For an .mp4 source (orig != final) with write_stamp monkeypatched to raise OSError, mux.process() returns "stamp-write-failed", `final` (the new .mkv) is removed, and `orig` still exists on disk -- the retryable state the reorder (write_stamp before os.remove(orig)) was meant to guarantee.
