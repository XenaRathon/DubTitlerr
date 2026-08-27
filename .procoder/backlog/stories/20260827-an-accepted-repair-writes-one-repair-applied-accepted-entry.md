# An accepted repair writes one `repair_applied`/`accepted` entry to `<stem>.dubtitles.unresolved.jsonl` whose `original_text` equals the card's pre-repair text and whose `proposed_text` equals the text actually applied -- asserted on the FIELDS, not only on the count, which a pair of empty strings would satisfy. The entry count also equals the summary's `repaired` count for that episode.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 3. The reviewer cannot judge what they cannot see. `unresolved.py` already queues what the
pipeline could NOT settle; an accepted repair was settled -- by a gate that does not check meaning --
and so is never queued at all. Done means every admitted repair lands in the episode's queue
carrying the card's pre-repair text and the text actually applied.

Asserted on the FIELDS, not the count: two empty strings would satisfy a count-only test, and an
entry stripped of the evidence it escalated with cannot be reviewed, which is the whole point.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] An accepted repair writes one `repair_applied`/`accepted` entry to `<stem>.dubtitles.unresolved.jsonl` whose `original_text` equals the card's pre-repair text and whose `proposed_text` equals the text actually applied -- asserted on the FIELDS, not only on the count, which a pair of empty strings would satisfy. The entry count also equals the summary's `repaired` count for that episode.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
