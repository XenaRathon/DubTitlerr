# Opening `MAX_CONCURRENT + 1` simultaneous connections results in the extra connection being closed by the server rather than queued indefinitely.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 013-v0-2-0-work

## Description

Scope S-15 of `.procoder/specs/v0-2-0-hardening.md`: Add a real-socket HTTP test: the server started on port 0 in a thread, not the handler called directly.

Delivered by Task 15 of `.procoder/plans/v0-2-0-hardening.md` (sprint 013); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Opening `MAX_CONCURRENT + 1` simultaneous connections results in the extra connection being closed by the server rather than queued indefinitely.

## Evidence

- `tests/test_review_server_http.py::test_opening_max_concurrent_plus_one_connections_results_in_extra_being_closed` — opens MAX_CONCURRENT+1 connections, verifies extra one is closed. Tests pass.
