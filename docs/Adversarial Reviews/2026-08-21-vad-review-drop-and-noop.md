# Adversarial review — the two deliberate non-decisions

## 1. “No drop rule” because the base rate is 0.31%

### The base-rate arithmetic is a constraint, not a proof

The claim “precision cannot exceed approximately 20%” does not follow from a 0.31% base rate.

For a classifier with prevalence `p`, true-positive rate `t`, and false-positive rate `f`:

```text
precision = p*t / (p*t + (1-p)*f)
```

At `p = 0.0031`, precision exceeds 20% whenever:

```text
f < 0.0125 * t
```

So at 82.6% recall, the false-positive rate only needs to be below about 1.03% for precision to exceed 20%. That is difficult, but not impossible. At zero false positives, even a 0.31%-prevalence detector has 100% precision on the cards it catches.

The reported table is consistent with prevalence pressure, but it does not establish a mathematical ceiling:

```text
NSP>.70, LP<-.3: 171 TP, 753 FP
recall:           171/207 = 82.6%
FPR:              753/57,572 ≈ 1.31%
precision:        171/(171+753) = 18.5%
```

That result says the tested conjunction is just too leaky at that operating point. It does not say that no threshold, tail, feature combination, or independent confirmation rule can get above 20%.

The 1.31% FPR is close to, rather than orders of magnitude above, the roughly 1.03% FPR needed to cross 20% precision at the reported recall. A modest specificity improvement could cross that line.

For intuition:

```text
50% precision at 82.6% recall requires FPR < about 0.26%
90% precision at 82.6% recall requires FPR < about 0.029%
```

Those may be unacceptable engineering targets, but they are policy/evidence questions, not consequences of the base rate alone.

### “At any operating point” is stronger than the evidence shown

The spec reports four threshold pairs for `no_speech_prob` and `avg_logprob`:

```text
NSP>.70, LP<-.3
NSP>.80, LP<-.3
NSP>.90, LP<-2.0
NSP>.95, LP<-2.0
```

That is not a complete operating-point search unless the underlying evaluation generated a full PR curve and the table is merely a selected excerpt. It also does not test:

- a threshold on the joint score rather than an AND rectangle;
- a high-precision extreme tail of `compression_ratio`;
- a rule requiring independent text evidence plus audio evidence;
- episode/show-specific calibration;
- a two-stage rule that drops only a tiny, manually validated candidate set and flags the rest;
- a model or feature trained/evaluated on held-out episodes.

The AUC argument has the same limitation. A mediocre whole-range AUC does not rule out a useful extreme tail. Individual AUC values do not rule out a useful combination.

### The labels do not support a universal “no drop rule” conclusion

The 207 positives are blocklist-defined certain hallucinations. The 57,572 negatives are every other card, not manually adjudicated true negatives. That choice is defensible for avoiding clean-speech sampling bias, but it creates two unknowns:

1. some “negatives” may be unlabelled hallucinations, which makes measured false positives look worse than precision against fully adjudicated truth;
2. the rule's recall is only measured against the blocklist subtype, not hallucinations with different wording or morphology.

The right conclusion from that set is narrower:

> The tested `NSP`/`avg_logprob` rules have poor precision against this mixed, blocklist-positive evaluation set at the reported thresholds.

The broader conclusion:

> No useful drop rule exists because prevalence is 0.31%.

is not established.

### The strongest defense of the no-drop decision

The author may still be right not to ship a drop rule. Deletion has an asymmetric cost: one deleted real line is lost content, while one retained hallucination is visible noise. The measured 19.8% real-dialogue deletion from the VAD drop experiment is a strong warning, and a classifier with 90% precision may still be unacceptable if the remaining 10% are real lines across a whole library.

But that would be a **loss-policy decision**, supported by measured false deletions, not a base-rate theorem. The design should say:

```text
No drop rule ships because no evaluated rule meets the allowed false-deletion budget.
```

It should not say or imply:

```text
The base rate makes acceptable precision impossible.
```

### What would settle the decision

Use episode/show-held-out, manually adjudicated labels and report the region that matters operationally:

```text
precision at fixed false-positive counts per episode
recall by hallucination subtype
false deletion rate on verified dialogue
precision at the first 1, 5, 10, and 25 drops per episode
PR curve, not only ROC/AUC
```

Also test a conservative cascade rather than one broad drop gate:

```text
exact blocklist/repetition evidence
AND
independent audio/no-speech evidence
AND
confidence/text sanity evidence
```

If that still cannot meet the explicit false-deletion budget on held-out episodes, “no drop” is defensible. The current base-rate argument alone is not.

