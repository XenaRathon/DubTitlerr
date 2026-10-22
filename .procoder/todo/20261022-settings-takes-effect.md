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

Out of scope: new settings or toggles (verify/repair kill switches were explicitly not chosen), Python and API changes, README/CHANGELOG (docs are frozen until the release pass), and every other file.

## Acceptance criteria

- [ ] `describeRow` returns the four strings above for `next_show`, `next_episode`, `next_merge_pass` and `next_sweep`. It returns empty text and warns once for an unknown or missing `applies`. A `restart` row keeps `restart: true` with empty takes-effect text. The new tests in `web/tests/settingsRows.test.mjs` cover all of this and fail on `main` (show the failing run).
- [ ] `SettingRow.svelte` renders the note for both editable and read-only rows. The existing badges are unchanged.
- [ ] In `web/`: `npm run format:check && npm run check && npm test && npm run build` all pass. This is the CI line in `.github/workflows/ci.yml:70`.
- [ ] `procoder check` on the three changed files reports 0 BLOCKING. Prettier must actually run, not report UNCHECKED: `web/node_modules` is installed in this checkout.
- [ ] The Python suite still passes: `python -m pytest -q` with `/home/xena/work/code/DubTitlerr/.venv/bin` first on PATH.
- [ ] `git diff --stat main...HEAD` lists only the three Owns files plus this task file.

## Review

## Evidence

## Result
