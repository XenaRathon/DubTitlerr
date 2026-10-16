# Spec — Runtime Settings Writes and Model Selection

## Context and problem

Operators cannot select LLM repair/verify models or toggle pipeline parameters from the web workspace (`web/src/pages/Settings.svelte:169`), requiring direct container environment edits and restarts that risk interrupting active transcription (`container_run.sh:14-16`). Phase 1 (`specs/webui-settings/spec.md:1-16`) delivered read-only display and connectivity testing; Phase 2 introduces validated runtime overrides via `/config/runtime.env` without exposing dangerous URL or secret mutations to web callers.

## Acceptance criteria (verifiable)

- [ ] `PUT /api/settings` accepts an admin-guarded JSON payload (`specs/webui-admin-token/spec.md:27`), validates allow-listed keys, and atomically writes `/config/runtime.env` with mode `0664`.
- [ ] Requests without both a valid review token (HTTP 401) and admin token (`X-Review-Admin-Token`, HTTP 403) are refused (`review_server.py:1024-1028`).
- [ ] Writable keys are strictly restricted to: `repair_profile`, `repair_model`, `verify_backend`, `verify_decision_model`, `require_eng`. Arbitrary URLs (`*_url`), secret names (`*_key*`), and host paths are rejected with HTTP 400.
- [ ] URLs and credentials can only be switched by choosing pre-configured profile names defined server-side in `REPAIR_PROFILES` (`compose.yaml`).
- [ ] Model identifiers are validated against `^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$`; invalid characters or lengths reject with HTTP 400.
- [ ] Prior override state is preserved at `/config/runtime.env.prev`; `POST /api/settings/reset` restores it (or removes `runtime.env`).
- [ ] `gen_loop.sh:104` (before each show and request) and `merge_pass.sh:42` (before each merge pass) source `/config/runtime.env`; in-flight units are never interrupted mid-episode.
- [ ] Precedence is strictly enforced: per-request `require_eng` (`gen_loop.sh:62`) > `/config/runtime.env` > container environment > defaults.
- [ ] `GET /api/settings` reports `pending` overrides whenever `/config/runtime.env` differs from active `/config/effective.env`.
- [ ] Every mutation emits an audit log line: `review server: settings updated by admin: keys=<keys>` (`common.py:log`).
- [ ] The Settings UI (`web/src/pages/Settings.svelte`) adds profile and model dropdowns, an override reset button, and "pending next sweep" status indicators.
- [ ] Verified by unit tests in `tests/test_review_settings_write.py`, shell execution tests in `tests/test_gen_loop_runtime_env.py` and `tests/test_merge_pass_runtime_env.py`, and Playwright tests in `web/tests/browser/settings.spec.ts`.

## Out of scope (explicit)

- Modifying host timers or scheduling windows via `runtime.env` (managed separately via `/config/schedule.json`, `specs/webui-run-control/spec.md:40`).
- Arbitrary URL or API key injection via the web UI; URLs and credentials remain statically declared in container configuration.
- Mid-episode process restarts or live mutation of in-memory Whisper GPU contexts.

## Data contracts

- **Inputs (`PUT /api/settings`):** Headers `X-Review-Token: <token>`, `X-Review-Admin-Token: <token>`. JSON body:
  `{"repair_profile": str|null, "repair_model": str|null, "verify_backend": str|null, "verify_decision_model": str|null, "require_eng": int|null}`.
- **Outputs (`PUT /api/settings`):** HTTP 200 `{"ok": true, "written": {<key>: <val>}, "pending": true}`.
- **Outputs (`GET /api/settings`):** Existing payload (`specs/webui-settings/spec.md:30`) plus `"pending": {<key>: <val>}` and `"profiles": [str]`.
- **Runtime File Schema (`/config/runtime.env`):** Flat POSIX `KEY=VALUE\n` lines with single-line values, no quoting or expansion.
- **Profile Schema (`REPAIR_PROFILES` in env):** JSON map, e.g. `{"local": {"backend": "llamacpp", "url": "..."}, "openai": {"backend": "openai", "url": "...", "key_env": "..."}}`.

## Authorization

