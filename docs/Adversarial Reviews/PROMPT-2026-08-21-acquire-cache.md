# Review prompt — acquire decision cache

Third review on **DubTitlerr**. Your previous two are in this same directory
(`GLM-2026-08-21-glossary-and-watchgate.md`) — the Round 1 findings on `apply_results` landed
and shipped; the Round 2 corroboration guard was refuted on measurement and did not. Both are
worth skimming for context on how this codebase fails.

**Spec under review:** `docs/superpowers/specs/2026-08-21-acquire-decision-cache-design.md`

## The situation

`glossary_acquire.py` runs once per show per sweep from `gen_loop.sh`. On One Pace (462
episodes) it has **never completed** — killed by timeout on three consecutive sweeps, first at
600 s, then at 1800 s after the limit was raised. Because it never completes, it contributes
nothing, and each sweep pays 30 minutes for that nothing.

Profiled in-container against the live corpus:

    harvest_candidates (462 conf.json over CIFS)      35.3 s    5%
    fetch_titles (8,109 titles, disk-cached)           0.0 s    0%
    _resolve_tokens (8,199 tok x 8,109 titles)        44.7 s    6%
    propose -> 7,695 proposals                         0.5 s    0%
    context_lines #1 (462 files, 597 tokens)         115.3 s   16%
    escalate (371 LLM calls @ ~1.3 s)                470.7 s   71%
    context_lines #2 (462 files, flagged terms)      >420 s    killed, still running

`settled` (= `known | acquired`) is **107 terms against 8,199 harvested**, so ~99% of the work
repeats every sweep.

## The one rule

**Verify every factual claim against the source before accepting or attacking it.** This author
has been wrong about exactly this kind of claim repeatedly — most recently by checking the
repo's glossaries and reporting "the other 14 are clean" when the *deployed* copies had 8 of 15
damaged. Same filename, different artifact, opposite answer. When a claim matches what you'd
expect, that is when to check it hardest.

Anchors worth confirming: `glossary_acquire.acquire()` (the phase order), `harvest_candidates`,
`context_lines`, `_resolve_tokens`, `escalate`, `source_gate`, and `common.stamp_valid()` (the
`(path, size, mtime)` triple the harvest cache proposes to reuse).

## Attack these specifically

1. **"Absence is the cache miss."** The spec deliberately has no fingerprint, no TTL and no
   versioned key, arguing that a token's verdict does not change when new episodes arrive.
   **Find the case where that is false.** Wiki content changes, `propose`'s thresholds change,
   a human overturns a ruling, a show's glossary is edited by hand. Which of these silently
   serves a wrong answer forever, and what is the cheapest correct guard — given that a
   fingerprint's own failure modes are what the spec is avoiding?

2. **`(path, size, mtime)` over CIFS.** The harvest cache reuses the `.dubtitles.done` triple.
   But this library is mounted over CIFS with `cache=none,nobrl,actimeo=1`. Is mtime trustworthy
   enough there for a cache key? `stamp_valid()` uses it to decide whether to *redo expensive
   work*, which fails safe; this cache would use it to decide whether to *skip reading a file*,
   which fails silent. Are those the same risk? If not, say what changes.

3. **Junk recycling at 3x growth.** Frequency-derived `junk` re-enters the queue when a token's
   count exceeds `cached_count * 3`; structural junk (`english-word`) never recycles. Is 3
   defensible, is growth the right trigger at all, and is the structural/frequency split clean —
   or is there a `junk` reason that looks structural and is not?

4. **Does the cache change what the pipeline decides?** It is meant to be purely a performance
   change. Find a path where caching a verdict produces a *different* glossary than not caching
   it — ordering effects, `anchor_terms` growing between runs, `escalate` seeing a smaller
   proposal set and therefore different context.

5. **The deferred 94% proposal rate.** `propose` returns 7,695 proposals from 8,199 tokens. The
   spec defers this on the grounds that the cache makes it cost nothing per sweep. Is deferring
   right, or does a near-pass-through `propose` mean the cache is about to memoize a large pile
   of *wrong* verdicts — making a bad decision permanent instead of merely repeated?

6. **What did the spec miss entirely?**

## Output

Append to `docs/Adversarial Reviews/GLM-2026-08-21-glossary-and-watchgate.md` under a
`# Round 3 — acquire decision cache` heading.

Tag each finding `[CONFIRMED]` (checked in source), `[REFUTED]` (with the file:line that
disproves it), or `[UNVERIFIABLE]` (and why). Rank by cost of being wrong. Short is fine — the
mechanism matters more than the prose. If something is right, say so in one line and move on.
