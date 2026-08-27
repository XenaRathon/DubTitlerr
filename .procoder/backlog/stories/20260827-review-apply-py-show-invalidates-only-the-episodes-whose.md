# `review_apply.py --show` invalidates only the episodes whose text actually changes, leaving the rest of the show's stamps valid.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 005-task-5-review-apply-py-rebuild-an-episode-s-srt-from-conf

## Description

Task 5. A downstream user pulling a store for a show they already generated has valid stamps everywhere
and nothing to re-trigger; a sweep is the mechanism. Done means only the episodes whose text actually
changes lose their stamp, so the re-mux is targeted rather than a whole-show re-run.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `review_apply.py --show` invalidates only the episodes whose text actually changes, leaving the rest of the show's stamps valid.

## Evidence

- `test_a_show_sweep_invalidates_only_the_episodes_that_change` -- three episodes, one
  verdict, and only the matching episode loses its stamp. Throwing a stamp away costs a
  re-mux of a multi-GB file, so a sweep must not punish a whole show for one decision.
- `test_an_episode_no_decision_matches_is_left_completely_alone` asserts the unaffected
  episode also gains NO sidecar, which is what would silently re-open it.
- Two defects the review found here, both fixed and pinned:
  - the store was resolved ONCE from the first episode found, so a sweep spanning two shows
    checked every episode against one show's verdicts -- silently, since a wrong store
    yields `changed: 0`, which reads exactly like "nothing to fix". Now resolved per show
    and cached. `test_a_sweep_resolves_the_store_per_show_not_once`.
  - an unresolvable show produced the same "0 changed" output as a clean run, so a
    misconfigured `GLOSSARY_DIR` looked like success. Now warned by name.
    `test_a_show_that_cannot_be_resolved_is_reported_not_silently_empty`.
- A stale `.ass` is removed: `mux.sub_source` prefers it over the srt, so leaving it would
  re-mux the OLD text and drop the verdict. `test_a_stale_ass_is_removed...`; mutation on
  the removal fails it.
