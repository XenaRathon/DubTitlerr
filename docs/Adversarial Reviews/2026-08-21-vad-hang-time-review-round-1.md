# Adversarial review — VAD-located hang trim

**Round 1 scope:** only interactions between §3.2, the runt cascade, §5, and the no-op-on-no-VAD rule; then falsifiable implementation predictions.

**Verdict:** do not implement the timing mutation unchanged. The dangerous boundary is not VAD accuracy in isolation. It is that the proposed final pass can mutate timings after the pass that owns the timing invariants, without re-establishing those invariants.

## 1. Trim plus readability extension plus `MIN_GAP`

### The trim can cover less of the actual line

Yes. Step 4 can move `start` later and `end` earlier. Step 5 only moves `end` later; it can never restore speech that was removed from the front, and it cannot restore a final word that VAD failed to include in its last interval.

A concrete case satisfying the stated gate:

```text
settled card before trim: [10.00, 14.00]       duration 4.00
needed:                    1.00
next card start:           14.083
MIN_GAP:                    0.083
selected VAD interval:     [13.20, 13.40]
```

Step 4 produces `[13.20, 13.40]`. Step 5 wants an end of `14.20`, but the `MIN_GAP` cap makes the end `14.000`. The final card is `[13.20, 14.00]`, only `0.80 s`, and it has lost the earlier `3.20 s` of the old display window. If the VAD interval omitted a real leading word, that word is now uncovered.

This is not fixed by saying that the VAD interval is “speech.” The interval can be speech while still being an incomplete observation of the card's speech.

**Required rule:** a trim candidate must be rejected unless its selected VAD envelope is known to cover the card's required speech boundaries, or the operation must be transactional and no-op when that cannot be established. A duration floor alone does not prove speech coverage.

### The cap can be worse than no-op

Yes. The cap can leave a newly trimmed card below `MIN_DUR`, while the no-op would have preserved the settled card. The spec explicitly says to accept that short result, but no later cascade is specified.

The more severe case is an ordering failure:

```text
trim_start > next_start - MIN_GAP
```

Then the stated end cap is earlier than the new start. The design does not state a positive-duration guard or a successor-start rollback. Depending on the exact values, the result can be zero/negative duration or an overlap with the successor. Even if an existing helper happens to prevent that today, the VAD step must name and enforce the invariant after the new start is installed.

There is also no predecessor check. A start located from the source window can be earlier than the already-settled display start, so the trim can move a card backward into the preceding card even though the existing timing pass only moves starts later.

## 2. Trim after the runt cascade

### The direct “cascade extended this same card, then trim shrank it” case is constrained by the gate

There is an important algebraic limitation: a card repaired as a runt is normally extended to approximately `needed`. The hang gate requires:

```text
duration > max(3.0, 3.4 * needed)
```

A card whose final duration is just `needed` therefore cannot also pass the hang gate. So the simplest claim — “the cascade extends a runt, then the hang gate trims that same repaired runt” — is not generally reachable if `dur` is the settled display duration.

That is a prediction worth checking, not an excuse to leave the ordering unspecified. It fails if the implementation computes the hang gate against a pre-cascade duration, a source duration, or another value rather than the settled display duration.

### The ordering still permits the cascade's work to be undone

The cascade also moves successor starts. A successor can have enough duration left after being displaced to pass the hang gate. The later trim then replaces its settled display start with a VAD-derived start from the original source window.

That can:

1. move the successor back earlier than the cascade placed it, recreating an overlap with the card whose time it was supposed to yield;
2. shrink the successor below `MIN_DUR` after the cascade has finished, creating a new runt with no repair pass; or
3. move the successor later again, consuming time that the cascade had allocated to a different card.

The sentence “the runt cascade already owns short cards” is therefore only true for cards short **before** the hang trim. It does not own cards made short by the trim, and it does not prove that a displaced successor still respects the gap after its start is replaced.

**Required rule:** either run the trim before the cascade and re-settle all timings, or make the trim a transactional final pass that preserves predecessor/successor gaps, positive duration, `MIN_DUR`, and EOF. If a candidate cannot satisfy those constraints, it must no-op rather than rely on a cascade that has already run.

**Speculation — needs a synthetic trace:** whether the observed data contains a hang-eligible successor that was actually displaced by a cascade. The mechanism is possible from the ordering, but the supplied measurements do not establish its frequency.

## 3. No VAD result plus no drop rule

Yes, there is a failure the spec explicitly declines to fix:

1. A card passes the hang gate.
2. Its text is a hallucination not caught by the existing blocklist/repetition rules.
3. The source window is verified silence or SFX, so VAD returns no interval.
4. Step 3 no-ops.
5. §5 supplies no new drop action.
6. The card remains on screen for its existing long duration, potentially the `MAX_DUR` ceiling.

That card is provably wrong in the constructed case, and a reader would reasonably expect a feature whose purpose includes locating speech in non-speech spans to remove or at least quarantine it.

