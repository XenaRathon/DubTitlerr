# `git status --porcelain` shows no untracked entry for `.craftsman-baseline.json` or `.lycheecache`; `docs/agents/`, `docs/beta-feedback/`, `docs/promo/`, `.procoder/github/LESSONS.md`, and `ISSUE-s32e02-timing.md` are tracked; `git stash list` is empty.

Status: done 2026-09-21
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 010-ground-truth-ci-green-compose-committed-with-a-safe-auth

## Description

Scope S-3 of `.procoder/specs/v0-2-0-hardening.md`: Classify every untracked/modified path from `git status`: `.craftsman-baseline.json` and `.lycheecache` are gitignored (the baseline's own entries reference only ignored worktree/venv paths, so ignoring it drops nothing meaningful); `docs/agents/`, `docs/beta-feedback/`, `docs/promo/`, and the modified `.procoder/github/LESSONS.md` are committed; `stash@{0}` ("luna pre-fix export_reviewed") is dropped — its content already shipped as `1da6879` (`tools/export_reviewed.py` + `tests/test_export_reviewed.py` exist on `main`); `ISSUE-s32e02-timing.md` is committed next to the other `ISSUE-*.md` files (owner decision — recommended default, confirm at sprint 010 open).

Delivered by Task 3 of `.procoder/plans/v0-2-0-hardening.md` (sprint 010); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `git status --porcelain` shows no untracked entry for `.craftsman-baseline.json` or `.lycheecache`; `docs/agents/`, `docs/beta-feedback/`, `docs/promo/`, `.procoder/github/LESSONS.md`, and `ISSUE-s32e02-timing.md` are tracked; `git stash list` is empty.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

- `.gitignore` updated + commit `50bde8e`; `docs/agents/`, `docs/beta-feedback/`,
  `docs/promo/`, `ISSUE-s32e02-timing.md`, `.procoder/github/LESSONS.md` committed in
  `41e39d4`; `git stash show --stat stash@{0}` confirmed both files already tracked and
  superseded by commit `1da6879`, then `git stash drop stash@{0}` succeeded. Final
  `git status --porcelain --branch` returned only the branch line (clean tree).
