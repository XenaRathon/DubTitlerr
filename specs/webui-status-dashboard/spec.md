# Spec — Read-Only Episode Status Dashboard

## Context and problem

Operators lack visibility into pipeline progress across library episodes without inspecting filesystem sidecars over SSH. The review web UI (`web/src/App.svelte:31-32`) surfaces only episodes with pending human review items (`review_server.py:339-378`), leaving transcribed, repaired, muxed, failed, and stale states invisible. A read-only status dashboard provides Servarr-style visibility without adding filesystem tree walks over high-latency network mounts (`review_server.py:93-104`).

## Acceptance criteria (verifiable)

- [ ] New route `GET /api/status` is registered in `review_server.py:970-997` and delegates to new module `review_status.py`.
- [ ] `GET /api/status` performs zero filesystem walks (`os.walk`), sourcing stems only from the already-filled `_STEMS_CACHE` (`review_server.py:105`), never by calling `known_stems()` on the request thread (it walks when the cache has expired, `review_server.py:300-318`). If the cache is empty the route returns 503 `{"error": "cache warming"}`. Episodes without a `.dubtitles.conf.json` are not in the cache and are not listed.
- [ ] File reads per stem on the requested page slice are bounded to at most 5 small sidecars: `.dubtitles.done` (`common.py:363-395`), `.dubtitles.fail` (`generate.py:949`), `.dubtitles.stages.json` (`common.py:477-526`), `.dubtitles.repair-summary.json` (`repair.py:1900-1908`), and `.dubtitles.conf.json` (`review_server.py:121`).
- [ ] Episode stage is classified into one of: `transcribed`, `repaired`, `muxed`, `failed`, `stale`, or `pending-review`.
- [ ] Episode payload includes: `show`, `season`, `episode`, `stem`, `stage`, `last_outcome` (`common.py:480-493`), `repair_model` (read from the summary key `"model"`, `repair.py:1900`), `text_version` (`common.py:390`), `pending_review_count` (`review_server.py:350-372`), and `updated_at`.
- [ ] Header includes: `builder_heartbeat_age_s` (`common.py:67-73`), `last_sweep_end` (`review_server.py:1433`), `current_show`, `counts_per_stage` (page slice only, see `counts_scope`), `counts_scope` ("page"), `cache_age_s`, `total`, `page`, `limit`, and `pages`.
- [ ] Supports query filtering by `show` and pagination via `page` (default 1) and `limit` (default 50, maximum 200).
- [ ] Unauthenticated requests return HTTP 401 (`review_server.py:968-969`); `OPEN_ROUTES` (`review_server.py:770`) remains unchanged.
- [ ] Corrupt or unreadable stamps fall back to safe defaults without raising HTTP 500 (`common.py:401-402,534-535`).
- [ ] Concurrency with `review_server._warm_cache_forever` (`review_server.py:1635-1647`) is non-blocking and thread-safe under Python atomic reference swaps (`review_server.py:317`).
- [ ] `web/src/App.svelte:31-32` adds `dashboard` to `View`, navigation entry, and renders `web/src/pages/Dashboard.svelte` with Servarr-style status colors.
- [ ] Backend test suite in `tests/test_review_status.py` passes: `test_status_requires_auth`, `test_status_registered`, `test_status_zero_walks`, `test_status_stages`, `test_status_cost_bound`, `test_status_malformed_sidecars`, `test_status_cache_age_and_heartbeat`, `test_status_filtering_and_pagination`, `test_status_concurrency_with_warm_thread`.
- [ ] Frontend tests in `web/tests` pass: unit badge styling in `web/tests/review.test.mjs` and navigation/table display in `web/tests/browser/dashboard.spec.ts`.

## Out of scope (explicit)

- Mutation actions (e.g., triggering re-transcription, clearing `.dubtitles.fail`, or forcing re-mux).
- Triggering on-demand library tree walks or invalidating `review_server._STEMS_CACHE` (`review_server.py:105,317`).
- Unauthenticated access to `/api/status`.
- Real-time WebSocket or Server-Sent Events push updates.

## Data contracts

