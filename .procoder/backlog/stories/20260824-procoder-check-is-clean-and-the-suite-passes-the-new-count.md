# `procoder check` is clean and the suite passes; the new count is recorded (baseline 1,108 passing before this work, boxxo excluded).

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: -

## Description

Implements plan all tasks of `.procoder/plans/v5-two-tier-idempotency.md`.

The gate and the suite are the release condition for the whole epic. Done means `procoder check` passes with no blocking finding and the full suite is green, with the new test count recorded against the 1,108 baseline so a silent drop in collected tests cannot pass unnoticed.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `procoder check` is clean and the suite passes; the new count is recorded (baseline 1,108 passing before this work, boxxo excluded).

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

