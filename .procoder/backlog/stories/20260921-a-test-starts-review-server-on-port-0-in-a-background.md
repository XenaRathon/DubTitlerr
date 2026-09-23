# A test starts `review_server` on port 0 in a background thread (real socket): `GET /api/episodes` with no token → 401; with the correct token → 200.

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

- [x] A test starts `review_server` on port 0 in a background thread (real socket): `GET /api/episodes` with no token → 401; with the correct token → 200.

## Evidence

- `tests/test_review_server_http.py::test_a_real_socket_get_api_episodes_gated_by_token` — starts server on port 0, monkeypatches `REVIEW_TOKEN`, sends GET `/api/episodes` with no token → 401, with token → 200. `python3 -m pytest tests/test_review_server_http.py -v` passes.
