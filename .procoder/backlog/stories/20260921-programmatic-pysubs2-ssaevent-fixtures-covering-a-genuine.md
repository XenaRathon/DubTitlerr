# Programmatic `pysubs2.SSAEvent` fixtures covering a genuine off-position sign, a karaoke event, a credits event, and a plain dialogue event produce the expected true/false-positive classification in a test.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-20 of `.procoder/specs/v0-2-0-hardening.md`: Build a read-only S&S (signs & songs) extract-only prototype, `tools/sns_extract.py`: standalone, imports `dub_signs_merge.keep_event` and adds a numeric heuristic `off_default_position(ev, play_res_y)`.

Delivered by Task 22 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] Programmatic `pysubs2.SSAEvent` fixtures covering a genuine off-position sign, a karaoke event, a credits event, and a plain dialogue event produce the expected true/false-positive classification in a test.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
