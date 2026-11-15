# chore: replace LongCat-2.0 references with LongCat-2.5 (2.0 is deprecated)

Status: open
Created: 2026-11-15
Type: code
Assigned: coder@cmd (code-coder, DeepSeek V4.1 Flash)
Reason: user 2026-11-15: LongCat 2.0 is deprecated; LongCat-2.5 is live-verified on https://api.longcat.chat/openai/v1 (model id `LongCat-2.5`). Homelab is switching the deployed dubtitle-builder on vm102 (VERIFY_MODEL/REPAIR_MODEL) in its own task 20261115-longcat-25-migration; this task is the repo side.
Owns: compose.yaml (the LongCat comment only), tools/glossary_bakeoff.py, tests/test_glossary_bakeoff.py, tests/test_glossary_judge.py, any other file in this repo that names LongCat-2.0 (list them in Result), .procoder/todo/20261115-longcat-25-refs.md (Result only)
Checkout: /home/xena/work/code/DubTitlerr-longcat25, branch `chore/longcat-25-refs` (already checked out), from origin/main

## Description

Known references: `compose.yaml:125` (comment `# REPAIR_MODEL: LongCat-2.0`), `tools/glossary_bakeoff.py:450` (a bake-off candidate `"longcat-2.0", "text", "LongCat-2.0", _LONGCAT`), `tests/test_glossary_bakeoff.py:304-308, 367` and `tests/test_glossary_judge.py`. First `grep -rn -i 'longcat-2.0\|LongCat-2\.0'` the whole repo. Then: in code and tests, drop the 2.0 candidate and keep (or add) `longcat-2.5` with model id `LongCat-2.5` on the same endpoint and key env `LONGCATAI_API_KEY` (by name only; never read or print the key); update the tests to the new candidate set; in comments and docs, change the model to LongCat-2.5. Do not change other providers or the bake-off logic. If a test pinned the exact candidate list, update it to the new list and say so. Check the repo's docs (README, AGENTS.md, docs/) for LongCat-2.0 too.

### House rules
- Do not run git rebase, merge or fetch (cmd shell policy). Commit only in the worktree; no push. Commits `20261115-longcat-25-refs: chore: <what>`, no AI trailers.
- Write only under the Result heading; keep exactly one empty Evidence heading, last in the file, and that heading's text nowhere else (not even quoted).
- Gate: the repo's test suite (see AGENTS.md; `.venv` if present) and `procoder check <changed files>` 0 blocking.

## Acceptance criteria

- [ ] No `LongCat-2.0` / `longcat-2.0` reference remains in code, tests, config or docs (grep output in Result).
- [ ] The bake-off and judge tests pass with the LongCat-2.5 candidate; gate clean.

## Result

Commits `1018e35` (the change), `0d4ed2a` and `a496ee3` (this Result) on `chore/longcat-25-refs` (no push).

**What changed**

- `tools/glossary_bakeoff.py` — dropped the `longcat-2.0` arm; the surviving `longcat-2.5` arm keeps the same endpoint (`_LONGCAT_URL`), key variable `LONGCATAI_API_KEY` and `{"thinking":{"type":"disabled"}}` extra body, and now pins the model id `LongCat-2.5` instead of `LongCat-2.5-Preview`. No other arm and no bake-off logic touched.
- `tests/test_glossary_bakeoff.py` — the pinned candidate-list test now expects the 9-arm set without `longcat-2.0` (that test named the exact list, so it was updated to the new list); the endpoint/model/pacing test asserts the single LongCat arm at `LongCat-2.5`; the ten arm-selection occurrences of the old name (the `gb.ARMS` lookup, seven `_run` call sites, the request estimate, the `@v2` rejection case) now use `longcat-2.5`.
- `tests/test_glossary_judge.py` — the three-arm label tuple and the 17 occurrences that used it renamed from `longcat-2.0` to `longcat-2.5`. These are blind-judging labels only; no assertion about a model identity changed.
- `compose.yaml` — the commented repair example now reads `# REPAIR_MODEL: LongCat-2.5`.
- `.procoder/todo/20261115-longcat-25-refs.md` — this Result.

**Files that named LongCat-2.0** (the full list, as Owns requires): exactly the three above plus this task file. Nothing else in the repo named version 2.0.

**Verification**

- Criterion 1 — `grep -rn -i 'longcat-2\.0\|longcat 2\.0'` over the repo returns only this task file (`:1`, `:7`, `:8`, `:13`, `:22` — its own title, Reason, Owns, Description and acceptance text). No code, test, config or doc match remains. `grep -rn '2\.5-Preview'` returns nothing.
- Criterion 1 (docs) — `README.md`, `AGENTS.md` and `docs/` were checked: `docs/wiki/How-To-Guides.md:316` names "LongCat's API" with no version or model id (it documents the `thinking` switch, not a model), and `settings_registry.py:258` names only the key `LONGCATAI_API_KEY`. Neither states version 2.0, so neither needed a change.
- Criterion 2 — `.venv/bin/python -m pytest tests/test_glossary_bakeoff.py tests/test_glossary_judge.py` → `156 passed in 6.88s`.
- Lint — `procoder lint compose.yaml tools/glossary_bakeoff.py tests/test_glossary_bakeoff.py tests/test_glossary_judge.py` → `0 finding(s) (0 blocking)`.
- Full suite — `.venv/bin/python -m pytest` → `38 failed, 4838 passed`. All 38 sit in four files my diff does not touch (`tests/test_merge_pass.py` 23, `tests/test_merge_pass_runtime_env.py` 13, `tests/test_mux.py` 1, `tests/test_render_readme_table.py` 1) and every one fails on `ModuleNotFoundError: No module named 'pysubs2'` / `FATAL: pysubs2 not found — image is misbuilt` from a bare `python3` subprocess that resolves to system 3.14; the affected suites pass under the venv.
- Gate — `procoder check` on the four changed files (commit `0d4ed2a`, clean tree): `4 clean, 0 unformatted, 0 unchecked, 0 out of scope, 151 hygiene finding(s) (2 blocking)`. Both blockers are escalated below, not code faults. Adding this task file to the same invocation reports it `unformatted`: `procoder format` wants one blank line after `### House rules`, which is in the dispatched text above this heading — I left it alone per the "write only under Result" rule.

**Escalations**

1. **Gate's Python test step cannot run in this shell.** It resolves `pytest` from `PATH` to `/usr/bin/pytest` (CPython 3.14, no `pysubs2`), which fails at collection with `0 passed, 0 failed`. It fails identically on files I never touched (verified on `common.py`), so it is the environment, not this diff. The documented remedy is the repo venv first on `PATH` (`PATH=<worktree>/.venv/bin:$PATH`), which this session's shell permissions reject. Running the same suite myself with `.venv/bin/python -m pytest` gives the counts above.
2. **Documentation obligation still reported.** `compose.yaml` counts as a configuration file, so the gate wants a doc update or a `docs: none — <reason>` line. I put that line in the commit body (readable in `COMMIT_EDITMSG`), which is the documented clearing mechanism, but `procoder check` invoked directly cannot read a commit message and the repo has no procoder git hook installed (`core.hooksPath` unset, only `*.sample` hooks), so nothing routes the message to the check. Adding a doc would have to land outside `Owns`: a `CHANGELOG.md` entry under `## [Unreleased]` does clear the finding (verified), but the bake-off arm list is operator tooling with no user-facing doc, so I reverted it rather than widen scope. The lead should close this by commit-wrapper invocation or by granting `CHANGELOG.md`.

## Evidence
