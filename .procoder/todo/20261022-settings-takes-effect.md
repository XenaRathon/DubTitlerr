# feat(web): settings rows say when a change takes effect

Status: open
Created: 2026-10-22
Type: code
Assigned: coder@claude-sonnet+opus-advisor
  Reason: first seat in the coder row, warm and idle on this repo (code-coder); quota.md shows no limit.
Owns: web/src/lib/settingsModel.js, web/src/pages/settings/SettingRow.svelte, web/tests/settingsRows.test.mjs
Epic: .procoder/backlog/epics/runtime-toggles.md (T-2 remainder; user decision 2026-10-22: build only this)

## Description

v0.3.0 already made `ACQUIRE_APPLY` an editable, admin-only setting (`settings_registry.py:91`; `PUT /api/settings` is admin-only in `settings_api.py:26`), and `gen_loop.sh` applies it before each show. One piece of the epic is still missing: the settings page says when a change takes effect only for restart settings (the "Restart required" badge, `web/src/pages/settings/SettingRow.svelte:40`, fed by `restart: entry.applies === 'restart'` in `describeRow`, `web/src/lib/settingsModel.js:222`). Every other row is silent. An admin who switches off "Apply acquired names" can't tell whether that stops the show being processed right now.

Work in `/home/xena/work/code/DubTitlerr` on the branch `feat/settings-takes-effect` (already created from `main` 94bae4d). Do not push.

1. In `describeRow`, add a field (e.g. `takesEffect`) with the user-facing text for the schema entry's `applies` value. The values are listed in `settings_registry.py:34`:
   - `next_show` → "Takes effect from the next show"
   - `next_episode` → "Takes effect from the next episode"
   - `next_merge_pass` → "Takes effect at the next merge pass"
   - `next_sweep` → "Takes effect at the next library sweep"
   - `restart` → no new text; keep the existing `restart` flag and badge exactly as they are.
   - Missing or unknown `applies` → empty text, plus one `console.warn` naming the key and the value (workspace rule: visible defaults). Don't throw.
2. In `SettingRow.svelte`, show the text as a muted note in the row (under the value or control, next to `setting-reason`), for editable and read-only rows alike. Leave secret handling, the badges and the controls untouched.
3. Extend `web/tests/settingsRows.test.mjs`: one case per `applies` value, the unknown/missing case (no throw, empty text, warns), and the restart row still has `restart: true` and no takes-effect text. Use an `ACQUIRE_APPLY`-shaped entry (`applies: 'next_show'`) for the next_show case.

House rules for this task: commit on `feat/settings-takes-effect` only, never push or switch branches. Commit messages carry no `Co-Authored-By` or other AI-attribution trailer, because the repo's procoder gate blocks them. Write only under `## Result`: leave the criteria boxes and `## Evidence` to the lead.

Out of scope: new settings or toggles (verify/repair kill switches were explicitly not chosen), Python and API changes, README/CHANGELOG (docs are frozen until the release pass), and every other file.

## Acceptance criteria

- [ ] `describeRow` returns the four strings above for `next_show`, `next_episode`, `next_merge_pass` and `next_sweep`. It returns empty text and warns once for an unknown or missing `applies`. A `restart` row keeps `restart: true` with empty takes-effect text. The new tests in `web/tests/settingsRows.test.mjs` cover all of this and fail on `main` (show the failing run).
- [ ] `SettingRow.svelte` renders the note for both editable and read-only rows. The existing badges are unchanged.
- [ ] In `web/`: `npx prettier --check src/lib/settingsModel.js src/pages/settings/SettingRow.svelte tests/settingsRows.test.mjs && npm run check && npm test && npm run build` all pass. The full `npm run format:check` (CI, `.github/workflows/ci.yml:70`) is already red on `main` because of `web/tests/browser/settings.spec.ts`, which PR #32 fixes. Leave that file alone.
- [ ] `procoder check` on the three changed files reports 0 BLOCKING, with one known exception: the eqeqeq at `settingsModel.js:130` (`isDirty`), which PR #32 fixes. Don't touch that line, so the two PRs don't conflict. procoder reports the .js/.svelte files as UNCHECKED, because its prettier can't load prettier-plugin-svelte from the repo root. That is a known tooling gap; the scoped prettier check above covers it.
- [ ] The Python suite still passes: `python -m pytest -q` with `/home/xena/work/code/DubTitlerr/.venv/bin` first on PATH.
- [ ] `git diff --stat main...HEAD` lists only the three Owns files plus this task file.

