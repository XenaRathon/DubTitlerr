# Split a card at review time so a human's correction can fit

Status: closed
Created: 2026-08-29
Closed: 2026-09-02
Needs: `superpowers:brainstorming` before any code — this changes the shape of a durable
artifact and the timing-allocation question has no obvious right answer. (Done via a
`/grilling` session, one question at a time; see Evidence for the settled design.)

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

## A third case, found 2026-08-30 — and splitting does NOT fix it

The 18-episode re-run surfaced a third refused correction, and it fails on a DIFFERENT
dimension:

| ep     | card | dur    | fault      | before -> after    |
| ------ | ---- | ------ | ---------- | ------------------ |
| S31E18 | #177 | 3.16 s | `over_cps` | 19.32 -> 19.64 cps |

    ASR : Although I'm still in a state of disbelief over such we folk,
    YOU : Although I'm still in a state of disbelief over such wee folk.

One letter and a full stop. The card was ALREADY at 19.32 cps against a 17.0 ceiling, so
`fits_card`'s already-over branch refuses anything that worsens a dimension, and 62 chars in
3.16 s worsens it.

**Splitting cannot fix this one.** A proportional split leaves both halves at the same
cps as the original — total characters and total duration are unchanged, so the reading
speed is identical. Splitting only ever relieves `over_line_len` and `over_chars`. Fixing
`over_cps` requires extending the card's DURATION, which is the immutability wall (C1), not a
layout problem.

So the three blocked corrections are two different problems:

- **E08, E10** — `over_line_len`, one character over. Splitting fixes these.
- **E18** — `over_cps`, one character over on an already-too-fast card. Splitting does
  nothing; this needs either borrowed time or a relaxed bar for human verdicts.

The second is worth a decision of its own: the guard is refusing text that is objectively
MORE accurate ("wee folk" is right, "we folk" is not) because it adds one character to a card
that already broke the profile before the human touched it. Per the owner's stated bar --
"if I'm reviewing it myself I'm going to try to get it as perfect as my ears allow" -- a
human verdict arguably earns a bounded worsening allowance on a dimension that was already
failing. That is a policy question, not a layout one, and it is NOT proposed here.

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

- [x] A `correct` verdict whose text does not fit is SPLIT rather than refused, when a legal
      split exists — asserted on both live cases above.
- [x] No legal split exists -> the verdict is still refused and still recorded as
      `decision_unfittable`. Splitting must not become a way to ship an unreadable card.
- [x] Both halves independently pass `reflow.layout_faults` and clear `MIN_DUR`.
- [x] Card timing remains immutable for MACHINE repairs (C1 unchanged on that path).
- [x] `conf.json` and the shipped cue list stay consistent across a `repair.py` re-run and a
      `review_apply` rebuild — no drift between the two writers.
- [x] Existing `unresolved` entries survive the index shift, or are migrated. (Moot under the
      settled design: the split is derived at write time only and never touches `conf.json`,
      so no index ever shifts — see Evidence.)
- [x] The 2 `over_line_len` corrections (E08, E10) ship. E18 is out of scope for splitting --
      it is an `over_cps` refusal and needs the separate policy decision above.

## Evidence

**Design settled via `/grilling`, one question at a time (2026-09-02):**

1. Scope: splitting only fixes `over_line_len`/`over_chars`. `over_cps` (E18) stays
   explicitly out of scope and unsplittable.
2. Applies to human `correct`/`force` verdicts only; a machine repair proposal that needs a
   split is still refused outright by `accept_repair`'s own `fits_card` call.
3. Split point: automatic, best-ranked (sentence end > clause end > word boundary), applied
   immediately on save — no new reviewer interaction.
4. Split lives at srt/ass-write time only, never written into `conf.json` — a pure function
   of the human's stored correction text and the card's own immutable timing, so it
   re-derives byte-identically every time. One durable card, one index, forever.
5. Duration allocated by real word-timing when the correction has the same word count as
   the original ASR text (word[n1-1].end anchors the cut); proportional-by-character
   otherwise (no word data, count mismatch, or a word missing its own timing).
