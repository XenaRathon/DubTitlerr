# A vault note exists (`Homelab/Projects/DubTitlerr/<date> Production Snapshot.md`) recording `docker ps` output from vm102, fasc, and 3200g; the deployed `REPAIR_UNANCHORED` value; per-show `unanchored_repair` opt-ins found (if any); the review bind/token/`REVIEW_AUTH` posture; a diff between the live order file and `watch_queue.py --dry-run`; the publish timer's status; and the stopped 3200g `dubtitle-builder` container's classification.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 010-ground-truth-ci-green-compose-committed-with-a-safe-auth

## Description

Scope S-4 of `.procoder/specs/v0-2-0-hardening.md`: Take a read-only production snapshot and write it to the vault: the active worker host, checked with `docker ps` on vm102 AND fasc AND 3200g (not assumed from the last note); the deployed `REPAIR_UNANCHORED` value; any per-show `unanchored_repair` glossary opt-ins found; the review server's bind address and whether `REVIEW_TOKEN`/`REVIEW_AUTH` is set; a diff between the deployed order file and a fresh `watch_queue.py --dry-run`; the publish timer's status; and whether the stopped `dubtitle-builder` container on the old 3200g host is classified dead-weight or standby.

Delivered by Task 4 of `.procoder/plans/v0-2-0-hardening.md` (sprint 010); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A vault note exists (`Homelab/Projects/DubTitlerr/<date> Production Snapshot.md`) recording `docker ps` output from vm102, fasc, and 3200g; the deployed `REPAIR_UNANCHORED` value; per-show `unanchored_repair` opt-ins found (if any); the review bind/token/`REVIEW_AUTH` posture; a diff between the live order file and `watch_queue.py --dry-run`; the publish timer's status; and the stopped 3200g `dubtitle-builder` container's classification.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
