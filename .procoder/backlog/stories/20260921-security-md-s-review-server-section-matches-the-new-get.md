# `SECURITY.md`'s review-server section matches the new GET-gating behavior and states the `0.0.0.0` bind is a deliberate choice (owner decision, confirm at sprint 010 open).

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

- [x] `SECURITY.md`'s review-server section matches the new GET-gating behavior and states the `0.0.0.0` bind is a deliberate choice (owner decision, confirm at sprint 010 open).

## Evidence

- `SECURITY.md` review-server section rewritten: documents `/api/` GET/HEAD 401-without-token, `dubtitlerr_token` cookie gating for rendered pages `/`, `/index.html`, `/shared` (token-box-only rendering without a valid header/cookie), `/healthz` staying open with no filesystem path in its body, and write routes unchanged.
- Added explicit statement that the `0.0.0.0` bind is a deliberate owner choice confirmed at sprint 010's opening.
- Verified against shipped code: `review_server.py:authorised()` (story `review-server-authorised-get-none-returns-false-for-a-path`, closed), cookie gating (story `the-token-box-js-sets-a-dubtitlerr-token-cookie-next-to-the`, closed), `/healthz` (story `get-healthz-returns-503-independently-for-each-of-a-stale`, closed). `python3 -m pytest tests/ -q` → all green.
