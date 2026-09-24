# Programmatic `pysubs2.SSAEvent` fixtures covering a genuine off-position sign, a karaoke event, a credits event, and a plain dialogue event produce the expected true/false-positive classification in a test.

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

- [x] Programmatic `pysubs2.SSAEvent` fixtures covering a genuine off-position sign, a karaoke event, a credits event, and a plain dialogue event produce the expected true/false-positive classification in a test.

## Evidence

- `tests/test_sns_extract.py` (84 lines, added by `d604337`) builds every fixture in code via an `ev()` helper that constructs `pysubs2.SSAEvent(...)` directly — no `.ass` fixture files on disk.
- The four required classes are covered by name: `test_classify_event_keeps_positioned_sign` (off-position sign), `test_classify_event_keeps_karaoke`, `test_classify_event_keeps_credits_style`, `test_classify_event_drops_plain_dialogue` (the false positive → `drop`). Two further tests pin the geometry: `test_classify_event_an8_top_alignment_counted_position_only` and `test_off_default_position_true_for_move_near_top` / `..._false_for_an2_bottom_center` / `..._false_with_no_override_tags`.
- `test_extract_counts_a_mixed_track` asserts the end-to-end tally over one mixed track: `counts[("Main", "drop")] == 1`, `counts[("Default", "position_only")] == 1`, `counts[("Credits", "keep")] == 1`, and `len(kept.events) == 3`.
- `.venv/bin/python -m pytest tests/test_sns_extract.py -q` → all 9 tests pass, exit 0.
