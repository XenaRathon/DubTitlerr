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

## Evidence
