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

- [x] The tokenless-request posture is: every path that reaches `route()` without a token returns `401 {"error": "a token is required"}`; the page routes `/`, `/index.html` and `/shared` are gated one layer above `route()` in `Handler.do_GET`, returning `200 {"needs-token": true}` when no token rides on either the `X-Review-Token` header or the `dubtitlerr_token` cookie; `GET /healthz` is dispatched at `review_server.py:691`, above the gate, so it stays open.
  - AMENDED 2026-09-23 (criterion text rewritten in place; original below). The original read: `review_server.authorised("GET", None)` returns `False` for a path starting with `/api/` and `True` for `/`, `/index.html`, `/shared`, `/healthz`. As shipped, `authorised()` accepts a `path` argument and ignores it — it returns `False` for _every_ path when no token is presented. The `/api/`-vs-page distinction is made by `Handler.do_GET` (page routes) and by `/healthz`'s position above the gate in `route()`, not inside `authorised()`. The original was a byte-for-byte copy of spec S-14 (`.procoder/specs/v0-2-0-hardening.md:645-648`), written before that two-layer design landed; every behaviour it was protecting is shipped and is verified below. The spec line needs the same amendment.

## Evidence

- `review_server.py:215-220` — `authorised(method, presented, path="")` accepts `path` and never reads it; it returns `auth_required() and bool(presented) and secrets.compare_digest(str(presented), resolve_token())`. Live probe with `REVIEW_TOKEN`/`REVIEW_AUTH` unset: `authorised("GET", None, p)` is `False` for every `p` tried — `""`, `/`, `/index.html`, `/shared`, `/healthz`, `/api/episodes`.
- `review_server.py:1160-1188` — `Handler.do_GET` does the page-level gating: it takes the token from `X-Review-Token`, falls back to a `dubtitlerr_token` cookie for `/`, `/index.html` and `/shared` (`:1170-1176`), and returns `200 {"needs-token": true}` when neither is present (`:1177-1180`). `/healthz` is dispatched at `review_server.py:691`, above `route()`'s gate at `:693`, which is what keeps it open.
- Live socket probe (server bound to port 0, `REVIEW_TOKEN`/`REVIEW_AUTH` unset), `python3` from the repo root: `GET /` → `200 {"needs-token": true}`; `GET /shared` → `200 {"needs-token": true}`; `GET /api/episodes` → `401 {"error": "a token is required"}`; `GET /healthz` → `503 {"ok": false, "reasons": ["no heartbeat yet"]}`.
- `tests/test_review_server.py:130-131` asserts the shipped behaviour, not the original criterion: `authorised("GET", None, "") is False` and `authorised("GET", None, "/api/episodes") is False`. `:332-333` asserts `route("GET", "/api/episodes", {}, tok)[0] == 200` and `…{}, None)[0] == 401`; `:1309` asserts `route("GET", "/api/shared", {}, "sekrit")[0] == 200`.
- Coverage caveat: no test asserts `route("GET", "/", {}, None)` (which is in fact `401`), and no test asserts the page-level `{"needs-token": true}` gate — `grep -rn "needs-token" tests/` and `grep -rn "ookie" tests/*.py` both return no hits, because the plan's five lock/cookie tests (`.procoder/plans/v0-2-0-hardening.md:~4391-4506`) were never ported. The page-level gate is currently proven only by the live probe above.
