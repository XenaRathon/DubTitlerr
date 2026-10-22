# subtitle-duration-fix

Status: roadmap, not started
Created: 2026-10-14

## Why

Some cards stay on screen far too long, or a sentence is dripped out one or two words at a time
over a long stretch. User saw several in One Pace Wano (S35E13 "Void", watched 2026-10-13 evening
per Plex history). Measured in the live Dubtitles track of that episode: a 4-word card ("I want to
be.") shown for 22.9 s at 17:46, "Meow!" for 10.6 s at 26:36, "My eyes are" for 6.9 s at 25:28,
and several 6+ s cards of 4 to 6 words ("mom what do you" 6.4 s at 15:32).

## Scope

- **[D-1]** Detector: flag cards whose duration is out of proportion to word count (cap by reading
  speed plus a floor, e.g. > max(3 s, words * 0.6 s) and > 6 s), and chains of 1 to 2 word cards
  that span a long time. Report per episode in the QC sidecar so it is visible without a rewrite.
- **[D-2]** Fixer: trim an over-long card's end to when the last word was actually spoken
  (word timestamps in `words.json`), and never past the next card's start. Where a long card hides
  a silence or music gap, split it or shorten it, never stretch neighbours.
- **[D-3]** Merge drip-fed fragments: join consecutive 1 to 2 word cards of one sentence into a
  single card when the gaps are short; otherwise leave them (real pauses are real).
- **[D-4]** Review view: list flagged cards in the web UI with a one-click "trim to speech", and
  tie it into the episode proofreading view (timing fix is already a roadmap item there).
- **[D-5]** Regression set: S35E13 cards above plus a Digimon episode, as fixtures with real times.

## Notes

- Look first at why the card is long: missing word timestamps, a Whisper segment end that includes
  music, or reflow extending a card to cover a gap. Fix the cause where it is cheap; trim otherwise.
- Related: `reflow.py` (card timing), `qc.py`, the "episode proofreading + timing fix" item.
- README roadmap line goes in the release docs pass (docs frozen until the release).
