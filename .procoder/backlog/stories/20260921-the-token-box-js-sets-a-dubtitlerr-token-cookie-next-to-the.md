# The token box JS sets a `dubtitlerr_token` cookie next to the localStorage write; `GET /` and `GET /shared` with no header and no cookie return 200 with `needs-token` in the body and no stem from a monkeypatched `known_stems`; with the cookie they render the full page.

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

- [x] The token box JS sets a `dubtitlerr_token` cookie next to the localStorage write; `GET /` and `GET /shared` with no header and no cookie return 200 with `needs-token` in the body and no stem from a monkeypatched `known_stems`; with the cookie they render the full page.

## Evidence

- Token box JS sets `document.cookie = "dubtitlerr_token=" + token + "; path=/"`
- `render_page()` checks cookie in addition to header/localStorage
- Tests in `tests/test_review_server_http.py` pass
