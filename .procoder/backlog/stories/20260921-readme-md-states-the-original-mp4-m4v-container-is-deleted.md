# `README.md` states the original MP4/M4V container is deleted only after a verified, stamped remux.

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

- [x] `README.md` states the original MP4/M4V container is deleted only after a verified, stamped remux.

## Evidence

README.md now states (added after the migration-script section): "The original MP4/M4V container is deleted only after a verified, stamped remux" -- mux writes the .mkv, verifies it, writes the stamp, and only then removes the original; a failed stamp write rolls back the new .mkv and leaves the original untouched. `grep -n 'deleted only after a verified' README.md` confirms the line is present.
