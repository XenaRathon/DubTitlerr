# Spec — Run Requests and Pipeline Scheduling

## Context and problem

The review server (`review_server.py`, container `dubtitle-review`) has no mechanism to trigger targeted runs or alter the generator schedule. The builder loop (`gen_loop.sh`, container `dubtitle-builder`) continuously sweeps `$ANIME_ORDER` or idles for `RESCAN_INTERVAL` (default 21600s, `gen_loop.sh:163-164`). Operators require on-demand runs for specific shows, seasons, or episodes and configurable nightly windows, without introducing concurrent worker races on `<stem>.muxtmp.mkv` (`AGENTS.md`, `Docs/sol-suggestions-10-10.md:26`).

## Acceptance criteria (verifiable)

- [ ] `POST /api/requests` writes an atomic JSON request file to `/config/requests/<id>.json` with mode `0664` (`common.py:38`), returning `201 Created` with the request ID.
- [ ] Submitting a request whose `show`, `season` and `episode_re` match an existing pending request returns `409 Conflict` with the existing ID.
- [ ] `GET /api/requests` returns all requests across pending, `done/`, and `failed/` via `os.scandir` without scanning media trees (`review_server.py:97-104`).
- [ ] At the start of each sweep `gen_loop.sh` writes the active `REPAIR_*`, `VERIFY_*`, `REQUIRE_ENG`, `GLOSSARY_ARC_TAGS`, `RESCAN_INTERVAL` and `MERGE_WINDOW` values (no keys, no secrets, names matching KEY/TOKEN/PASSWORD/SECRET are skipped) to `/config/effective.env` atomically; `specs/webui-settings` reads it.
- [ ] `gen_loop.sh` drains pending requests in FIFO order before regular sweeps (`gen_loop.sh:48`) and wakes from idle wait (`gen_loop.sh:164`) within 60 seconds of file arrival: the idle wait becomes a loop of 5 s `sleep_unless_stopped` slices that checks `/config/requests/` every 60 s instead of one `RESCAN_INTERVAL` sleep ( matches the 5 s slices of `sleep_unless_stopped`, `shell/lib.sh:39-51`).
- [ ] `gen_loop.sh` maps `season` and `episode_re` to `GENERATE_ONLY_RE` for `generate.py:1126-1128`, moves completed files to `/config/requests/done/`, and moves errors to `/config/requests/failed/`.
- [ ] A request carries no repair model in v1 (see Out of scope); repair uses the merge loop's configured model.
- [ ] `GET /api/schedule` and `PUT /api/schedule` read and atomically write `/config/schedule.json`.
- [ ] When outside the schedule window, `gen_loop.sh` sleeps until window open while remaining interruptible by `$STOP_FLAG` (`shell/lib.sh:32-60`).
- [ ] Concrete tests written: unit tests in `tests/test_run_requests_api.py`, `tests/test_schedule_api.py`, and loop tests in `tests/test_gen_loop_requests.py` (subprocess, stub `generate.py`).

## Out of scope (explicit)

- [ ] Modifying host systemd timers (`deploy/dubtitlerr-window-open.timer`) or invoking the Docker socket from the container.
- [ ] Concurrent worker execution: `gen_loop.sh` remains the sole executor to prevent `<stem>.muxtmp.mkv` corruption (`AGENTS.md`).
- [ ] Automatic download or synchronization of media files from Sonarr/Radarr.
- [ ] Arbitrary shell execution or arbitrary environment variable injection from the web UI.
- [x] Out of scope, decided (user, 2026-10-12): per-request repair model override: repair runs in `merge_pass.sh:75` on its own 600 s loop (`container_run.sh:23`), a separate process from the request's sweep, so a per-request env would race with it. Needs a design decision first (see Open questions).

## Data contracts

- **Inputs (`POST /api/requests`):**
  - `show` (string, required): Directory name under `ANIME_ROOT` (`gen_loop.sh:11`). Must exist and contain no path traversal (`/` or `..`, `review_server.py:29-32`).
  - `season` (integer, optional): Positive integer. Derived regex: `(?:^|[\W_])[Ss]0*<season>[\W_Ee]`.
  - `episode_re` (string, optional): Valid Python regular expression tested via `re.compile()`.
  - (`repair_model` removed in v1, see Out of scope.)
  - `require_eng` (integer, optional): `0` or `1`, overrides `REQUIRE_ENG` (`gen_loop.sh:148`, `generate.py:246`).
