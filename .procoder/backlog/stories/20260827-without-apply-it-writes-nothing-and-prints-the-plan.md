# Without `--apply` it writes nothing and prints the plan.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 005-task-5-review-apply-py-rebuild-an-episode-s-srt-from-conf

## Description

Task 5. Every write-capable tool in this repo is dry-run by default -- `mux.py`, `glossary_acquire.py`.
Done means the plan prints and nothing on disk changes without `--apply`.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Without `--apply` it writes nothing and prints the plan.

## Evidence

- `test_dry_run_writes_nothing_and_reports_the_plan` passes: `changed` is still reported,
  no sidecar appears and the stamp survives.
- Matches the repo convention (`mux.py`, `glossary_acquire.py`, `tools/reapply_glossary.py`).
- Mutation: removing `or not apply` from the guard fails it.
