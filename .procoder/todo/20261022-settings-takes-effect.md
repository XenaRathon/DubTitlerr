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

## Evidence

## Result
