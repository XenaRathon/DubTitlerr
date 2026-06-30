# Spec — A1: Sentence-split & re-timing reflow (`generate.py`)

> Step A1 of the DubTitlerr transcription-quality build. Grilled on top of the
> brainstorming session (sequencing A1 → C1 → B1 → D1). Project north-star:
> the dubtitles should be **as accurate and as close to the definitive English-dub
> subtitle as possible** — accuracy beats speed.

## Context and problem

Whisper emits multi-sentence, multi-speaker mega-segments: on `One Pace S19E16`
single cards run 7+ seconds and span 4 sentences / 2 speakers, and in noisy
stretches punctuation collapses into a run-on wall that breaks **mid-sentence
across segment boundaries** (e.g. *"everyone is going / to die"*). The result is
unreadable, mistimed cards. A1 restructures whisper's word-level output into
clean, well-timed subtitle cards before the name/hallucination/mux steps run.

## Acceptance criteria (verifiable)

Every card written to the `.srt` MUST satisfy:

- [ ] ≤ 42 characters per line.
- [ ] ≤ 2 lines (≤ ~84 visible chars).
- [ ] Reading speed ≤ 17 cps (visible chars ÷ display seconds), when trailing
      silence allows (see hold-time rule).
- [ ] Display duration ≥ 0.83 s and ≤ 7.0 s.
- [ ] ≥ 2-frame (~0.083 s) gap before the next card (no overlap).
- [ ] Card `start` == the spoken onset of its first word (never earlier — no
      early reveal of a later line / punchline).
- [ ] No card contains two words separated by > 0.5 s of silence.
- [ ] `conf.json` has exactly one entry per emitted card, in time order.
- [ ] Verifiable on a re-run of `S19E16`: zero cards > 7 s; the
      *"everyone is going / to die"* class of mid-sentence break is gone.

## Out of scope (explicit)

- The name-correction logic (`correct()`/`fix_word()`) — that's **C1**. A1 leaves
  the existing correction wired and applies it to each final card's text.
- The hallucination confidence-gate — that's **B1**. A1 keeps the existing
  `BLOCKLIST` drop (applied per-card after reflow) but adds no new gating.
- Muxing / signs / fonts — that's **D1**.
- Whisper decode parameters (model, beam, VAD) — unchanged in A1 except where a
  param is required to expose word probabilities (already enabled).

## Data contracts

- **Inputs:** faster-whisper segments produced with `word_timestamps=True`:
  per word `word.start`, `word.end`, `word.probability` (linear 0–1); per segment
  `segment.avg_logprob`, `segment.no_speech_prob`.
- **Outputs (unchanged filenames):**
  - `<stem>.eng.dubtitles.srt` — SRT cards built by the reflow.
  - `<stem>.dubtitles.conf.json` — JSON list, **one object per card**, time-ordered:
    `{start, end, avg_logprob, no_speech_prob, text}`.
- **Per-card confidence (the B1/C3 contract):**
  - `avg_logprob` = mean of `ln(word.probability)` over the card's words
    (preserves the existing log-space semantics; B1 threshold `lp < -0.8` stays meaningful).
  - `no_speech_prob` = **max** `no_speech_prob` among the whisper segments whose
    time range overlaps the card (worst-case, conservative for hallucination drop).
  - `text` = the final card text (post wrap).
- **External dependencies:** none. Pure Python stdlib (`re`) inside the existing
  subgen CUDA image — no new packages.

## Algorithm

1. **Flatten:** collect all words (text, start, end, probability) across all
   segments in order; remember which source segment each word came from (for
   `no_speech_prob`).
2. **Span split (hard guard):** start a new span wherever the gap between word[i].end
   and word[i+1].start > **0.5 s**. Spans never glue across pauses.
3. **Card segmentation within a span:**
   - Primary: split at sentence-final punctuation `. ! ? …`.
   - If a resulting piece exceeds 2 lines × 42 chars **or** > 7 s: break it by, in
     order, (a) the largest internal word-gap, (b) a clause delimiter `, ; :` nearest
     the midpoint, (c) plain word-boundary wrap at the char limit.
   - Wrap each final card to ≤ 2 lines, ≤ 42 chars/line (balance the two lines).
4. **Timing:** `start` = first word onset; `end` = last word offset. Then:
   - If duration < 0.83 s **or** cps > 17: extend `end` into trailing silence, up to
     2 frames before the next card's `start`, capped at 7 s. Start is never moved.
   - If still < 0.83 s or > 17 cps after extension: accept the residual.
   - Enforce the ≥ 2-frame gap (trim `end` if it would overlap the next `start`).
5. **Per-card text post-processing:** apply the existing `BLOCKLIST` (drop a card
   that is a known music/silence hallucination phrase) and the existing `correct()`
   name pass (to be replaced in C1).
6. **Write** the `.srt` and the per-card `conf.json`.

## Edge cases and failure modes

| Case | Expected behavior |
|---|---|
| Word with `None` start/end | Interpolate from adjacent words / segment bounds; never crash, never drop the word silently. |
| Card text empty after strip | Skip the card (no SRT entry, no conf entry). |
| Single sentence > 7 s with no internal gap/punctuation | Force a break by largest micro-gap → clause → word-wrap; each card still ≤ 7 s and ≤ 2 lines. |
| Sung dub lyrics (whisper transcribes songs as dialogue) | Treated identically; the > 0.5 s gap rule naturally breaks lyric lines at musical pauses. |
| Segment with no words | Skipped. |
| Last card of file (no "next card") | Hold-time extension capped only by 7 s. |
| Trailing silence shorter than needed | Extend as far as it allows, then accept residual overspeed. |

## Decisions taken

| Decision | Rejected alternative | Why |
|---|---|---|
| Netflix profile (42×2, 17 cps, 0.83–7 s, 2-frame gap) | Looser / tighter | Proven pro-subtitle norms; matches player/user expectations. |
| Full reflow (discard whisper boundaries, re-segment) | Split-only; reflow-within-pauses | Only full reflow fixes mid-sentence cross-boundary breaks. |
| Hard break at gap > 0.5 s | > 1.0 s / > 2.0 s | Keeps cards tight to delivery; avoids revealing a punchline/spoiler before it's spoken. |
| Overflow cut: largest pause → clause punct → word-wrap | Clause-first; plain wrap | Consistent with timing-preservation; degrades gracefully. |
| Hold time: extend END into trailing silence only | Accept as-is; extend both ways | Improves readability without moving the start (no early reveal). |
| Recompute confidence per card | Inherit from source segment; drop it | Precise per-card signal for B1/C3; serves the "definitive dubtitles" bar. |

## Constraints

- Runs inside the subgen CUDA image; **no new dependencies** (stdlib only).
- Fully deterministic (same input → same cards).
- Must not regress the existing crash-resilience (`.fail` poison marker), idempotency
  skips, or `OUTPUT_ROOT` sidecar redirection in `generate.py`.

## Open questions (risks)

- [ ] Line-balancing algorithm for 2-line wrap is unspecified beyond "≤42/line";
      plan.md will pick a concrete balancer (e.g. minimize max line length). Low risk.
- [ ] `word.probability` → `ln()` of 0 is `-inf`; clamp tiny probabilities (e.g.
      `max(p, 1e-4)`) before `ln`. To be handled in implementation. Low risk.
