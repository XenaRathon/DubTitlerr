# Spec — Admin token for builder-affecting writes

## Context and problem

Every review-server route sits behind one token (`authorised()`, `review_server.py:254`), and the browser keeps it in a cookie (`review_server.py:127-145`). Anyone who can approve a subtitle line can therefore also do anything a later route allows. The user decided on 2026-10-12 that writes which affect the builder (settings changes, run requests, schedule) need a separate admin token. The glossary editor and review decisions stay on the normal token.

## Acceptance criteria (verifiable)

- [ ] `REVIEW_ADMIN_TOKEN` is read from the environment (or the file named by `REVIEW_ADMIN_TOKEN_FILE`). It is never generated or persisted by the server.
- [ ] `route()` (`review_server.py:958`) gains an `admin_token` argument filled by the HTTP layer from `X-Review-Admin-Token`; callers and tests that call `route()` directly keep working because it defaults to "". A new helper `admin_authorised(presented)` in `review_server.py` compares the header `X-Review-Admin-Token` with `secrets.compare_digest`, like `authorised()` (`review_server.py:254`).
- [ ] Admin-guarded routes (listed in Data contracts) check the review token first (401 if missing), then the admin token (403 if missing or wrong).
- [ ] `REVIEW_ADMIN_TOKEN` unset or empty: every admin-guarded route returns 403 `{"error": "admin writes are disabled"}`, in every auth mode including `REVIEW_AUTH=off`.
- [ ] The admin token is accepted from the header only. A cookie or query-string value is ignored, so it cannot be set by a link.
- [ ] `GET /api/auth-mode` (open route, `review_server.py:770`) gains `admin_enabled: bool` and nothing else, so the UI knows whether to show write controls. `OPEN_ROUTES` itself is unchanged.
- [ ] The token value never appears in logs, error bodies, or `GET /api/settings` (reported as set/unset only).
- [ ] The Svelte UI asks for the admin token the first time a guarded action is used, keeps it in `sessionStorage` (tab lifetime, never `localStorage` or a cookie), and sends it in the header. A 403 clears it and asks again.
- [ ] Tests in `tests/test_review_admin.py`: `test_admin_routes_403_when_unset`, `test_admin_routes_403_when_wrong`, `test_admin_routes_401_without_review_token`, `test_admin_ok_with_both`, `test_cookie_admin_ignored`, `test_auth_mode_reports_admin_enabled`, `test_open_routes_unchanged` (extends the pin at `tests/test_review_login.py:234`), `test_token_not_logged`. Frontend: `web/tests/review.test.mjs` covers the header helper and the 403 retry.

## Out of scope (explicit)

- Multiple admin users, roles, rotation UI, or expiry.
- Guarding the glossary editor or review decisions with the admin token.
- Webhook routes, which use `WEBHOOK_TOKEN` (`specs/arr-webhooks`).

## Data contracts

- **Admin-guarded routes:** `PUT /api/settings` (settings Phase 2), `POST /api/requests`, `PUT /api/schedule` (`specs/webui-run-control`). Read routes stay on the review token.
- **Header:** `X-Review-Admin-Token: <value>`.
- **Errors:** 401 `{"error": "a token is required"}`; 403 `{"error": "admin token required"}` (wrong or missing); 403 `{"error": "admin writes are disabled"}` (unset).
- **`GET /api/auth-mode`:** existing fields plus `admin_enabled`.

## Authorization

- **Who can execute:** callers with both the review token and the admin token.
- **Behavior without permission:** as in the error list above.

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| Admin token equals the review token | Allowed; the operator chose it. The spec does not forbid reuse. |
| `REVIEW_AUTH=off` and admin token set | Review token check is skipped as today; the admin check still runs. |
| Admin token sent in a cookie or `?token=` | Ignored; treated as missing. |
| Constant-time comparison with different lengths | `secrets.compare_digest` on `str`; no early return on length. |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| Separate static secret in env | Role system on top of the review token | One new variable; no user store exists to attach roles to. |
| Header-only | Cookie after login | A cookie would travel on every request and survive the tab; header plus `sessionStorage` limits exposure. |
| Unset means writes disabled | Unset means open | A deployment that never configured it must not gain write routes by upgrading. |

## Constraints

- Privacy / security: no logging of the value; constant-time compare; no new open route.
- Architecture: the check is one helper called at the top of each guarded handler, not a new middleware, so the guarded set is greppable.

## Open questions (risks)

- [ ] Should `compose.yaml` ship `REVIEW_ADMIN_TOKEN` as an env name with no default, and should the install docs tell users to set it? (Docs are frozen until release; record for the release pass.)
