# Punctuation Restoration -- Design

**Date:** 2026-08-20
**Status:** design, pending implementation
**Follows:** `2026-08-20-timing-and-repair-tightening-design.md` (v5, shipped)

## Problem

Measured on One Pace S30 (22 episodes, 9,424 cards):

- **27% of cards end without sentence-terminal punctuation**; 21% begin with a lowercase
  letter.
- The damage is CLUSTERED, not scattered: 565 runs of consecutive unpunctuated cards,
  **149 of them 5+ cards long, containing 1,812 cards (20% of the season)**. The longest
  runs are 30-35 cards.
- Only 21 of the 148 long runs start in the first two minutes (the OP song). **127 are
  mid-episode dialogue.**
- Confidence inside those runs is INDISTINGUISHABLE from punctuated text:
  `avg_logprob` -0.130 vs -0.138. Every confidence gate the pipeline owns -- `low_conf`,
  `has_low_prob_word`, the hallucination flags, `is_target` -- is structurally blind to it.

The consequence is not merely cosmetic. `reflow._split_sentences()` splits a span on
`SENT_END`. With no punctuation there is nothing to split on, so the span falls through
to `_split_overflow()`, which balances on character count -- and lands mid-phrase, across
speaker changes:

```
466.2  "They all died somewhere at see we have to go it's way too"
469.8  'dangerous so they ended up somewhere totally different huh'
475.3  "cool i say we jump in and see where we go i don't think so h"
```

## Root cause, and why it cannot be fixed at the Whisper layer

`generate.py` sets `condition_on_previous_text=False`. Whisper's punctuation and casing
are driven by preceding-text context; decoding each segment cold, a segment that begins
mid-sentence comes back as an uncapitalised, unpunctuated fragment.

Two independent reasons that flag stays False:

1. **The original one (pre-existing):** with True, a music-masked stretch of One Pace
   S19E16 collapsed into a single 139s segment and real dialogue was LOST.
2. **VRAM, measured 2026-08-20:** True OOMs on this box -- `CUDA failed with error out of
   memory`, in a fresh process, GPU idle at 121MiB, 1060/6GB/large-v3/beam 7. True grows
   the decoder prompt with previous text and there is no headroom. Fitting it would mean
   `beam_size=1` or `large-v3-turbo`, both of which cost accuracy elsewhere.

So the deterministic layer cannot settle this, and it escalates -- exactly the standing
ladder. The LLM layer is not a fallback here; it is strictly better equipped: the flag
would have given Whisper only PRECEDING context, while a restoration pass sees the whole
transcript in BOTH directions and knows what follows the boundary it is punctuating.

## Design

**Restoration happens in `generate.py`, on the WORD LIST, BEFORE `reflow()`.**

This is the load-bearing choice. Restoring punctuation in `repair.py` -- the obvious
home, since repair already edits card text -- would arrive after cards are split and
timed. The text would read better and the splits would still land mid-phrase. Splitting
must be DOWNSTREAM of the fix.

### R1. Deterministic detection (layer 1)

A segment is a restoration candidate when its text has no sentence-terminal punctuation.
Consecutive candidate segments form a RUN. Only runs are sent; a lone unpunctuated
segment between two punctuated ones is left alone (it is usually a real fragment).

`RESTORE_MIN_RUN` (default 2) -- a run shorter than this is not worth a call.

### R2. The unit is the RUN, not the card or the segment

Batch by the unit the decision belongs to, never by the stage. Restoring punctuation
requires seeing the whole continuous stretch -- knowing where one sentence ends depends
on what starts next. A run is that stretch.

Measured call volume: ~150 long runs per 22 episodes plus short ones, so roughly 30-60
calls per episode against 114 if batched per card. The LLM runs on 192.168.1.196, NOT the
1060, so these calls cost no VRAM and do not compete with Whisper.

### R3. The model may change ONLY punctuation and casing

The prompt asks for the same words back with sentence punctuation and capitalisation
restored. Nothing else.

### R4. The guard is mechanical, not fuzzy (layer 1 again, after layer 2)

`accept_restoration(orig, new)` accepts only if the token sequences are identical after
casefolding and stripping punctuation:

```
normalise(s) = [t.strip(PUNCT).casefold() for t in s.split() if t.strip(PUNCT)]
accept  <=>  normalise(new) == normalise(orig)
```

This is far stronger than repair's length-ratio band, and it is the property that makes
the whole design safe: a rejected restoration costs one run's punctuation; an accepted one
CANNOT have altered a word. No judgement, no drift, no reference-borrowing risk.

### R5. Mapping back onto timestamped words

Because R4 guarantees token-for-token correspondence, the restored tokens map 1:1 onto
the original word dicts in order. Only `word["text"]` changes; every timestamp is
untouched. `reflow()` then splits on the restored punctuation.

A mismatch in token COUNT is impossible past R4, so the mapping needs no fuzzy alignment.

### R6. Failure is always non-fatal

An unreachable model, a timeout, an empty answer or a rejected guard leaves the words
exactly as Whisper produced them. Restoration is an improvement pass; it must never cost
an episode. `common.llm_chat()` already returns `""` rather than raising.

### R7. QC

New counters: `restore_runs_seen`, `restore_runs_sent`, `restore_accepted`,
`restore_rejected_guard`, `restore_empty`, `restore_words_repunctuated`. Plus a bounded
sample of rejected runs as events, since a systematic rejection pattern is the signal that
the prompt is wrong.

## Environment

- `RESTORE_PUNCTUATION` (default `"1"`) -- master switch; `"0"` disables the pass entirely.
- `RESTORE_MIN_RUN` (default `"2"`).
- Backend/URL/model default to the `REPAIR_*` values, as `glossary_verify.py` already does.

## Testing

Pure-function tests, no model:

- `accept_restoration` accepts case+punctuation-only changes; rejects an added word, a
  dropped word, a substituted word, and a reordering.
- Curly apostrophes: `chr(0x2019)` vs `'` must normalise equal, so a model that
  "corrects" the quote style is not rejected for it.
- Run detection: a lone unpunctuated segment is not a run; N consecutive ones are.
- Mapping: restored tokens land on the right word dicts, timestamps unchanged.
- Failure paths: empty answer, transport failure and guard rejection all leave words
  untouched and the episode successful.
- End-to-end with a stub model: an unpunctuated run comes back punctuated, and
  `reflow()` then splits it at the restored sentence boundaries rather than on character
  balance.

## Out of scope

Re-splitting already-generated episodes (this affects new generations only; a rollout
needs a `PIPELINE_VERSION` bump); the split heuristic for spans that remain unpunctuated
after restoration (next item); max hang time (item after that).