## 2. The 11/30 no-speech cards keep their 7-second hang

### This is a real scope hole, not automatically a bug

The 11 cards are 36.7% of the gated population, not a rounding detail. The feature's gate identifies cards that are implausibly long for their own text; then the no-VAD branch leaves more than a third of those candidates unchanged.

That means the new pass has a hard upper bound of roughly 63.3% candidate coverage before checking whether any of the 19 changed cards are safe or useful.

The “11 keep their 7-second hang” statement also needs one qualification: current `generate.py` independently applies `hallucination.drop_reason` after reflow, so a blocklisted/repetition card may be removed for another reason. The accurate claim is:

> surviving gated cards with no VAD interval remain on their old long timing; the new hang-trim decision does not improve them.

For a non-blocklisted hallucination over silence, that is the hardest case the feature appears designed to illuminate, and the spec deliberately declines to act.

### Why no-op is defensible

The no-op policy has a legitimate safety argument:

- VAD is known to miss shouted dialogue over SFX;
- VAD cannot reliably separate sung vocals/music from speech;
- a false drop loses a real caption permanently;
- a no-op preserves the existing content and timing;
- the project explicitly values lost content as worse than timing noise.

If the conditional probability of real dialogue among these 11 is high, dropping them is worse. The fact that VAD says “nothing” is not proof of silence; it is an imperfect detector result conditioned on a difficult subset.

This is the best case for the author's choice:

> “When the locator has no positive evidence, do not move or delete the caption. Preserve content and defer the unresolved case to the existing confidence/blocklist layers.”

That is defensible as a conservative safety policy.

### Why it may be quietly declining the hardest third

The no-speech group is not a random 37% sample of gated cards. It is selected precisely where the detector fails to locate speech. It may be enriched for:

- real dialogue under loud SFX;
- shouted or overlapping dialogue;
- timing mismatch between Whisper word timestamps and the extracted waveform;
- accents or vocal textures Silero VAD misses;
- genuine hallucinations over music/silence.

The first four are false negatives where no-op protects content. The last is the target failure where no-op preserves the 7-second hallucination. Without labels, the spec does not know which population it has left untouched.

The contradiction is especially sharp because the design's decision table says:

```text
Q2 action on detection: drop if silent, flag if low-confidence
Q6 if no detector clears the bar: ship hang trim only
§3.2 step 3: no speech located -> no-op
```

The operative decision is not “drop if silent.” It is “never use this detector's silence result to drop,” while still describing no-speech cards as a known residual. That may be the right safety boundary, but it should be named as an explicit non-goal rather than presented as a complete hang solution.

### Expected-loss framing

Let:

```text
q       = P(real dialogue | gated, no VAD interval)
C_drop  = cost of deleting real dialogue
C_keep  = cost of leaving a hallucinated 7-second card
```

Dropping is preferable only when:

```text
q * C_drop < (1-q) * C_keep
```

The spec supplies neither `q` for the 11 cards nor a usable ratio between these costs. The global 0.31% hallucination base rate cannot substitute for `q`: this is a heavily conditioned subgroup, not a random card.

The 11 cards need their own audit. Applying the all-card base rate to them would be another unrepresentative comparison set — exactly the failure mode the project is trying to avoid.

### What would make accepting the 11 defensible

The no-op branch is defensible if the implementation makes it an unresolved outcome with evidence, not an invisible success:

```text
hang_candidate: true
hang_action: no_vad_noop
vad_intervals: []
needed: ...
old/new timing: unchanged
confidence fields: ...
manual-review reason: no speech located
```

Then manually adjudicate all 11 and report:

```text
real dialogue / VAD miss
verified hallucination
ambiguous
existing independent drop
```

If most are real dialogue or ambiguous, no-op is the correct conservative choice. If most are verified hallucinations, the spec is knowingly leaving its hardest subgroup untouched and needs either a separate high-precision drop rule, a wider/fallback locator, or an explicit product decision to accept those 7-second false captions.

A “flag” is only a mitigation if something consumes it. The project review already found that the existing `flag` field has no downstream consumer. A new `hang_unresolved` QC count without a queue, report, or operator action would be observability, not remediation.

## Verdict

1. **No drop rule:** defensible only as a measured false-deletion-budget decision. The 0.31% base rate explains why precision is hard; it does not prove that precision cannot exceed 20%.
2. **11 no-op cards:** defensible as a lost-content safety policy, but currently under-evidenced. They are 36.7% of the selected problem population and may be the detector's hardest, most consequential subgroup. Calling the feature safe because it no-ops is incomplete; calling it a complete hang fix is false.
