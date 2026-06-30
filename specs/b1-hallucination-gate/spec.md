# Spec — B1: Hallucination confidence-gate

> Step B1 of the DubTitlerr quality build (A1 + C1 done). Grilled on the brainstorm.
> North-star: the definitive dub subtitle. Conservative — losing a real line is worse
> than a rare surviving hallucination, so B1 drops only near-certain garbage and flags
> the rest.

## Context and problem

Whisper still emits the occasional hallucination the existing guards miss: a phrase not
in the small `BLOCKLIST`, a within-line repeat loop, a runaway loop of the same line over
many cards, or invented text over music/silence. `vad_filter` + `BLOCKLIST` + A1's blank
drop catch some; B1 adds a confidence-gate (using the per-card `avg_logprob`/`no_speech_prob`
A1 already records), repeat guards, and one decode-time guard — biased to NOT delete real
dialogue.

## Acceptance criteria (verifiable)

- [ ] A card matching the **extended phrase blocklist** is dropped.
- [ ] A **within-card repetition loop** (a 1–3-word n-gram dominating the card, or a single
      word ≥4×) is dropped.
- [ ] A card with `no_speech_prob > 0.8` **AND** `avg_logprob < -1.0` (music/silence) is dropped.
- [ ] A **run of ≥4 identical/near-identical consecutive cards** collapses to one; a genuine
      ≤3-card repeat (e.g. "Run! Run! Run!") is left intact.
- [ ] **Weaker single signals do NOT drop** — a card that is only mid-`no_speech_prob` OR only
      mid-low `avg_logprob` is kept and **flagged** (a `flag` field in its conf row) for the
      anchored LLM / review.
- [ ] `transcribe()` sets `hallucination_silence_threshold ≈ 2.0`; `condition_on_previous_text`
      stays `True` (context/name coherence).
- [ ] **Regression on real S19E16** (a clean episode, meanlp -0.17): B1 drops **0** of its real
      lines and collapses nothing — confirms it doesn't nuke good content.
- [ ] Deterministic; stdlib only; runs in the subgen image.

## Out of scope (explicit)

- C1 name correction (done); D1 mux; A1 reflow/timing (unchanged except the one transcribe param).
- LLM-based hallucination judging — flagged cards ride the existing C1/C3 anchored-LLM path.

## Data contracts

- **Input:** reflow cards `{start, end, text, avg_logprob, no_speech_prob}` (post-A1, post-C1
  correction).
- **Output:** same cards minus dropped/collapsed ones; surviving suspicious cards gain
  `"flag": "<reason>"` in their `conf.json` row (e.g. `low_conf`, `music`). SRT unaffected by the flag.
- **Decode param:** `hallucination_silence_threshold=2.0` on `WMODEL.transcribe(...)`.

## Components / changes

1. **New `hallucination.py`** (pure stdlib, testable):
   - `BLOCKLIST` (moved here from generate.py + extended with more known phrases).
   - `is_repetition(text)` — within-card loop detector.
   - `drop_reason(card) -> str|None` — `"blocklist"` | `"repetition"` | `"music"` (the
     nsp>0.8 ∧ lp<-1.0 combo) | `None`.
   - `flag_reason(card) -> str|None` — weaker single-signal suspicion (kept, not dropped).
   - `collapse_runs(cards) -> cards` — merge runs of ≥4 near-identical consecutive cards.
2. **`generate.py`:** replace the inline `BLOCKLIST` drop with `hallucination.drop_reason`
   (drop) + `flag_reason` (annotate conf), then `collapse_runs` over survivors; add
   `hallucination_silence_threshold=2.0` to the transcribe call.
3. **`Dockerfile.builder`:** `COPY hallucination.py`.
4. **Tests:** `tests/test_hallucination.py` — every drop signal, the flag tier, repetition
   (within + across), and the "don't drop real dialogue / ≤3 repeats survive" guards.

## Edge cases and failure modes

| Case | Expected |
|---|---|
| Genuinely repetitive real line ("No no no no") | Within-card: only dropped if it's *almost entirely* the repeat; tune so short emphatic repeats survive. Across-card: ≤3 survive. |
| Low-conf but real quiet line (single weak signal) | Kept + flagged, never dropped. |
| Near-identical (punctuation/case differ) consecutive cards | Counted as duplicates for the run collapse (normalized compare). |
| Collapsed run timing | Keep the first card's start; extend its end to the run's last end. |
| Empty after drops | Fine (SRT may be short); never error. |

## Decisions taken

| Decision | Rejected | Why |
|---|---|---|
| Conservative drop (multi-signal) + flag weaker | Aggressive single-signal; flag-only | Definitive: don't delete real lines; still kill certain garbage. |
| Drop = blocklist ∨ repetition ∨ (nsp>0.8 ∧ lp<-1.0) | + compression-ratio gate | Three strong/combined signals; avoid over-dropping repetitive real lines. |
| Collapse runs of ≥4 identical | ≥2 (any dup) | Protects deliberate ≤3 repeats; still kills runaway loops. |
| `hallucination_silence_threshold` only | tune no_speech/log_prob; disable condition_on_previous_text | "Slight B2"; preserve context/name coherence. |

## Constraints

- Pure stdlib, deterministic, subgen image. No new deps.
- Must not regress A1 timing/conf or C1 correction (B1 runs after both, on the cards).

## Open questions (risks)

- [ ] Exact within-card repetition thresholds tuned in implementation against real data (low risk).
- [ ] `hallucination_silence_threshold` value (2.0) validated at rollout on a sample (decode-time, not unit-testable).
