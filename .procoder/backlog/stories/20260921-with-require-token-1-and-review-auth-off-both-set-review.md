# With `REQUIRE_TOKEN=1` and `REVIEW_AUTH=off` both set, `review_server.serve()` exits with status 2 and logs the exact message before `BoundedHTTPServer(...)` is ever constructed (asserted by mocking the constructor and confirming it is never called).

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-14 of `.procoder/specs/v0-2-0-hardening.md`: Harden the review server's auth posture in code: `GET`/`HEAD` on any path starting with `/api/` requires the token like writes do (401 `{"error": "a token is required"}`); the rendered pages `/`, `/index.html` and `/shared` are gated the same way through a `dubtitlerr_token` cookie the token box sets alongside localStorage — without a valid header or cookie they render only the token box, never a stem or repair text; `/healthz` stays open.

Delivered by Task 14 and 17 of `.procoder/plans/v0-2-0-hardening.md` (sprint 013); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] With `REQUIRE_TOKEN=1` and `REVIEW_AUTH=off` both set, `review_server.serve()` exits with status 2 and logs the exact message before `BoundedHTTPServer(...)` is ever constructed (asserted by mocking the constructor and confirming it is never called).

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
