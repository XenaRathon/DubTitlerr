# Review page: user-selectable sorting options

Status: open
Created: 2026-08-28

## Description

The episode queue is sorted server-side and the reviewer cannot change it. Today's order is
`_triage_key` in `review_server.py`: stage (admitted before refused), then risk class (a word
added or dropped, a word swapped, punctuation only), then card start, then queue index. That
order was chosen from a measurement — 529 of 682 admitted repairs on the 2026-08-28 run
changed no word at all — and it is the right DEFAULT. It is not the only order a reviewer
wants.

Owner, 2026-08-28: "there should be user selectable sorting options." Deferred deliberately;
raised while the auto-hide and shared-lines work was in flight and explicitly marked
not-now.

Orders that have a reason to exist:

- **chronological** — read the episode start to finish, following the video. The one order
  that lets a reviewer scrub once and check many lines in a single pass.
- **risk first** (today's default) — spend attention where a mistake is still possible.
- **queue order** — what the run actually produced, for anyone debugging repair.py rather
  than reviewing content.
- **longest first** — a proxy for how much of a card the repair rewrote.

Done looks like: a control on the episode page that reorders WITHOUT a round trip, and
without touching `index`. The sort is presentation-only today and must stay that way — a
verdict posts the jsonl row number, so reordering can never change where a decision lands.
Worth checking whether the choice should persist in localStorage beside the token.

## Acceptance criteria

- [ ] The episode page offers at least chronological and risk-first, with risk-first the
      default (the measured 78%-punctuation argument for it is unchanged).
- [ ] Reordering does not re-request the page and does not renumber anything: a verdict
      saved after reordering lands on the same queue entry it would have before. Covered by
      a test that reorders, then asserts the posted index set is identical.
- [ ] The shared-lines page is considered too — most-repeated-first is its measured default,
      but risk-first is defensible there as well.
- [ ] `procoder check` 0 blocking, `lint --types` 0, suite green.

## Evidence

<!-- Filled at close time. -->
