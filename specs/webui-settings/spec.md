# Spec — Application Settings Page (Web UI & Runtime Configuration)

## Context and problem

DubTitlerr configuration is currently managed via ~60 environment variables declared across `compose.yaml:39-100` and host systemd timers (`deploy/dubtitlerr-window-open.timer:6-9`). Operators have no visibility into active flags or model endpoints from the web workspace (`web/src/App.svelte:32`), requiring direct SSH and container inspection. In split builder and review container topologies (production host `the production host`; the repo `compose.yaml` has a single `dubtitlerr` service), the review process does not receive `REPAIR_*` and `VERIFY_*` variables, leaving it blind to active pipeline settings.

## Acceptance criteria (verifiable)

- [ ] `GET /api/settings` returns HTTP 200 with JSON payload of allow-listed configuration keys and effective values (`repair_backend`, `repair_model`, `repair_llamacpp_url`, `repair_openai_url`, `verify_backend`, `verify_decision_model`, `acquire_backend`, `whisper_model`, `compute_type`, `require_eng`, `repair_unanchored`, `glossary_arc_tags`, `rescan_interval`, `merge_roots`, `anime_order`).
- [ ] Any key matching `KEY`, `TOKEN`, `PASSWORD`, or `SECRET` returns a boolean presence status (`true`/`false`), never the secret value.
- [ ] Unauthenticated requests to `/api/settings` and `/api/settings/test` return HTTP 401 (`OPEN_ROUTES` in `review_server.py:770` remains strictly unchanged).
- [ ] `POST /api/settings/test` accepts `{"backend": "<name>"}` and returns `{"ok": bool, "latency_ms": int, "error": str}` within a 5-second socket timeout.
- [ ] `web/src/App.svelte` adds a dedicated Settings view displaying effective configurations and a per-backend connectivity test action.
- [ ] `review_server.py` reads `/config/effective.env` (exported by `gen_loop.sh`) to report the builder's actual environment, falling back to process `os.environ`.
- [ ] Covered by new unit test suite in `tests/test_review_settings.py` (`test_settings_requires_auth`, `test_settings_masks_secrets`, `test_settings_reads_effective_env`, `test_settings_test_success`, `test_settings_test_timeout`) and Playwright spec in `web/tests/browser/settings.spec.ts`.

## Out of scope (explicit)

- Phase 2 writing of `/config/runtime.env` (live mutation of parameters from the web UI is deferred).
- Direct modification of host systemd timers (`deploy/dubtitlerr-window-*.timer`) from the web container.
- Modifying GPU allocation or in-flight faster-whisper transcription parameters.
- Unauthenticated access to settings or connectivity testing.

## Data contracts

- **Inputs:**
  - `GET /api/settings`: Header `X-Review-Token: <token>`.
  - `POST /api/settings/test`: Header `X-Review-Token: <token>`, JSON body `{"backend": "repair" | "verify" | "acquire"}`.
- **Outputs:**
  - `GET /api/settings`: `{"settings": {<key>: <value>}, "secrets": {<key>: bool}, "source": "effective.env" | "env"}`.
  - `POST /api/settings/test`: `{"ok": true, "latency_ms": 115, "model": "qwen3-4b-instruct"}` or `{"ok": false, "latency_ms": 0, "error": "connection refused"}`.
- **Phase 2 Data Contract (Deferred Design):**
  - File `/config/runtime.env`: Simple `KEY=VALUE` pairs without shell expansion. Sourced by `gen_loop.sh:47` before each show sweep. Precedence: `runtime.env` overrides `compose.yaml` defaults. Allow-listed keys: `REPAIR_BACKEND`, `REPAIR_MODEL`, `REPAIR_LLAMACPP_URL`, `VERIFY_BACKEND`, `ACQUIRE_BACKEND`, `REQUIRE_ENG`. UI displays "pending next sweep" until `gen_loop.sh` mirrors active state into `/config/effective.env`.
- **Schemas / models affected:** `review_server.py:958` routing table, `web/src/types.ts` (`SettingsState`, `TestResult`).
- **External dependencies:** Tested HTTP endpoints (`repair.py:180` `REPAIR_LLAMACPP_URL`, `repair.py:182` `REPAIR_OPENAI_URL`).

## Authorization

- **Who can execute:** Authenticated callers presenting a valid review token via `X-Review-Token` header or `dubtitlerr_token` cookie [`review_server.py:192-224`, `1492`].
- **Behavior without permission:** HTTP 401 `{"error": "a token is required"}` [`review_server.py:969`].

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| `/config/effective.env` absent or unreadable | Falls back to `review_server.py` process environment with `"source": "env"` |
| Backend server unreachable or timed out | Returns HTTP 200 with `{"ok": false, "latency_ms": 0, "error": "<sanitized error>"}` within 5s |
| Invalid backend name in test request | Returns HTTP 400 `{"error": "unsupported backend"}` |
| Secret key inspection | Any variable containing `KEY`, `TOKEN`, `PASSWORD`, or `SECRET` maps to boolean presence |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| Builder writes `/config/effective.env` at sweep start for review server to read | Passing all `REPAIR_*` and `VERIFY_*` env to review service in `compose.yaml` | `compose.yaml` drifts across deployment setups; `/config/effective.env` captures actual runtime parameters executed by `gen_loop.sh:148` regardless of container topology. |
| Test backends on demand via `POST /api/settings/test` | Continuous background health polling | Avoids unnecessary token costs, GPU power state changes, and rate limit exhaustion on metered APIs (`specs/glossary-decision-bakeoff/spec.md:92`). |
| Phase 2 runtime overrides via `/config/runtime.env` sourced per show in `gen_loop.sh` | Immediate container restart on configuration save | Prevents interrupting active media processing and avoids creating `.dubtitles.fail` markers on SIGKILL (`container_run.sh:16`). |

## Constraints

- Performance / cost: Connectivity tests enforce a strict 5-second socket timeout and issue minimal metadata queries (e.g. `GET /v1/models`).
- Privacy / security: Values for `LONGCATAI_API_KEY`, `COMMANDCODE_API_KEY`, `REVIEW_TOKEN`, and `REVIEW_PASSWORD` are never returned in plaintext.
- Architecture: `OPEN_ROUTES` in `review_server.py:770` remains unchanged; all new routes require token validation.

## Open questions (risks)

- [x] Decided (user, 2026-10-12): the openai-style test calls `GET <base>/v1/models` only, with the 5 s timeout; it does not send a completion. A provider that lacks that route reports `ok:false` with the HTTP status.
- [x] Decided (user, 2026-10-12): window times come from env vars in the allow-list (MERGE_WINDOW now, the schedule.json open/close once run-control ships). The page does not read host systemd timers; it labels the value "container window" so it is not mistaken for the host timers.
- [x] Decided (user, 2026-10-12): Phase 2 writes (and, pending confirmation, run-control and webhook-adjacent writes) require a separate admin token (`REVIEW_ADMIN_TOKEN`, header `X-Review-Admin-Token`). Reads stay on the review token. Spec for the admin-token mechanics is still to be written.
