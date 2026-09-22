# An MKV source (`orig == final`) never calls `os.remove` on the original, asserted by a fixture where `orig` and `final` are the same path.

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

- [x] An MKV source (`orig == final`) never calls `os.remove` on the original, asserted by a fixture where `orig` and `final` are the same path.

## Evidence

`python3 -m pytest tests/test_mux.py::test_mkv_source_never_removes_orig -v` -- PASSED. os.remove is wrapped with a guard asserting it is never called with orig's path for an MKV source (orig == final); process() still returns "muxed".
