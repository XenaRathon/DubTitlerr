# A queue entry orphaned by a version bump does not hold an episode -- the gate ignores pending entries whose original text matches no current conf.json row, so review history survives a re-transcription without becoming a permanent hold

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 007-task-7-the-review-server-plus-the-orphan-entry-fix-the

## Description

Surfaced by the sprint-006 adversarial review, decided by the owner 2026-08-27.

`<stem>.dubtitles.unresolved.jsonl` is not in `generate.SIDECAR_SUFFIXES`, so
`park_stale_sidecars` leaves it in place across a `TRANSCRIBE_VERSION`/`TEXT_VERSION` bump.
After a re-transcription the file still holds pending entries describing text that no longer
appears anywhere in the episode. With `[S-6]` active those orphans hold the episode
permanently: nothing will ever re-queue them, so nothing will ever resolve them, and the
STALLED alert is the only thing that ever mentions it.

Two options were put to the owner: park the queue with the other sidecars (clean slate per
version, review history lost), or keep it and have the gate ignore orphans. The owner chose
to KEEP the history -- it is the record of what a human has already judged, and it is the
input to the later `accept_repair` tightening.

Fails closed: when `conf.json` cannot be read the gate holds everything, because the
alternative is releasing unreviewed repairs, which is the failure the whole spec exists to
prevent. A sidecar present with no conf.json is an anomaly, and the STALLED alert is what
surfaces it.

## Acceptance criteria

- [x] A pending `repair_applied` entry whose `original_text` matches no row in the episode's
      current `conf.json` does not hold the episode.
- [x] A pending entry that DOES match a current row still holds it -- asserted in the same
      test, or the criterion above is satisfied by a gate that never holds anything.
- [x] With `conf.json` absent or unreadable, every pending entry still holds: the gate fails
      closed rather than releasing unreviewed repairs.
- [x] Matching uses the same normalisation as the decision store (`decisions.key`), so
      whitespace and case cannot orphan a live entry.

## Evidence

- `test_an_entry_orphaned_by_a_version_bump_does_not_hold_the_episode` -- an entry whose
  original_text matches no current conf.json row releases the episode; a second entry that
  DOES match still holds it, in the same test, so a gate that never held anything cannot
  pass.
- `test_matching_a_live_entry_ignores_case_and_whitespace` -- normalised through
  `decisions.key`, so a doubled space cannot orphan a live entry and release it silently.
- `test_an_unreadable_conf_json_holds_everything` -- fails CLOSED. Without conf.json an
  orphan cannot be told from a live entry, and the alternative to holding is releasing
  unreviewed repairs.
- Mutations caught: filter removed (1 test), raw string compare instead of decisions.key
  (1), failing open on an unreadable conf (6).
- Recorded in the spec's Edge cases with the owner's reasoning for keeping the history.
