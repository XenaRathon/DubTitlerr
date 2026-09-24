# A client that stalls its body write is disconnected at `Handler.timeout`, asserted by wall-clock bound in the test.

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

- [x] A client that stalls its body write is disconnected at `Handler.timeout`, asserted by wall-clock bound in the test.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

- `tests/test_review_server_http.py::test_a_client_that_stalls_its_body_write_is_disconnected_at_handler_timeout` — starts `review_server.BoundedHTTPServer` on port 0 in a background thread, patches `Handler.timeout` to 0.5s, opens a real socket, sends a request declaring a 1MB body, then sends nothing further. Asserts the server returns an empty read (connection closed) and that the elapsed wall-clock time is bounded near the patched timeout (`>= 0.25s` and `< 5.5s`). `python3 -m pytest tests/test_review_server_http.py -v` → `1 passed in 1.25s`.
