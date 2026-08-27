# `DECISIONS_APPLY=0` produces byte-identical output to an empty store for the same episode and the same NON-empty stored decisions, and no verdict is applied -- asserted on the application, not only on the bytes, since identical output proves the flag works without proving it is read before the verdict takes effect.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 4. The casual user wants dubtitles and no subsystem; the fanatic wants control. `DECISIONS_APPLY=0`
is that switch: matches become suggestions and change nothing on disk. Done means a NON-empty store
applies no verdict under the flag.

Asserted on the application, not the bytes -- identical output proves the flag exists without proving
it is read before the verdict takes effect.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `DECISIONS_APPLY=0` produces byte-identical output to an empty store for the same episode and the same NON-empty stored decisions, and no verdict is applied -- asserted on the application, not only on the bytes, since identical output proves the flag works without proving it is read before the verdict takes effect.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
