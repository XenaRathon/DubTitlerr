# `procoder check` is clean and the full suite passes on the synced, committed tree at release time.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-22 of `.procoder/specs/v0-2-0-hardening.md`: Release 0.2.0: bump `pyproject.toml`'s version, finalize the `CHANGELOG.md` `0.2.0` section with a date, run `procoder release 0.2.0` clean, and print (never execute) the tag command.

Delivered by Task 24 of `.procoder/plans/v0-2-0-hardening.md` (sprint 015); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `procoder check` is clean and the full suite passes on the synced, committed tree at release time.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
