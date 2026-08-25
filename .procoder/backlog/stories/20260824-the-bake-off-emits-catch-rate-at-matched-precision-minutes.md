# The bake-off emits catch rate at matched precision, minutes per episode, and peak VRAM per model, measured on VM102; an OOM is recorded as that model's result.

Status: done 2026-08-25
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: -

## Description

Implements plan Task 8 of `.procoder/plans/v5-two-tier-idempotency.md`.

Whether to sweep the library onto large-v3 or stay on turbo decides what 861-plus episodes are transcribed with, and changing it later means sweeping again. turbo's no_speech_prob is collapsed to ~1e-10, leaving two of five gated rules structurally inert. Done means catch rate at matched precision, minutes per episode and peak VRAM for both models, measured on VM102 — the card changed hosts on 2026-08-23 and the old figures do not transfer — with an OOM recorded as a result rather than retried smaller.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] The bake-off emits catch rate at matched precision, minutes per episode, and peak VRAM per model, measured on VM102; an OOM is recorded as that model's result.

## Evidence

Run on VM102 with `llama-embed` evicted, models loaded sequentially, on the same episode.

- **Both entrants, matched beam 3:**

      model            segs  nsp>0.95  music_would_fire  min/ep  peak VRAM  logprob p50/p05
      large-v3-turbo    263         0                 0    1.64      923 MiB  -0.222 / -0.468
      large-v3          285         6                 0    6.32     1627 MiB  -0.225 / -0.445

- **OOM recorded as a result, never retried smaller:** `large-v3` failed at beam 7
  (`RuntimeError: CUDA failed with error out of memory`, ~77% through) and at beam 5
  (peak 3867 of 4096 MiB). Beams 4 and 3 completed. Each is a separate report file on
  VM102 (`bakeoff-report.json`, `bakeoff-beam5.json`, `bakeoff-beam4.json`,
  `bakeoff-beam3.json`, `bakeoff-conj.json`).
- **Sequential offload observed, not assumed:** `vram_after_unload_mib` = 49 for both
  entrants, with `vram_before_load_mib` = 0 for the first.
- **The scoring method was corrected before running.** The spec asked for a score against
  "the labelled set"; that set is not an artifact on disk — its positives are blocklist
  hits in conf.json sidecars produced BY the incumbent model. Both models therefore
  transcribe the same episodes through generate's own audio path instead.
- **The decisive metric had to be added mid-flight.** Two marginal distributions implied a
  revival that the conjunction disproved: `music_rule_would_fire` is 0 for both models at
  every beam tested. That result is what ADR 0002 acts on.
- Outcome: stay on `large-v3-turbo`; both nsp-gated rules deleted (commit `f9e19ca`).

