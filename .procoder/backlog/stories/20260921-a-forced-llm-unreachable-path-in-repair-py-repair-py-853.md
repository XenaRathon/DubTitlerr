# A forced `LLM_UNREACHABLE` path in `repair.py` (`repair.py:853`) results in `write_stage(stem, "repair", "backend-unreachable")`, never `"llm-empty"` — a test asserts the two outcomes are never produced by the same code path.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-6 of `.procoder/specs/v0-2-0-hardening.md`: Add a durable per-episode stage-status artifact with typed outcomes: `common.STAGES_SUFFIX = ".dubtitles.stages.json"`, `common.STAGE_OUTCOMES = ("ok", "no-reference", "llm-empty", "backend-unreachable", "extract-error", "build-error", "no-video", "timeout", "crashed", "unwritable")`, `common.write_stage(stem, stage, outcome, detail="")` (merges into the per-episode JSON), `common.read_stages(stem) -> dict` (empty dict when absent/unreadable), and `common.failed_stage(stem) -> str | None` (first stage whose outcome is not in `{"ok", "no-reference", "no-video"}`).

Delivered by Task 6 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A forced `LLM_UNREACHABLE` path in `repair.py` (`repair.py:853`) results in `write_stage(stem, "repair", "backend-unreachable")`, never `"llm-empty"` — a test asserts the two outcomes are never produced by the same code path.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
