# `tools/timing_compare.py` produces `docs/timing-compare/<date>-phase0-report.json` and `docs/timing-compare/<date>-phase0-go-no-go.md` for 3 named shows (one fansub dialogue, one signs-only, one One Pace); `in_gap_vad_error` is a separate field from offset/drift; no gate is wired into any script as a result.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-17 of `.procoder/specs/v0-2-0-hardening.md`: Run the T12 real-media leg of timing-compare on 3 selected shows (one fansub dialogue track, one signs-only, one One Pace episode), producing a report and a go/no-go note under `docs/timing-compare/`.

Delivered by Task 18 and 19 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `tools/timing_compare.py` produces `docs/timing-compare/<date>-phase0-report.json` and `docs/timing-compare/<date>-phase0-go-no-go.md` for 3 named shows (one fansub dialogue, one signs-only, one One Pace); `in_gap_vad_error` is a separate field from offset/drift; no gate is wired into any script as a result.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
