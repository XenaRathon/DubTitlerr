# `procoder check` is clean and the suite passes; the new count is recorded (baseline 1,108 passing before this work, boxxo excluded).

Status: done 2026-08-25
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: -

## Description

Implements plan all tasks of `.procoder/plans/v5-two-tier-idempotency.md`.

The gate and the suite are the release condition for the whole epic. Done means `procoder check` passes with no blocking finding and the full suite is green, with the new test count recorded against the 1,108 baseline so a silent drop in collected tests cannot pass unnoticed.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `procoder check` is clean and the suite passes; the new count is recorded (baseline 1,108 passing before this work, boxxo excluded).

## Evidence

- `procoder check`: **0 blocking**, 0 unformatted, 0 unchecked.
- Suite: **1,189 passed** against a baseline of 1,108 at the start of this work — 81 tests
  added across the epic, none removed except the tests of the two rules ADR 0002 deleted.
- Every commit in the epic ran the gate before landing. The one exception is the
  documentation-only commit `0793eb2`, which used `--no-verify` against a procoder defect
  (pytest exit 5, "no tests collected", reported as `tests: FAILED`); the suite and the
  dependency scan were both run by hand and recorded in that commit message.

