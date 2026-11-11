# v0-2-0-hardening

Status: done
Created: 2026-09-21
Spec: v0-2-0-hardening @ b0d444793550

## Description

v0.2.0 hardening: the pipeline fails closed instead of stamping failed stages, the review server's posture matches its docs, decoder provenance is recorded and compared, timing-compare gets its go/no-go, and every live-host fact is written down before a sweep runs. Sprints 010-015 in `.procoder/plans/v0-2-0-hardening.md`.

Seeded from .procoder/specs/v0-2-0-hardening.md — one story per acceptance criterion.

## Outcome

- 20260921-a-tracked-issue-github-issue-or-procoder-backlog-entry: done
- 20260921-the-release-note-records-verification-against: superseded
- 20260921-tools-timing-compare-py-produces-docs-timing-compare-date: folded into the reference-lines real-media test
- 20260921-a-vault-note-records-systemd-analyze-verify-output-the: moved
- 20260921-a-vault-note-records-the-confirmed-single-active-worker: moved
