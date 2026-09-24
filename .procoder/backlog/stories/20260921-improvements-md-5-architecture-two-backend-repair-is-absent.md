# `IMPROVEMENTS.md` §5 ("Architecture: Two-Backend Repair") is absent from the file; `REVIEW.md:1025-1029` and `:1099` state `REPAIR_BACKEND_SECONDARY` is retired, not "not yet implemented" (owner decision — recommended default: retire; confirm at sprint 010 open).

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 012-provenance-and-policy-decoder-identity-in-words-json

## Description

Scope S-13 of `.procoder/specs/v0-2-0-hardening.md`: Retire `REPAIR_BACKEND_SECONDARY`: remove `IMPROVEMENTS.md` §5 ("Architecture: Two-Backend Repair") entirely; update `REVIEW.md:1025-1029` and `REVIEW.md:1099` to state it is retired rather than "not yet implemented" (owner decision — recommended default: retire; three prior reviews already recommend this, and `REPAIR_MODEL_SECONDARY` already covers the second-opinion need).

Delivered by Task 13 of `.procoder/plans/v0-2-0-hardening.md` (sprint 012); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `IMPROVEMENTS.md` §5 ("Architecture: Two-Backend Repair") is absent from the file; `REVIEW.md:1025-1029` and `:1099` state `REPAIR_BACKEND_SECONDARY` is retired, not "not yet implemented" (owner decision — recommended default: retire; confirm at sprint 010 open). `IMPROVEMENTS.md` §5 ("Architecture: Two-Backend Repair") is absent from the file; `REVIEW.md:1025-1029` and `:1099` state `REPAIR_BACKEND_SECONDARY` is retired, not "not yet implemented" (owner decision — recommended default: retire; confirm at sprint 010 open).

## Evidence

`python3 -m pytest tests/test_public_repo_hygiene.py -k test_repair_backend_secondary_is_retired_not_referenced_outside_history -q` -> 1 passed in commit 21e2656.
