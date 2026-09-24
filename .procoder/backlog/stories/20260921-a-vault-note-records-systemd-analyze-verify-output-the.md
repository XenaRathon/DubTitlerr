# A vault note records `systemd-analyze verify` output, the publish timer's live status, a diff between the deployed order file and `watch_queue.py --dry-run`, and confirmation of the manifest/title policy.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-18 of `.procoder/specs/v0-2-0-hardening.md`: Write a queue/publish operations verification note: `systemd-analyze verify` output, the publish timer's status, the last publish result, a drift check between the deployed order file and `watch_queue.py --dry-run`, and confirmation the public manifest/title policy (release-group stripping, duplicate-encode handling) remains intentional.

Delivered by Task 20 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A vault note records `systemd-analyze verify` output, the publish timer's live status, a diff between the deployed order file and `watch_queue.py --dry-run`, and confirmation of the manifest/title policy.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
