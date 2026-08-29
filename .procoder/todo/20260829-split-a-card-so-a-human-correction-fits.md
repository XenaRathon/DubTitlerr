# Split a card at review time so a human's correction can fit

Status: open
Created: 2026-08-29
Needs: `superpowers:brainstorming` before any code — this changes the shape of a durable
artifact and the timing-allocation question has no obvious right answer.

## Description

`fits_card` refuses a human's `correct`/`force` verdict whose text cannot be displayed on
the card it is repairing. Card timing is immutable (C1) — "a repair that does not fit the
card it is repairing is rejected, never accommodated by moving the card" (`repair.py:493`).
For a machine proposal that is right. For a human who has listened to the line, it means
their transcription is discarded because the card is one character too narrow.

Two live cases, both One Pace, both blocked as of 2026-08-29:

| ep     | card | dur   | your text                                                                             | fault                      |
| ------ | ---- | ----- | ------------------------------------------------------------------------------------- | -------------------------- |
| S31E08 | #137 | 5.98s | `Just wait till I get my hands on that Flame-Flame Fruit! With that power I can be`   | `over_line_len` (43 vs 42) |
| S31E10 | #132 | 5.18s | `It says their names are Luffy-Land, Zoro-Land, Nami-Land, Sanji-Land, Chopper-Land,` | `over_line_len` (46 vs 45) |

Neither is a reading-speed problem. Both are ONE character over `MAX_LINE`.

## Splitting works on both — measured, 2026-08-29

Splitting at a natural boundary, with duration allocated proportionally by character share:

    E08  [4.19s cps 13.4]  Just wait till I get my hands / on that Flame-Flame Fruit!   <- sentence end
         [1.79s cps 13.4]  With that power I can be

    E10  [2.91s cps 15.8]  It says their names are / Luffy-Land, Zoro-Land,             <- clause end
         [2.27s cps 15.8]  Nami-Land, Sanji-Land, Chopper-Land,

Every dimension legal: lines, longest line, total chars, cps, and both halves clear
`MIN_DUR` (0.83s). 11 legal split points for E08, 5 for E10.

## Library context (One Pace, 209,231 cards, 2026-08-29)

| fault                 | count  | share |
| --------------------- | ------ | ----- |
| `over_line_len` (>42) | 1,051  | 0.5%  |
| `over_chars` (>84)    | 5      | 0.0%  |
| `over_cps` (>17.0)    | 58,728 | 28.1% |

Over-length lines are RARE; over-cps is the common violation and A2 deliberately does not
retime for it. Note the inconsistency this exposes: E10's ASR card shipped at 45 chars, and
the guard then refused the human's 45 -> 46 edit on that same already-illegal line.

## This is NOT the split idea that died on 2026-08-21

That investigation was about VAD hang-trim `#---#` cards (see
`docs/superpowers/specs/2026-08-21-vad-hang-trim-design.md`). It was killed by measurement:
the hang gate fired on 30 of 5,296 cards, 13 of which had 2+ silence intervals, and of those
**0 were splittable by sentence** — there was no boundary to split at.

Different population, opposite finding. These cards are being split for TEXT LENGTH, not
silence, and they have clean boundaries. Do not let the earlier null result close this one.

Related existing machinery: `reflow._split_sentences()` already splits spans at sentence
boundaries, and `punctuation.py` exists precisely because 27% of cards arrived with no
terminal punctuation for it to split on (`common.py` v3 note). Sentence-splitting is core,
not new — what is new is doing it at REPAIR/REVIEW time, on text a human wrote.

## What blocks it

The layout logic is not the problem. The 1:1 coupling between `conf.json` rows and srt cues
is:

- `review_apply._write_srt` -> `zip(rows, texts)`
- `repair.process` -> `for i, c in enumerate(conf, 1)`
- `conf.json` is the durable card list, so a split means REWRITING it
- `unresolved` entries and the review page address cards by INDEX, so a split shifts every
  index after it

Already safe: `decisions` is keyed on the normalised `(orig, proposed)` text pair, never on
position — explicitly so verdicts survive a `TEXT_VERSION` bump. Verdicts survive a re-split
unchanged. That is the hard part already solved.

## Open questions for the brainstorm

1. **Where does the split live?** Rewriting `conf.json` makes it durable but shifts every
   downstream index. Splitting only at srt-write time keeps `conf.json` canonical but means
   the shipped cue list and the card list no longer correspond — and `review_apply` rebuilds
   the srt from `conf.json`, so the split would have to be re-derived identically every time
   or the two writers drift (the exact drift `review_apply` imports `fits_card` to avoid).
2. **How is duration allocated?** The human's text has no word timings. `words.json` has
   them for whisper's words; both live cases are near word-aligned (capitalisation plus one
   name), so real alignment is feasible there, but a free rewrite has nothing to align to.
   Proportional-by-character is the fallback and it is a guess, not a measurement. Is a
   guess acceptable here, given the owner's "different bars for machine and human review"?
3. **Does the gap between the halves matter?** Splitting creates a `MIN_GAP` (0.083s) that
   was previously mid-card. The 2026-08-21 work raised this as its Q8 and it was never
   answered because that idea died first.
4. **Who chooses the split point?** Automatic (rank sentence end > clause end > mid-phrase,
   as measured above), or shown to the reviewer for approval? The review page already has a
   write path; this would be a second kind of edit.
5. **Should this apply to machine repairs too, or only to human verdicts?** Only-human keeps
   C1 intact for the automated path, which is where it earns its keep.

## Acceptance criteria

- [ ] A `correct` verdict whose text does not fit is SPLIT rather than refused, when a legal
      split exists — asserted on both live cases above.
- [ ] No legal split exists -> the verdict is still refused and still recorded as
      `decision_unfittable`. Splitting must not become a way to ship an unreadable card.
- [ ] Both halves independently pass `reflow.layout_faults` and clear `MIN_DUR`.
- [ ] Card timing remains immutable for MACHINE repairs (C1 unchanged on that path).
- [ ] `conf.json` and the shipped cue list stay consistent across a `repair.py` re-run and a
      `review_apply` rebuild — no drift between the two writers.
- [ ] Existing `unresolved` entries survive the index shift, or are migrated.
- [ ] The 2 blocked One Pace corrections ship.

## Evidence

Pending.

Scripts used for the measurements above are in this session's scratchpad
(`why_refused.py`, `clause_split.py`, `overlen.py`) — re-derive rather than trust these
numbers if the library has been regenerated since.
