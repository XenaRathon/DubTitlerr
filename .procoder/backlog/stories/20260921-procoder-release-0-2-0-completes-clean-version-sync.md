# `procoder release 0.2.0` completes clean (version sync, changelog, clean tree, gate, suite all pass) and prints the tag command without executing it.

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

- [x] `procoder release 0.2.0` completes clean (version sync, changelog, clean tree, gate, suite all pass) and prints the tag command without executing it.

## Evidence

- `procoder release 0.2.0` -> exit 0, printing exactly two lines:
  `release 0.2.0 is ready — tag it:` and `  git tag -a v0.2.0 -m "0.2.0"`. Re-run on
  2026-09-23 against tree `8acc889` to confirm the result is current, not a stale transcript.
- The controller performed all five checks itself before printing that line — version sync
  against `pyproject.toml` (`[release] files`), the `CHANGELOG.md` `0.2.0` heading, a clean
  tree, `.procoder/config.toml`'s `[lint]`/`[test]`/`[docs]`/`[ask]` `block` policies, and the
  full suite (the run takes ~70 s because the gate and suite actually execute).
- The tag command was printed, not executed: `git tag -l` -> `backup/pre-attribution-strip`,
  `v0.1.0` only; no `v0.2.0`.
- `procoder backlog close story ...` re-ran the same gate and suite on this story's behalf and
  returned clean after the criteria were checked.
- Shipped in `8acc889`.
