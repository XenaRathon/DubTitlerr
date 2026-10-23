# runtime-kill-switches

Status: roadmap, not started
Created: 2026-10-23

## Description

Runtime on/off switches for the whole verify stage and the whole repair stage, using the same mechanism as `ACQUIRE_APPLY`: an admin-only runtime setting, so no container restart or compose edit is needed per change. Like `ACQUIRE_APPLY` (`next_show`) and the repair-side keys (`next_merge_pass`), each switch would take effect per show or per merge pass, and the settings page would show that takes-effect note.

Unanchored repair already has a runtime switch: `REPAIR_UNANCHORED` (`settings_registry.py:98`), admin-editable, which takes effect at the next merge pass. It is out of scope here.

This was T-3 of `runtime-toggles`. The user scoped it out of that epic on 2026-10-22, so it is recorded here and not scheduled. It needs a decision on which switches to add and whether each is safe to change mid-sweep.
