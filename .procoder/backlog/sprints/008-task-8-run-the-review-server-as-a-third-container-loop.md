# Task 8: run the review server as a third container loop, without letting it take down the generate loop

Status: closed 2026-08-27
Created: 2026-08-27

## Goal

The last build task of the epic. `container_run.sh` gains a third background loop beside the
existing merge loop, so the review page is reachable for the whole life of the container.

The constraint that shapes it: the generate loop is the container's FOREGROUND process
(`exec sh /app/gen_loop.sh`), and it is what keeps the container alive. [S-8] must not be
able to end it. A crashed or unstartable server -- a port already in use, an unwritable
token directory -- has to be a logged annoyance, not an outage that stops the GPU sweep
mid-episode and leaves a `.dubtitles.fail` poison marker behind.

Also closes the epic's verification story: `procoder test` green and `procoder check` with
zero blocking findings, over everything [S-1] through [S-8] added.

## On-disk / process state, verified before design (sprint 005 lesson)

- `container_run.sh` runs the merge loop as `( while :; ... ) &` and the generate loop as
  `exec sh /app/gen_loop.sh`. `exec` replaces the shell, so nothing after it runs and the
  generate loop IS the container's PID 1 payload.
- `Dockerfile.builder` already COPYs `review_server.py`, `review_apply.py` and
  `decisions.py`; `tests/test_dockerfile_copy.py` checks only what ENTRYPOINTS import, and
  `review_server.py` is not yet in that list. Adding it there is the RED step -- `qc.py`
  passed 987 tests and ImportError'd on container start for exactly this reason.

## Carried from the sprint 007 retro

For each guard, ask what input makes the GUARD PASS while the property it protects is FALSE,
not merely what mutation breaks the test. And when a test file states what it does not
cover, treat that sentence as a to-do rather than a boundary.

## Retro

What the sprint-007 adaptation bought, immediately: asking "what input makes this guard PASS
while the property is false" caught two of my own tests before they were committed. The
container_run assertion matched the whole file, so a mention of review_server.py in a
COMMENT would have satisfied it with nothing launching the server. Stripping comments before
matching is a one-line change that turns a decorative test into a real one.

The finding that matters: a mutation removing review_server.py from the Dockerfile COPY line
broke NOTHING. `test_every_module_an_entrypoint_imports_is_copied_into_the_image` walks what
each entrypoint imports and never asks whether the entrypoint itself is in the image -- so a
new entrypoint could be added, have every dependency satisfied, pass, and not exist in the
container. That is the qc.py failure the file was written to prevent, surviving inside the
file written to prevent it, for every entrypoint added since.

What we change next sprint: when a test enforces a rule over a LIST, check the list's own
membership as well as the property. This test asked "is everything X depends on present"
and never "is X present". The same shape is worth looking for wherever a test iterates a
registry -- ENTRYPOINTS here, REASONS and PRIMARY in unresolved.py, OFFERED in
review_server.py.

Also recorded, not fixed: `procoder test` reports `pass (0 test(s))`. Verified pre-existing
by stashing and re-running at HEAD. It is green because it found nothing, which is the
failure mode the security skill names for scanners -- "a check that silently didn't run is
worse than a red one" -- appearing in the test runner instead. The epic's verification story
rests on the direct pytest run and says so.

## Result

committed: 2
done: 2 (20260827-all-of-the-above-verified-by-procoder-test-green-and, 20260827-container-run-sh-starts-the-server-as-a-background-loop)
carried: 0
