# Spec — Sonarr/Radarr Webhook Receiver

## Context and problem

> Checked 2026-10-12 against the upstream sources: Sonarr v5.0.0.2569 (beta) and Radarr v6.4.4 webhook payload classes differ from Sonarr v4.0.20 and Radarr v5.28 only by ADDED fields (Sonarr: `indexerFlags`, `finaleType`, `malIds`, `aniListIds`, `originalCountry`). No field this spec reads was renamed or removed; event names are unchanged. The receiver must ignore unknown fields. Sonarr v5 removes Basic Auth for its own UI, which does not affect the webhook (custom header or query token).

Sonarr/Radarr "Connect > Webhook" fires on every import, but the pipeline only learns about new
episodes when an operator files a run request by hand (`specs/webui-run-control/spec.md:9`). The
receiver turns Download/Upgrade events into queue files in `/config/requests/` so the next sweep
picks the series up; the loop stays the sole executor (`specs/webui-run-control/spec.md:22`).

## Acceptance criteria (verifiable)

- [ ] `POST /api/webhook/sonarr` and `POST /api/webhook/radarr` exist in `route()`
  (`review_server.py:960`), each with its own `WEBHOOK_TOKEN` check; `OPEN_ROUTES`
  (`review_server.py:770`) is untouched.
- [ ] `WEBHOOK_TOKEN` unset → both routes return `404`; missing token → `401`, wrong token → `403`.
- [ ] Sonarr Download (including `isUpgrade: true`) and Upgrade for a series under `ANIME_ROOT`
  (`gen_loop.sh:11`) enqueue one request file and return `200` with its id.
- [ ] Season/episode parse from `episodeFile.relativePath` (`SxxEyy`); the request carries the
  queue's `season` int and a derived `episode_re` (`specs/webui-run-control/spec.md:31-32`).
- [ ] Rename/Test/Health/unknown events return `200` and enqueue nothing; Test says the hook works.
- [ ] Same series plus file path within 24 h enqueues once; repeats return `200` with the existing id.
- [ ] Bodies over 256 KiB get `413`; unparseable JSON gets `400`; the token never appears in logs.
- [ ] Tests in `tests/test_review_webhooks.py` with fixtures under `tests/fixtures/webhooks/`.

## Out of scope (explicit)

- Downloading or syncing media; the arr suite owns fetching (mirrors `specs/webui-run-control/spec.md:23`).
- Starting runs or touching the builder: the loop remains the sole executor.
- Notifying Sonarr/Radarr or the operator on completion (no completion callback by decision, `specs/webui-run-control/spec.md:80`).
- Non-anime libraries: Radarr movies outside `ANIME_ROOT` are `200 ignored`, never auto-added.

## Data contracts

- **Sonarr fields read:** `eventType`, `isUpgrade`, `series{title,path,tvdbId}`,
  `episodes[]{seasonNumber,episodeNumber}`, `episodeFiles[]{relativePath,path}` (or singular
  `episodeFile{relativePath,path}` on older payloads). `series.path` is the arr-side path.
- **Radarr fields read:** `eventType`, `movie{title,folderPath,tmdbId}`,
  `movieFile{relativePath,path}`. Only `Download` enqueues; everything else is `200 ignored`.
- **Enqueue mapping:** `show` is the first path component below `ANIME_ROOT` after remote-path
  mapping; `season` is the int from `SxxEyy` (or `episodes[0].seasonNumber` when the path has none);
  `episode_re` joins one `[Ss]0*<S>[Ee]0*<E>(?!\d)` branch per episode with `|` (the trailing `(?!\d)` stops E2 matching E20, because `generate.py:1112` uses `rx.search` on the file name); movies use
  `season: null, episode_re: null`. The file written matches the queue schema
  (`specs/webui-run-control/spec.md:36-38`) plus a `webhook{source,event,remote_path}` object.
- **Responses:** `200 {"ok": true, "id": "<request id>"}` enqueued (or dedup hit, same shape);
  `200 {"ok": true, "ignored": true, "reason": "..."}` for Rename/Health/unknown events,
  unmapped paths, and movies outside `ANIME_ROOT`; `200 {"ok": true, "message": "webhook works,
  nothing enqueued"}` for Test; `400` bad JSON; `401` missing token; `403` wrong token;
  `404` when `WEBHOOK_TOKEN` is unset; `413` over 256 KiB.
- **External dependencies:** none beyond the `/config` mount shared with the builder
  (`specs/webui-run-control/spec.md:45`).

## Authorization

- **Who can execute:** callers presenting `WEBHOOK_TOKEN` as `X-Webhook-Token` header (Sonarr's
  webhook "Headers" field) or `?token=` query fallback, compared with `secrets.compare_digest`
  (same timing-safe idiom as `authorised()`, `review_server.py:254`).
