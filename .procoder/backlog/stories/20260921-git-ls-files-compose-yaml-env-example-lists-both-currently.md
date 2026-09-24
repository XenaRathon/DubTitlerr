# `git ls-files compose.yaml .env.example` lists both (currently untracked).

Status: done 2026-09-21
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 010-ground-truth-ci-green-compose-committed-with-a-safe-auth

## Description

Scope S-2 of `.procoder/specs/v0-2-0-hardening.md`: Commit `compose.yaml` and `.env.example`, and stop the Compose install path from disabling auth by default: `auth_required()` (`review_server.py:138-140`) must treat an EMPTY `REVIEW_TOKEN` as unset (a token is generated), not as "disabled" — disabling requires the explicit `REVIEW_AUTH=off`.

Delivered by Task 2 of `.procoder/plans/v0-2-0-hardening.md` (sprint 010); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `git ls-files compose.yaml .env.example` lists both (currently untracked).

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

- `git ls-files compose.yaml .env.example` lists both after commit `496944b`
  "chore(deploy): commit the Compose example files"; confirmed tracked with
  `git status --porcelain` returning empty for both paths.
