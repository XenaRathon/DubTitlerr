# `container_run.sh` starts the server as a background loop; killing the server leaves the merge and generate loops running.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

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

- [ ] `container_run.sh` starts the server as a background loop; killing the server leaves the merge and generate loops running.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
