# glossary_verify.resolve_redirects both-direction redirect resolution

Status: closed 2026-09-01
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

- [x] `glossary_verify.resolve_redirects()` exists, matching the plan's
      Task 3 signature and chunking behavior.
- [x] `pytest tests/test_glossary_verify.py -k resolve_redirects -q`
      passes all 4 tests (input-is-redirect, incoming-redirect,
      fail-open, chunking over 50 titles).
- [x] `Kirito`/`Kirigaya Kazuto` resolve to each other in the test suite
      regardless of which direction the fixture links, pinning the
      todo's explicit regression case.
- [x] A live smoke check (or a captured real MediaWiki response saved as
      a fixture/comment) against a real Fandom wiki has been run at least
      once, confirming the assumed response shape — recorded in Evidence
      below at close time, per Luna review F5.
- [x] `ruff check glossary_verify.py tests/test_glossary_verify.py`
      reports 0 findings.

## Evidence

- RED: `rtk proxy python3 -m pytest tests/test_glossary_verify.py -k resolve_redirects -q`
  — 4 failed, `AttributeError: module 'glossary_verify' has no attribute
'resolve_redirects'`.
- GREEN: implemented per the plan. `rtk proxy python3 -m pytest tests/test_glossary_verify.py -q`
  → 37 passed.
- **Live verification (Luna F5)**: ran a real `curl` GET against
  `https://swordartonline.fandom.com/api.php?action=query&redirects=1&prop=redirects&rdlimit=500&format=json&titles=Kirito`
  and the reverse-direction query for `Kirigaya Kazuto` — both returned
  the identical response shape my implementation assumes:
  `query.redirects: [{"from": "Kirito", "to": "Kirigaya Kazuto"}]` and
  `query.pages["2090"].redirects` listing 8 incoming redirects including
  `Kirito`. Captured to
  `tests/fixtures/mediawiki_redirects_sample.json` and pinned by a new
  regression test,
  `test_resolve_redirects_parses_a_real_captured_mediawiki_response`, not
  left as a one-off manual check.
- Full suite: `rtk proxy python3 -m pytest -q` → 100%, no failures.
- Lint: `rtk proxy ruff check glossary_verify.py tests/test_glossary_verify.py`
  → "All checks passed!"
- Mutation check (mental): ignoring `query.redirects` breaks the
  input-is-redirect test; ignoring a page's own `redirects` list breaks
  the incoming-redirect test; not chunking breaks the 120-title test;
  raising instead of failing open breaks the network-down test.
- Committed: `f3e93d1 feat(glossary_verify): resolve wiki redirects both
directions in one call`.