## Review

reviewer @ agy Gemini 3.8 Flash high: PASS

Branch head is commit af17a9f (adds coder Result in task file), parent 9f6608e; reviewed diff main...HEAD.

Findings: None. All acceptance criteria and five review axes (correctness, readability, architecture, security, performance) are satisfied. Verified that:
- `describeRow` correctly translates all schema `applies` values (`next_show`, `next_episode`, `next_merge_pass`, `next_sweep`) into user-facing text, leaves `restart` with empty text while preserving `restart: true`, and falls back to empty text while warning once via `console.warn` on unknown or missing `applies` values without throwing.
- `SettingRow.svelte` renders `.setting-effect` note for both editable and read-only rows.
- Web unit test suite passes (109 passed, 0 failed via `npm test` in `web/`, including 3 new tests in `web/tests/settingsRows.test.mjs` covering all `applies` variants).
- Python test suite passes (100% passed via `python3 -m pytest -q`).
- `procoder check` on changed files reports 0 blocking findings other than the two known inherited baseline `eqeqeq` findings on `settingsModel.js:130` deliberately deferred to PR #32.
- `git diff --stat main...HEAD` is strictly confined to the three `Owns:` files and the task file.

critic @ claude-opus-5-5: PASS (code commits e041411 and 9f6608e. Two minor findings, neither blocks.)

Head reviewed: c4edadb on `feat/settings-takes-effect`, the branch checked out in `~/work/code/DubTitlerr`. The reviewer checked af17a9f. That is fine: `git diff --stat af17a9f HEAD` shows only this task file (+12), and `git diff --stat 9f6608e HEAD -- web` is empty, so the reviewer saw the same code.

### Reviewer findings
The reviewer reported none. Their claims, checked one by one:
- **describeRow behaviour: CONFIRMED.** `web/src/lib/settingsModel.js:207-227` maps the four values. `restart` returns `''`. A missing or unknown value warns and returns `''`, and the `Object.hasOwn` guard means values like `toString` or `__proto__` can't pick up prototype text. The `restart` line itself is unchanged (`:245`).
- **Note shown on both row kinds: CONFIRMED.** `web/src/pages/settings/SettingRow.svelte:115` sits after the editable/read-only `{#if}` block closes, and the badges are untouched.
- **"109 passed": CONFIRMED.** My own `npm test` gave `tests 109 / pass 109 / fail 0 / skipped 0`. The coder's "108 pass / 1 skipped" was a skip that depends on the environment, not a gap.
- **Tests fail on main: CONFIRMED.** I ran the branch's test file against `main:web/src/lib/settingsModel.js` in a scratch copy: `tests 12 / pass 9 / fail 3`.
- **Gates: CONFIRMED.**
  - Scoped prettier: "All matched files use Prettier code style!".
  - `npm run check`: 0 errors, 0 warnings.
  - `npm run build`: built in 1.09s.
  - pytest: rc 0.
  - `procoder check` on the 3 files: 2 BLOCKING, both the known eqeqeq at `settingsModel.js:130`, nothing else.
  - Diff scope: the 3 `Owns:` files plus the task file.

### New findings
- **N1, minor, escalate (registry data is outside `Owns:`).** `SettingRow.svelte:115` together with `settings_registry.py:256-258`. Three bootstrap rows will show "Takes effect from the next show": `OPENROUTER_JEV_API_KEY`, `COMMANDCODE_API_KEY` and `LONGCATAI_API_KEY`, all `managed_by=bootstrap`, `applies=next_show`. They appear in the Bootstrap section (`web/src/pages/Settings.svelte:344-353`), whose heading says "These values are fixed by the container before it can read the settings store", and each row's own help text says the key is "read by name from the container environment". An admin reads "from the next show", but no change made on this page reaches those rows, and changing the container env needs a recreate. The PR does what the spec asked (show the note on every row), so this isn't a defect in the PR. The lead or user decides: correct `applies` for those three keys in the registry, or have `describeRow` skip the note for `managed_by === 'bootstrap'`. The other 32 bootstrap rows are `restart` and show nothing new.
- **N2, nit (repo rule).** `AGENTS.md` asks for Conventional Commits. e041411 and 9f6608e use the task-id prefix (`20261022-settings-takes-effect: ...`), not `feat(web): ...` / `test(web): ...`. If the merge is a squash, the PR title (`feat(web): settings rows say when a change takes effect`) fixes this. A merge commit would not.