- **Who can execute:** Authenticated callers presenting both a valid review token (`review_server.py:291`) and admin token (`review_admin.py:38-55`, `review_server.py:282`).
- **Behavior without permission:** Missing review token returns 401; missing/invalid admin token returns 403; unset `REVIEW_ADMIN_TOKEN` returns 403 `{"error": "admin writes are disabled"}` (`specs/webui-admin-token/spec.md:29`).

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| Unknown key in `PUT /api/settings` body | HTTP 400 `{"error": "unknown key: <key>"}`. |
| Model name contains spaces, newlines, or shell meta | HTTP 400 `{"error": "invalid model format"}`. |
| Profile name not found in `REPAIR_PROFILES` | HTTP 400 `{"error": "unknown repair profile"}`. |
| `/config` filesystem read-only or disk full | Atomic write via temp file fails safely; HTTP 500 error returned; existing file intact. |
| Crash during `runtime.env` write | Temp file `.runtime.env.tmp` unlinked; `os.replace` guarantees atomic swap. |
| Merge loop runs while `runtime.env` is modified | `merge_pass.sh:42` sources file at pass start; active episode assembly uses consistent env. |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| Static profiles for URLs and keys | Allowing custom URL input in PUT payload | Prevents SSRF and credential exfiltration via stolen admin token pointing repair to attacker IP. |
| Source per-show in `gen_loop.sh` & per-pass in `merge_pass.sh` | Sourcing mid-episode or restarting container | Avoids corrupted `.muxtmp.mkv` sidecars and `.dubtitles.fail` poison markers (`container_run.sh:14-16`). |
| Compare `runtime.env` vs `effective.env` in UI | Polling builder process memory | Decoupled and resilient; `effective.env` represents true active state logged by builder (`review_requests.py:198`). |
| `verify_backend` and `verify_decision_model` limited to operator opt-in lists in the environment: `RUNTIME_VERIFY_BACKENDS` (default `llamacpp,ollama`, the local ones) and `RUNTIME_DECISION_MODELS` (default empty; comma-separated exact ids). PUT refuses anything else with 400 naming the variable; GET returns `allowed_verify_backends` and `allowed_decision_models`; the exporter drops stored values outside the lists | Free choice of any `MODEL_RE` id and any verify backend | A model id selects the provider, its URL and its billed key (OpenRouter, CommandCode), so an admin token could move glossary adjudication to a cloud account without a profile (reviewer-settings-write M5). The spec rule "URLs and credentials only via pre-configured names" applies to verify too |
| A profile replaces the whole repair endpoint: backend, URL, key variable name (exported empty when the profile has none), optional `extra_body` and `model_secondary` (exported empty when absent) | Layering a profile over the container's own key pointer and routing flags | Otherwise the container's API key and provider routing flags travel to the new profile's URL (M3) |
| `export --scope gen` leaves the profile out; only `merge_pass.sh` applies it | Applying the profile in both loops | An `openai` repair backend in the generate loop switches off punctuation restoration and glossary verify (M4) |
| Atomic write with `.prev` backup | Single direct file write | Enables one-click rollback if a selected model fails or OOMs. |

## Constraints

- Performance: `PUT /api/settings` executes within <50ms without invoking network requests.
- Security: Admin token never logged or persisted in `runtime.env`; API keys never written to disk by the web server.
- Media Safety: Setting updates take effect at next show/pass boundary; existing in-flight episode work finishes with prior configuration.

## Open questions (risks)

- [x] Decided (boss, default 2026-10-12): one env var `REPAIR_PROFILES` holding a JSON map, so compose needs a single line; invalid JSON disables writes and the settings page says why.
- [x] Decided (boss, default): no automatic connectivity test on write; the existing Test connection button covers it.
- [x] Decided (boss, default): reset deletes `/config/runtime.env` (back to the container environment) after copying it to `runtime.env.prev`.

## Implementation notes (boss, 2026-10-12)

- Neither loop `source`s `runtime.env`. `gen_loop.sh` and `merge_pass.sh` call `python3 review_settings_write.py export`, which parses the file, re-validates every value and prints only allow-listed, shell-quoted assignments; the shell evals that output. This replaces the "source" wording in the acceptance criteria.
- `VERIFY_BACKEND` accepts `llamacpp`, `ollama`, `openai` and `decision`, the same set as `glossary_verify.VERIFY_BACKENDS`.
