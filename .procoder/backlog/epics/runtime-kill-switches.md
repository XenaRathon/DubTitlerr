# runtime-kill-switches

Status: roadmap, not started
Created: 2026-10-23

## Description

Runtime on/off switches for the whole verify stage and the whole repair stage, using the same mechanism as `ACQUIRE_APPLY`: an admin-only runtime setting, so no container restart or compose edit is needed per change. Like `ACQUIRE_APPLY` (`next_show`) and the repair-side keys (`next_merge_pass`), each switch would take effect per show or per merge pass, and the settings page would show that takes-effect note.

Unanchored repair already has a runtime switch: `REPAIR_UNANCHORED` (`settings_registry.py:98`), admin-editable, which takes effect at the next merge pass. It is out of scope here.

This was T-3 of `runtime-toggles`. The user scoped it out of that epic on 2026-10-22, so it is recorded here and not scheduled. It needs a decision on which switches to add and whether each is safe to change mid-sweep.

## Result

### Outcome
- Two new boolean switches: `VERIFY` and `REPAIR` are registered as admin-only in `settings_registry.py`.
  - `VERIFY` applies to `next_show`.
  - `REPAIR` applies to `next_merge_pass`.
- Setting `VERIFY` to off correctly skips the verification process for each show, outputting `gen_loop: VERIFY off, skipping verify on <show>`. Story arcs generation (`GLOSSARY_ARC_TAGS`) is preserved.
- Setting `REPAIR` to off holds episodes before repair, preventing them from proceeding to signs, mux, or being stamped. It counts the number of episodes held and logs a summary message `merge_pass: REPAIR off, held <N> episodes`. Turning it back on continues the processing properly in the next pass.