### Attempts to break it
1. **Real data reaches the code.** `settings_registry.py:53` asserts every `applies` is in `APPLIES`, and `public()` (`:305`) keeps `applies` in `/api/settings` schema. So on today's registry the warn path never fires. Counts: next_show 77, next_merge_pass 45, next_sweep 11, restart 50, next_episode 0. `ACQUIRE_APPLY` is `next_show` with scope `gen`, which matches the Description.
2. **Repeated warnings.** `describeRow` runs inside `$derived` (`Settings.svelte:84-89`), so if the frontend and registry ever drift, the warning repeats every time the rows are recomputed, not once per session. Given point 1 this is acceptable, and the unit test asserts one warning per call, which matches the spec wording. Info only.
3. **Conflict with PR #32.** `git merge-tree --write-tree --name-only HEAD 60250be` → `fc50340...`, rc 0, no conflicted files. The two PRs touch separate parts of `settingsModel.js`.
4. **Prototype keys and missing values.** `Object.hasOwn(TAKES_EFFECT, entry.applies ?? '')` returns false for `undefined`, `'toString'` and `'__proto__'`, so all three take the warn path with empty text. The test covers `'someday'` and a missing value.
5. **Unverified:** how the note looks in a browser. No component or browser test covers it, as the coder's Result also says.

## Evidence

## Result

Outcome: done on `feat/settings-takes-effect` (not pushed). Commits e041411 (feature) and 9f6608e (drop an unused binding in my own test that procoder flagged). All criteria hold, with the known exceptions below.

### What changed
- `web/src/lib/settingsModel.js`: `describeRow` returns `takesEffect`: the four strings for `next_show`/`next_episode`/`next_merge_pass`/`next_sweep`; empty for `restart` (the `restart` flag is unchanged); empty plus one `console.warn` naming the key and value for a missing or unknown `applies`. No throw.
- `web/src/pages/settings/SettingRow.svelte`: renders `row.takesEffect` as a muted `.setting-effect` note above the help text, outside the editable/read-only branch, so both row kinds show it. Badges, controls and secret handling are untouched.
- `web/tests/settingsRows.test.mjs`: three new tests. One covers all four `applies` values (using an `ACQUIRE_APPLY`-shaped `next_show` entry); one covers `restart` (flag true, empty text); one covers unknown and missing `applies` (empty text, one warn each, key and value named, no throw).

### Evidence (verified)
- Fails on main: the new test file copied into a detached `main` worktree, then `node --test tests/settingsRows.test.mjs`: `ℹ tests 12 / pass 9 / fail 3`; failing: "turns each applies value into its takes-effect text", "gives a restart row no takes-effect text...", "warns once and returns empty text...". Same three failed before the implementation (`undefined !== ''`).
- `npm test` in `web/`: `tests 109 / pass 108 / fail 0` (one test skipped by the suite, not by me: unverified which).
- `npx prettier --check` on the three files: "All matched files use Prettier code style!" (re-run after the 9f6608e test edit on the test file: same).
- `npm run check`: `COMPLETED 4201 FILES 0 ERRORS 0 WARNINGS`. `npm run build`: `✓ built in 1.08s`.
- Python: `PATH=.venv/bin:$PATH python -m pytest -q`: all dots to 100%, `exit=0`. This pytest config prints no summary line, so I have no passed count.
- `procoder check` on the three files: 2 BLOCKING, both the known eqeqeq at `settingsModel.js:130` (`isDirty`, left untouched, PR #32). The first run also flagged `_omit` unused in my test (BLOCKING); fixed in 9f6608e and re-run: only the eqeqeq remains. The .js files report UNCHECKED (prettier-plugin-svelte tooling gap, as the task said). Info-only: release.yml no timeout-minutes, Dockerfile.builder DL3025, and a 76-char commit subject (aim <=72), which I did not rewrite.
- `git diff --stat main...HEAD` (run before 9f6608e, which only touches the test file): `.procoder/todo/20261022-settings-takes-effect.md`, `web/src/lib/settingsModel.js`, `web/src/pages/settings/SettingRow.svelte`, `web/tests/settingsRows.test.mjs`. Nothing else.
- Unverified: the note's rendering in a browser (no component test exists; covered only by svelte-check and build).

### Escalations
- None blocking. The two eqeqeq BLOCKING lines at `settingsModel.js:130` remain until PR #32 lands.

