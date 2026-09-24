# `pyproject.toml`'s `version` field reads `"0.2.0"`.

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

- [x] `pyproject.toml`'s `version` field reads `"0.2.0"`.

## Evidence

- `grep -n '^version' pyproject.toml` -> `3:version = "0.2.0"`. The field is the first
  top-level key under `[project]`, which is what `procoder release` reads via
  `.procoder/config.toml`'s `[release] files = ["pyproject.toml"]`.
- Shipped in `8acc889` (`release: prepare 0.2.0 -- version bump and changelog finalize`).
