# Timing and Repair Tightening -- Design

**Date:** 2026-08-20
**Status:** v4 -- FINAL. Review closed after three adversarial rounds (Buffy/GPT-5.6 Luna).
Verdict: ship with conditions; the four conditions are folded in below.
Measurement corrections and one newly discovered live defect folded in.
**Supersedes nothing.** Extends `2026-08-19-glossary-name-acquisition-design.md`.

## Problem

The Punk Hazard verification run (One Pace S30, 22 episodes, 10,020 cards) completed
cleanly -- 22/22, zero failures, names correct in the muxed output -- and then
verification of the output found three defects the pipeline had no way to see.

1. **730 cards (7.3%) are below `MIN_DUR` (0.83s)**, 56 of them below 0.25s.
   The worst observed is `'Cool!'` at 0.02s -- 294 cps, roughly one frame.

   MEASUREMENT CORRECTION (v2): the first count was 1,140. A naive `duration <
MIN_DUR` test counts 410 cards that the current code deliberately set to exactly
   `start + MIN_DUR`, whose duration recomputes as 0.8299999999999998 from the
   3-decimal values stored in `conf.json`. Every comparison against a duration
   threshold in this pipeline MUST carry an epsilon (1e-6). The naive form
   overstated the defect by 56%.

2. **The QC data that would have caught this is computed and discarded.**
   `generate.py:320-323` calculates `over_cps`, `max_dur` and `violations` on every
   episode, logs them, and persists only four unrelated counters to `lastrun.json`.
3. **Three misspellings shipped to the library**: `Hazzard` (4x), `Kinamon` (2x),
   `Whitestrom` (2x). Nothing in the pipeline can propose a fix for them, because the
   only name-acquisition input is a fansub track and One Pace S29-S30 ships none.

4. **Line wrapping is destroyed on every episode that passes through repair** (found
   in v2 review, verified against muxed output). `reflow._wrap()` produces correct
   two-line cards; `generate.py` writes a correctly wrapped srt; then
   `generate.py:303` flattens `\n` to a space when building `conf.json`, and
   `repair.py:388-390` rewrites the srt from those conf rows without ever re-wrapping.
   Measured on shipped, muxed Dubtitles tracks:

   | show            | cues  | multi-line | line > 42 chars |
   | --------------- | ----- | ---------- | --------------- |
   | One Pace S30E01 | 520   | **0**      | 165 (32%)       |
   | Chainsaw Man    | 1,123 | **0**      | 298 (27%)       |
   | BEASTARS        | 411   | **0**      | 101 (25%)       |

   Zero multi-line cues exist anywhere in the library. This is a larger and more
   visible defect than the runt cards, and it is invisible to the current QC because
   `generate.py`'s violation counter runs on `rows` (correctly wrapped) rather than on
   what repair actually ships.

### Root cause of (1)

`reflow.py:153-171`, `time_cards()`:

```python
target = max(natural_end, start + MIN_DUR, start + chars / MAX_CPS)
cap = start + MAX_DUR
if j + 1 < n:
    cap = min(cap, groups[j + 1][0]["start"] - MIN_GAP)
end = min(target, cap)
if end <= start:
    end = start + MIN_GAP
```

`MIN_DUR` and `MAX_CPS` enter as floors inside `target`, and are then silently
overridden by `cap`. When the next card starts almost immediately, the degenerate
branch "rescues" the card to `MIN_GAP` -- two frames -- and reports success. The
median gap from a runt to its successor is 0.083s, exactly `MIN_GAP`, confirming
these cards were squeezed against their neighbour rather than genuinely brief.

93% of runts end in sentence punctuation. They are sentence _tails_ -- the last word
or two of a sentence, followed immediately by a new one.

### Root cause of (2)

`generate.py:322`'s `bad` counter checks `dur > 7.001`, line count, and line length.
It validates every **ceiling** and no **floor**. A 0.02s card was never a violation
by definition, so 465 episodes passed QC while carrying the defect.

### Root cause of (3)

`mine_glossary.py:58-65` deliberately excludes our own dubtitle track from mining, so
a regeneration cannot reinforce its own errors into the glossary. Correct -- but it
means a release with no embedded fansub track mines nothing at all, and the
transcript, the only text that exists for those episodes, is never examined.

## Design

Three independent changes, shipped together, each validated against the completed
Punk Hazard run.

---

### A. Runt cards: merge backward, else steal forward

**A1. Backward merge (primary).** Before `time_cards()` runs, at the **group** level,
a group whose spoken span is below `MIN_DUR` merges into its predecessor when all of:

- gap to predecessor <= `GAP_MAX` (0.5s)
- combined text <= `MAX_CHARS` (84)
- merged span <= `MAX_DUR` (7.0s)
- merged text / merged span <= `MAX_CPS` (17.0)

**Preference, not a gate:** prefer not to merge when the predecessor already ends in
sentence-terminal punctuation, so a card does not carry two complete sentences. This
preference is skipped rather than honoured when honouring it would push the pair into
the steal path unnecessarily; it never overrides the cps constraint.

Merging happens at group level, before timings are derived, so no timing is ever
hand-patched -- `time_cards()` re-derives from the merged group.

**A2. Forward steal (fallback).** A card still below `MIN_DUR` extends to exactly
`MIN_DUR`. The following card's start moves later by the same delta. That card absorbs
the shift in this order:

1. **surplus duration** above its own `MIN_DUR` -- it simply becomes shorter, its end
   does not move, and the cascade terminates
2. **the gap** to the card after it
3. whatever remains propagates to the next card, recursively

No cap on cascade depth. No card ever moves _earlier_: a caption arriving slightly
late is preferable to one arriving early, which can spoil.

**A2a (v3) -- the shift is not the extension delta.** A2 originally said the successor
moves later "by the same delta". That is wrong, and its precondition already occurs in
production: `time_cards()`'s degenerate branch sets `end = start + MIN_GAP` without
consulting the successor, so a card can already END AFTER its successor STARTS.
Measured on shipped Punk Hazard output: **9 overlapping adjacent pairs** in 22
episodes -- e.g. `'Huh.'` overlapping `"Let's be honest."` by exactly -0.083s.

Feeding that state into a same-delta shift reproduces the overlap. The shift must
absorb any pre-existing deficit as well:

```python
required_shift = (card.start + MIN_DUR) + MIN_GAP - successor.start
```

**v5 CORRECTION -- this was `max(extension_delta, deficit, 0.0)` and that is WRONG.**
Found during implementation, verified against the `'Huh.'` pair: extension_delta 0.747,
pre-existing deficit 0.116, `max()` yields 0.747, the successor lands at 0.797 while the
card now ends at 0.830 -- **gap -0.033, still overlapping**, failing the very invariant
the rule exists to establish.

The two quantities are shortfalls measured from DIFFERENT reference points: the
extension is measured from the card's start, the deficit from its OLD end. Taking the
larger satisfies one and abandons the other. They compose ADDITIVELY, and the sum
telescopes to the single expression above -- which is also correct when the deficit is
negative, so it needs no `max(..., 0)` guard.

`preexisting_gap_deficit` is still recorded separately in the QC event so the two
causes stay distinguishable.

