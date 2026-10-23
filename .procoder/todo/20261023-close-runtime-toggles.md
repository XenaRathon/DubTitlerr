# chore(backlog): close runtime-toggles, add runtime-kill-switches (PR #37)

Status: open (F1+F2 fixed at 076409e; re-review, 2026-10-23)
Created: 2026-10-23
Type: code
Assigned: code-coder (fix round; first version by lead)
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

## Fix brief (code-coder)

Fix the critic's F1 and F2 under `## Review` (9079a1f critic REJECT). The boss has verified F1. Planning text only.

- **Checkout:** `/home/xena/work/code/scratch-dt-backlog`, branch `chore/close-runtime-toggles`. Commit there with the message `20261023-close-runtime-toggles: <what changed>` and no AI or Co-Authored-By trailers. Don't push; the boss pushes.
- **F1, `.procoder/backlog/epics/runtime-kill-switches.md`:** scope the epic to whole-stage verify and repair on/off switches. Add one line saying unanchored repair already has a runtime switch: `REPAIR_UNANCHORED` (`settings_registry.py:98`), admin-editable, which takes effect at the next merge pass.
- **F1, `.procoder/backlog/epics/runtime-toggles.md` (Outcome, T-3 line):** say that the verify and repair switches were dropped and that unanchored repair already had `REPAIR_UNANCHORED`. Leave the original Scope and Why text unchanged.
- **F2:** in `runtime-kill-switches.md`, replace "the loop reads at each sweep" with wording that matches the registry. `ACQUIRE_APPLY` applies `next_show` and the repair-side keys apply `next_merge_pass`.
- **Gate:** run `procoder check` on both epic files (0 BLOCKING), and run `procoder format` on each so it is formatted. Then check that `git diff --stat origin/main HEAD` still lists only the two epic files and this task file. Write the outcome under `## Result`.

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

9079a1f: critic @ claude-opus-5-5: REJECT

SHA: `git-ro ... rev-parse HEAD` = 5aa8e80, not the REVIEW_SHA. That is expected under the brief: `git diff --stat 9079a1f HEAD` shows only this task file. I reviewed 9079a1f, the head the reviewer also checked.

### Independent checks

- **File set:** `git diff --stat origin/main...9079a1f` lists `runtime-kill-switches.md` (+10), `runtime-toggles.md` (+8/-1) and this task file (+40). Nothing else.
- **T-1: holds.** `settings_registry.py:91` at both 9079a1f and the `v0.3.0` ref is `_wave('ACQUIRE_APPLY', ..., 'bool', True, 'gen', 'next_show')`. `_wave` sets `first_wave=True`, and `editable` comes from `first_wave` (`settings_registry.py:64-65`). `PUT /api/settings` is `"admin"` in `settings_api.py:26`.
- **T-2: holds.** 707ed9a is "Merge pull request #33 from XenaRathon/feat/settings-takes-effect". It adds 25 lines to `web/src/lib/settingsModel.js`, and `git grep -c takesEffect 707ed9a -- web/src/lib/settingsModel.js` gives 2.
- **T-3: half true** (see F1).
  - There's no whole-stage verify or repair on/off switch. `gen_loop.sh:154-170` runs `glossary_verify.py` for every show with no enable gate, and `merge_pass.sh:109` runs `repair.py` with none either. No `VERIFY`/`REPAIR` registry key is an enable flag; the `VERIFY_*`/`REPAIR_*` bools tune behaviour inside the stage.
  - But the unanchored-repair switch already exists.
- **Gate:** `review-run procoder check` on both epic files: `2 clean, 0 unformatted, 0 unchecked, 0 out of scope, 2 hygiene finding(s) (0 blocking)`.
- **`procoder backlog list`: unverified by me.** `review-run` refuses it ("not a check or test command"). The Status lines read `done 2026-10-23` and `roadmap, not started`.
- **Public content:** I read both files in full. They contain no secret value, credential or personal data, and no IPs, emails or paths.

### Reviewer's 9079a1f PASS

- **File set, T-1, T-2, gate, public read: CONFIRMED** by my runs above.
- **T-3: REFUTED.** The reviewer checked only `gen_loop.sh` and `merge_pass.sh` for switches "analogous to `ACQUIRE_APPLY`". The registry already has one, so the T-3 criterion ("No verify, repair or unanchored-repair runtime switch exists") fails for unanchored repair.

### Findings

