# chore(backlog): close runtime-toggles, add runtime-kill-switches (PR #37)

Status: open (in review: reviewer, then critic, 2026-10-23)
Created: 2026-10-23
Type: code
Assigned: lead
Reason: the boss wrote these two planning files directly when the user asked to close the epic; the user then asked for the normal review route before any merge.
Owns: .procoder/backlog/epics/runtime-toggles.md, .procoder/backlog/epics/runtime-kill-switches.md, .procoder/todo/20261023-close-runtime-toggles.md (Review only)

## Description

The user asked to close the `runtime-toggles` epic and record the dropped part in a backlog note. Commit 0df5c24 on PR #37 (branch `chore/close-runtime-toggles`, base `main` b20c65e) does three things:

1. Runs `procoder backlog close epic runtime-toggles`, so its Status reads `done 2026-10-23`.
2. Adds an Outcome section to that epic:
   - T-1 was done in v0.3.0 (`ACQUIRE_APPLY` is an editable, admin-only runtime setting).
   - T-2 was done in #33 (707ed9a): the takes-effect note on settings rows.
   - T-3 was dropped by the user's 2026-10-22 scope decision ("(a) only").
3. Adds `.procoder/backlog/epics/runtime-kill-switches.md`, a roadmap epic (not started) for the dropped T-3.

These are planning files only, with no code or docs change. The repo is public, so everything in them must be publishable.

## Acceptance criteria

- [ ] `git diff --stat origin/main <REVIEW_SHA>` lists only the two epic files and this task file.
- [ ] Every Outcome claim in `runtime-toggles.md` holds against the repo:
  - T-1: `ACQUIRE_APPLY` is editable and admin-only in the settings registry and schema on `main`.
  - T-2: #33 / 707ed9a added `takesEffect` in `web/src/lib/settingsModel.js`.
  - T-3: T-3 is really not built. No verify, repair or unanchored-repair runtime switch exists.
- [ ] `runtime-kill-switches.md` describes T-3 accurately and doesn't promise a schedule.
- [ ] `procoder check` on the two epic files reports 0 BLOCKING, and `procoder backlog list` shows `runtime-toggles` done and `runtime-kill-switches` on the roadmap.
- [ ] Neither file contains a secret value, credential or personal data.

## Review

## Evidence

## Result

Boss: 0df5c24 written by the boss. `procoder backlog close epic runtime-toggles` printed "epic runtime-toggles closed — every story done". `procoder check` on both epic files: 2 clean, 0 blocking. PR: https://github.com/XenaRathon/DubTitlerr/pull/37
