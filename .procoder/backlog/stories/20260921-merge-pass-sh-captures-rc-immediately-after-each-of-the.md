# `merge_pass.sh` captures `rc=$?` immediately after each of the three `python3` invocations (repair.py, dub_signs_merge.py, mux.py) and writes a `"crashed"` stage record via `python3 -c` when `rc != 0` and no stage record exists for that stem.

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

- [ ] `merge_pass.sh` captures `rc=$?` immediately after each of the three `python3` invocations (repair.py, dub_signs_merge.py, mux.py) and writes a `"crashed"` stage record via `python3 -c` when `rc != 0` and no stage record exists for that stem.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