This must be stated carefully: current `generate.py` already calls `hallucination.drop_reason`, so a blocklisted phrase may be removed independently of VAD. The uncovered case is a non-blocklisted/missed hallucination, not every silent card.

The no-op policy is safe only in the narrow sense “VAD never causes deletion.” It is not “never worse” in product outcome: it knowingly preserves a wrong caption when the no-speech observation is correct.

**Speculation — needs labels:** the 11/30 no-interval gated cards are not enough to quantify this. We need to know how many are real dialogue missed by VAD versus verified non-speech hallucinations.

## 4. Falsifiable predictions about the implementation

These are conditions that must hold for the design to work. Each is phrased so a grep plus a small synthetic test can confirm or refute it. The current checkout has no VAD implementation yet; these are predictions about the implementation that would satisfy the spec.

### Prediction 1 — VAD must use the exact transcription WAV and timeline

`generate.py` must call VAD:

- after `extract_wav()` succeeds;
- on that exact `wav` path;
- inside the existing `TemporaryDirectory` block;
- before the block exits;
- with results expressed in episode-relative seconds;
- and pass the interval list into the reflow path.

A second extraction, a different seek offset, or a post-temp-file call invalidates comparison with Whisper's word timestamps.

Check:

```bash
grep -nE 'TemporaryDirectory|extract_wav|media_duration|vad|reflow' DubTitlerr/generate.py
```

### Prediction 2 — the trim must see source bounds separately from display bounds

`reflow.py` currently computes settled display times in `time_cards()` and constructs `source_start/source_end` on the cards afterward. Therefore the implementation must either pass source bounds explicitly into the trim routine or move the trim to a point where the card carries both coordinate systems.

For every merged group, the source window must remain the union of its original word timings:

```text
source_start = first source word start
source_end   = last source word end
```

It must not be replaced with the cascade-shifted display `start/end`.

Check:

```bash
grep -nE 'def time_cards|source_start|source_end|merge_runts|forward_steal|hang_trim' DubTitlerr/reflow.py
```

A trim routine that only receives `(start, end, text)` cannot implement §3.2 step 2 correctly.

### Prediction 3 — overlapping VAD intervals must be clipped and validated per card

The implementation must sort selected intervals, intersect each interval with the card's source window, discard empty intersections, and derive endpoints from the clipped intervals. The required shape is equivalent to:

```python
lo = max(vad_start, source_start)
hi = min(vad_end, source_end)
```

Selecting raw endpoints from an interval that overlaps two cards lets one card inherit the neighbor's speech. Clipping is necessary but not sufficient: a single interval that fills the whole source window is not evidence that VAD located an internal speech boundary, so that case needs an explicit safe policy (normally no-op).

Check:

```bash
grep -nE 'vad|source_start|source_end|max\(|min\(|sort|overlap' DubTitlerr/reflow.py DubTitlerr/generate.py
```

### Prediction 4 — final invariants must be checked after step 5

The last timing mutation must be followed by checks for at least:

```text
start < end
end <= audio_duration                 # when known
end <= next_start - MIN_GAP
start >= previous_end + MIN_GAP       # or an explicitly documented exception
end - start >= MIN_DUR                 # unless a same-pass repair owns it
```

In particular, the EOF clamp currently present before the proposed trim cannot protect an end that step 5 extends afterward. Likewise, the existing cascade cannot repair a runt created afterward.

Check:

```bash
grep -nE 'audio_duration|MIN_GAP|MIN_DUR|cascade|hang_trim|vad|tail' DubTitlerr/reflow.py
```

A synthetic case should assert that a trimmed card capped by `next_start - MIN_GAP` either remains valid or is unchanged from the pre-trim card.

### Prediction 5 — the gate's text must be the text whose duration is being judged

Because `needed` depends on `len(text)`, the implementation must establish whether the gate is defined over pre-correction or final displayed text. In the current pipeline, `reflow.reflow()` runs before the per-card glossary correction in `generate.py`; a future hang gate inside reflow will therefore see pre-correction text unless the order changes or the gate is recomputed.

This is not harmless bookkeeping: a correction can alter character count and wrapping, changing both `needed` and eligibility.

Check call order:

```bash
grep -nE 'punctuation\.restore|reflow\.reflow|glossary\.correct|repair|hang' DubTitlerr/generate.py
```

The code must make the chosen text boundary explicit rather than silently using whichever representation happens to be available.

### Prediction 6 — VAD must remain a locator, not a hidden drop signal

With §5 unchanged, no-VAD must not flow into `hallucination.drop_reason` as an implicit deletion condition. Existing blocklist/repetition decisions may remain, but the new VAD result must not turn “no intervals” into a drop unless the design is changed and separately evaluated.

Check:

```bash
grep -nE 'drop_reason|no_speech|vad|interval|hang' DubTitlerr/generate.py DubTitlerr/hallucination.py
```

A test card with no VAD intervals should prove that the hang pass leaves it unchanged, while existing independent drop rules retain their documented behavior.
