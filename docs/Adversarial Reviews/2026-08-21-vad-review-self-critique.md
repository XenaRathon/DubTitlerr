# Adversarial self-critique — VAD review

The earlier review mixed three levels of claim:

1. facts stated by the spec or visible code;
2. failures that are mechanically possible from the proposed ordering;
3. failures likely to occur in the measured 0.57% population.

I was strongest on (1), reasonably strong on (2), and least justified when I let (2) sound like (3).

## Strongest earlier finding: post-cascade trim can violate timing invariants

### The finding as I stated it

I argued that the hang trim runs after the runt cascade, can move a card's start later or earlier and its end earlier, and can therefore create a new runt, overlap, or EOF violation that no later pass repairs.

The mechanical part is real:

- the spec orders trim after the cascade;
- step 5 can accept a card below `MIN_DUR` after the `MIN_GAP` cap;
- the spec says the cascade already owns short cards, but does not schedule a second cascade;
- the stated placement is after the existing tail clamp even though step 5 can extend `end`.

### The best case that I am wrong

The spec's author may already have handled the practical case through the shape of the data and the existing timing helpers, even if the prose does not spell out every invariant.

1. **The gate selects unusually long cards.** A gated card is longer than both 3 seconds and `3.4 × needed`. These may generally be isolated hang cards rather than cards pressed against an immediate successor. If every measured gated card has enough room after its VAD speech, the `MIN_GAP` cap never creates the synthetic failure I described.
2. **The 3.2-second “lost window” is mostly silence, not lost speech.** My example compares display coverage, not word coverage. If VAD's selected interval really contains all of the card's speech, removing the old silence is the intended improvement. The example does not prove that a word disappears.
3. **The actual implementation may reuse the degenerate timing guard.** The spec names the trim as living in `reflow.time_cards()`, and the existing `time_cards()` already has a guard for a next card that is too close. The author may place the trim inside a helper that clamps `end`, rejects nonpositive candidates, or reuses the cascade despite the abbreviated prose.
4. **A short final card may be an intentional trade.** The spec explicitly says to accept a card under `MIN_DUR` when the successor cap wins. A short but correctly placed caption may be judged less harmful than preserving a caption that sits over seconds of non-speech. I treated “below the normal invariant” as automatically worse, but the product tie-breaker is lost content versus timing noise, not `MIN_DUR` in isolation.
5. **The fire rate bounds the absolute blast radius.** The proposed gate fires on 30/5,296 cards and reportedly changes about 19. Even if the mechanism is possible, it may be cheaper to manually inspect those 19 results than to reject the feature or redesign the whole timing pipeline.

That is the strongest opposing case. It means my earlier wording should have been:

> “The ordering creates an untested invariant hazard that must be checked against the 30-card candidate set.”

It was too strong to present it as an established production failure. The synthetic example proves reachability in abstract timing space, not occurrence in this episode cohort.

### What evidence would decide it

Run the actual proposed implementation in read-only mode over the 30 gated cards and emit, per card:

```text
settled start/end
source start/end
selected and clipped VAD intervals
needed
uncapped candidate end
successor start
final candidate start/end
candidate duration
word-overlap before/after
cascade-displaced flag
```

Then adjudicate two separate outcomes:

- **timing invariant failure:** overlap, EOF, nonpositive duration, or newly-created runt;
- **speech-coverage loss:** a pre-existing word's audio span is no longer covered.

If all 19 changed cards preserve both sets of properties, my strongest VAD objection becomes a documentation/test gap, not a demonstrated blocker. If even one card violates an invariant or loses an actual word, the ordering concern is confirmed.

## Self-audit of the falsifiable predictions

### Prediction 1 — exact extracted WAV and episode-relative timeline

**Confidence: high; likely wrong only in details.**

The spec explicitly places VAD after `extract_wav()` inside the temporary directory and passes plain `(start, end)` floats onward. The visible `generate.py` already has one extracted WAV and one measured WAV duration. The best case against my prediction is that VAD could safely use an equivalent decoded stream or a deliberate offset if the implementation records and applies that offset consistently. I said “exact path/timeline” because silent second extraction is dangerous, not because byte identity is intrinsically required.

**Settling evidence:** compare the VAD input stream, sample rate/channel layout, seek offset, and returned timestamp origin with Whisper's input. An equivalent deterministic decode should count as satisfying the design even if it is not the same filename.

### Prediction 2 — source bounds must remain separate from display bounds

**Confidence: high.**

