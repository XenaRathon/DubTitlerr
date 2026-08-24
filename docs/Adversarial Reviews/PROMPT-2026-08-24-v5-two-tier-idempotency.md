# Review prompt — v5 two-tier idempotency

Fourth review on **DubTitlerr**. Your previous three are in this directory
(`GLM-2026-08-21-glossary-and-watchgate.md`, and the VAD hang-trim round where you
recommended dropping the feature, proposed the §5 rescue, and identified the §6
successor item — all three of your calls there held up). Worth skimming for how this
codebase fails.

**Spec under review:** `.procoder/specs/v5-two-tier-idempotency.md`

**Prior art the spec builds on, both in this repo:**
- `docs/superpowers/specs/2026-08-21-vad-hang-trim-design.md` — §6 is [S-6] in the spec
- `docs/superpowers/specs/2026-08-21-project-review-brief.md` — §6.4 is [S-5], and its
  numbers are now superseded (see below)

## Deliverable

**Write your review to a markdown file in `docs/Adversarial Reviews/` named
`GLM-2026-08-24-v5-two-tier-idempotency.md`.** Do not return it as chat output for
copy-paste — the file is what gets read. Structure it however serves the argument, but
every finding needs a file:line anchor or a measurement, and state plainly which of your
findings you would block the build on versus merely note.

## The situation

`PIPELINE_VERSION` (`common.py:127`, currently 4) is one global integer. `stamp_valid()`
(`common.py:208-217`) rejects any stamp below it, so a glossary fix that needs only a
re-mux invalidates the library exactly as hard as a decoder change. The spec splits it
into `TRANSCRIBE_VERSION` and `TEXT_VERSION`, and makes the cheap tier possible by
persisting the Whisper word list — which today dies in memory after reflow
(`generate.py:679` requests `word_timestamps=True`; nothing writes the words).

Measured on the live library 2026-08-24, from the VM102 NFS mount:

    video files                     3,889
    stamps                            813      (576 at v4, 236 at v2, 1 at v3)
    orphaned stamps                    67
      match a video by size            46
      match by size AND mtime          31

**The review brief's "285 of 861 orphaned" is wrong** — that is the number this spec was
originally motivated by, and it did not survive measurement. Treat that as a live warning
about the rest of the brief's figures.

Hardware: GTX 1050 Ti 4 GB on VM102, shared with `llama-embed` (714 MiB measured).
`large-v3-turbo` int8 peaks ~1.4 GB. Repair LLM is remote (nanbeige4.2-3b on a 1060).

## The one rule

**Verify every factual claim against the source before accepting or attacking it.** This
author's failure mode is a defaulted value silently answering the question asked — the VAD
design records two of its own measurements invalidated by exactly that, including a
`.get("source_end", c["end"])` fallback that guaranteed a zero result and was reported as a
refutation. When a claim matches what you'd expect, check it hardest.

Anchors worth confirming: `common.stamp_valid`, `common._stamp_matches_file` (the
`size` + `mtime < 1.0` comparison), `common.py:173-175` (the stamp doc, including the
`stages` field that `mux.py:354` writes and nothing reads), `mux.py:325-326` (stem-based
lookup), `generate.py:112` and `:684` (glossary → `initial_prompt` → Whisper),
`repair.overlap_ref`, `generate._card_word_probs`, `generate.park_stale_sidecars`,
`watch_queue.py`, `qc.Recorder`, `hallucination._tick`.

## Attack these specifically

1. **Is two tiers the right cut, or does it just move the problem?** Per-stage versioning
   was rejected for creating a dependency graph whose wrong edge silently skips a stage.
   Two tiers has the same failure in miniature: anything misclassified as text-tier that
   actually depends on transcription is now silently stale forever. Enumerate what sits
   near that boundary and say whether the classification is decidable at all.

2. **`[S-3]`, the glossary hash — the load-bearing claim.** The glossary feeds
   `initial_prompt`, so it is a transcription input. The spec applies glossary changes
   through the text tier immediately and marks the episode transcription-stale for later.
   That means the library is permanently in a state of "corrected but not re-prompted."
   Is the string-correction path actually able to recover what a better `initial_prompt`
   would have produced, or does this design bank a permanent quality deficit and call it
   a queue depth?

3. **`[S-5]`, orphan reclaim — 46 by size vs 31 by size+mtime.** 15 orphans match size but
   not mtime. What produces that? Is size-only matching safe on a 3,889-file library, and
   what is the actual probability of two distinct anime episodes sharing a byte count?
   The spec currently does not choose; tell us which comparison you'd use and why.

4. **`[S-2]`, the word list sidecar.** ~200 KB × N, written per episode, on NFS. Is
   round-tripping through JSON lossless for what `reflow` consumes — specifically the
   `seg` field that `_dejitter()` depends on (`reflow.py:218-236`)? A text-tier re-run
   that produces different cards than the original run is a silent regression the
   acceptance criteria may not catch.

5. **The 236 stamps at v2.** A third of the stamped library is two versions behind and has
   been for some time, apparently unnoticed. What does that say about whether *any*
   version-based invalidation scheme in this codebase actually drains?

6. **What is missing from the spec entirely.** Prior rounds found the highest-value items
   this way — you identified the §6 successor when the topic was hang trimming. The
   review brief's §6.5 (no cross-host locking) and §6.2 (63 env vars) are explicitly out
   of scope; say if either is load-bearing for *this* change rather than in general.

## What a useful review looks like

Refute, don't validate. If the design is sound, say which specific claim you tried hardest
to break and what stopped you — a review that agrees without naming its strongest attempted
counter-argument is not evidence. If any acceptance criterion in the spec would pass while
the underlying behaviour is broken, that is the single most valuable thing you can report.