- **Behavior without permission:** missing token → `401`; wrong token → `403`; unset
  `WEBHOOK_TOKEN` → `404` on both routes, hiding them entirely. The routes are handled inside
  `route()` (`review_server.py:960`), never added to `OPEN_ROUTES` (`review_server.py:770`), so the
  exact-list test (`tests/test_review_login.py:234`) keeps passing unchanged.

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| Series path not under `ANIME_ROOT` | `200 ignored` with reason; non-anime series must not look like errors in Sonarr. |
| `REMOTE_PATH_MAPPINGS` matches nothing | The raw arr path is tried as-is; still outside the root → `200 ignored`. |
| Traversal, `..`, symlinks escaping the root | Resolved with `realpath`; outside → `200 ignored`, nothing enqueued. |
| Multi-episode file (`S01E01E02`) | One request; `episode_re` alternates each episode branch. |
| Relative path has no `SxxEyy` | Fall back to `episodes[0]` numbers; absent → season-only request for the show. |
| Same file re-imported within 24 h | Dedup hit: `200` with the existing id; `failed/` entries do not block re-enqueue. |
| Request file already pending (same show/season/episode_re) | Underlying queue answers `409` (`specs/webui-run-control/spec.md:10`); webhook returns `200` with that id. |
| Builder mid-sweep | Request waits for the show boundary like any manual request (`specs/webui-run-control/spec.md:56`). |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| Separate `WEBHOOK_TOKEN` via header or `?token=`, `compare_digest`, routes outside `OPEN_ROUTES` | Reuse review/admin token or open the routes | Arr can send custom headers; a dedicated secret limits blast radius and the open list stays pinned (`tests/test_review_login.py:234`). |
| `REMOTE_PATH_MAPPINGS="remote=local;..."`, longest prefix wins | Trust arr paths directly | Arr reports its own mount view; unmapped client paths risk traversal. |
| 24 h dedup on series plus file path, state in the request files | New database or sidecar index | The queue files are already the store; no new state to migrate or back up. |
| Loop stays sole executor; no requester notification | Webhook triggers a run or callback | Preserves the single-executor invariant; completion callbacks were decided out (`specs/webui-run-control/spec.md:80`). |
| Radarr accepted only under `ANIME_ROOT`, else `200 ignored` | `404` or auto-adding foreign movies | The library is anime; arr suites manage other content that must not error or intrude. |

## Constraints

- Performance: show resolution and dedup scan only `/config/requests/` filenames and small JSON sidecars, never the media tree (queue style, `specs/webui-run-control/spec.md:11`).
- Body cap 256 KiB (same fail-fast idea as `LOGIN_MAX_BODY`, `review_server.py:771`).
- Security: token never logged (headers, query, and body excluded from log lines); mapped paths confined under `ANIME_ROOT` (`gen_loop.sh:11`).

## Open questions (risks)

- [x] Decided (boss, default): keep 401 for a missing token and 403 for a wrong one.
- [x] Decided (boss, default): 24 h window; `done/` entries within the window also block re-enqueue, `failed/` entries do not.
- [x] Decided (boss, default): one request per file with an alternation regex.
- [x] Decided (boss, default): no 429 in v1; dedup is the rate limit. The optional 429 mentions above are removed.
- [x] Decided (boss, default): no escaping; a path containing `;` or `=` cannot be mapped and is ignored with a reason.
- [x] Decided (boss, default): no merging; an Upgrade dedups by file path only.
- [x] Decided (boss, default): Test requires the token like every other event.

## Auth relation to the admin token

The webhook token is the only credential these routes accept. The admin token required for `POST /api/requests` (specs/webui-run-control, user decision 2026-10-12) is not accepted here and not needed: the webhook writes the queue file through the same internal function, bypassing the HTTP admin check, so `WEBHOOK_TOKEN` must be treated as a write credential equal to the admin token.

## Implementation notes (boss, 2026-10-12, from the code-versus-spec review)

- The enqueue response may carry `"hint": "anime"` when the payload looks like anime (`series.type == "anime"` or non-empty `malIds`/`aniListIds`). It is informational only; the path under `ANIME_ROOT` stays the gate.
- `episode_re` holds only the episode branches, `(?:[Ee]0*(?:N1|N2))(?!\d)`. The season token comes from the `season` field, which `review_requests.derive_generate_only_re` turns into `[Ss]0*<season>`; repeating it in `episode_re` would duplicate the season match. Specials (season 0) require `S00`.
- A refusal from the queue (`create`/`validate`) is returned to Sonarr/Radarr as `200 {"ok": true, "ignored": true, "reason": ...}`; an `episode_re` longer than 200 characters falls back to a season-only request.
