# The swap plan states the move as completed and verified 2026-08-23, checkboxes ticked.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 9 of `.procoder/plans/v5-two-tier-idempotency.md`.

The swap plan still reads 'planned, not started' for a move completed and verified 2026-08-23. A document asserting the opposite of reality is the same failure class as configuration that looks applied and is not — it will mislead the next reader. Done means the status and checkboxes match what was actually performed, with anything unconfirmed left unticked and said so.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] The swap plan states the move as completed and verified 2026-08-23, checkboxes ticked.

## Evidence

- Status line now reads "DONE — executed and verified 2026-08-23", citing commit
  `4f0b827`, and says plainly that the document was wrong for three days and why that
  matters.
- Verified directly on 2026-08-24 rather than recalled: `ssh vm102` showing
  `dubtitle-builder Up (healthy)`, `nvidia-smi` reporting `GTX 1050 Ti, 4096 MiB`, the
  NFS mount at `/mnt/r520-media-full` walked during the orphan scan, and the 3200g
  carrying no dubtitle-builder.
- 11 checkboxes ticked where the outcome was observed; **12 marked `[~]`** rather than
  ticked — performed during the move but not independently re-verified. An unverified
  tick is worth less than an honest gap, which is the lesson this document just taught.
- `procoder check`: 0 blocking.

