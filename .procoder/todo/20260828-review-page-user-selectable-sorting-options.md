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

Implemented on branch `feat/review-sorting`.

- Episode pages retain the server's risk-first order by default and add client-side
  `chronological`, `queue order`, and `longest first` modes. Sorting moves existing DOM rows;
  it does not fetch, reload, or alter the JSONL-derived radio indexes.
- The episode invariant is tested by reordering the rendered rows and asserting the posted
  index set is unchanged. Row metadata carries the stable index, risk, start time, and length.
- Shared lines retain the measured **most-repeated-first** default because one decision then
  clears the most duplicate questions. They also offer **risk-first**; chronological is not
  meaningful across multiple episodes and was intentionally not added there.
- Sort selections persist in localStorage beside the existing token, using separate keys:
  `dubtitlerr_episode_sort` and `dubtitlerr_shared_sort`.
- TDD failing run: `FFF` — the three new tests failed because the sort controls/functions
  did not yet exist (`episode-sort` absent, `sortEpisode` absent, `shared-sort` absent).
- Passing focused run: `3 passed` for the episode/shared sorting tests.
- Required full suite: `python3 -m pytest tests/ -q --tb=short > /tmp/suite.txt 2>&1; echo $?`
  returned `0`; `/tmp/suite.txt` reached `[100%]` with no failures. Direct pytest is the
  authoritative result because procoder's test-stage report is unreliable in this repo.
- Final `procoder check`: `0 unformatted, 0 unchecked, 0 out of scope`; no code or lint
  blocker remains. One procedural blocker remains because no commit message exists for the
  required documentation acknowledgment, and this task was deliberately left uncommitted.
- This was presentation-only: no authenticated write route was changed, so
  `procoder:security` was not invoked.

Acceptance limitation: no item from the feature acceptance list remains unimplemented. No
commit or push was performed.
