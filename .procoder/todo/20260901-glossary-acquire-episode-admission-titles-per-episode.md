# glossary_acquire.episode_admission_titles per-episode admission resolution

Status: open
Created: 2026-09-01

## Description

Task 9 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-7]`, and the per-episode half of `[S-13]`). New
`episode_admission_titles(video, gloss, wiki_api, show, source_episodes_fn=None)
-> (titles_or_None, method, detail)`. Tries
`episode_page_pattern_absolute` (via Task 1's `source_episodes` + Task
5's `episode_page_titles`) first, then `episode_page_pattern_relative`
(via the episode's own `SxxExx`) when absolute yields nothing; falls back
to franchise-wide `allpages` — reported via `method`, never silent — when
neither resolves, when there's no `SxxExx` at all, or when neither
pattern field is declared on the show (`"unscoped"`, today's behavior,
byte-for-byte unchanged). `detail` carries `nfo_present`/`nfo_parsed`/
`partial_pages` for Task 10's aggregation. Depends on Tasks 1, 5, and 8.

## Acceptance criteria

- [ ] `glossary_acquire.episode_admission_titles()` exists, matching the
      plan's Task 9 signature and the five `method` values
      (`absolute`/`relative`/`fallback-allpages`/`unscoped`/
      `no-episode-tag`).
- [ ] `pytest tests/test_glossary_acquire.py -k admission_titles -q`
      passes all 4 tests: unscoped with no pattern declared; absolute
      wins when it resolves; fallback with accurate `nfo_present` when
      no `.nfo` exists; partial mapping keeps the resolved pages' union
      and reports `partial_pages`.
- [ ] `ruff check glossary_acquire.py tests/test_glossary_acquire.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
