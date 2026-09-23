# `review_server.authorised("GET", None)` returns `False` for a path starting with `/api/` and `True` for `/`, `/index.html`, `/shared`, `/healthz`.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 013-v0-2-0-work

## Description

Scope S-14 of `.procoder/specs/v0-2-0-hardening.md`: Harden the review server's auth posture in code: `GET`/`HEAD` on any path starting with `/api/` requires the token like writes do (401 `{"error": "a token is required"}`); the rendered pages `/`, `/index.html` and `/shared` are gated the same way through a `dubtitlerr_token` cookie the token box sets alongside localStorage — without a valid header or cookie they render only the token box, never a stem or repair text; `/healthz` stays open.

Delivered by Task 14 and 17 of `.procoder/plans/v0-2-0-hardening.md` (sprint 013); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `review_server.authorised("GET", None)` returns `False` for a path starting with `/api/` and `True` for `/`, `/index.html`, `/shared`, `/healthz`.

## Evidence

- `review_server.py:authorised()` rewritten to accept `path` parameter (default `""`); returns `False` for GET/HEAD on paths starting with `/api/` when no token presented; `True` otherwise (rendered pages, `/healthz` stay open).
- `review_server.py:route()` updated to pass `path` into `authorised()`.
- `tests/test_review_server.py` updated: `authorised("GET", None, "")` → `True`, `authorised("GET", None, "/api/episodes")` → `False`; `route("GET", "/api/episodes", {}, None)` → `401`; `route("GET", "/", {}, None)` → `200`; `route("GET", "/api/shared", {}, tok)` → `200`.
