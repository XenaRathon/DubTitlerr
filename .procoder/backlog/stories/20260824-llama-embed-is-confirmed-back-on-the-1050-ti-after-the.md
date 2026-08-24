# `llama-embed` is confirmed back on the 1050 Ti after the sweep, by recorded `nvidia-smi` output.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: -

## Description

Implements plan Task 8 of `.procoder/plans/v5-two-tier-idempotency.md`.

llama-embed is evicted from the 1050 Ti so large-v3 gets the full 4 GB during the bake-off and sweep. Restoring it is precisely the kind of ops step that silently does not happen and is noticed weeks later. Done means nvidia-smi output showing it resident on the card again is recorded as evidence.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `llama-embed` is confirmed back on the 1050 Ti after the sweep, by recorded `nvidia-smi` output.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

