# A false-positive inventory file exists under `docs/beta-feedback/`; `grep -rn sns_extract merge_pass.sh mux.py dub_signs_merge.py` returns no matches (not wired into the merge path).

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 014-measurement-timing-compare-t12-on-three-shows-queue-publish

## Description

Scope S-20 of `.procoder/specs/v0-2-0-hardening.md`: Build a read-only S&S (signs & songs) extract-only prototype, `tools/sns_extract.py`: standalone, imports `dub_signs_merge.keep_event` and adds a numeric heuristic `off_default_position(ev, play_res_y)`.

Delivered by Task 22 of `.procoder/plans/v0-2-0-hardening.md` (sprint 014); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A false-positive inventory file exists under `docs/beta-feedback/`; `grep -rn sns_extract merge_pass.sh mux.py dub_signs_merge.py` returns no matches (not wired into the merge path).

## Evidence

- The inventory file exists: `docs/beta-feedback/2026-09-23-sns-extract-fp-inventory.md` (1662 bytes, added by `6159227`).
- `grep -rn "sns_extract" merge_pass.sh mux.py dub_signs_merge.py` → no matches, exit 1. The prototype is not referenced from the merge path.
- Shipped in `6159227`.
- Honest scope note: the criterion is existence-only, and the file is still the template it was committed as — its body carries the instructions for the run (what to count and 2-3 example lines) and its `## Decision` section is still the `<standalone script vs. future pipeline stage -- …>` placeholder. Existence and non-wiring are both verifiably true; no false-positive run has actually been recorded in it yet.
