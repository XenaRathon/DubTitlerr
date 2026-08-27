# With a show listed in `REVIEW_GATE_SHOWS`, `mux.py` skips an episode holding a pending `repair_applied` entry and muxes it once that entry is resolved; with the list empty, both episodes mux.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 006-task-6-the-pre-mux-review-gate-and-its-stall-alert-a-listed

## Description

Task 6. On a show where every card is unanchored, a regression that reaches the library is permanent, so
the owner may want review BEFORE mux rather than after. Done means a listed show holds an episode
while it has a pending entry and muxes once resolved, and an unlisted show behaves exactly as today.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] With a show listed in `REVIEW_GATE_SHOWS`, `mux.py` skips an episode holding a pending `repair_applied` entry and muxes it once that entry is resolved; with the list empty, both episodes mux.

## Evidence

- `pytest tests/test_mux.py` -> 45 passed, including
  `test_a_gated_show_holds_an_episode_with_a_pending_accepted_repair`, which carries its own
  controls: an UNLISTED show muxes exactly as today, and resolving the entry releases the
  episode. Without those halves a gate that never muxed anything would pass.
- `test_a_gate_holds_only_on_accepted_repairs_not_on_guard_rejections`: a REFUSED repair
  left the ASR text in place, which is the safe outcome; the ADMITTED repair is the
  unchecked change and the only thing worth stopping a release for.
- Gate placed AFTER the stamp check, against the plan's sketch: an episode that already
  shipped cannot be held, and reporting a hold for it would inflate the backlog with
  episodes no review can affect. That decision was pinned by NOTHING until a mutation moving
  the gate above the stamp check passed the whole suite; now
  `test_an_already_muxed_episode_reports_already_muxed_not_held`.
- The adversarial review found the gate could be re-armed forever. merge_pass.sh re-runs
  repair on every sweep while an srt exists, a held episode never loses its srt, and
  `dub_signs_merge.build()` returns "no-signs" BEFORE writing any .ass for a dialogue-only
  episode (dub_signs_merge.py:126-127) -- so repair appended a fresh `repair_applied` row
  every 600s. Fixed in repair.py with a one-read-per-episode pair set;
  `test_a_second_repair_pass_does_not_re_queue_a_line_already_in_the_queue`.
- The gate now treats a stored VERDICT as settling a line regardless of the queue's resolved
  flag: `unresolved.resolve()` and `decisions.record()` are independent write paths, and the
  verdict is what actually stops repair re-queueing.
  `test_a_queued_line_that_already_has_a_verdict_does_not_hold_the_episode`.
- Two silent misconfigurations now reported: a show that cannot be resolved at all, and a
  listed name that never matches anything (the display-name vs directory-basename trap that
  already cost one design bug in sprint 002). Both warn once, not per episode.
- Mutations caught: auto-release on stale, gate before the stamp check, holding on any
  pending entry, REVIEW_GATE_SHOWS ignored, re-queue suppression removed, verdict filter
  removed, unmatched-name warning removed.
