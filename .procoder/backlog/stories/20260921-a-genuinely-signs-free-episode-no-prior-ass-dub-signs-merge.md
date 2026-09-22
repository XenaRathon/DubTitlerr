# A genuinely signs-free episode (no prior `.ass`, `dub_signs_merge.py` returns `"no-signs"`) mux proceeds normally under the identical forced-failure test harness — the two fixtures produce different mux outcomes.

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 011-fail-closed-stage-status-artifact-merge-pass-exit-capture

## Description

Scope S-8 of `.procoder/specs/v0-2-0-hardening.md`: A transient signs extract/build failure is made distinguishable from a genuinely signs-free episode: `mux.py` refuses to mux a dialogue-only replacement as though it were the combined track when `common.read_stages` says the `signs` stage failed AND the prior `.ass` sidecar had at least one sign event — it must not silently fall through `sub_source()`'s ASS-then-SRT fallback (`mux.py:403-409`) and stamp the demoted output as done.

Delivered by Task 8 of `.procoder/plans/v0-2-0-hardening.md` (sprint 011); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A genuinely signs-free episode (no prior `.ass`, `dub_signs_merge.py` returns `"no-signs"`) mux proceeds normally under the identical forced-failure test harness — the two fixtures produce different mux outcomes.

## Evidence

`python3 -m pytest tests/test_mux.py::test_genuinely_signs_free_episode_muxes_normally -v` -- PASSED. Under the identical harness, a signs stage outcome of "ok" (detail "no-signs", i.e. dub_signs_merge.py returned "no-signs") lets mux.process() proceed and return "muxed" -- a different outcome from the forced-failure fixtures above, proving the guard distinguishes the two.
