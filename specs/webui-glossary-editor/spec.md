# Spec — Web UI Glossary Editor

## Context and problem

Operators fix recurring dub-name mishears by editing per-show glossary JSON over SSH, while the
review server exposes no glossary route (route table at `review_server.py:960`) and the frontend
offers only `inbox`/`shared` views (`web/src/App.svelte:32`). A token-authenticated Glossary view
lets operators view, add, edit, and delete terms in the deployed glossaries without SSH.

## Acceptance criteria (verifiable)

- [ ] `GET /api/glossary` returns every show that has a deployed glossary, sorted by name.
- [ ] `GET /api/glossary?show=<name>` returns the editable keys plus a `version` for concurrency.
- [ ] `POST /api/glossary` applies `add`/`update`/`delete` on `names`, `phrases`, `hard_fixes` only,
  preserving all machine-owned keys byte-for-byte in meaning.
- [ ] Every write holds `glossary_lock.locked(path, "webui")` (`glossary_lock.py:69`; it yields a bool, so the handler must test it and return 503 on False), writes via
  temp file plus rename, and copies the prior file to `<file>.bak-<UTC timestamp>`; at most 20
  backups are kept per glossary.
- [ ] A stale `expected_version` fails with `409` and the current version; nothing is written.
- [ ] `hard_fixes` stays literal: keys match escaped with word boundaries (`glossary.py:383`) and are
  lowercased on load (`glossary.py:127`).
- [ ] Invalid payloads fail with `400`; unknown shows with `404`; a busy glossary with `503`.
- [ ] The frontend adds `view=glossary` (`web/src/App.svelte:32`) rendering
  `web/src/pages/Glossary.svelte`: searchable per-key tables, add/edit/delete, delete confirm;
  `OPEN_ROUTES` (`review_server.py:770`) is unchanged.
- [ ] Each write emits one audit log line (operator, time, show, op, term) alongside the backup.
- [ ] Tests land in `tests/test_review_glossary.py` (style: `tests/test_review_server.py:1`):
  list/detail round-trip, add/update/delete per key, machine-key preservation, 409 on stale
  version, 503 on busy lock, traversal rejection; plus `web/tests/glossary.test.mjs` (style:
  `web/tests/review.test.mjs:1`; fixtures via `web/tests/fixture_server.py:28`) for search and
  delete-confirm behavior.

## Out of scope (explicit)

- Creating a new glossary file; a missing file is `404` on both read and write.
- Editing machine-owned keys (`verified`, `flagged`, `acquired`, `known`, `_curated`, any
  underscore key; schema in `docs/wiki/Reference.md:397`).
- Re-running finished episodes; already-built output is untouched (re-apply stays manual via
  `tools/reapply_glossary.py:4`).
- Changes to authentication, `OPEN_ROUTES`, or the builder sweep loop.

## Data contracts

- **List (`GET /api/glossary`):** `200 {"shows": ["My Hero Academia", "One Pace"]}` — stems of
  `*.json` in the deployed dir (`decisions.py:38`), excluding sidecars (`*.lock` never matches
  `*.json` per `glossary_lock.py:9`; also excluded: `*.review-pending*`, `*.acquire-cache.json`,
  `*.journal.jsonl`, `*.lastrun.json`, `.bak-*`).
- **Detail (`GET /api/glossary?show=One%20Pace`):** `200 {"show": "One Pace", "version": "<sha256
  hex of raw file bytes>", "names": [...], "phrases": [...], "hard_fixes": {...}}`; unknown show
  gives `404 {"error": "no such glossary"}`.
- **Write (`POST /api/glossary`):** body `{"show": str, "op": "add"|"update"|"delete", "key":
  "names"|"phrases"|"hard_fixes", "term": str, "value": str|null, "expected_version": str}`.
  For `names`/`phrases`: `add` inserts `term`; `update` renames `term` to `value`; `delete`
  removes `term` (`value` ignored). For `hard_fixes`: `add`/`update` set `term` to `value`;
  `delete` removes `term`.
- **Write responses:** `200 {"ok": true, "show": str, "version": "<new sha256>", "backup":
  "<file>.bak-<UTC timestamp>"}`; `400` validation, `404` unknown show, `409 {"error": "version
  conflict", "version": "<current sha256>"}`, `503 {"error": "glossary busy"}` when the lock
  is held past its wait.
