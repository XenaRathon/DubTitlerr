# For an MP4/M4V source with a monkeypatched `write_stamp` that raises `OSError`, `final` (the new mkv) is removed and `orig` still exists on disk afterward; the return value signals a retryable state distinct from today's `"stamp-write-failed"`-with-`orig`-already-gone.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-9 of `.procoder/specs/v0-2-0-hardening.md`: For an MP4/M4V source, reorder `mux.process()` so the stamp is written BEFORE `os.remove(orig)`, not after (today's order is the reverse: `mux.py:462-467`).

Delivered by Task 9 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] For an MP4/M4V source with a monkeypatched `write_stamp` that raises `OSError`, `final` (the new mkv) is removed and `orig` still exists on disk afterward; the return value signals a retryable state distinct from today's `"stamp-write-failed"`-with-`orig`-already-gone.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
