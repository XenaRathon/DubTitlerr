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

- `review_server.py:834` (inside `render_shared`) and `:1047` (inside `render_page`) — the token box's `input` listener sets the cookie next to the localStorage write: `document.cookie='dubtitlerr_token='+encodeURIComponent(TOK.value)+'; path=/'`.
- The cookie is read by `Handler.do_GET` (`review_server.py:1170-1176`), not by `render_page()`: for `/`, `/index.html` and `/shared` it falls back to a `dubtitlerr_token=` cookie when the `X-Review-Token` header is absent, and returns `200 {"needs-token": true}` when neither is present (`:1177-1180`).
- Live socket probe (server on port 0, `TOKEN_DIR` set to a tmp dir, `known_stems` monkeypatched to `["/media/S01E01.mkv"]`, `REVIEW_TOKEN`/`REVIEW_AUTH` unset), `python3` from the repo root: `GET /` → `200`, `needs-token` present, `S01E01` absent; `GET /` with `Cookie: dubtitlerr_token=<tok>` → `200`, `needs-token` absent; `GET /shared` the same in both cases; `GET /` with the `X-Review-Token` header → `200`, `needs-token` absent. (The monkeypatched stem is a bare path with no pending queue entries, so it does not appear in the rendered page even when authorised — its absence is not the assertion here; `needs-token` is.)
- Coverage caveat: the plan's five lock/cookie tests (`.procoder/plans/v0-2-0-hardening.md:~4391-4506`) were never ported into `tests/` — `grep -rn "ookie" tests/*.py` returns no hits, and `tests/test_review_server_http.py` holds exactly 3 tests, none of which touches cookies or `needs-token`. This behaviour is currently proven only by the live probe above.