- **F1, should-fix, blocking: the T-3 claim is false for unanchored repair.**
  - **Where:** `.procoder/backlog/epics/runtime-kill-switches.md:8` ("Runtime on/off switches for verify, repair and unanchored repair") and `.procoder/backlog/epics/runtime-toggles.md:25`.
  - **Evidence:** `settings_registry.py:98` at 9079a1f is `_wave('REPAIR_UNANCHORED', 'repair', 'Unanchored repair', 'Let repair fix lines that no glossary entry anchors; ...', 'bool', False, 'merge', 'next_merge_pass')`. So it is an editable (`first_wave`), admin-only (`settings_api.py:26`) runtime setting that the merge pass picks up at the next pass. `repair.py:563` reads it, and `repair.py:418` uses it. It has been in the registry since e763c8b (2026-10-14, "registry of first-wave settings"), and `common.py:204` records it as enabled library-wide since v10. With #33 it also shows "Takes effect at the next merge pass".
  - **Failure:** the new roadmap epic says an unanchored-repair switch still needs building, and the T-3 Outcome implies it too. Whoever picks up `runtime-kill-switches` would design a second switch for a key that already has one: two settings for the same behaviour, or a rename of a live key. The epic's open question ("which switches to add") also starts from a wrong inventory.
  - **Fix (planning text only):**
    - In `runtime-kill-switches.md`, scope the epic to whole-stage verify and repair switches. Add one line saying unanchored repair already has a runtime switch (`REPAIR_UNANCHORED`, admin-editable, next merge pass).
    - In the T-3 Outcome of `runtime-toggles.md`, either say the same, or leave it and let the roadmap epic carry the correction.
- **F2, nit: "reads at each sweep."** `runtime-kill-switches.md:8` says the mechanism is "an admin-only runtime setting the loop reads at each sweep". `ACQUIRE_APPLY` is `next_show` (`settings_registry.py:91`), and repair-side keys are `next_merge_pass`, so a switch would apply per show or per merge pass, not per sweep. `runtime-toggles.md`'s original T-1 Scope line uses the same wording, but that is pre-existing text. Fix only if F1 reopens the file anyway.

### Attempts to break it

1. **An existing switch contradicting T-3:** found one, F1.
2. **T-1 attributed to the wrong release:** checked the `v0.3.0` ref. `ACQUIRE_APPLY` is `_wave` there. Holds.
3. **T-2 attributed to the wrong PR:** 707ed9a is the #33 merge, and it carries `takesEffect`. Holds.
4. **Schedule promise or private data in the new epic:** none. It says "not scheduled".

## Evidence

## Result

Boss: 0df5c24 written by the boss. `procoder backlog close epic runtime-toggles` printed "epic runtime-toggles closed — every story done". `procoder check` on both epic files: 2 clean, 0 blocking. PR: https://github.com/XenaRathon/DubTitlerr/pull/37

Code-coder, 2026-10-23: F1 and F2 fixed in 076409e on `chore/close-runtime-toggles` (not pushed). Planning text only.
- `runtime-kill-switches.md`: scoped to whole-stage verify and repair on/off switches. Added a line that unanchored repair already has `REPAIR_UNANCHORED` (`settings_registry.py:98`, admin-editable, next merge pass) and is out of scope. F2: "the loop reads at each sweep" replaced with wording matching the registry (`ACQUIRE_APPLY` is `next_show`, repair-side keys are `next_merge_pass`, so a switch applies per show or per merge pass).
- `runtime-toggles.md`: only the T-3 Outcome line changed; it says the verify and repair switches were not built and that unanchored repair already had `REPAIR_UNANCHORED`. Original Scope and Why text untouched (`git diff` shows 1 line changed in that file's Outcome).

Evidence (verified):
- `settings_registry.py:98` read in this checkout: `_wave('REPAIR_UNANCHORED', 'repair', ..., 'bool', False, 'merge', 'next_merge_pass')`; `settings_registry.py:97` `DECISIONS_APPLY` and `:99` `RESTORE_PUNCTUATION` are the same `merge`/`next_merge_pass` kind.
- `procoder format` on each epic file: "already formatted". `procoder check` on both: `2 clean, 0 unformatted, 0 unchecked, 0 out of scope, 2 hygiene finding(s) (0 blocking)`.
- `procoder backlog list`: `[done 2026-10-23] epic runtime-toggles` and `[roadmap, not started] epic runtime-kill-switches`.
- `git diff --stat origin/main HEAD`: the two epic files and this task file only.
- Public content: the new text names only `REPAIR_UNANCHORED`, a registry path and release terms; no secret, credential or personal data.

Escalations: none.