This is directly required by §3.2 step 2 and by the current code's distinction between `source_*` and display timing. The only overstatement was implementation shape: the trim does not need a finished card dict inside `time_cards()` if it receives each group's original source bounds explicitly.

**Best case against:** “source window” could be reconstructed from the groups at the exact point of trimming, so a separate persistent card field is unnecessary. That would still satisfy the semantic prediction.

**Settling evidence:** inspect the trim function's arguments and trace a merged/forward-displaced card. If its VAD query uses original word bounds rather than settled `start/end`, the prediction is satisfied regardless of field names.

### Prediction 3 — intervals must be clipped, sorted, and validated per card

**Confidence: medium-high, but I was too prescriptive about the code shape.**

A global VAD interval can overlap two source windows. Using raw interval endpoints would let a card inherit neighboring speech, so some equivalent ownership rule is necessary. But `max(vad_start, source_start)` / `min(vad_end, source_end)` is not the only safe implementation:

- the VAD extractor could emit already partitioned per-card intervals;
- an interval-to-owner pass could assign a continuous interval to one card before trimming;
- the implementation could reject any interval crossing a source boundary rather than clip it.

My real prediction should be “raw cross-boundary endpoints are unsafe,” not “the implementation must contain these exact `max` and `min` calls.”

**Settling evidence:** feed one continuous VAD interval across two adjacent source windows into the implementation and verify that neither card receives audio outside its ownership policy.

### Prediction 4 — all final invariants must be checked after step 5

**Confidence: medium.**

The EOF point is strong: a clamp before an operation that can extend `end` cannot guarantee `end <= audio_duration` afterward. The new-runt point is also strong unless accepting a short card is an intentional documented exception.

The weaker part is my demand for a predecessor `MIN_GAP` invariant. The project's existing philosophy says starts move later, while the VAD design deliberately allows both edges to move to located speech. If the author proves that source windows are ordered and non-overlapping, a predecessor check may be redundant. I should not call that check universally required without tracing those ordering guarantees.

Likewise, “`duration >= MIN_DUR` must hold” conflicts with the spec's explicit “accept short” branch. The correct prediction is narrower:

> every short-card exception must be explicit, observable, and either proven safe or repaired in the same pass.

**Settling evidence:** run property tests on the actual final cards, including the accepted-short branch, and inspect whether the project intentionally defines short post-trim cards as legal.

### Prediction 5 — the gate must use final displayed text

**Confidence: low-to-medium; this is the prediction I am most likely to have overreached on.**

The current pipeline calls `reflow.reflow()` before per-card glossary correction. I inferred that `needed = len(text)/MAX_CPS` should therefore be recomputed after correction. But the spec says the measured text gate is unchanged from the earlier implementation, and the author may intentionally define that gate over raw transcription text before deterministic spelling correction. Glossary edits are generally semantic/name substitutions, not a new timing decision, and reordering correction before segmentation could itself change boundaries the design is trying not to disturb.

So “the implementation must use final displayed text” is not established. The defensible requirement is only:

> the implementation must document whether the gate is pre-correction or post-correction, and that choice must match the measured gate population.

**Settling evidence:** take a gated card whose glossary correction changes visible character count, run both definitions, and compare eligibility, final CPS, and actual rendered text. If the pre-correction choice preserves the declared readability invariants or the correction is length-neutral in all candidates, my stronger prediction should be withdrawn.

### Prediction 6 — VAD must remain a locator, not a hidden drop signal

**Confidence: very high.**

This follows directly from §5 and §3.2 step 3. The author can change the design later, but under the stated design “no intervals” cannot become a new deletion condition. Existing independent blocklist/repetition drops are not a contradiction; my earlier wording was careful about that distinction.

**Settling evidence:** inspect the call graph and run a no-interval card through the hang pass with and without an existing `drop_reason`. The VAD pass should not add a drop reason.

## Confidence ranking

From least to most confidence in the earlier predictions:

```text
least:  P5 — final displayed text must define the gate
         P4 — predecessor/min-duration details are mandatory invariants
         P3 — clipping is mandatory as opposed to another ownership policy
         P1 — exact WAV identity rather than equivalent aligned decode
         P2 — source timing must remain distinct from display timing
most:   P6 — no-VAD must not silently become a new drop rule
```

The main correction to my prior review is therefore methodological: the 0.57% rate makes occurrence and impact empirical questions. It does not make a reachable invariant violation safe, but neither does a synthetic counterexample prove that the measured 19 changed cards contain one.
