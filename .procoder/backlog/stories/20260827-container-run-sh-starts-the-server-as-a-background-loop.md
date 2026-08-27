# `container_run.sh` starts the server as a background loop; killing the server leaves the merge and generate loops running.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 008-task-8-run-the-review-server-as-a-third-container-loop

## Description

Task 8. The generate loop is the container's foreground process and `set -e` is active in that script.
Done means the server runs as a THIRD background loop whose death logs and retries, and killing it
leaves the merge and generate loops running.

This story also covers the image: `decisions.py`, `review_apply.py` and `review_server.py` must reach
the COPY list. `qc.py` passed 987 tests and ImportError'd on container start across 33 commits for
exactly this omission, which is why `tests/test_dockerfile_copy.py` exists.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `container_run.sh` starts the server as a background loop; killing the server leaves the merge and generate loops running.

## Evidence

- `test_container_run_starts_the_review_server_as_a_background_loop` -- the launch is on an
  EXECUTABLE line (comments stripped before matching, or a mention in a comment would
  satisfy the guard while nothing started the server), it precedes the `exec`, and nothing
  after the `exec` references it, because `exec` replaces the shell and nothing after it
  ever runs.
- `test_the_review_server_loop_cannot_end_the_container` -- the launch sits inside a `while`
  inside a subshell that is backgrounded, with a `sleep` so a crash-loop cannot spin the CPU
  and a `||` so a non-zero exit is logged and retried rather than propagating.
- `test_container_run_is_valid_posix_shell` -- `sh -n` parses it. A syntax error here does
  not fail a test, it fails the container at boot, and nothing in that file may be executed
  by the suite because it launches GPU sweeps.
- Mutations caught: server in the exec slot (kills the generate loop), launch replaced by a
  comment, bare launch with no restart loop, no sleep between restarts.
- A FIFTH mutation was NOT caught and exposed a real gap: removing review_server.py from the
  Dockerfile COPY line broke nothing, because the existing check walks what each entrypoint
  IMPORTS and never asks whether the entrypoint itself is in the image. That is the qc.py
  failure exactly -- 987 tests green, ImportError on container start. Closed by
  `test_every_entrypoint_is_itself_copied_into_the_image`, which also confirms every
  pre-existing entrypoint is genuinely copied.
