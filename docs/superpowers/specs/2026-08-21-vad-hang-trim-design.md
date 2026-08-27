# VAD-located hang trim — DROPPED

**Status: NOT BUILT. Decided 2026-08-21 after measurement, two adversarial reviews, and one
retracted refutation of my own.**

This document is kept as a **negative result**. The idea is attractive and will occur to the
next person who looks at a 7-second caption; everything below is the evidence that it does not
work, so it does not have to be rediscovered. If you are about to propose locating speech
acoustically in this pipeline, read §3 first.

**Successor item:** the _cause_ of the hang is live and unfixed — see §6.

---

## 1. The problem (real, still unfixed)

Cards sit on screen far longer than their text needs. Measured in `986481f`: **74 cards per
season (0.8%) over 2.5 s at under 5 cps, median 5.91 s**, worst cases single function words
pinned at the `MAX_DUR` 7 s ceiling. Re-measured 2026-08-21 with an independent gate:
**30 of 5,296 cards (0.57%)**, and separately **401 of 54,792**. Consistent.

Examples, with their `source_end - source_start` (the word's own timestamp span):

    'disobeys'       7.0 s      one word
    'it'             7.0 s      one word
    "I'm rubber."   11.5 s
    'Eve, ho!'       8.2 s

## 2. Why it cannot be fixed by trimming

`986481f` shrank such cards from the front. It was reverted the same night (`0ee667e`) because
the trim direction was assumed, not measured. This design proposed measuring it with VAD.

**On 99% of gated cards, `end == source_end` exactly.** The display window _is_ the word's
timestamp span; there is no display padding to remove. The word is somewhere inside a 7-second
window and nothing available says where.

- Trim the front → if the speech was at the front, the caption appears _after_ the line.
- Trim the end → if the speech was at the end, the caption is gone _before_ the line.
- Trim both → misses whichever edge holds it.

Each risks the failure `0ee667e` named as the worst one: _"a caption that never covers its
line is lost content."_ **The 7-second caption is the content-safe choice** — it covers the
entire window in which the word might fall. It is ugly, and it is correct.

## 3. Everything that was tried, and the number that killed it

Do not re-run these. Each was measured on real library data, not reasoned about.

| approach                                                                                                                                                     | result                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Silero VAD** as a drop gate                                                                                                                                | **deletes 19.8% of cards** (82/415). Returns 0.00 coverage on real shouted dialogue: `'Luffy!'` (lp −0.19), `'My eyes! My eyes!'` (−0.01), `'Damn it!'` (−0.14)                      |
| Silero VAD as a `no_speech_prob` substitute                                                                                                                  | **F1 0.267** (≈chance). Anime songs have vocals, so VAD says "speech" exactly where `no_speech_prob` says "music"                                                                    |
| Silero parameter sweep (threshold 0.15–0.5 × pad 0–400 ms)                                                                                                   | **no operating point exists.** Loosen enough to keep dialogue and the known hallucinations score 1.00                                                                                |
| **webrtcvad** (the backend `tools/vad.py` already chose, for being better against music/SFX)                                                                 | **saturated.** Scores 1.00 on the cards Silero scored 0.00 — but _also_ 0.96–1.00 on known hallucinations, at or above real dialogue in the same episode, in 5 of 6 sampled episodes |
| RMS / silence gate                                                                                                                                           | hallucinations are **not quiet**: 0.79×, 1.19×, 0.67×, 0.60×, 0.20× of median dialogue RMS                                                                                           |
| 12 deterministic audio features (Scheirer-Slaney 4 Hz modulation, spectral flatness, low-energy ratio, harmonicity, ZCR, flux, centroid, speech-band ratio…) | **best is 0.894, beaten by `avg_logprob` at 0.936.** The best audio feature loses to a scalar the pipeline already has                                                               |
| Whisper's `compression_ratio` (its own degeneracy measure, discarded at `generate.py:603`)                                                                   | **0.635** — barely better than counting characters                                                                                                                                   |
| Word timestamps as the locator                                                                                                                               | **they are the bug.** `source_end - source_start` is the implausible span                                                                                                            |
| GLM's `end = min(end, source_end + needed)`                                                                                                                  | **correct but fires on 1 of 69 gated cards (1%)** — see §5                                                                                                                           |
| EN-vs-JA audio differencing                                                                                                                                  | only 3 of 84 shows carry ≥2 audio tracks                                                                                                                                             |
| Chapter markers                                                                                                                                              | present on 29 of 60 sampled files                                                                                                                                                    |

### 3.1 Why every acoustic method fails, in one sentence

**An anime dub's music bed is voice-like signal** — it contains actual singing, and orchestral
stings occupy the same spectral space as speech. Silero is trained on clean speech, so loud SFX
blinds it; webrtcvad is a voiced-frame detector, so any structured loud audio reads as voiced.
They fail as exact mirrors, and neither is wrong about its own question.

### 3.2 And why no better feature will help

Positives are **0.31% of cards** (207 of 57,779 labelled). At that prevalence the 99.7%
negative mass leaks more through any threshold than the 0.3% positive mass supplies. Tested for
a high-precision tail explicitly, after an adversarial reviewer correctly objected that a
4×6 grid of AND-rectangles does not license a universal claim:

    max precision, any recall:
      no_speech_prob 5.3%   avg_logprob 2.6%   cps 2.7%   compression_ratio 0.9%
      JOINT z-sum (6 features)      4.4%
      JOINT z-sum (nsp + logprob)   8.0%
      AND-rectangle (the original)  19.8%   <- still the best

No single-feature tail, and joint scores do **worse** than the rectangle — a rank-sum accepts a
card with terrible logprob and unremarkable nsp, which the conjunction refuses.

## 4. Evidence that is now suspect

`0ee667e` justified the revert with a per-slice **loudness** measurement across 8 hang cards:
`loudest slice at END 4 | at START 3 | MIDDLE 1`.

**That evidence should no longer be cited.** §3 established that loudness does not locate
speech in this audio — hallucinations sit at 0.60–1.19× dialogue RMS. "The loudest slice is at
the start" may mean the _sting_ is at the start. The revert's conclusion (don't assume a
direction) still stands; its stated reason does not.

