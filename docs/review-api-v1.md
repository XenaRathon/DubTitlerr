# Review workspace API, version 1

This describes the API used by `/review`. Routes remain unversioned for compatibility;
this document versions their contract. Stems are opaque server-issued episode identifiers.
Clients must not construct paths or infer filesystem access from a stem.

## Authorization and response handling

Send `X-Api-Key: <token>` on every `/api/*` request except the open routes below.
Existing cookie authorization also remains supported by the Python handler. Missing/invalid
credentials return HTTP 401 with `{"error":"a token is required"}` unless `REVIEW_AUTH=off`
was explicitly configured. Tokens do not belong in URLs. All responses carry
`Cache-Control: no-store`.

The token is the only credential the server checks. An operator may additionally enable a
human login (`REVIEW_USERNAME` with `REVIEW_PASSWORD` or `REVIEW_PASSWORD_FILE`): a correct
username and password fetch the token from `POST /api/login`, and every other route still
takes the token exactly as before. **The password travels in clear text over plain HTTP.**
Use it only on a trusted LAN or behind TLS.

Routes that need no token (the explicit list `OPEN_ROUTES` in `review_server.py`, plus the
`/review` document and its assets): `GET /healthz`, `GET /api/auth-mode`, `POST /api/login`.

Except audio success and static assets, bodies are JSON. Existing mutation endpoints may
return HTTP 200 with an `error` field or per-item `errors`; clients must inspect the body
and must not treat HTTP 200 alone as a saved batch.

## Routes

| Method and path | Request | Response |
| --- | --- | --- |
| GET `/review`, `/review/` | None | Inert HTML application; no authentication or private data |
| GET `/review/assets/<name>` | None | Allow-listed static JS/CSS/font/SVG build asset |
| GET `/api/episodes` | None | `{"episodes":[Episode]}` |
| GET `/api/episode` | Query `stem`; optional `all` (any non-empty value, including `0`, adds the guard-refusal backlog) | `{"stem","name","entries":[Entry],"settled_elsewhere"}` |
| GET `/api/shared` | None | `{"pairs":[SharedPair]}` |
| POST `/api/decide` | `{"stem","decisions":[Decision]}`. The legacy single form `{"stem","index","verdict","text","note"}` is also accepted and answered as `{"saved":true,"verdict","show","queue_cleared"}` or `{"error"}` | `{"saved":number,"show":string,"errors":[],"queue_cleared":boolean}`; optional `warning`. Always these four keys, also when nothing was saved. An unknown episode, a show that cannot be resolved, or a store that could not be written answer `{"error":string}` (the last with `errors`) instead |
| POST `/api/shared` | `{"decisions":[SharedDecision]}` | `{"saved":number,"errors":[]}` |
| GET `/api/auth-mode` | None | `{"password_login":boolean}`: whether `POST /api/login` exists. Nothing else |
| POST `/api/login` | JSON `{"username","password"}`, `Content-Type: application/json`, at most 4 KiB | 200 `{"token"}`; 401 `{"error":"wrong username or password"}`; 404 when password login is not configured; 413/415 for a large body or another content type; 429 `{"error","retry_after"}` with a `Retry-After` header |
| POST `/api/apply` | `{"stem"}` | Existing apply report including `changed`, optional `stamp_dropped`, `ass_dropped`, or `error` |
| GET `/api/audio` | Query `stem`, `index`, `id`, optional `occurrence` | `audio/wav` on 200; JSON error otherwise |
| GET `/healthz` | None | Unauthenticated `{"ok":true}` on 200, or `{"ok":false,"reasons":[]}` on 503 |

Unknown workspace assets return 404. A missing frontend build returns 503 with build
instructions. Static paths are restricted to the built index and flat asset directory.
The SPA document carries a same-origin Content Security Policy; no inline scripts or
external resources are needed.

## Data shapes