- **Outputs (`POST /api/requests`):** `201 Created` with `{"id": string, "status": "pending"}` or `409 Conflict` with `{"error": string, "existing_id": string}`.
- **Request File Schema (`/config/requests/<id>.json`):**
  - Fields: `id` (string), `webhook` (object|null, set only by specs/arr-webhooks: `{source, event, remote_path}`), `created_at` (ISO-8601 string), `show` (string), `season` (int|null), `episode_re` (string|null), `generate_only_re` (string|null), `require_eng` (int|null), `status` ("pending"|"running"|"done"|"failed"), `error` (string|null), `finished_at` (ISO-8601 string|null).
- **ID and Ordering:** `<timestamp>-<8_hex_uuid>.json` (e.g. `20261012T140000Z-a1b2c3d4.json`). Strict FIFO ordering via lexicographical sort.
- **Schedule File Schema (`/config/schedule.json`):**
  - `{"enabled": boolean, "open": string (HH:MM), "close": string (HH:MM), "tz": string (IANA name)}`.
  - Next open computed in the loop with `zoneinfo.ZoneInfo(tz)`. `common.within_window` (`common.py:978`) takes a local-time "HH:MM-HH:MM" spec and drives only the merge loop (`container_run.sh:47`); it is not reused here.
- **Merge Pass & REQUIRE_ENG Interaction:**
  - `merge_pass.sh:60-70` picks up `.eng.dubtitles.srt` sidecars independently on its interval (`container_run.sh:23`). No separate mux trigger is needed.
  - If `require_eng` is set, `gen_loop.sh:148` passes `REQUIRE_ENG="$require_eng"` to `generate.py`.
- **External dependencies:** Shared filesystem mount `/config` between `dubtitle-review` and `dubtitle-builder`.

## Authorization

- **Who can execute:** reads (`GET /api/requests`, `GET /api/schedule`) need the review token (`X-Review-Token` header or `dubtitlerr_token` cookie, `review_server.py:124, 127-145`). Writes (`POST /api/requests`, `PUT /api/schedule`) additionally need the admin token (`X-Review-Admin-Token` matching `REVIEW_ADMIN_TOKEN`; decided by user 2026-10-12). If `REVIEW_ADMIN_TOKEN` is unset the write routes return 403.
- **Behavior without permission:** not in `OPEN_ROUTES` (`review_server.py:770`); missing review token returns 401 `{"error": "a token is required"}` (`review_server.py:968-969`); missing or wrong admin token on a write returns 403.

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| Request arrives mid-show | Active show finishes current unit; request is executed at next show boundary (`gen_loop.sh:48`). |
| Request arrives when window is closed | Request persists in `/config/requests/`; executes immediately when window opens. |
| Show directory does not exist | `gen_loop.sh:54` detects missing path, moves file to `failed/` with `error: "show directory not found"`. |
| Invalid regex submitted | `POST /api/requests` rejects with `400 Bad Request`. If corrupted on disk, `generate.py:1110` exits 2 and loop moves file to `failed/`. |
| Container restart mid-request | Incomplete request marked `.running` on disk is detected at startup and moved to `failed/` with `error: "interrupted by restart"`. |
| Retention limit reached | Files in `/config/requests/done/` and `/config/requests/failed/` older than 7 days are pruned during queue drain. |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| File queue in `/config/requests/` | Docker socket exec or REST IPC | Preserves single-executor invariant; avoids root Docker socket exposure (`AGENTS.md`). |
| Scan `/config/requests/` for state | Walk `MERGE_ROOTS` on every API call | Avoids 297s CIFS filesystem walk penalty (`review_server.py:97-104`). |
| Pre-compile regex in API route | Defer regex validation to `generate.py` | Fails fast with `400` before writing an unexecutable file to the queue. |
| Dynamic `/config/schedule.json` | Direct modification of host systemd timers | Container lacks host systemd privileges; systemd timers in `deploy/` remain outer bounds. |

## Constraints

- Performance: `GET /api/requests` must complete in <50ms by scanning only `/config/requests/`.
- Media Safety: `gen_loop.sh` must remain the sole executor to prevent `<stem>.muxtmp.mkv` overwrites (`AGENTS.md`).
- Compatibility: `merge_pass.sh:60-70` picks up sidecars independently without requiring new mux IPC.

## Open questions (risks)

- [x] Decided (user, 2026-10-12): no completion notification; request state is visible in the UI only.
- [x] Decided (user, 2026-10-12): a request waits for the current show to finish; no preemption. The UI shows "queued, waiting for <show>".
- [x] Decided (user, 2026-10-12): per-request repair model is dropped from v1. Model choice is global (compose now, runtime.env in settings Phase 2).