6. Standard `MIN_GAP` (0.083s) between the two halves, same as every other card boundary.

**New module `card_split.py`** (shared by `repair.py` and `review_apply.py` so the two
writers of the shipped srt cannot drift on what counts as a legal split — the same
guarantee `fits_card` itself already gave):

- `_candidates(text)` — ranked cut positions (sentence > clause > word boundary).
- `_duration_split(text1, text2, total_dur, words)` — word-aligned or proportional.
- `find_legal_split(text, start, end, words)` — the public entry point; tries candidates in
  rank order, returns the first whose two halves both clear `MIN_DUR` and pass
  `reflow.layout_faults`, or `None`.

**Wired at all three points a human correction is admitted:** `repair.py`'s main per-card
loop (`ruling in APPLYING`), `repair.apply_human_text` (the skipped-card rescue path), and
`review_apply.apply_episode`. All three try `card_split.find_legal_split` before refusing;
none change the machine (`accept_repair`) path. The srt-write loops in both files expand a
split card to two sequentially-numbered cues; `conf.json` is never written to by either
file (confirmed: no `json.dump` back to `conf_path` anywhere in `repair.py`).

**RED/GREEN, `tests/test_card_split.py` (new, 11 tests):** every test failed with
`AttributeError`/`ModuleNotFoundError` before the corresponding function existed
(`.venv/bin/python -m pytest tests/test_card_split.py -q`), including two cases where the
RED run caught a bug in the TEST's own independently-derived expected value (dividing by
the space-joined string length instead of the sum of the two pieces' lengths) rather than
the production code — fixed before re-running GREEN.

**RED/GREEN, integration (`tests/test_repair.py`, `tests/test_review_apply.py`):**
`test_a_correct_too_wide_for_one_line_but_splittable_ships_as_two_cues` (both files) failed
RED with the pre-existing behavior (raw ASR shipped, correction refused) before the
call-site wiring landed. Fixture verified directly against `reflow` before writing the
test: at 10.0s, "The captain ordered everyone to abandon ship at once. Nobody thought
twice about it." (84 chars) wraps to a 44-char second line — `over_line_len` only, no
`over_cps` — and the sentence-boundary split gives two individually legal single-line
halves, `MIN_GAP` confirmed exact between them (`46.333` → `46.416`).

**Scope-boundary regression:** `test_accept_repair_never_splits_a_machine_proposal` pins
the same fixture through the machine gate directly, asserting `False` — proves the refusal
is real, not an artifact of the fixture happening not to be splittable there.

**Deploy gap caught by an existing test:** `test_dockerfile_copy.py`'s
`test_every_module_an_entrypoint_imports_is_copied_into_the_image` failed after
`card_split.py` was created (imported by `repair.py`, not `COPY`'d into
`Dockerfile.builder`) — fixed by adding it to the `COPY` line.

**Full suite green** (`.venv/bin/python -m pytest -q`), **`ruff check .` clean.**

**Not literally replayed against E08/E10's original source text** — the todo's own prose
gives the human's corrected text but not the underlying original ASR text/words.json,
which weren't available to re-derive from. The synthetic fixture above reproduces the same
fault shape (one character over `MAX_LINE`, `over_line_len` only) and the mechanism is
verified against the real `reflow.wrap_balance`/`layout_faults`/`MIN_DUR`/`MIN_GAP`
functions, not mocks.

The measurements above were taken by throwaway scripts run inside the `dubtitle-review`
container against the live library; they were not kept. Re-derive rather than trust these
numbers, especially after a regeneration:

- the per-card faults come from `reflow.layout_faults(reflow.wrap_balance(text), dur)` over
  every `*.dubtitles.conf.json` under the show root;
- the split candidates come from cutting the human's text at each word boundary, allocating
  duration by character share, and keeping cuts where both halves clear `MIN_DUR` and have
  no `layout_faults` — ranked sentence end > clause end > mid-phrase.
