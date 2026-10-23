# chore(backlog): close runtime-toggles, add runtime-kill-switches (PR #37)

Status: open (reviewer PASS at 9079a1f; critic next, 2026-10-23)
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

9079a1f: reviewer @ agy Gemini 3.8 Flash high: PASS

Reviewed checkout /home/xena/work/code/scratch-dt-backlog at REVIEW_SHA 9079a1f1490a8e0d3b593290ce3436d18223836b (branch chore/close-runtime-toggles, base origin/main b20c65e).

Summary: All Acceptance criteria are satisfied. The `runtime-toggles` epic is closed as `done 2026-10-23` with verified outcome claims for T-1, T-2, and T-3. The dropped T-3 is accurately recorded as unscheduled on the roadmap in `runtime-kill-switches.md`. No code, docs, secrets, or credentials are added.

Verification:
- File set: `git diff --stat origin/main 9079a1f` lists only `.procoder/backlog/epics/runtime-kill-switches.md` (+10), `.procoder/backlog/epics/runtime-toggles.md` (+8/-1), and `.procoder/todo/20261023-close-runtime-toggles.md` (+40). Untracked symlinks (`.venv`, `web/node_modules`) are excluded from git.
- T-1 Outcome claim: Verified `ACQUIRE_APPLY` is defined in `settings_registry.py:91` via `_wave(...)` with `first_wave=True` / `editable: True`, and `PUT /api/settings` requires role `"admin"` in `review_auth.py:623` and `settings_api.py:26`.
- T-2 Outcome claim: Verified PR #33 (`707ed9a`) added `TAKES_EFFECT` mapping and `takesEffect: takesEffectText(entry)` in `web/src/lib/settingsModel.js:211-251` (tested in `web/tests/settingsRows.test.mjs`).
- T-3 Outcome claim: Verified neither `gen_loop.sh` nor `merge_pass.sh` has runtime on/off kill switches for verify, repair, or unanchored repair analogous to `ACQUIRE_APPLY`.
- Roadmap note: `.procoder/backlog/epics/runtime-kill-switches.md` accurately describes the dropped scope and explicitly states `Status: roadmap, not started` with no schedule commitment.
- Status and gate: Status lines confirm `runtime-toggles` is `done 2026-10-23` and `runtime-kill-switches` is `roadmap, not started`. `procoder check` on both epic files via `review-run` reports `2 clean, 0 unformatted, 0 unchecked, 0 out of scope, 2 hygiene finding(s) (0 blocking)`.
- Public repo check: Manual read of both files confirms no secrets, credentials, or personal data.
- Commits: Commit messages on the branch follow convention (`chore(backlog): ...` / `20261023-close-runtime-toggles: ...`) with no AI or Co-Authored-By trailers.

Findings: none.

## Evidence

## Result

Boss: 0df5c24 written by the boss. `procoder backlog close epic runtime-toggles` printed "epic runtime-toggles closed — every story done". `procoder check` on both epic files: 2 clean, 0 blocking. PR: https://github.com/XenaRathon/DubTitlerr/pull/37
