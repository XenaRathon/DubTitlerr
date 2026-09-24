# With two fixture episodes, one forced to a failed stage, the script prints `MERGE PASS INCOMPLETE: 1 episodes with a failed stage`; the incomplete count is computed by scanning `.dubtitles.stages.json` files after the loop exits, not from a variable set inside the pipe-subshell loop (`merge_pass.sh:48-60`).

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-7 of `.procoder/specs/v0-2-0-hardening.md`: `merge_pass.sh` captures each stage invocation's exit code and prints `MERGE PASS COMPLETE` only when no episode has a failed stage (per `common.failed_stage`); otherwise it prints `MERGE PASS INCOMPLETE: <n> episodes with a failed stage`.

Delivered by Task 7 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] With two fixture episodes, one forced to a failed stage, the script prints `MERGE PASS INCOMPLETE: 1 episodes with a failed stage`; the incomplete count is computed by scanning `.dubtitles.stages.json` files after the loop exits, not from a variable set inside the pipe-subshell loop (`merge_pass.sh:48-60`).

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
