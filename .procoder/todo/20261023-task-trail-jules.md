# docs: land the task-file trail for the Jules jobs (#32, #35)

Status: open (dispatched to code-coder, 2026-10-23)
Created: 2026-10-23
Type: code
Assigned: code-coder
Reason: a docs-only trail change that runs through the normal route; the user approved one small PR.
Owns: .procoder/todo/20261022-gate-debt-cleanup.md, .procoder/todo/20261023-pre-1-0-cleanup-redo.md, .procoder/todo/20261023-task-trail-jules.md (Result only)

## Description

Two Jules jobs ran with their procoder task files on local branches. Jules opened the PRs from its own branches, so those files never reached `main`: PR #32 (task `20261022-gate-debt-cleanup`, merged 57a6463) and PR #35 (task `20261023-pre-1-0-cleanup-redo`, merged 9ef25e2). Both tasks are closed. Bring both closed files onto `main` in one small PR.

- **Checkout:** `/home/xena/work/code/scratch-dt-trail`, on branch `chore/task-trail-jules` from `origin/main` 9ef25e2. `.venv` and `web/node_modules` are symlinked there; keep them out of commits.
- **Sources:** these local branches in the same repository:
  - `task/jules-debt-cleanup` carries `.procoder/todo/20261022-gate-debt-cleanup.md`.
  - `task/jules-pre-1.0-redo` carries `.procoder/todo/20261023-pre-1-0-cleanup-redo.md`.
  - Each branch adds only that one file compared with its merge base on `main`. Take each file exactly as its branch has it, for example with `git checkout <branch> -- <path>`. Don't edit its content.
- **Public repo check:** the repo is public and `.procoder/` is published. Read both files. If either contains anything that shouldn't be public (a secret value, a credential, personal data), stop and escalate it in Result instead of committing. Local absolute paths, seat names and the Jules session URL are fine.
- **Commits:** message `20261023-task-trail-jules: <what changed>`, with no AI or Co-Authored-By trailers (the repo gate blocks them). Don't push; the boss pushes and opens the PR.
- **Untouched:** every other path.

## Acceptance criteria

- [ ] `git diff --stat origin/main HEAD` lists only the two task files, plus this task file.
- [ ] Each file is byte-identical to its source branch: `git diff task/jules-debt-cleanup HEAD -- .procoder/todo/20261022-gate-debt-cleanup.md` and `git diff task/jules-pre-1.0-redo HEAD -- .procoder/todo/20261023-pre-1-0-cleanup-redo.md` are both empty.
- [ ] Both files read `Status: closed`.
- [ ] `procoder check` on the two files reports 0 BLOCKING.
- [ ] Neither file contains a secret value, credential or personal data (escalate if unsure).

## Review

## Evidence

## Result
