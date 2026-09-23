# `Dockerfile.builder` contains the exact `HEALTHCHECK` instruction targeting `127.0.0.1:8842/healthz`.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 013-v0-2-0-work

## Description

Scope S-16 of `.procoder/specs/v0-2-0-hardening.md`: Add a heartbeat file, `GET /healthz`, and a Dockerfile HEALTHCHECK: `common.HEARTBEAT_PATH`, `common.heartbeat(**fields)` (atomic merge-write), `common.read_heartbeat()`.

Delivered by Task 16 of `.procoder/plans/v0-2-0-hardening.md` (sprint 013); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `Dockerfile.builder` contains the exact `HEALTHCHECK` instruction targeting `127.0.0.1:8842/healthz`.

## Evidence

- `Dockerfile.builder` now contains: `HEALTHCHECK --interval=5m --timeout=10s --start-period=10m --retries=3 CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8842/healthz', timeout=5).status==200 else 1)"`
- `procoder check Dockerfile.builder` passes (pre-existing hygiene issues like DL3025 are out of scope)
