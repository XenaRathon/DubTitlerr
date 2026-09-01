# glossary_verify.resolve_redirects both-direction redirect resolution

Status: open
Created: 2026-09-01

## Description

Task 3 of `.procoder/plans/per-episode-glossary-acquisition.md`
(implements spec `[S-3]`). The todo's original measurement showed a naive
intersection silently drops the main cast unless redirects are resolved
on both sides — `Kirito` (the prose form) vs `Kirigaya Kazuto` (the
canonical wiki title). This task adds
`glossary_verify.resolve_redirects(wiki_api, titles) -> set[str]`, one
chunked (`<=50` titles/call) `redirects=1&prop=redirects` MediaWiki call
resolving both directions per chunk, failing open to the unresolved input
set on any error. Per Luna's adversarial review (F5,
`docs/Adversarial Reviews/LUNA-2026-09-01-per-episode-glossary-acquisition.md`),
a hand-built mock alone is not sufficient evidence this parses the REAL
API response shape — a captured or documented live response is required
before this task is done, not just green mocked tests.

## Acceptance criteria

- [ ] `glossary_verify.resolve_redirects()` exists, matching the plan's
      Task 3 signature and chunking behavior.
- [ ] `pytest tests/test_glossary_verify.py -k resolve_redirects -q`
      passes all 4 tests (input-is-redirect, incoming-redirect,
      fail-open, chunking over 50 titles).
- [ ] `Kirito`/`Kirigaya Kazuto` resolve to each other in the test suite
      regardless of which direction the fixture links, pinning the
      todo's explicit regression case.
- [ ] A live smoke check (or a captured real MediaWiki response saved as
      a fixture/comment) against a real Fandom wiki has been run at least
      once, confirming the assumed response shape — recorded in Evidence
      below at close time, per Luna review F5.
- [ ] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the task open. -->