`Episode` contains `stem`, `name`, `show`, `season`, and numeric `pending`, `admitted`,
`refused` counts. The list represents episodes with pending questions, not the full library.
Counts can include repeated pairs that one shared decision settles.

`Entry` includes queue fields `stage`, `reason`, `original_text`, `proposed_text`, optional
`reference`, and derived fields:

- `index`: legacy queue offset, not a stable identity.
- `id`: opaque identity of the exact stage/reason/original/proposed question. Submit it
  unchanged alongside `index`. Resolved, replaced, already-decided, or orphaned questions
  are refused as stale. IDs do not encode a request authorization.
- `risk`: `words`, `substitution`, or `punctuation`.
- `offered`: allowed verdict strings for this question; enforce these on the server.
- `starts`: occurrence times in seconds, aligned with `context` occurrences.
- `context`: array of `{before:string[], after:string[]}`.
- `permanent`: legacy field indicating absence of a subtitle anchor.
- `avg_logprob` (optional): the ASR model's average log-probability for the card, when the
  repair stage recorded one. Passed through from the queue record; absent otherwise.

`Decision` contains `index`, `id`, `verdict`, and optional `text` and `note`. Verdict is
`accept`, `reject`, `correct`, or `force`, restricted by `offered`. A correction needs
visible text. A correction equal to the original is normalized to rejection by the
existing store. Legacy clients may omit `id`; they retain index-only semantics.

`SharedPair` contains opaque stable `id`, `show`, `original_text`, `proposed_text`,
`episodes`, `risk`, and `offered`. `pair` is a display order only. `SharedDecision`
contains `id`, `verdict`, and optional correction `text`. Shared decisions affect the
show-wide store without rewriting each episode's queue. No shared audio endpoint exists.

Per-item save errors identify the item by `index` (episode saves) or `id` (shared saves);
`id` is `null` for a malformed item or a store failure, whose message names the show.
Re-fetch the authoritative list to determine which drafts remain open following partial
success; do not discard the whole draft batch on failure.

## Password login

`POST /api/login` exists only when the operator configured it (otherwise 404, and
`/api/auth-mode` reports `false`). Both fields are compared in constant time on their UTF-8
bytes, always both, so a wrong username and a wrong password are indistinguishable. After
five consecutive failures from one client address within five minutes the address gets 429
with `Retry-After: 60` (the credentials are not compared during the lockout); a success
clears the count. The counter lives in memory, tracks a bounded number of addresses and
resets on restart. An empty configured username or password disables the login instead of
opening it. Neither the password nor which field was wrong is ever logged.

## Audio evidence

The server validates the entry identity and derives the card's time bounds from the
known episode, not from client-provided timestamps. `occurrence` is a zero-based index
into cards matching the original text; default 0. Clips include up to 1.5s context before
and after, capped at 20s. Longer cards are therefore truncated previews, not full-card
recordings. Only an English-tagged, non-commentary audio stream is selected.

The response is mono, 16 kHz PCM WAV. It requires no range requests or browser media
cookies: the frontend fetches with the token header and creates an in-memory blob URL.
Two extraction slots, a 10s probe timeout, and a 30s decode timeout bound resource use.
No preview file is persisted.

| HTTP status | Meaning |
| --- | --- |
| 400 | `invalid parameter: …` when `index` or `occurrence` is missing, not an integer or negative; `no playable card for this occurrence` when the index or occurrence does not point at a usable card |
| 401 | Authentication required |
| 404 | Unknown episode, missing media, or evidence outside configured roots |
| 409 | Entry identity changed; reload before listening |
| 422 | No English dialogue audio track |
| 429 | Both extraction slots busy; retry later |
| 502 | Probe/decode failed or timed out |

## Save versus apply

Saving writes decisions, not media. Applying is an explicit second action that rebuilds
subtitle sidecars and removes the completion stamp so the existing merge worker can
remux. It is not a synchronous mux or a new worker. Frontends should confirm this action
and must not imply that queued remux means remux has already completed.
