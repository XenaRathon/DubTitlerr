# `procoder check` is clean and the full suite passes on the synced, committed tree at release time.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 015-release-osv-scanner-gap-ledger-and-the-0-2-0-release

## Description

Scope S-22 of `.procoder/specs/v0-2-0-hardening.md`: Release 0.2.0: bump `pyproject.toml`'s version, finalize the `CHANGELOG.md` `0.2.0` section with a date, run `procoder release 0.2.0` clean, and print (never execute) the tag command.

Delivered by Task 24 of `.procoder/plans/v0-2-0-hardening.md` (sprint 015); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `procoder check` is clean and the full suite passes on the synced, committed tree at release time.

## Evidence

- `procoder check` on the release-time tree `8acc889` -> clean (no BLOCK findings; only
  `info` notes on changed files). `procoder release 0.2.0` reaches its ready line only under
  `.procoder/config.toml`'s block policies for `[lint]`, `[test]`, `[docs]` and `[ask]`, so a
  clean ready line is itself the proof that the gate and the full suite passed — the ~70 s run
  is the suite executing.
- `.procoder/ask/QA.md` had no live questions at release time ("Cleared 2026-09-23"), and
  `answers.md` held only `## (no longer asked)` entries, so `[ask] policy = "block"` did not
  stop the run.
- The tree was clean at release time: `git status --porcelain` had no source changes; the only
  new/modified paths were this sprint's own `.procoder/backlog/` bookkeeping.
- Shipped in `8acc889`.
