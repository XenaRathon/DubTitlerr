# `DECISIONS_APPLY=0` produces byte-identical output to an empty store for the same episode and the same NON-empty stored decisions, and no verdict is applied -- asserted on the application, not only on the bytes, since identical output proves the flag works without proving it is read before the verdict takes effect.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 004-task-4-consult-the-decision-store-inside-repair-reject

## Description

Task 4. The casual user wants dubtitles and no subsystem; the fanatic wants control. `DECISIONS_APPLY=0`
is that switch: matches become suggestions and change nothing on disk. Done means a NON-empty store
applies no verdict under the flag.

Asserted on the application, not the bytes -- identical output proves the flag exists without proving
it is read before the verdict takes effect.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `DECISIONS_APPLY=0` produces byte-identical output to an empty store for the same episode and the same NON-empty stored decisions, and no verdict is applied -- asserted on the application, not only on the bytes, since identical output proves the flag works without proving it is read before the verdict takes effect.

## Evidence

- `pytest -k apply_0` -> `test_decisions_apply_0_applies_no_verdict` passes.
- HONEST NOTE: this never went red on its own. The flag shipped with the first consult, so the test
  was written after the behaviour existed. It is held by the mutation check instead: deleting the
  `DECISIONS_APPLY` guard makes the stored `reject` take effect and fails the test (`AssertionError:
the reject must NOT take effect`). Recorded in the test docstring, not dressed up as red-green.
- Asserted on the APPLICATION: a stored `reject` would suppress the `repair_applied` entry, so that
  entry's presence proves the verdict was never consulted. Byte-identity alone would pass on a flag
  read after the verdict took effect.
