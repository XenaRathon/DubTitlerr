# An episode held longer than `REVIEW_GATE_STALE_DAYS` is reported loudly and counted in the sweep summary, and is still NOT muxed -- the alert must not become a release.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 006-task-6-the-pre-mux-review-gate-and-its-stall-alert-a-listed

## Description

Task 6. The gate's real failure is not holding -- it is holding SILENTLY. Two weeks away and the library
falls behind with nothing said. Done means a stale hold is reported loudly and counted in the sweep
summary, and the episode is STILL held.

The alert must never become a release: auto-releasing unreviewed repairs is the failure this whole
epic exists to prevent.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] An episode held longer than `REVIEW_GATE_STALE_DAYS` is reported loudly and counted in the sweep summary, and is still NOT muxed -- the alert must not become a release.

## Evidence

- `test_a_stale_hold_is_reported_loudly_and_is_still_not_released`: a 30-day-old queue
  produces a STALLED line naming the age and the pending count, AND `process()` still
  returns "held-for-review". The second assertion is the story -- an alert that releases is
  worse than no alert, because it reads as supervision.
- `test_a_fresh_hold_is_silent` is the counterpart: a hold inside the window is normal
  operation, so the STALLED line means something when it appears.
- Written after the branch existed, so held by mutation rather than a red run: making the
  stale path return False (an "auto-release after N days") passes the logging half and fails
  the release assertion.
- The alert was UNFIRABLE as first written, and the review is what surfaced it. The clock is
  the queue file's mtime, and repair.py re-appended to that file on every merge sweep for
  exactly the episodes that were stuck -- so the age never exceeded one sweep interval. The
  re-queue suppression in repair.py is what makes the mtime stable enough for this alert to
  fire at all; the two are one fix.
- `test_the_sweep_summary_carries_the_held_count`: "held-for-review" is a distinct
  `process()` status, so main()'s existing counts dict carries the backlog with no new
  plumbing.
- Staleness approximation documented in `held_for_review`: entries carry no timestamp, so
  the mtime measures "time since the queue last changed", not "time since the oldest entry".