- **Inputs:** `GET /api/status?show=<str>&page=<int>&limit=<int>`. Header: `X-Review-Token: <str>` (`review_server.py:124`, `web/src/App.svelte:119`) or `dubtitlerr_token` cookie (`review_server.py:143,1493`).
- **Outputs:** HTTP 200 JSON:
  `{"header": {"builder_heartbeat_age_s": 14.2, "last_sweep_end": 1726058400.0, "current_show": "One Pace", "cache_age_s": 8.5, "counts_per_stage": {"transcribed": 10, "repaired": 4, "muxed": 120, "failed": 1, "stale": 6, "pending-review": 2}, "total": 143, "page": 1, "limit": 50, "pages": 3}, "episodes": [{"show": "One Pace", "season": "Season 31", "episode": "One Pace - E01", "stem": "/media/One Pace/Season 31/One Pace - E01", "stage": "muxed", "last_outcome": "ok", "repair_model": "qwen3-4b-instruct", "text_version": 4, "pending_review_count": 0, "updated_at": 1726058100.0}]}`.
- **Schemas / models affected:** Routing in `review_server.py:970-997`, `web/src/App.svelte:31` (`View`), `web/src/types.ts` (`DashboardResponse`, `EpisodeStatus`).
- **External dependencies:** None (reads existing filesystem sidecars and in-memory caches).

## Authorization

- **Who can execute:** Authenticated callers presenting a valid token via header `X-Review-Token` (`review_server.py:124`) or cookie `dubtitlerr_token` (`review_server.py:143,1493`).
- **Behavior without permission:** HTTP 401 `{"error": "a token is required"}` (`review_server.py:968-969`).

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| Unreadable/corrupt `.dubtitles.done` | `common.read_stamp` returns `None` (`common.py:401-402`); defaults `text_version: null`, maps stage to `transcribed` or `stale`. |
| Unreadable/corrupt `.dubtitles.stages.json` | `common.read_stages` returns `{}` (`common.py:534-535`); `last_outcome` defaults to `"unknown"`. |
| Missing/unreadable `.dubtitles.repair-summary.json` | Swallows `OSError`/`ValueError`; defaults `repair_model: null`. |
| Poison marker `.dubtitles.fail` exists | Stage maps to `failed` (`generate.py:949`); `last_outcome: "crashed"`. |
| Stamp behind current `text_version` | Stage maps to `stale` when the `.dubtitles.done` stamp records a `text_version` below the current one (`common.stamp_valid`, `common.py:363-395`). There is no standalone `.dubtitles.stale` marker: `generate.py:405,487` only appends `.stale` to parked sidecars, which the dashboard does not look for. |
| Heartbeat missing (`common.HEARTBEAT_PATH`) | `common.read_heartbeat()` returns `None` (`common.py:72-73`); header fields set to `null`. |
| Stems cache empty | 503 `{"error": "cache warming"}`; the warm thread fills it (`review_server.py:1635`). Expired but filled: serve the stale list and report `cache_age_s`. |
| Page out of bounds (`page > pages`) | Returns HTTP 200 with empty `episodes: []` and correct `header` pagination metadata. |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| Delegate implementation to `review_status.py` | Placing all logic inside `review_server.py` | Keeps `review_server.py` lightweight and follows module delegation pattern like `review_apply.py` (`review_server.py:760`). |
| Read sidecars on paginated slice only | Reading sidecars across all library stems per request | 50 episodes require up to 250 stats/reads (~25ms), whereas touching 1,000 episodes on network CIFS/NFS takes >170s (`review_server.py:110-112`). |
| Reuse `known_stems()` cache (`review_server.py:285-320`) | Triggering directory walk on request | Full walk across media library costs 115-297s on network mounts (`review_server.py:99-102,1619`). |
| Expose `cache_age_s` in header | Statting directories to test freshness | Stat validation per request defeats cache savings (`review_server.py:110-116`). |

## Constraints

- Performance / cost: Bounded to maximum 5 stat/read calls per stem on paginated page; no `os.walk` directory listings.
- Privacy / security: Token requirement enforced; `OPEN_ROUTES` (`review_server.py:770`) is unchanged; media stems verified under `ROOTS` (`review_server.py:310`).
- Concurrency: Thread-safe reads against `review_server._STEMS_CACHE` (`review_server.py:105,317`) while background `_warm_cache_forever` runs (`review_server.py:1635-1647`).

## Open questions (risks)

- [x] Decided (boss, default): `counts_per_stage` counts the returned page only and the header says `counts_scope: "page"`. A library-wide count needs a stat per stem, which is the walk cost this spec forbids. A background aggregate can be a later spec.
- [x] Decided (boss, default): `current_show` is null unless the heartbeat already carries it; this spec does not change `gen_loop.sh`.
- [x] Decided (boss, default): colours come from the tokens in specs/servarr-restyle; the dashboard defines no hex values of its own.
