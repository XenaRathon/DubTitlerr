# chore(deps): bump filelock and setuptools in uv.lock to clear the osv-scan advisories

Status: open
Created: 2026-11-15
Type: code
Assigned: coder@cmd (code-coder, DeepSeek V4.1 Flash) — free coder seat; a lockfile-only bump
Reason: user 2026-11-15: CI's osv-scan job fails on uv.lock (filelock 3.32.4: 12 advisories incl. GHSA-v4x8-3wr5-3wq8 High, fixed in 4.2.1; setuptools 84.0.0: GHSA-xmj3-9gf7-h52w, fixed in 84.1.0). It blocks PR #60 (LongCat refs) and fails on main too. Bump first, then PR #60 is rebased and merged.
Owns: uv.lock, pyproject.toml (only if a constraint must move; say why), CHANGELOG.md (one line under Unreleased), .procoder/todo/20261115-osv-dep-bump.md (Result only)
Checkout: /home/xena/work/code/DubTitlerr-depbump, branch `chore/osv-dep-bump` (already checked out), from origin/main. `.venv` is a symlink to ../DubTitlerr/.venv: do NOT install into it or `uv sync` it (another worktree uses it).

## Description

filelock is pulled in by huggingface-hub, setuptools by ctranslate2 (both transitive; see `uv.lock`). Upgrade only those two packages in the lockfile: `uv lock --upgrade-package filelock --upgrade-package setuptools` (needs PyPI access; if the seat has no network, stop and escalate with the exact error). Target filelock >= 4.2.1 and setuptools >= 84.1.0; if a dependent's constraint caps filelock below 4.2.1, report the cap (package, constraint) instead of forcing it. No other package may change version: show `git diff --stat` and the list of version lines that changed in uv.lock.

Verify: filelock 4.x is a major bump. Search the repo's own code for direct `filelock` imports (`grep -rn 'filelock' --include='*.py' .`) and report them; if any, the suite must cover them. Run the full test suite in a throwaway venv built from the new lock (`uv venv /tmp/<scratch>/venv && uv sync --frozen --python /tmp/<scratch>/venv/bin/python` or `uv run --isolated`; never the shared `.venv`), and paste the counts. Run the osv check locally if osv-scanner is installed (`osv-scanner --lockfile=uv.lock`), otherwise say it was not run.

### House rules
- Do not run git rebase, merge or fetch. Commit only in the worktree; no push. Commits `20261115-osv-dep-bump: chore: <what>`, no AI trailers.
- Write only under the Result heading; keep exactly one empty Evidence heading, last in the file, and that heading's text nowhere else (not even quoted).
- Gate: the repo's test suite (see AGENTS.md) and `procoder check <changed files>` 0 blocking.

## Acceptance criteria

- [ ] uv.lock pins filelock >= 4.2.1 and setuptools >= 84.1.0; no other package version changed (diff in Result).
- [ ] Full test suite passes against an environment built from the new lock; gate clean.

## Result

## Evidence
