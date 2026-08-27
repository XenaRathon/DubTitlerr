# [F-2] A changed proposal for the same original line does not leave two competing pending entries that must be settled separately

Status: open
Created: 2026-08-27
Epic: review-loop-followups
Sprint: 009-review-loop-follow-ups-from-the-pre-merge-round-honour-a

## Description

Luna finding 3's surviving tail, conceded in the rebuttal. `repair.py`'s re-queue suppression
keys on the `(original, proposed)` PAIR (`repair.py:631`, `repair.py:802`). That is correct
for the case it was built for -- an identical re-run appending duplicates every
`MERGE_INTERVAL` -- but it does not cover a proposal that CHANGES.

Change the model, the glossary, or the fansub reference between two runs and the same ASR
line yields proposal `Y` where it previously yielded `X`. `(orig, X)` is in the queue, so
`(orig, Y)` is appended alongside it. The reviewer now sees one card twice, with two
different proposed texts, and a verdict on either pair leaves the other pending -- which,
for a show listed in `REVIEW_GATE_SHOWS`, keeps the episode held.

The pair must stay the DECISION key: matching on `orig` alone would let a rejection of one
proposal suppress every future proposal for that line, including the one that fixes it
(`decisions.lookup`'s docstring). This is about the QUEUE's pending set, which is a different
question from the store's key.

## Acceptance criteria

- [ ] Two runs producing different proposals for the same original leave the reviewer ONE
      actionable pending item for that card, not two.
- [ ] The superseded proposal is not lost from the audit trail -- the queue is the record of
      what was proposed, and `unresolved.resolve`'s docstring is explicit that a rejection is
      itself durable information.
- [ ] A verdict on the surviving item settles the card: no `repair_applied` entry for that
      original remains pending, and a gated episode is released.
- [ ] The decision store's key is unchanged -- still the pair, never `orig` alone. Asserted,
      because the obvious fix here is to weaken it.
