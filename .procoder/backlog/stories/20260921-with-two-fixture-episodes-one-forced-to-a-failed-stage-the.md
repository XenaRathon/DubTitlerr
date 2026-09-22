# With two fixture episodes, one forced to a failed stage, the script prints `MERGE PASS INCOMPLETE: 1 episodes with a failed stage`; the incomplete count is computed by scanning `.dubtitles.stages.json` files after the loop exits, not from a variable set inside the pipe-subshell loop (`merge_pass.sh:48-60`).

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-7 of `.procoder/specs/v0-2-0-hardening.md`: `merge_pass.sh` captures each stage invocation's exit code and prints `MERGE PASS COMPLETE` only when no episode has a failed stage (per `common.failed_stage`); otherwise it prints `MERGE PASS INCOMPLETE: <n> episodes with a failed stage`.

Delivered by Task 7 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] With two fixture episodes, one forced to a failed stage, the script prints `MERGE PASS INCOMPLETE: 1 episodes with a failed stage`; the incomplete count is computed by scanning `.dubtitles.stages.json` files after the loop exits, not from a variable set inside the pipe-subshell loop (`merge_pass.sh:48-60`).

## Evidence

`python3 -m pytest tests/test_merge_pass.py::test_one_failed_stage_of_two_episodes_prints_incomplete_with_count -v` -- PASSED. merge_pass.sh run end-to-end (real script, stubbed mkvmerge) over two pre-seeded .dubtitles.stages.json fixtures (one all-ok, one repair=backend-unreachable) prints exactly "MERGE PASS INCOMPLETE: 1 episodes with a failed stage", computed by the post-loop find|xargs scan, not a subshell-local counter.
