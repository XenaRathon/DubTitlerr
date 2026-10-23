# runtime-toggles

Status: done 2026-10-23
Created: 2026-10-14

## Why

User request: acquire on/off (`ACQUIRE_APPLY`) must be togglable in the web UI settings, so no container restart or compose edit is needed per change.

## Scope

- **[T-1]** Make `ACQUIRE_APPLY` a writable runtime setting (admin only), read by `gen_loop.sh` at each sweep from the runtime settings file the loop already applies.
- **[T-2]** Settings page toggle with the current effective value and a note on when it takes effect.
- **[T-3]** Same mechanism for other on/off switches (verify, repair, unanchored repair) once T-1 is proven.

## Notes

- Depends on the acquire fix that protects curated hard fixes; do not expose the toggle before that is deployed.
- README Roadmap line goes in the release docs pass (docs are frozen until the release).

## Outcome (2026-10-23)

- **[T-1] Done in v0.3.0:** `ACQUIRE_APPLY` is an editable, admin-only runtime setting.
- **[T-2] Done in #33 (707ed9a):** each settings row says when a saved change takes effect (`describeRow` `takesEffect` in `web/src/lib/settingsModel.js`).
- **[T-3] Dropped from this epic** by the user's scope decision on 2026-10-22 ("(a) only"). The verify and repair on/off switches were not built; they are kept as a separate roadmap epic, `runtime-kill-switches`. The third switch in the T-3 list, unanchored repair, already had one: `REPAIR_UNANCHORED` (`settings_registry.py:98`), an admin-editable setting that takes effect at the next merge pass.
