# `llama-embed` is confirmed back on the 1050 Ti after the sweep, by recorded `nvidia-smi` output.

Status: done 2026-08-25
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: -

## Description

Implements plan Task 8 of `.procoder/plans/v5-two-tier-idempotency.md`.

llama-embed is evicted from the 1050 Ti so large-v3 gets the full 4 GB during the bake-off and sweep. Restoring it is precisely the kind of ops step that silently does not happen and is noticed weeks later. Done means nvidia-smi output showing it resident on the card again is recorded as evidence.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `llama-embed` is confirmed back on the 1050 Ti after the sweep, by recorded `nvidia-smi` output.

## Evidence

- Evicted for the duration so `large-v3` had the whole card:

      after eviction:  0 MiB used, 4032 MiB free   (no compute apps)

- Restored after the last run, confirmed by `nvidia-smi` and `docker ps`:

      llama-embed   Up 7 seconds
      compute apps: 90914  /app/llama-server  44 MiB
      gpu: 47 MiB used, 3986 MiB free

- `dubtitle-builder` deliberately left `Exited (137)` — production stays stopped per the
  owner's decision until every change from this week is committed.