## 5. The 1% that is still fixable (deferred, not rejected)

On cards where `end > source_end`, the excess is genuine display padding and cutting it back
cannot lose content — the speech provably ended at `source_end`.

    measured on 26 episodes carrying source_* fields:
      hang-gate fires : 69
      would trim      :  1  (1%)   'Damn you!' 4.6s -> 2.0s, spoken span 1.14s
      would no-op     : 68 (99%)

~10 lines, no VAD, no new dependency, mean 2.59 s removed when it fires. Deferred to be done
alongside §6, since both touch `source_*` handling. Roughly one card per four episodes.

## 6. SUCCESSOR ITEM — the cause is live and affects other stages

The hang is **Whisper emitting an implausible word timestamp** under `word_timestamps=True` on
music-masked audio. That value is not confined to display timing:

- **`repair.overlap_ref()`** selects the fansub reference by overlapping `source_start`/
  `source_end`. A 7-second window selects whatever fansub line falls in it — possibly a
  different line entirely. The guard then rejects the repair and counts `rejected`, recording
  nothing about the _reference_ having been wrong.
- **`generate._card_word_probs()`** joins word probabilities on the source window (_"joined on
  the SOURCE window (C6), never the display one"_). A 7-second window inherits neighbouring
  cards' probabilities. **Measured: 20 of 401 gated cards (5%) carry more probabilities than
  they have words; 1 would be flagged for repair purely on borrowed evidence.**

Proposed guard (not yet built): treat `source_end - source_start > MAX_DUR` on a ≤2-word card
as a known-bad window — `overlap_ref` falls back to the display window, `_card_word_probs`
returns empty rather than inheriting. Small blast radius, but it stops two stages trusting a
value proven wrong.

## 7. Provenance

Reviewed adversarially by GPT-5.6 Luna (interaction analysis, falsifiable predictions,
self-critique) and GLM-5.2 (buildability and sequencing). Both recommended dropping the
feature; GLM proposed the §5 rescue and identified §6.

Two corrections to my own work, recorded because the errors were instructive:

1. I claimed nothing reads the `flag` field. **Wrong** — `tools/timing_compare.py:707,724` do.
   My grep was `*.py` in the repo root and silently excluded `tools/`.
2. I claimed GLM's §5 trim was refuted, "no-ops on 401 of 401." **Wrong** — those cards lack
   `source_*` fields entirely, and my own `.get("source_end", c["end"])` fallback guaranteed a
   zero result. Re-tested on cards that carry the field: 1 of 69.

Both are the same failure the code kept exhibiting: **a defaulted value that silently answers
the question you asked.**
