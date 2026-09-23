# `CHANGELOG.md`'s `0.2.0` section carries a release date and the full included-item list.

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

- [x] `CHANGELOG.md`'s `0.2.0` section carries a release date and the full included-item list.

## Evidence

- `grep -n '^## ' CHANGELOG.md` -> `9:## [Unreleased]`, `11:## 0.2.0 - 2026-09-23` (empty
  unreleased section above a dated release section). The heading is deliberately bracket-free:
  `internal/release`'s `changelogHasVersion()` compares `strings.Fields(line[3:])[0]` to the
  version, so `## [0.2.0] - ...` would not match. It matches `## 0.1.0 - 2026-09-04`'s shape.
- The section's `### Included` (line 17) carries the full per-scope list S-1 through S-22, closing with
  "S-21 and S-22 (sprint 015, Release): the osv-scanner/pyproject extractor gap is tracked and
  the uv.lock scanning decision recorded (S-21); the 0.2.0 release itself (S-22)." — plus the
  `### Deferred` and `### Fixed` sections the release note needs.
- Shipped in `8acc889` (`release: prepare 0.2.0 -- version bump and changelog finalize`).
