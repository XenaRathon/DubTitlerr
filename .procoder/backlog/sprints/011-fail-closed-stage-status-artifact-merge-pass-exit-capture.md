# Fail closed: stage status artifact, merge_pass exit capture, signs transient vs signs-free, MP4 stamp-before-remove

Status: closed 2026-09-22
Created: 2026-09-21

## Goal

Implement the fail-closed core: a per-episode stage-status sidecar that `repair.py`, `dub_signs_merge.py`, `mux.py`, and `merge_pass.sh` write, which `mux.py` and `review_server.py`'s new `/healthz` read. Capture `merge_pass.sh` exit codes immediately after each stage. Distinguish transient signs (prior `.ass` exists) from genuinely signs-free episodes (no prior `.ass`, `dub_signs_merge.py` returns `"no-signs"`). Reorder the MP4 path so the stamp lands before the original is removed. Delivers S-6 through S-9 of `.procoder/specs/v0-2-0-hardening.md`.

## Result

committed: 0
done: 0
carried: 0

## Retro

<!-- What slowed us down this sprint. -->

`procoder backlog close story` runs the full suite + gate per call and stalls under a
short shell timeout — a 60-300s cap looked like a hang and cost several wasted round
trips before switching to an unbounded (`timeout=0`) invocation, which completed in
under 4 minutes. A separate real bug (`merge_pass.sh`'s inline `python3 -c` snippets had
no `PYTHONPATH`, so `import common` silently failed inside the crash-record path) was
only caught by writing a fixture test, not by inspection — the failure mode is silent by
construction (`|| true`).

<!-- What we change next sprint because of it. -->

Always invoke `procoder backlog close story`/`procoder check` with no shell timeout (or
a generous one, 5+ minutes) from the first attempt; treat a hang under a short cap as
"still running," not "stuck." Batch multiple story IDs into one `close story` call to
pay the gate/suite overhead once instead of per story.

<!-- One adaptation from this sprint worth keeping. -->

Writing the stage-status protocol as pure functions in `common.py` first, then wiring
call sites into `repair.py`/`dub_signs_merge.py`/`mux.py`/`merge_pass.sh` one at a time
with a test per call site, caught the `signs-regression-refused` gap (mux.py had no
integration with `read_stages()` at all) before it shipped silently.

## Result

committed: 13
done: 13 (20260921-a-forced-llm-unreachable-path-in-repair-py-repair-py-853, 20260921-a-genuinely-signs-free-episode-no-prior-ass-dub-signs-merge, 20260921-an-mkv-source-orig-final-never-calls-os-remove-on-the, 20260921-common-failed-stage-stem-returns-none-when-every-recorded, 20260921-common-write-stage-stem-repair-ok-then-common-read-stages, 20260921-fixture-runs-of-repair-py-dub-signs-merge-py-and-mux-py, 20260921-for-an-mp4-m4v-source-with-a-monkeypatched-write-stamp-that, 20260921-given-a-prior-ass-sidecar-containing-at-least-one-non, 20260921-merge-pass-sh-captures-rc-immediately-after-each-of-the, 20260921-readme-md-states-the-original-mp4-m4v-container-is-deleted, 20260921-two-new-tests-pass-one-with-an-unwritable-stamp-path-one, 20260921-with-two-fixture-episodes-one-forced-to-a-failed-stage-the, 20260921-with-zero-failed-stages-the-script-prints-exactly-merge)
carried: 0