- **Validation:** all terms/values are strings, trimmed, with no empty or control characters;
  `names` entries 1–80 chars; `phrases` entries 1–120 chars and contain a space (single tokens
  belong in `names`); `hard_fixes` key/value 1–120 chars, key unequal to value
  case-insensitively, no case-insensitive duplicate keys (load lowercases keys,
  `glossary.py:127`); POST body capped at 64 KiB.
- **External dependencies:** shared `/config/glossaries` mount (default in `decisions.py:38`)
  between review and builder containers; no new services.

## Authorization

- **Who can execute:** holders of the review token via `X-Review-Token` header
  (`review_server.py:124`) or the page cookie fallback accepted by `authorised()`
  (`review_server.py:254`); all three routes sit behind it.
- **Behavior without permission:** `401 {"error": "a token is required"}` (`review_server.py:969`);
  `OPEN_ROUTES` stays exactly the three pinned entries (`tests/test_review_login.py:234`).

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| File missing | `404` on GET and POST; the editor never creates files. |
| File unreadable | `500 {"error": "glossary unreadable"}`; POST writes nothing. |
| Invalid JSON on disk | `500 {"error": "glossary corrupt"}` on GET; POST refused, nothing written. |
| `expected_version` stale | `409` with current version; operator reloads and retries. |
| Builder mid-sweep | Glossary loads once per stage start (`generate.py:136`); repair resolves per episode (`repair.py:295`). Edits reach work started after the write; finished episodes are not re-run (manual `tools/reapply_glossary.py:4`). |
| Lock busy | `503 {"error": "glossary busy"}`; no partial write, backup, or prune. |
| Traversal in `show` (`/`, `..`, NUL) | `400`; `show` resolves only against the server-side stem list. |
| More than 20 backups | Oldest `.bak-*` pruned after a successful write, newest 20 kept. |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| Editable keys are `names`, `phrases`, `hard_fixes` only; machine keys preserved | Full-document edit | Verifier/acquire provenance (`verified`, `flagged`, `acquired`, `known`; `docs/wiki/Reference.md:397`) must survive UI edits. |
| Writes under `locked(path, "webui")` with temp-plus-rename and UTC backups, max 20 | Direct overwrite | The advisory lock is the only cross-stage coordination (`glossary_lock.py:73`); backups give human undo. |
| New routes behind existing token auth; `OPEN_ROUTES` unchanged | Separate editor credential | One auth surface; the open list is pinned by test (`tests/test_review_login.py:234`). |
| Deployed `GLOSSARY_DIR` only (`decisions.py:38`, `repair.py:189`); server-side stem list | Repo `glossaries/` copy or client-supplied path | The pipeline reads the deployed dir, never the repo copy; client paths allow traversal. |
| `expected_version` concurrency with `409` on mismatch | Last-write-wins | Two operators or tabs must not silently clobber each other. |
| `hard_fixes` literal semantics, never regex | Regex-valued fixes | `correct()` escapes every key (`glossary.py:383`); regex would alter pipeline behavior. |

## Constraints

- Performance: list/detail serve from local JSON reads only, never a media-tree walk (route style at `review_server.py:960`).
- Media safety: writes stay inside `GLOSSARY_DIR`, are atomic via rename, and never touch episode output or stamps.
- Frontend: Svelte 5 `$state` runes matching `web/src/App.svelte:32`; destructive action needs explicit confirm.

## Open questions (risks)

- [x] Decided (user, 2026-10-12): newest 20 backups only, no age rule.
- [x] Decided (user, 2026-10-12): the editor never creates a glossary; a missing file is 404.
- [x] Decided (boss, default): the UI shows a plain "glossary busy, try again" message; no auto-retry.
- [x] Decided (user, 2026-10-12): after a save the UI offers a "reapply to this show" button that queues a run request (webui-run-control, admin token). v1 of the editor ships without the button if run-control is not merged; the save response carries `reapply_hint: true` so the UI can show the note "applies to episodes processed from now on" until then.
- [x] Decided (boss, from data): limits stay 80/120; the longest entry in the shipped glossaries is 26 characters and every shipped phrase contains a space.
- [x] Decided (boss, default): audit "who" is the literal "token" when auth is on and "anonymous" when REVIEW_AUTH=off; the server holds no user names.
