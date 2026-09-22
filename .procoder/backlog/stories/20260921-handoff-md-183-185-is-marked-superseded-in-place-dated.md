# `handoff.md:183-185` is marked superseded in place, dated.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 012-provenance-and-policy-decoder-identity-in-words-json

## Description

Scope S-11 of `.procoder/specs/v0-2-0-hardening.md`: Reconcile the deployed unanchored-repair policy: the 4 rejected S31 targets from `REVIEW-2026-08-27-unanchored-repair-45-lines.md` are recorded in the One Pace decision store via `decisions.record(...)` under `decisions.locked(show, dir)` (followed by `decisions.save`), joining the 41 already-approved lines; `handoff.md:183-185` is marked superseded in place; `docs/wiki/How-To-Guides.md:44` and `Reference.md:106` (both currently say "do not use `REPAIR_UNANCHORED`" / "unset — closed") are reconciled with the deployed global flag; one vault operator note holds the deployed value, the human-review boundary, and the recovery procedure together (owner decision — recommended default: keep the global flag, since v10's `TEXT_VERSION` bump already paid the regeneration cost; recovery is a `reject` verdict through `decisions.record` + `review_apply.py`; confirm at sprint 010 open).

Delivered by Task 12 of `.procoder/plans/v0-2-0-hardening.md` (sprint 012); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `handoff.md:183-185` is marked superseded in place, dated.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
