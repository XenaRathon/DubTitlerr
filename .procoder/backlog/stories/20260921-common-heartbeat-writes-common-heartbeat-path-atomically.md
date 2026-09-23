# `common.heartbeat(...)` writes `common.HEARTBEAT_PATH` atomically; `common.read_heartbeat()` returns the same fields back.

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

- [x] `common.heartbeat(...)` writes `common.HEARTBEAT_PATH` atomically; `common.read_heartbeat()` returns the same fields back.

## Evidence

- `common.py`: `HEARTBEAT_PATH` = env `HEARTBEAT_PATH` default `/config/heartbeat.json`; `heartbeat(**fields)` merges with existing fields, writes temp + `os.replace()`; `read_heartbeat()` returns dict or None
- `tests/test_common.py`: `test_heartbeat_merges_rather_than_replaces`, `test_heartbeat_write_is_atomic_no_tmp_file_left_behind` pass
- `procoder check common.py` passes
