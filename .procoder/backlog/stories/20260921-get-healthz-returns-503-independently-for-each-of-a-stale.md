# `GET /healthz` returns 503 independently for each of: a stale `last_sweep_end` (> `3 * RESCAN_INTERVAL`), `roots_readable=False`, and `order_file_present=False`; returns 200 otherwise; the response body never contains a filesystem path.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-16 of `.procoder/specs/v0-2-0-hardening.md`: Add a heartbeat file, `GET /healthz`, and a Dockerfile HEALTHCHECK: `common.HEARTBEAT_PATH`, `common.heartbeat(**fields)` (atomic merge-write), `common.read_heartbeat()`.

Delivered by Task 16 of `.procoder/plans/v0-2-0-hardening.md` (sprint 013); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `GET /healthz` returns 503 independently for each of: a stale `last_sweep_end` (> `3 * RESCAN_INTERVAL`), `roots_readable=False`, and `order_file_present=False`; returns 200 otherwise; the response body never contains a filesystem path.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
