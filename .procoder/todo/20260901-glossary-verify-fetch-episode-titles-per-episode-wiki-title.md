# glossary_verify.fetch_episode_titles per-episode wiki title cache

Status: open
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

- [ ] `glossary_verify.fetch_episode_titles()` exists, matching the
      plan's Task 4 signature and cache file shape
      (`<CACHE_DIR>/<show_key>_episodes.json`).
- [ ] `pytest tests/test_glossary_verify.py -k fetch_episode_titles -q`
      passes all 3 tests: a second call within `WIKI_TTL` makes no HTTP
      request; a negative result is not cached (retried); a call past
      `WIKI_TTL` re-fetches.
- [ ] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
