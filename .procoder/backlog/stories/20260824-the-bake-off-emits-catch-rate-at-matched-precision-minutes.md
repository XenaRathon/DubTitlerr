# The bake-off emits catch rate at matched precision, minutes per episode, and peak VRAM per model, measured on VM102; an OOM is recorded as that model's result.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: -

## Description

Implements plan Task 8 of `.procoder/plans/v5-two-tier-idempotency.md`.

Whether to sweep the library onto large-v3 or stay on turbo decides what 861-plus episodes are transcribed with, and changing it later means sweeping again. turbo's no_speech_prob is collapsed to ~1e-10, leaving two of five gated rules structurally inert. Done means catch rate at matched precision, minutes per episode and peak VRAM for both models, measured on VM102 — the card changed hosts on 2026-08-23 and the old figures do not transfer — with an OOM recorded as a result rather than retried smaller.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] The bake-off emits catch rate at matched precision, minutes per episode, and peak VRAM per model, measured on VM102; an OOM is recorded as that model's result.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

