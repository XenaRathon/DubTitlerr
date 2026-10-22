# runtime-toggles

Status: roadmap, not started
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
