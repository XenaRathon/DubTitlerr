# All of the above verified by `procoder test` green and `procoder check` with zero blocking findings.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 008-task-8-run-the-review-server-as-a-third-container-loop

## Description

The epic's definition of done, not a unit of work. Every story above closes only on a green
`procoder test` and a `procoder check` with zero blocking findings, with the RED and GREEN commands
and their output recorded as evidence.

Closed last, after the other 24, and it is the story that fails if any task was closed on an
unverified claim.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] All of the above verified by `procoder test` green and `procoder check` with zero blocking findings.

## Evidence

- `python3 -m pytest`: **1339 passed**, 0 failed, no warnings. Baseline at the start of this
  epic was 1272.
- `procoder check`: 0 blocking findings.
- `procoder lint --types`: 0 findings.
- `procoder security --deep`: zero findings in any file this epic added
  (decisions.py, review_apply.py, review_server.py); secrets scan clean. Its one BLOCK is
  the known osv-scanner issue -- procoder hands the scanner `pyproject.toml`, which has no
  extractor -- so dependencies were verified directly instead: `osv-scanner --lockfile
uv.lock` reports **no issues found**.
- HONEST NOTE on the criterion's wording: `procoder test` reports `pass (0 test(s))`. It is
  "green", but vacuously -- it discovers nothing. Verified pre-existing by stashing this
  branch's changes and re-running it at HEAD, where it reports the same. The evidence above
  therefore rests on the direct pytest run, not on that command, and the discrepancy is
  recorded here rather than papered over: a test runner that reports zero tests as a pass is
  the kind of check that silently did not run.