This formula was introduced in v3 to fix the same-delta rule the round-2 review
correctly rejected, and then survived round 3 unchallenged. A rule shaped like a safety
maximum reads as conservative; it was caught only by running the fixture through the
asserted invariant.

The cascade consumes `required_shift`, not `extension_delta`. The QC event records
both plus `preexisting_gap_deficit`, so the two causes stay distinguishable.

Incidental benefit: this repairs the 9 existing overlaps, which no current check
detects (`generate.py`'s violation counter has no gap term).

**A2b (v3) -- feasibility at the end of the audio.** A cascade can delay a card that
was never a runt. If its end is held while its start moves, `start >= end` becomes
reachable, violating A5. A6's clamp only covered the last card when the last card was
itself a runt. Rule: no card's start may move to or past `audio_duration`; if the
required displacement would do so, the cascade is marked unfixable, the episode records
`cascade_infeasible` with its reason, and no zero- or negative-duration card is emitted.
"No cascade cap" and "every card stays valid inside the audio" cannot both hold for
arbitrary input; this is the explicit exception.

**v4 -- the output contract, which v3 left undefined.** Detecting the impossible
transition is not enough: stopping the cascade early can leave a runt, a sub-`MIN_GAP`
gap, a downstream overlap, or an unapplied displacement, and A5 has no exception for
any of those. The policy is **strict**:

> If A2b cannot produce a card list satisfying the A5 temporal invariants, the episode
> is structurally unfixable. No srt/ass is written and nothing is muxed. The episode
> gets a `.dubtitles.fail` marker -- the existing poison-file mechanism, so
> `gen_loop.sh` moves on instead of retrying forever -- and the `qc.json` sidecar IS
> still written.

Emitting a known-invalid subtitle and calling it "observable" is worse than stalling
one episode. The failure records `requested_shift`, `applied_shift`, `residual_shift`,
`failure_reason` and `affected_card_range`, with
`requested_shift == applied_shift + residual_shift` within EPS.

Measured frequency of the precondition on this corpus: 0. If it proves common on
another show, that is a signal to revisit A3, not to relax the contract.

**A3. Trigger scope: `MIN_DUR` only.** `MAX_CPS` does not trigger a steal. Extending
the same mechanism to cps was measured and rejected -- see Rejected Alternatives.

**A4. Determinism (v2).** `merge_runts()` is specified as a single left-to-right pass
to a fixed point, not an unordered rewrite. Two implementations must produce identical
group boundaries. Explicitly:

- the scan is left-to-right; a runt merges into its immediate predecessor only
- a predecessor that has already absorbed a runt in this pass is a legal target for
  the next one, subject to the same four constraints re-evaluated on the merged form
- a merged card that is _still_ below `MIN_DUR` (both parts were short) is not a
  failure -- it falls through to A2 like any other short card
- every merge records a `merge_reason`; every steal records `stolen_from` and the
  cascade id

**A5. Invariants (v2).** Asserted over the whole card list, not per case:

```
start < end                                     for every card
start >= original_onset                         (no card ever moves earlier)
start[i+1] - end[i] >= MIN_GAP - EPS            for every adjacent pair
duration >= MIN_DUR - EPS                       unless flagged unfixable_runt
duration <= MAX_DUR + EPS                       for every card
flatten(groups_out) == flatten(groups_in)       word-for-word, in order
merge_runts(merge_runts(x)) == merge_runts(x)   idempotent

if natural_end <= audio_duration + EPS:         # v3: conditional, see below
    end >= natural_end
else:
    end == audio_duration
    source_timestamp_overrun == True
```

**v3 correction:** `end >= natural_end` and `end <= audio_duration` are jointly
unsatisfiable when Whisper's final word timestamp overruns the measured audio duration
-- reachable through timestamp drift even though it was not observed on this corpus.
The invariant is conditional, and the overrun is recorded rather than silently clamped.

**EPS policy (v3).** One comparison policy everywhere: `< X - EPS` / `> X + EPS`, with
EPS = 1e-6. Metrics are computed from full-precision internal values and rounded ONLY
at JSON serialisation, so quantiles and event classification cannot disagree with the
decision path. This is the discipline whose absence inflated the v1 runt count by 56%.

**A6. End-of-episode clamp (v2).** A runt that is the last card of an episode extends
freely today. It is clamped to the audio duration; if the clamp leaves it short it is
recorded as an unfixable runt rather than silently extended past the end of the file.
Measured frequency on Punk Hazard: 0 occurrences. Cheap insurance, not a live bug.

**Measured on Punk Hazard (10,020 cards, 730 genuine runts, epsilon-corrected):**

| outcome                       | count     |
| ----------------------------- | --------- |
| fixed by backward merge       | 313 (43%) |
| fixed by forward steal        | 395 (54%) |
| last-card extended freely     | 0         |
| **remaining below `MIN_DUR`** | **0**     |

Cascade behaviour with surplus absorption: 80% terminate in one hop, p90 two hops,
max seven. 489 cards (5.0%) end up displaced later at all; median 0.27s, p90 0.67s,
p99 1.01s, max 1.36s, and only 5 cards across 22 episodes exceed 1.0s. 383 cards are
shortened by a neighbour without being displaced themselves.

The measured maximum displacement is a property of this corpus, NOT a bound on the
algorithm. A pathological episode -- continuous dense dialogue with no gaps and no
surplus anywhere -- can propagate a steal to the end of the episode. A6's clamp is the
only hard stop. This is accepted knowingly; the QC sidecar records cascade depth so a
pathological episode is visible rather than silent.

---

### B. QC persistence

**B1.** Every episode writes `<stem>.dubtitles.qc.json` alongside `conf.json`.
`mux.py:339-341` removes only `ASS_SUFFIX` and `SRT_SUFFIX` on success, so like
`conf.json` this sidecar survives muxing and remains available for library-wide
aggregation.

**Revised in v2:** counters alone cannot decide the deferred thresholds. A count says
a number moved; a threshold decision needs the distribution. The schema therefore
carries quantiles over the whole population and an event list over changed cards only.

```json
{
  "schema_version": 1,
  "show": "...", "episode": "...", "stem": "...",
  "pipeline_version": "...", "glossary_sha": "...",
  "profile": {"min_dur": 0.83, "max_dur": 7.0, "max_cps": 17.0,
              "min_gap": 0.083, "max_line": 42, "max_chars": 84},
  "counters": {
    "cards_before": 0, "cards_after": 0,
    "under_min_dur_before": 0, "under_min_dur_after": 0,
    "over_cps": 0, "over_line_len": 0, "violations": 0,
    "merged_backward": 0, "stolen": 0, "shortened_by_neighbour": 0,
    "displaced": 0, "unfixable_runts": 0, "flagged": 0, "low_conf": 0
  },
  "quantiles": {
    "cps":                 {"p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0},
    "required_extension":  {"p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0},
    "displacement":        {"p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0},
    "cascade_depth":       {"p50": 0, "p90": 0, "max": 0}
  },
  "event_count_total": 0, "events_retained": 0, "events_truncated": false,
  "events": [
    {"card_id": "...", "source_group_ids": ["..."], "cascade_id": "...",
     "effects": ["shortened", "displaced"],
     "delta_start": 0.0, "delta_end": 0.0,
     "required_shift": 0.0, "extension_delta": 0.0,
     "preexisting_gap_deficit": 0.0,
     "dur_before": 0.0, "dur_after": 0.0,
     "cps_before": 0.0, "cps_after": 0.0}
  ]
}
```

`required_extension` is `chars / MAX_CPS - duration` per card -- the quantity the
deferred cps-stealing decision needs and that a bare `over_cps` count cannot supply.
Every counter counts CARDS unless its name ends in `_seconds`.

`shortened_by_neighbour` and `displaced` stay separate: a card that lost duration is a
different event from one that started later.

**v3 corrections to the event list:**

- `effects` is a LIST, not an enum. A card can be shortened AND displaced by the same
  cascade; a single `cause` field cannot represent that while the counters treat them
  as distinct.
- Identity is `card_id` plus `source_group_ids`, never a positional index. Merging and
  filtering make an index unstable across passes.
- ONE final event per output card plus one cascade summary -- not one event per time a
  card is touched. Without that rule the list is O(cards x runts), not O(cards): a
  single suffix can be re-shifted once per upstream runt.
- The list is bounded. `event_count_total`, `events_retained` and `events_truncated`
  make truncation explicit, and the QUANTILES REMAIN COMPLETE even when detail is
  capped -- the quantiles are what the deferred threshold decisions consume.

**v4 -- reconciliation across a partial cascade.** The composition that must be tested
is `merge -> source-group union -> steal -> infeasible cascade -> final event summary`.
Two invariants:

```
sum(final event effects + cascade summaries) == every observable timing mutation
quarantined orphan groups never appear inside an ordinary merge-fixed event
```

The second matters because a merged output card carries several `source_group_ids`; an
orphan correctly excluded from A1 could still be counted indirectly inside a merged
card's event without it.

**v4 -- orphan counters are separate, and the integration check must use them.** The
acceptance assertion `under_min_dur == 0` contradicts a quarantined orphan that stays
short. Split it:

```
ordinary_under_min_dur_after   -> must be 0
orphan_under_min_dur_after     -> may be > 0; muxing it is an explicit decision
orphan_candidates              -> reported
orphan_candidates_fixed        -> must be 0 (quarantine is not a fix)
```

A single aggregate counter would erase exactly the distinction the prerequisite exists
to preserve.

**B4 (v2).** A missing sidecar must be distinguishable from a clean episode. QC write
failures are still swallowed so they cannot fail an episode, but the failure is
recorded in the episode's log line AND the aggregate reporter counts missing sidecars
explicitly. "No file" must never aggregate as "zero violations".

`shortened_by_neighbour` and `displaced` are **separate** counters. A card that lost
duration to a neighbour is a different event from one that merely started later, and
conflating them hides whichever is the real problem.

**B2.** `generate.py:322`'s `bad` counter gains the `MIN_DUR` floor. This is the check
that was supposed to catch the defect and structurally could not.

**B3.** No failure gate in this increment. A gate needs a defensible threshold, and
discovering what normal looks like is the first thing this metric is for.

---

### C. Repair constrained by timing, never the reverse

**C1.** `repair.py` continues to treat card timings as immutable. It reads
`c["start"]`/`c["end"]` only in `overlap_ref()` and rewrites the srt with those
timestamps unchanged (`repair.py:390`).

**C2.** `accept_repair()` gains the card's duration in its signature and rejects any
repair whose result would exceed `MAX_CPS` or `MAX_CHARS` for the duration the card
already has.

**C3 (v2) -- restore line wrapping.** This is the fix for Problem 4 and it is the
highest-visibility item in the increment. `repair.py`'s srt rewrite passes
`conf.json`'s flattened single-line text straight through. It must re-wrap through the
same `reflow` wrapping function `generate.py` used, so the shipped srt is wrapped
whether or not repair changed anything. `recreate_srt.py` needs the same treatment for
the same reason.

**C4 (v2).** `accept_repair()`'s validation is per-line, not just total: at most
`MAX_LINES` (2) lines, each at most `MAX_LINE` (42) characters, after re-wrapping,
using the same normalisation generation used. A total-only check passes text that is
visually invalid -- which is exactly how Problem 4 survived.

**C5 (v2).** The secondary-model output (`_needs_secondary_check` path) goes through
the same acceptance validation as the first pass. Today it does not.

**C5 confirmed during implementation, and worse than stated:** the secondary output did
not bypass _part_ of the gate, it bypassed `accept_repair` ENTIRELY -- no length band,
no reference-borrow guard, no profile check. `new2` was written over an already-accepted
first-pass repair after only `glossary.correct()`. Since `_needs_secondary_check` fires
on ~every name-changing repair by design, that was the COMMON path, not a rare one. Now
gated identically; on failure the validated first-pass repair stands.

**C2a (v5) -- the profile gate is NON-WORSENING, not absolute.** As written, C2 rejects
any repair leaving the card over `MAX_CPS`. But ~28% of cards are already over cps and
A3 deliberately declines to retime for it, so an absolute gate refuses to fix a misheard
name on any dense line -- precisely the case repair exists to serve, and a direct
contradiction of C2's own "keep it permissive" clause.

Rule: a card that is currently VALID must stay valid -- a repair may not push it over
any limit. A card that is ALREADY invalid accepts a repair that worsens no dimension
(line count, longest line, visible chars, cps) and rejects one that worsens any.

**C4a (v5) -- one profile definition.** `repair.fits_card` and
`generate._layout_faults` were separate implementations of the same rules: the "two
algorithms that can disagree" hazard C7 warns about, reintroduced in the module that
consumes C7's output. Both now delegate to `reflow.layout_faults(text, dur)`, with
`reflow.layout_metrics(text, dur)` supplying the comparable dimensions C2a needs.

**C6 (v3) -- source timing vs display timing. BLOCKER for shipping A before C.**

A2 moves a card's display start later. `overlap_ref()` then selects the fansub
reference by that MOVED window. The dangerous case is not a missed reference (repair
simply skips); it is a card displaced far enough to overlap only its NEIGHBOUR's cue
and use it as the evidence justifying a repair. `accept_repair()`'s borrow and length
guards do not establish that the reference describes the card's audio -- a plausible
ordinary-word or punctuation repair from the wrong neighbouring subtitle passes every
gate. Displacement p99 of 1.01s is not reassurance when a rapid-dialogue cue lasts
300ms; the relevant ratio is displacement against reference-cue spacing, not
displacement alone.

`conf.json` therefore carries both:

```json
{"source_start": 120.41, "source_end": 121.02,   // audio evidence window
 "start": 121.29,        "end": 121.90}          // final display timing after A
```

`overlap_ref()` uses the SOURCE window. A merged card carries the union of its source
groups' windows. Display timing may be late without changing what evidence justified a
repair.

This is also the ladder in force: the deterministic timing layer must not silently
alter the evidence handed to the LLM layer.

**C7 (v3) -- the layout question, resolved.**

The open v2 question was whether corrected text needs the full treatment (correct
BEFORE group sizing and timing) or a post-glossary re-wrap-and-validate pass. The
architecturally clean answer is the former; the measurement says it is not worth its
cost yet:

- 61 `hard_fixes`; 34 are length-neutral, 18 shorten, and only 9 lengthen at all.
- The largest lengthening entry in the entire glossary is `shojo -> Shoujou`, **+2
  characters**.
- Applying `glossary.correct()` across the 10,020-card corpus changes 101 cards and
  **zero of them change length**.

So: **a deterministic post-glossary re-wrap and validate pass**, run inside generation
before `conf.json` is written. It re-wraps the corrected text through the same
`reflow` wrapping function and validates the full profile. When a corrected card cannot
be wrapped within `MAX_LINES` x `MAX_LINE`, it records an `over_line_len` violation in
`qc.json` and keeps the correction -- the right name beats the layout profile. **No
splitter is built**, because a splitter needs retiming and a second layout algorithm is
two chances to disagree.

**v4 CORRECTION -- growth is the wrong trigger.** Capping growth does not bound layout
risk, because wrapping depends on where word boundaries fall, not on total length. A
length-NEUTRAL replacement can redistribute characters so no legal break satisfies both
lines: an 84-character card whose word boundaries land at cumulative 20 / 40 / 60 has
no split with both halves <= 42, and `_wrap()` falls through to its over-long fallback.
A shortening replacement can do the same by changing which split wins. And +2
characters on a 0.83s card adds ~2.4 cps, enough to cross the 17 cps ceiling by itself.

The trigger is therefore the measured outcome, not a proxy for it:

```
revisit the full compiler when:  post_glossary_layout_invalid   (measured by C7)
NOT when:                        canonical growth > 2
```

C7 always validates the actual corrected card and records `layout_valid`,
`line_count`, `max_line_length`, `visible_chars`, `cps` and `layout_exception_reason`
-- including `over_cps`, not only `over_line_len`.

The +2 cap is RETAINED but demoted to what it actually is: a candidate-admission
throttle on D auto-applies, guarding against large wiki expansions like the rejected
`Zunesha -> "Zou Elephant (Zunisha)"` (+16). It is not a safety proof.

**A D-acquired term that creates a layout exception SHOULD not auto-apply -- and as
shipped, it does. NOT IMPLEMENTED; corrected here rather than left as a false claim.**

The intent stands: a term that breaks the layout profile ought to reach a human, because
otherwise the deterministic glossary layer silently overrides the deterministic layout
layer with no human in the loop -- a ladder violation, and the one place this increment
can introduce a defect invisibly.

What the code actually does: `glossary_acquire.source_gate()` enforces only the +2
`GROWTH_MAX` length cap. There is no layout check at admission -- the single mention of
layout in that module is the comment noting the growth cap "is NOT a layout-safety
proof". So a length-neutral or shortening auto-apply that redistributes word boundaries
still applies. C7's re-validate pass DETECTS it at generation time and emits a priority
`layout_exception` event with `caused_by_correction=True`, and the correction is KEPT
(the right name beats the layout profile). A human learns of it only by reading
`qc.json`.

Detected and recorded, then, but not prevented. **ROADMAP:** implement the admission
check. It is genuinely implementable -- `glossary_acquire` already reads `conf.json`
rows carrying `start`/`end`/`text`, so a candidate replacement can be applied to the
cards containing the variant and run through `reflow.layout_faults` before admission.
Risk while deferred is low (transcript auto-applies are near-misses of settled terms,
overwhelmingly single-token respellings) but it is LOW-VISIBILITY rather than
low-severity: the remedy is named in the spec and skipped in the code.

This closes a real hole: `LEN_RATIO_MAX` is 1.5, so a repair may grow a line by 50%
while nothing re-checks readability. A 40-char card at 3.0s (13 cps) rewritten to 58
chars becomes 19.3 cps, and today nothing notices.

**Why not retime after repair:** it would move card boundaries, which moves the
windows `overlap_ref()` used to select reference lines -- so the anchors justifying
each repair would no longer describe the cards they were applied to. It would also
place the timing pass downstream of a non-deterministic step, forfeiting `reflow.py`'s
current property of being fully deterministic and unit-testable without a model.

---

### D. Transcript-sourced name acquisition

**D1 -- v5 CORRECTION. There is no "new" source; there never was another one.**
`glossary_acquire._iter_episode_texts()` has ALWAYS read `.dubtitles.conf.json` and
`.eng.dubtitles.srt` -- both our own output. It has never had a fansub input.

v4 conflated two modules. The fansub lane is real but lives in `mine_glossary.py`,
whose `eng_sub_text()` reads embedded fansub tracks and explicitly excludes our own
dubtitle track. So the source asymmetry below is not two lanes inside one module; it is
the boundary BETWEEN the two:

| module                | source                                 | writes                  |
| --------------------- | -------------------------------------- | ----------------------- |
| `mine_glossary.py`    | embedded fansub track (human-authored) | auto-appends to `names` |
| `glossary_acquire.py` | our own transcript (Whisper guessing)  | wiki-adjudicated        |

What D1 actually contributes is the provenance model and the apply rule, not a new
input. The self-reinforcement objection still does not apply, for the reason v4 gave: a
candidate is never trusted, it is adjudicated against the wiki, and the wiki breaks the
loop.

**What this actually means in practice -- measured, not reasoned.** Because every
`glossary_acquire` candidate is transcript-sourced, D3's rule means only near-misses of
already-settled terms auto-apply there. The obvious worry is a show with no anchors, and
it does not occur in this library:

```
glossaries: 15   with anchors: 15   empty: 0
  One Pace 144 | JUJUTSU KAISEN 41 | My Hero Academia 32 | SPY x FAMILY 22
  ... smallest still 10 (Darker Than Black, MHA Vigilantes, Vending Machine)
```

`mine_glossary.py` mines an embedded fansub track on essentially every title, so anchors
are everywhere and the near-miss lane has something to anchor to. The three layers
compose as intended:

| layer              | fills                                            | gate                            |
| ------------------ | ------------------------------------------------ | ------------------------------- |
| `mine_glossary`    | bulk of `names`, from fansub tracks              | count floor, auto-append        |
| `glossary_verify`  | canonical dub-preferred spellings, from the wiki | cached, incremental             |
| `glossary_acquire` | the residue no fansub covers                     | wiki-adjudicated, D3 apply rule |

So the human gate bites only on a genuinely NEW term -- a name no fansub anywhere in the
show ever wrote, e.g. One Pace S29-S30's `Shirahoshi` and `Van Der Decken`, the case that
motivated this feature. Those went from UNACQUIRABLE to acquirable-with-a-human-glance,
which is the ladder working, not a restriction on it. The self-reinforcement objection that
justifies `mine_glossary.py`'s exclusion does not apply, because a candidate from this
source is never trusted -- it is adjudicated against the wiki. The wiki breaks the loop.

**D2. Signal.** Out-of-dictionary tokens, not flagged-card text.

Flagged text was measured and rejected: 36.8% of all cards carry a flag (3,207
`maybe_silence`, 483 `low_conf`), 3,025 distinct texts, and the top recurring entries
are the opening theme lyrics -- "raise up the flag that you believe in" 35 times,
"jump to the sky never give up our wishes" 21 times. A detector on that signal
escalates the OP song 22 episodes running.

The filter chain is the existing one: `mine_text()`'s mid-sentence + capitalisation
rule, the `COMMON` deny-list, the English-dictionary gate, and exclusion of already-
settled terms. It reduces 350 raw candidates to 74.

**D3. Source asymmetry.** Every candidate the acquisition module has seen so far came
from a fansub track -- text written by a human who knew the show. A transcript
candidate came from Whisper guessing at audio. A wiki title match therefore means
something different: for a fansub token it confirms a spelling; for a transcript token
it may confirm the wiki's word while the audio said something else.

Accordingly, a transcript-sourced candidate auto-applies **only** when it is a
near-miss of an already-settled term -- reduced-form equality or high similarity
against a known name. Any candidate that would introduce a **new** term to the
glossary goes to the review queue regardless of tier, because a new term originating
from our own output has nothing independent confirming it.

This is the distinction that `Zunesha -> "Zou Elephant (Zunisha)"` violated: a
plausible wiki match applied with nothing checking it belonged.

**D3a (v2) -- provenance must be representable.** D3 cannot be enforced by adjusting a
threshold. `harvest()` currently returns aggregate counts and a mid-sentence set; it
carries no source. The candidate model gains:

```
variant, source (fansub|transcript), raw_forms, normalized_forms,
settled_target (the term it is a near-miss of, or None),
occurrence_count, episode_count, contexts
```

and the apply rule becomes explicit:

```
fansub                              -> existing miner policy
transcript + settled_target set     -> deterministic/wiki-approved auto-apply
transcript + settled_target None    -> review queue, regardless of tier,
                                       count, or LLM adjudication confidence
```

The last line matters: today's `escalate()` path can promote a high-confidence context
adjudication to an apply. For a new transcript term that is forbidden, and the
prohibition has to live in the apply rule, not in the tier logic.

**D3b (v2) -- harvest scope.** `glossary_acquire.py` walks the whole show directory.
D4's floors were measured on a 22-episode arc. Harvest scope for floor purposes is the
set of episodes being processed, and the scope actually used is recorded alongside the
counts -- otherwise the floors are not the floors that were measured.

**D4. Split recurrence floors.**

- **>= 2 occurrences** for a candidate phonetically near a settled term (likely an
  error). Errors cluster at low counts.
- **>= 3 occurrences** for a brand-new term.

The distribution runs opposite to intuition. High counts are _correct names missing
from the glossary_ -- `Momonosuke` 21x, `Brownbeard` 16x, `Vegapunk` 14x -- because
Whisper hears a name consistently when it is clear. The errors live in the tail:
`Kinamon` 2x (a mangled `Kin'emon`, which _is_ already in the glossary and therefore
reachable as a near-miss target), `Whitestrom` 2x, `Morphosis` 2x, `Hazzard` 4x. A
flat floor of 3 keeps the names and discards the mistakes.

Candidate list at >= 2, after the full filter chain (22 items for a 22-episode arc):

```
Momonosuke(21) Brownbeard(16) Vegapunk(14) Doflamingo(10) Traffy(6) Toshiki(6)
Momo(5) Logia(5) Laboon(5) Blackleg(5) Hazzard(4) Kung(3) Foxfire(3) Fishman(3)
Akainu(3) Zoan(2) Whitestrom(2) Scratchman(2) Morphosis(2) Leggingston(2)
Kinamon(2)   [+ Kaido -> Kaidou as the one near-miss auto-apply]
```

**D5. Possessive folding in the shared `mine_text()`.** A trailing `'s`/`U+2019s` is
stripped before the pattern test. Today `mine_glossary.py:100` tests
`^[A-Z][a-z]{3,}$` against a core that still carries the apostrophe, so
`Brownbeard's`, `Vegapunk's`, `Hazzard's` and `Kinemon's` fail the match and vanish --
counted as neither the possessive nor the base form. Evidence for a name is split
across its forms and then discarded.

**Revised twice. v3 is the shipping design; v2's is withdrawn.**

v2 identified a real hazard: `mine_glossary.py:133-134` admits a term on
`count >= MIN_COUNT and not in COMMON and not in existing`, with **no
English-dictionary gate on the fansub path** (that gate exists only in `glossary.py`
and the acquisition chain), and `boss` is not among the 213 deny-list entries. Folding
possessives there could turn `Boss's` into counts of `Boss` and auto-append it.

v2's fix -- add the missing dictionary gate -- is WRONG, and the measurement is
emphatic: **13 of 81 glossary names are English dictionary words**, including `Brook`,
`Robin` and `Chopper` (three of the nine Straw Hats), plus `Crocodile`, `Buggy`,
`Smoker`, `Shanks`, `Marco`, `Roger`, `Bellamy`, `Wiper`, `Alto`, `Rick`. A dictionary
gate on the fansub miner would make 16% of this show's cast permanently unmineable --
trading a false positive for a systematic false negative on exactly the names that
matter most.

**v3: possessive evidence may REINFORCE a candidate but never ORIGINATE one.** A
possessive form contributes to the base token's count only if the bare form also occurs
mid-sentence at least once. `Brownbeard's` counts toward `Brownbeard` because
`Brownbeard` appears bare; `Boss's` contributes nothing unless `Boss` already qualifies
on its own, in which case the behaviour is unchanged from today.

No dictionary gate is added anywhere. The hazard becomes structurally impossible rather
than empirically absent.

**v4 CORRECTION -- "bare at least once" is not reinforce-only.** The v3 rule still lets
possessive evidence ORIGINATE a candidate whenever one bare occurrence exists:

```
I told the Boss to wait.     bare       -> 1
Boss's men arrived.          possessive -> 2
Boss's ship moved.           possessive -> 3   crosses MINE_MIN_COUNT, auto-appended
```

One generic title use plus two possessives is enough. My "measured cost: zero" only
tested terms with a bare count of ZERO; it never tested this case.

**The shipping rule uses two lanes:**

```
bare_count >= MINE_MIN_COUNT                          -> auto-append (unchanged today)
bare_count <  MINE_MIN_COUNT
  and bare_count + possessive_count >= MINE_MIN_COUNT -> review queue,
                                                         reason "possessive_floor_crossing"
```

Possessive evidence may raise a candidate into VISIBILITY; it may never raise one into
the glossary unattended. This is the escalation ladder applied to the miner: a term the
deterministic rule cannot settle on bare evidence goes to a human, with its bare and
possessive counts attached as the reason.

**v5 measurement correction.** The v4 figures ("89 auto-append, crossing queue holds
1 -- `Traffy`") came from a scratch script written during design, which counted bare
occurrences ONLY from mid-sentence positions. The real miner counts every occurrence and
applies mid-sentence as a SEPARATE gate. `Traffy` therefore already cleared the floor and
was already being auto-appended before this change; possessive folding did not push it
anywhere.

Measured against the shipped implementation, A/B on the same 22-episode corpus:

|                                 | old       | new                           |
| ------------------------------- | --------- | ----------------------------- |
| auto-append lane                | 122 terms | **122 terms, byte-identical** |
| possessive_floor_crossing queue | n/a       | **0**                         |

The safety property is what matters and it holds exactly: the lane that writes to the
glossary with no human in the loop is unchanged, term for term. The recovered evidence is
real but purely reinforcing -- `Caesar` 81 -> 97, `Vegapunk` 14 -> 22, `Nami` 38 -> 46 --
and on this corpus it moves nothing between lanes.

So the review lane currently catches NOTHING. That is an acceptable thing to ship: it is
a structural guarantee that possessive evidence cannot originate a term, not a feature
expected to fire. It should not be described as one.

The extraction is shared; the admission policy is not:

_(A code sketch stood here in v2 proposing a shared-extraction split with a dictionary
gate. It is REMOVED rather than annotated: revised prose sitting above stale code reads
as an instruction, which is exactly how the v3 review found an implementer would have
re-added the withdrawn gate. The two-lane rule below is the whole design.)_

Both paths get possessive folding, because the evidence loss is real on both. No
dictionary gate is added on either path -- see the v4 lane split below for what makes
the fold safe instead.

Tests: `Brownbeard's`, curly-quote `Brownbeard` + U+2019 + `s`, `Brownbeard` plus its
possessive aggregating to one count, internal-apostrophe names (`D'Arby`, `Kin'emon`),
contractions (`That's`, `He's`, `It's`), and ordinary possessives (`Boss's`, `James's`).

`MINE_MIN_COUNT` stays at 3.

**D6. Human review receives only what generalises.** A per-card queue would run to
roughly 1,000 items per season and reviewing one fixes one line. What escalates is a
recurring pattern arriving as a proposed `hard_fix` with its occurrence count and
context lines -- resolved once, applied library-wide, cached forever. Individual
one-off bad lines are recorded in `qc.json` and ship unfixed; at this volume that is
the correct trade.

---

## Data flow

```
transcribe (faster-whisper)
  |
reflow.group()          -- unchanged
reflow.merge_runts()    -- NEW (A1): group-level backward merge
reflow.time_cards()     -- MODIFIED (A2): MIN_DUR is a hard floor; steal forward
  |
glossary name correction  -- unchanged
repair.py                 -- MODIFIED (C2): accept_repair() is duration-aware
hallucination gate        -- unchanged
qc.json write             -- NEW (B1)
signs/songs merge, mux    -- unchanged

per-show sweep (gen_loop.sh):
  mine_glossary.py        -- MODIFIED (D5): possessive folding
  glossary_acquire.py     -- MODIFIED (D1-D4): conf.json candidate source,
                             source-aware auto-apply, split floors
```

## Error handling

- `merge_runts()` is pure and total: given any group list it returns a group list.
  A group that cannot legally merge is returned unchanged.
- The steal pass terminates unconditionally -- each hop either absorbs the remainder
  or reduces it, and it stops at the last card of the episode regardless.
- `qc.json` write failures are logged and swallowed. QC is observability; it must
  never fail an episode that otherwise generated correctly.
- The transcript candidate source follows the existing acquisition contract: never
  raises, writes atomically via temp file plus `os.replace`, and respects the
  `settled` guard so a sweep cannot override a human rejection.

## Testing

Every change is unit-testable without a model or a GPU.

- `merge_runts()`: table-driven over constraint combinations -- gap just inside and
  outside `GAP_MAX`, combined length at 84 and 85, a merge that would breach
  `MAX_DUR`, a merge that would breach `MAX_CPS`, the sentence-integrity preference
  both honoured and skipped.
- `time_cards()` steal: single runt with a surplus successor (terminates in one hop),
  with a zero-surplus successor (propagates), at the end of an episode (extends
  freely), and a chain requiring several hops.
- **Property-based whole-list tests (v2)**, generated from a seeded `random.Random`
  (stdlib; no new dependency), asserting the full A5 invariant set. The listed
  table-driven cases exercise merging and stealing separately; the failure surface is
  their composition, which only randomised whole-list generation reaches. Five groups:
  temporal validity, readability validity, word conservation, causality/idempotence,
  and event accounting (every changed card has exactly one recorded cause, and the
  counters equal the event list).
- Epsilon discipline: a test that a card set to exactly `start + MIN_DUR` and
  round-tripped through 3-decimal JSON is NOT counted as a runt. This is the bug that
  inflated the v1 measurement by 56%.
- Wrapping round-trip (C3): an episode processed by `repair.py` produces an srt whose
  every cue has <= 2 lines of <= 42 characters, whether or not any repair was applied.
- `accept_repair()`: a repair that fits, one that breaches cps for the card's
  duration, one that breaches `MAX_CHARS`.
- `mine_text()` possessive folding: `Brownbeard's` counts as `Brownbeard`; a genuine
  apostrophe name is unaffected.
- Acquisition: a near-miss candidate auto-applies; a new term does not, at any tier;
  floors applied per lane.

**Integration check:** re-run Punk Hazard (22 episodes) and assert
`ordinary_under_min_dur_after == 0` and `orphan_candidates_fixed == 0`
across all `qc.json` sidecars, `max_displacement <= 2.0s`, and that `Hazzard`,
`Kinamon` and `Whitestrom` appear in the acquisition output.

## Rejected alternatives

**Steal for `MAX_CPS` as well as `MIN_DUR`.** Measured: 2,869 cards stolen from
instead of 370; 4,680 cards displaced (49.4%) instead of 449 (4.7%); p99 lateness
5.88s and max 12.64s instead of 1.36s; cascades to 54 cards. A 12-second displacement
is a caption arriving in a different scene. The deeper objection is that cps and
duration have different correct fixes: a too-short card needs more time, a too-dense
card needs _fewer characters_ -- the repair step's job or the splitter's, not the
timer's. **Roadmap:** revisit with a delta cap once `qc.json` shows the real p90 cps
delta.

**A hard displacement cap on the cascade.** Reintroduces exactly the defect being
fixed (a card below `MIN_DUR`) via a threshold nobody can defend. With surplus
absorption the worst case is 1.36s across a season; that is rare enough to observe
rather than legislate against.

**Allowing overlap between the runt and its successor.** Trades a readability problem
for a synchronisation lie that is harder to notice and harder to undo.

**Accepting the residual runts** (merge-backward only, ~36% left short). Rejected by
the user: a slight caption delay is preferable, and the never-early invariant is what
actually matters.

**Retiming after repair.** See C2.

**Clustering flagged-card text for the review queue.** See D2 -- it escalates the
opening theme.

**Admitting apostrophe/hyphen tokens as _new_ candidates.** Measured: zero additional
finds on this show. `Kin'emon` is already in the glossary, so the near-miss path
reaches its variants without this change. **Roadmap** if another show needs it.

**A per-episode human review gate before mux.** Turns an unattended overnight sweep
into a manual pipeline; the first busy week leaves 40 episodes stalled.

## Prerequisite (raised to blocking in v2)

**The VAD orphan bug is upstream of A and must be handled before A's acceptance result
means anything.** `_dejitter()` (`reflow.py:218-236`) only closes gaps _within_ a
Whisper segment (`words[j]["seg"] == words[i]["seg"]`), so a word that belongs to the
next utterance but was emitted in the previous segment survives as its own tiny card
over silence.

That card is indistinguishable, by duration alone, from a sentence-tail runt. A1 would
merge it **backward** into the preceding utterance -- attaching a word to the sentence
it does not belong to, and doing so in a way that satisfies every A5 invariant. The
result is a card that passes QC and is wrong.

Minimum viable handling, in priority order:

1. Mark cross-segment single-word groups with a provenance flag during grouping.
2. A1 refuses to merge a flagged group backward; it may only merge FORWARD into the
   utterance it precedes, or fall through to A2.
3. If forward merging is not implemented in this increment, a flagged group is
   excluded from A1 entirely and handled by A2 alone, and the count is recorded.

Landing the full orphan fix first is better. Shipping A without at least (1) and (3)
risks cementing orphans into merged cards, which is harder to undo than leaving them
as runts.

**v3 -- quarantine is not a fix, and the acceptance criteria must say so.** Excluding a
flagged orphan from A1 and letting A2 extend it produces a caption that is correctly
timed and still shows the wrong word over the wrong audio. A2 makes the defect more
readable; it does not make it right. Acceptance is therefore reported as:

```
ordinary eligible runts fixed : 0 remaining
orphan candidates             : N
orphan candidates fixed       : 0
```

Orphan candidates never count toward "0 remaining" and must not disappear into
`under_min_dur == 0`. They enter a durable QC review category with their text, segment
ids, source boundaries and timing treatment -- an escalation reason, not just a tag.

The single-word criterion is also narrower than the defect. Measure all of: single-word
cross-segment groups; short multi-word cross-segment groups; segment-boundary groups
with silence/VAD evidence; and the false-positive rate on legitimate one-word
utterances (`Yes.`, `Wait.`) before trusting the flag.

## Out of scope

- Repair on episodes with no fansub reference. `repair.py:355-360` still skips them;
  enabling the grammar/readability-only path is the next increment. **v2 addition:**
  the skipped targets must still be RECORDED in `qc.json` with text, timestamp,
  confidence and reason. Today they vanish into a `skipped_no_ref` counter, which
  means the deterministic -> LLM -> human ladder terminates in a silent drop. Recording
  them is in scope; acting on them is not.
- LLM-selected line breaks for cards the deterministic clause rule cannot resolve.
- Library-wide rollout. This increment re-runs Punk Hazard only.
- Relocating the pipeline to the 3500g node.

---

## Appendix: v2 review disposition

Reviewed by Buffy (full spec) and by the salyut panel (condensed brief; cerebras 402,
glm 429/timeout, gemini truncated, llama70b 404, github 410 -- only groq returned
substantive content, itself truncated mid-table). Buffy's review carried the weight.

### Accepted and folded in

| finding                                                   | where                                  | evidence                                                                                     |
| --------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------- |
| Glossary correction runs AFTER timing and wrapping        | verified `generate.py:283` then `:290` | led directly to Problem 4                                                                    |
| Line wrapping destroyed by repair                         | Problem 4, C3                          | verified on muxed output, 3 shows, 0 multi-line cues                                         |
| A1 merge order is non-deterministic as specified          | A4                                     | two implementations could differ                                                             |
| A2 state transition underspecified; invariants incomplete | A5                                     | `end >= natural_end` and `start < end` were unasserted                                       |
| Cascade bound is a corpus property, not a proof           | A section note                         | stated explicitly rather than implied                                                        |
| Last card can extend past audio end                       | A6                                     | 0 occurrences measured; clamp is insurance                                                   |
| B1 records outcomes, not distributions                    | B1 schema                              | `required_extension` quantiles added                                                         |
| Missing sidecar must differ from clean episode            | B4                                     |                                                                                              |
| D5 shared fold is unsafe without a dictionary gate        | D5                                     | verified: `mine_glossary.py:133-134` has no dict gate; `boss` not in the 213-entry deny-list |
| D3 provenance not representable in `harvest()`            | D3a                                    |                                                                                              |
| Harvest scope vs measured floor scope                     | D3b                                    |                                                                                              |
| VAD orphan is upstream of A, not merely deferred          | Prerequisite                           | an orphan merged backward passes every invariant and is wrong                                |
| No-ref repair targets vanish silently                     | Out of scope note                      | ladder terminates in a drop                                                                  |
| C2 must validate per-line, not just total                 | C4                                     | this is how Problem 4 survived                                                               |
| Secondary-model output unvalidated                        | C5                                     |                                                                                              |
| Property-based whole-list tests needed                    | Testing                                | composition is the failure surface                                                           |
| No threshold may be set from one arc                      | B3 / roadmap                           | stated explicitly                                                                            |

### Accepted as caveat, not blocking

**A + C: stealing moves the windows `overlap_ref()` uses.** Real, but `overlap_ref`
matches on overlap rather than containment, and the measured p99 displacement is
1.01s. Recorded in QC so it is observable; not a reason to hold A.

**Metrics before and after A are not comparable.** True. The B-first ship order below
exists to make that explicit rather than to avoid it.

### Rejected

**groq A1-E1** ("a backward merge can leave the card still below `MIN_DUR` because the
merge does not recompute the duration"). The arithmetic in the counter-example is
wrong: a backward merge spans predecessor-start to runt-end, so the merged duration is
at least the predecessor's. The _underlying_ case -- both cards short, merged span
still under `MIN_DUR` -- is real and is now stated explicitly in A4 as falling through
to A2.

**groq A1-E3** ("merge then steal creates a negative gap"). Same arithmetic error; the
merged card ends where the absorbed runt ended, which already respected `MIN_GAP`
against its successor. A5 asserts the gap invariant regardless.

### Ship order (v2)

Buffy's ordering argument is accepted. The four changes are NOT independent.

1. **B first, instrumentation only** -- sidecar plus the `MIN_DUR` floor in the
   violation counter, while the old timing still runs. Captures the 730-runt baseline
   and freezes the schema before A starts emitting new event types.
2. **C3 second, wrapping only** -- it is a live, library-wide defect, independent of
   A, and fixing it first means A's output is judged against correctly wrapped text.
3. **A third, timing only** -- compared against the B baseline on the same corpus.
4. **C2/C4/C5 fourth** -- run against A-produced `conf.json`. Do not compare to pre-A
   repair statistics; A changed the reference windows.
5. **D last, dry-run then reviewed apply** -- harvested from final A output.

The open item this ordering does not resolve: glossary correction still runs after
timing and wrapping, so a name expansion can push a corrected line over `MAX_LINE`.
Either correct text before group sizing, or add a deterministic post-glossary
re-wrap/validate pass. C2's guard does not cover deterministic corrections. **This is
the one design question v2 leaves open.**

---

## Appendix: v3 review disposition (round 2, Buffy/GPT-5.6 Luna)

Round 2 reopened two of the four dispositions I had closed in v2. Both reversals were
verified against production data before being accepted.

### Reversals

**Groq A1-E3 -- I was wrong to reject it.** My rejection asserted the merged card
"already respected `MIN_GAP` against its successor." It does not: `MIN_GAP` is imposed
by `time_cards()`, not by the group data, and the degenerate branch sets
`end = start + MIN_GAP` without consulting the successor at all. Verified on shipped
output: **9 adjacent pairs already overlap** in Punk Hazard, up to -0.083s. The
same-delta shift rule would have reproduced the overlap. Fixed in A2a; the fix also
repairs the 9 pre-existing overlaps, which nothing currently detects.

**A+C promoted from caveat to blocker.** My downgrade rested on `overlap_ref()` using
overlap rather than containment, plus a p99 displacement of 1.01s. Neither is
sufficient: the failure is a card displaced onto its NEIGHBOUR's reference cue and
using it as justification, which passes every existing guard. Fixed in C6 by carrying
`source_start`/`source_end` separately from display timing.

### Upheld

**Groq A1-E1 rejection stands**, with a wording change: a recomputed merge is not
automatically long enough. Both parts can be short and the merged span still under
`MIN_DUR`; A4 already routes that to A2.

**Pre/post-A metric comparability stays a caveat for shipping**, but the appendix must
not claim B-first is sufficient for THRESHOLD decisions. A changes card count,
boundaries, identity and text length, so old and new sidecars are not paired data. A
future cps-stealing threshold requires replaying both timing algorithms against the
same captured Whisper word dump with source-group ids preserved. The B-first production
run is historical baseline only.

### Where round 2 changed a v2 fix outright

**D5's dictionary gate is withdrawn.** See D5 -- 13 of 81 glossary names are English
dictionary words including three Straw Hats. Replaced with reinforce-only possessive
folding, which needs no gate and measured zero cost.

### Where round 2's recommendation was not taken

**The full layout compiler (correct text before group sizing and timing).** Correct in
principle and rejected on measured cost: the largest lengthening `hard_fix` in the
glossary is +2 characters, and zero of the 101 corrections applied to this corpus
change length at all. C7 ships the cheaper post-glossary re-wrap-and-validate pass,
with an explicit trigger -- a D auto-apply growth cap of +2 characters -- whose removal
would make the compiler necessary.

### Corpus-scope warning (v3)

Every quantity in this document not otherwise labelled is **measured on One Pace S30
(Punk Hazard), 22 episodes, 10,020 cards** and is not a general property of the
pipeline. That includes: 730 runts / 7.3%; 56 under 0.25s; 93% sentence tails; the
0.083s median successor gap; 313 merges / 395 steals; 80% one-hop cascades, p90 2,
max 7; 489 displaced, p99 1.01s, max 1.36s; 5 cards over 1s; zero last-card clamps;
the 9 pre-existing overlaps; the rejected cps-stealing figures; D4's floors and
candidate list; 350 raw candidates reduced to 74; the 36.8% flagged rate; and the
correct-name-versus-error frequency split.

The wrapping measurement (Problem 4) samples three shows chosen as the first
dubtitled episode of three unrelated titles. It is strong evidence, not a library-wide
theorem; a full library scan runs after C3 lands.

### Revised release blockers

1. A2a's shift math (absorb pre-existing gap deficit) -- **live defect, 9 occurrences**
2. A2b's feasibility rule at `audio_duration`
3. A5/A6 conditional invariants and the uniform EPS policy
4. C6's source-vs-display timing before A and C ship together
5. C3's re-wrap -- **live defect, library-wide**
6. B1's bounded, effect-list event schema
7. Orphan quarantine reported as unfixed, never as fixed

---

## Appendix: v4 review disposition (round 3, final)

Verdict returned: **SHIP WITH CONDITIONS**, four conditions, all folded in above. The
review is closed; implementation proceeds from this document.

### The four conditions

| #   | Condition                                                                   | Section | Status    |
| --- | --------------------------------------------------------------------------- | ------- | --------- |
| 1   | D5 must require an independently qualifying bare-form lane                  | D5      | folded in |
| 2   | A2b must define the infeasible-cascade output contract (strict: do not mux) | A2b     | folded in |
| 3   | C7 must trigger on measured layout invalidity, not the +2 growth cap        | C7      | folded in |
| 4   | A2b/B1 must reconcile residual timing failures with the event schema        | B1      | folded in |

### What round 3 caught that rounds 1 and 2 did not

**A contradiction I left inside the document.** v2's withdrawn dictionary gate survived
as two lines of prose and a code comment inside D5 (`# PLUS a dictionary gate, added
here in v2` and "Without that gate the fold must not ship") while D5's surrounding text
said the opposite. An implementer would have added the gate that measurement showed
makes `Brook`, `Robin` and `Chopper` permanently unmineable. Deleted in v4.

The lesson generalises: revising a section's argument without deleting the artefacts of
the previous argument leaves a live instruction to do the wrong thing. A spec
contradiction is not cosmetic.

**My "measured cost: zero" for D5 tested the wrong population.** It checked terms with
a bare count of ZERO and found none, and I reported that as proof the rule was safe.
The actual hazard is a term with a bare count of ONE plus two possessives -- which my
query never looked at.

(The "89 auto-append / 1 crossing" figures recorded here in v4 were themselves from that
same scratch script and are also wrong -- see D5's v5 correction. Against the shipped
miner the auto lane is 122 terms, byte-identical before and after, and the crossing queue
is empty. The lesson stands and is if anything sharper: the re-measurement that "fixed"
the first bad number was taken with the same instrument that produced it.)

A measurement that confirms a design is only evidence if it queried the population the
design could actually fail on.

**The +2 growth cap was a proxy, not a bound.** Wrapping feasibility depends on word
boundary positions; a length-neutral substitution can destroy every legal break while
growth stays at zero.

### Prior findings that closed as PARTIALLY RESOLVED

Carried forward as roadmap rather than blockers, per the round-3 verdict:

- reference-cue ids or ambiguity reporting when a merged source window spans several
  fansub cues (C6 fixes the displaced-window defect; it does not guarantee an
  unambiguous reference)
- paired old/new timing replay against a captured Whisper word dump before any future
  cps-stealing threshold is chosen -- B-first is historical baseline only, never paired
  data
- orphan detector coverage and false-positive rate on legitimate one-word utterances
  (`Yes.`, `Wait.`), measured outside this corpus
- full-library wrapping scan after C3 lands, replacing the three-show sample
- a `possessive_floor_crossing` review view in the glossary tooling
- revisit the full layout compiler if layout exceptions occur outside inherently
  unsplittable names

### Corpus-specific DESIGN dependencies (not merely numbers)

Where another show could change the decision rather than the measurement:

| Decision                         | What would change it                                                                                                                                                                                                 |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A3: never steal for `MAX_CPS`    | denser dialogue, fewer gaps, or longer canonicals could leave a large unreadable population; the general rule is "do not enable until QC measures its displacement cost on that corpus", not "cps-stealing is wrong" |
| No hard cascade displacement cap | this corpus's surplus/gap distribution may not exist elsewhere; continuous dense dialogue could make `cascade_infeasible` routine rather than never                                                                  |
| Single-word orphan quarantine    | another model, VAD setting, language or audio mix can produce multi-word orphans; the guard needs coverage testing, not generalisation from one morphology                                                           |
| D4's floors of 2 and 3           | nicknames, two legitimate dub spellings, or names used mostly possessively all shift the distribution                                                                                                                |
| C7 deferring the compiler        | a glossary with multiword or heavily expanded canonicals changes the calculus; measured layout validity stays authoritative                                                                                          |
| A6/A2b infeasibility being rare  | zero observed clamps on one arc establishes nothing across codecs, Whisper versions, or show pacing                                                                                                                  |

The Netflix profile constants are general project requirements. The measured
frequencies that justify the chosen repair strategy are not.
