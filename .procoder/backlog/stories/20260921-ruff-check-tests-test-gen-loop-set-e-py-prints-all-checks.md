# `ruff check tests/test_gen_loop_set_e.py` prints "All checks passed!" (today it reports I001 at line 21 and W292 at line 144).

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 010-ground-truth-ci-green-compose-committed-with-a-safe-auth

## Description

Scope S-1 of `.procoder/specs/v0-2-0-hardening.md`: Get `main`'s CI green again: fix `ruff` I001 (import order) and W292 (missing final newline) in `tests/test_gen_loop_set_e.py` (both still present on this branch — verified: `ruff check tests/test_gen_loop_set_e.py` reports exactly these two), confirm the pushed `github/main` is already an ancestor of this branch (it is, at `defe151`; the local-only `2f8ae80` is not pulled in), push to the `github` remote, and record one green CI run on `main`.

Delivered by Task 1 of `.procoder/plans/v0-2-0-hardening.md` (sprint 010); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `ruff check tests/test_gen_loop_set_e.py` prints "All checks passed!" (today it reports I001 at line 21 and W292 at line 144).

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
