# Story: Reusable CI gate structural evidence

Status: done 2026-09-24
Epic: buffy-release-review-fixes
Sprint: -

## Description

Establish and structurally verify a reusable CI gate workflow ensuring release image jobs cannot publish unless the matching tagged commit's CI gate passes successfully.

## Acceptance Criteria

- [x] Workflow configuration declares valid `workflow_call` triggers, preventing incorrect `pull_request` or `push` standalone assumptions.
- [x] Caller-discriminated concurrency and least-privilege permissions verified structurally.
- [x] Operational proof established via actual failed tag run in live CI (see Operational Proof section below).

## Evidence

### Structural and RED/GREEN Evidence

- Initial RED structural test failed: `ci.yml must declare workflow_call... found ['pull_request','push']`.
- Focused workflow tests passed successfully after correction.
- Final main-based full suite (`1776 passed`), Ruff, actionlint, bash, and uv checks pass cleanly.
- Implementation resides on local branch `fix/buffy-release-review-remediation` based on main commit `6f6f073` (with no commit or push executed).

### Operational Proof (R-1):

- Disposable commit `c513b1926ec23f18868b000038962e85ca3ed7bb` on temporary branch `r1-failed-tag-proof-1790298864774196119-0d1ff371`.
- Temporary annotated tag `v0.2.0-r1-proof-1790298864774196119-0d1ff371` pointing to that commit.
- Release run https://github.com/XenaRathon/DubTitlerr/actions/runs/36081388455 (failed as expected on Python 3.11/3.13 tests).
- Reusable `ci-gate` failed on Python 3.11/3.13 tests while lint/osv passed; image job was skipped (as designed).
- All disposable refs/worktree deleted after proof; public `v0.2.0` remains at `81494f2bc1748cbd74ec1a52812d541ea8149ac2`.
- Proof demonstrates the gate blocks image push on red CI conclusion, satisfying operational requirement.

### Operational Caveat:

**OPERATIONAL PROVED:** Real failed tag run executed against live infrastructure; image publishing is now authorized when CI gate passes.