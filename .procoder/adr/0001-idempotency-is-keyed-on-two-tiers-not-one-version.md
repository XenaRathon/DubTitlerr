# 0001 — Idempotency is keyed on two tiers, not one version

Status: accepted
Date: 2026-08-24

## Context

Since the pipeline gained a version stamp, `PIPELINE_VERSION` has been a single
global integer and `stamp_valid()` has rejected any stamp below it. That made every
change equal: a glossary correction that alters only what a caption says invalidated
the library exactly as hard as a decoder change, forcing full re-transcription. On a
GTX 1050 Ti that is measured in GPU-days. The 2026-08-21 architectural review ranked
it the largest recurring cost in the system.

Two facts sharpened the fork. First, the raw Whisper word list is never persisted —
`generate.py` requests `word_timestamps=True` and the words die after reflow — so
changes at the word layer (punctuation, card splitting) genuinely cannot be re-run
without the GPU. Second, and discovered only during adversarial review of the spec,
`tools/reapply_glossary.py` already re-applies a glossary from `conf.json` with "no
GPU, no LLM, no re-transcription". The cheapest and most frequent case was already
solved; nothing recorded that it had happened, and nothing ran it automatically.

A live measurement the same day found 3,889 videos against 813 stamps — 576 at v4,
236 at v2, 1 at v3 — showing the library had been sitting several versions deep in
inconsistency without anything reporting it.

## Decision

Idempotency is keyed on **two** version constants, `TRANSCRIBE_VERSION` and
`TEXT_VERSION`, adopted at 4 and 5 respectively so the 576 live v4 stamps read as
transcribe-fresh and text-stale and migrate at watch-gated pace.

Rejected alternatives:

- **Per-stage versioning**, one constant per pipeline stage with a dependency graph.
  More precise, and the precision is not the problem: a wrong edge in that graph
  silently skips a stage that needed to run. Silent staleness is the exact bug class
  this work exists to remove, and the codebase had just produced three independent
  examples of it in a single day.
- **Keeping one global version plus a manual `--reuse-transcript` flag.** Zero design
  risk, but it puts the invariant in the operator's head. Two silent-degradation
  bugs in the same review were "configuration that looked applied and was not"; this
  would have been a third by construction.
- **Hashing the glossary file to decide transcription staleness.** Intuitive and
  wrong: the glossary reaches the decoder by exactly one route, `initial_prompt`,
  while `mine_glossary.py` appends `hard_fixes` on every sweep of a watched show.
  Hashing the file would re-queue an entire show for the GPU on edits that changed
  nothing about the decoder input. Classification compares the stored prompt string
  instead.

The boundary rule: everything computed from `(words, segments, conf.json, fansub,
LLM)` is text; everything computed from audio or the decoder is transcription. The
one genuinely undecidable case — an operator changing decoder-affecting configuration
— has no mechanical signal and is carried by documentation in both constants'
docstrings, the same register that kept the v2→v3→v4 bumps honest.

## Consequences

Easier: a glossary or punctuation fix ships for CPU-minutes instead of GPU-hours,
which in turn makes correctness work cheap enough to do. The per-tier staleness count
gives the operator a number for "how far behind is the part of the library I am not
watching", which did not exist while 236 episodes sat at v2. Deferred work like
repair-without-a-fansub-anchor becomes a text-tier change rather than a full sweep.

Harder, and paid deliberately: a new `words.json` sidecar per episode, roughly
200-300 KB plus segment records, which must carry per-segment `no_speech_prob` and
the episode's `audio_duration` because neither is recoverable from the word list. The
sidecar has to follow the `out_for()` write / raw-path read convention exactly; get
that half-right and the cache misses silently and every episode re-transcribes
forever. Two constants must be kept honest by hand where one was before, and the
failure mode of getting a classification wrong is an episode that is quietly never
re-transcribed. The `words_missing` and per-tier counters exist so that failure is
visible within one sweep rather than one month.

This decision does not converge the library to a uniform state. `watch_queue.py`
deliberately never queues unwatched shows, so the honest invariant is that the
library converges **ahead of the viewer**, with the residual readable as a number.
