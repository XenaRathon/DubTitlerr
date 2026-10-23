# runtime-kill-switches

Status: roadmap, not started
Created: 2026-10-23

## Description

Runtime on/off switches for verify, repair and unanchored repair, using the same mechanism as `ACQUIRE_APPLY`: an admin-only runtime setting the loop reads at each sweep, so no container restart or compose edit is needed per change. The settings page shows a takes-effect note for each one.

This was T-3 of `runtime-toggles`. The user scoped it out of that epic on 2026-10-22, so it is recorded here and not scheduled. It needs a decision on which switches to add and whether each is safe to change mid-sweep.
