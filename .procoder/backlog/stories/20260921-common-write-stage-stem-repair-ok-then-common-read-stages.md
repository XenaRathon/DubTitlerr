# `common.write_stage(stem, "repair", "ok")` then `common.read_stages(stem)` returns `{"repair": {"outcome": "ok", "detail": "", "at": <float>}}`; a second `write_stage` call for a different stage merges rather than overwrites the first.

Status: closed
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-6 of `.procoder/specs/v0-2-0-hardening.md`: Add a durable per-episode stage-status artifact with typed outcomes: `common.STAGES_SUFFIX = ".dubtitles.stages.json"`, `common.STAGE_OUTCOMES = ("ok", "no-reference", "llm-empty", "backend-unreachable", "extract-error", "build-error", "no-video", "timeout", "crashed", "unwritable")`, `common.write_stage(stem, stage, outcome, detail="")` (merges into the per-episode JSON), `common.read_stages(stem) -> dict` (empty dict when absent/unreadable), and `common.failed_stage(stem) -> str | None` (first stage whose outcome is not in `{"ok", "no-reference", "no-video"}`).

Delivered by Task 6 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `common.write_stage(stem, "repair", "ok")` then `common.read_stages(stem)` returns `{"repair": {"outcome": "ok", "detail": "", "at": <float>}}`; a second `write_stage` call for a different stage merges rather than overwrites the first.

## Evidence
Verified via `python3 -c "import common; ...` — after `write_stage(stem, 'repair', 'ok')`, `read_stages(stem)` returns `{'repair': {'outcome': 'ok', 'detail': '', 'at': 1790029731.0348203}}`; second `write_stage(stem, 'merge', 'ok', 'some detail')` merges, producing `{'repair': {...}, 'merge': {'outcome': 'ok', 'detail': 'some detail', 'at': ...}}`; `failed_stage(stem)` returns `None` when all outcomes are passing (`ok`, `no-reference`, `no-video`), and returns the first failing stage name (`repair`) when a non-passing outcome is recorded.
