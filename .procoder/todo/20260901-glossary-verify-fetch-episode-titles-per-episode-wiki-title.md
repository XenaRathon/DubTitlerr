# glossary_verify.fetch_episode_titles per-episode wiki title cache

Status: closed 2026-09-01
Created: 2026-09-01

## Description

Task 4 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-4]`). Composes Task 2's `plot_section_links` and
Task 3's `resolve_redirects` behind a cache: one JSON file per SHOW (not
per page) under `WIKI_CACHE_DIR`, each page entry independently
`WIKI_TTL`-gated, following `fetch_titles`'s existing TTL-file pattern —
not `acquire_cache.py`'s token-verdict cache, which has a different key
shape and invalidation semantics. Only positive results are cached
(mirrors `fetch_titles`'s own asymmetry), so a genuinely missing page is
retried every call rather than cached empty forever. Depends on Tasks 2
and 3 being merged first.

## Acceptance criteria

- [x] `glossary_verify.fetch_episode_titles()` exists, matching the
      plan's Task 4 signature and cache file shape
      (`<CACHE_DIR>/<show_key>_episodes.json`).
- [x] `pytest tests/test_glossary_verify.py -k fetch_episode_titles -q`
      passes all 3 tests: a second call within `WIKI_TTL` makes no HTTP
      request; a negative result is not cached (retried); a call past
      `WIKI_TTL` re-fetches.
- [x] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_glossary_verify.py -k fetch_episode_titles -q`
  — 3 failed, `AttributeError: module 'glossary_verify' has no attribute
'fetch_episode_titles'`.
- GREEN, with a real correction mid-cycle: `fetch_episode_titles`
  composes `plot_section_links` + `resolve_redirects` (S-2 + S-3) per
  the plan, which means a genuine (non-cached) fetch makes 2 `_http_json`
  calls, not 1 — the wikitext fetch and `resolve_redirects`' own call.
  My first-draft test assertions assumed 1 call and were wrong; fixed to
  assert 2 calls for one genuine fetch and 0 additional on a cache hit
  (not "1 total"), and 4 calls across two genuine fetches in the
  TTL-expiry test. `rtk proxy python3 -m pytest tests/test_glossary_verify.py -q`
  → 40 passed.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary_verify.py tests/test_glossary_verify.py`
  → "All checks passed!"
- Mutation check (mental): caching a negative result is caught by the
  retried-not-cached test; skipping the TTL check on a hit is caught by
  the TTL-expiry test asserting a re-fetch happens; dropping the
  `resolve_redirects` composition would silently under-count real calls,
  which is exactly what the corrected call-count assertions now pin.
- Committed: `c65cd10 feat(glossary_verify): cache per-episode wiki title
fetches`.
