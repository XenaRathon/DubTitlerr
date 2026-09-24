# `python3 -c "import generate; assert generate.FFMPEG_TIMEOUT == 1800"` passes with `FFMPEG_TIMEOUT` unset in the environment; the README/Reference table and `generate.py:32-33`'s comment both state the new default.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-19 of `.procoder/specs/v0-2-0-hardening.md`: Write a storage/host checklist note: the single active worker confirmed (not assumed), mergerfs `pfrd` persistence through the OMV-managed config, the unexplained continuous writer on `sdc1`, and `llama-embed` confirmed back on the 1050 Ti after any heavy run.

Delivered by Task 21 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `python3 -c "import generate; assert generate.FFMPEG_TIMEOUT == 1800"` passes with `FFMPEG_TIMEOUT` unset in the environment; the README/Reference table and `generate.py:32-33`'s comment both state the new default.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
