# Acquire decision cache: stop re-deciding what was already decided

**Status:** design, awaiting review
**Raised:** 2026-08-21, after `glossary_acquire.py` was killed by a timeout on three consecutive
sweeps and has never once completed on One Pace
**Related:** `2026-08-21-glossary-integrity-design.md`

---

## 1. The measurement

Profiled in-container against the live One Pace corpus (462 episodes), phase by phase:

| phase | cost | share |
|---|---|---|
| `harvest_candidates` (462 `conf.json` over CIFS) | 35.3 s | 5% |
| `fetch_titles` (8,109 titles, disk-cached) | 0.0 s | 0% |
| `_resolve_tokens` (8,199 tokens x 8,109 titles) | 44.7 s | 6% |
| `propose` -> **7,695 proposals** | 0.5 s | 0% |
| `context_lines` #1 (462 files, 597 tokens) | 115.3 s | 16% |
| **`escalate` — 371 LLM calls** | **470.7 s** | **71%** |
| `context_lines` #2 (462 files, flagged terms) | >420 s, killed | — |

Two facts do the damage.

**Nothing is remembered.** `settled` is `known | acquired` — **107 terms against 8,199
harvested**. Every sweep re-derives ~99% of the same conclusions, including all 371 LLM calls,
and pays ~1.3 s each to reach a verdict it already reached last time.

**The corpus is read three times.** `harvest_candidates` walks all 462 episodes, then
`context_lines` walks them again for escalation context, then again to attach evidence to
flagged proposals. The second `context_lines` call is the worst of the three — it was still
running after 7 minutes when the profile was killed, because its token list is drawn from the
flagged set rather than the 597 close pairs, and the scan is files x tokens.

The first scrape being expensive is fine and expected. **This is not a first-scrape cost — it is
the steady-state cost**, and it exceeds the stage's timeout, so the stage never completes and
therefore never contributes anything at all.

## 2. Design

### 2.1 Per-token decision cache — removes the 71%

A sidecar beside the glossary, `<show>.acquire-cache.json`, mapping token to verdict:

```json
{ "gum-gum": {"verdict": "settled", "canonical": "Gum-Gum", "source": "wiki",  "count": 41},
  "hockey":  {"verdict": "pending", "canonical": "Haki",    "source": "human", "count": 112},
  "the":     {"verdict": "junk",    "reason": "english-word",                  "count": 9314},
  "spandom": {"verdict": "junk",    "reason": "below-floor",                   "count": 1} }
```

`junk` is a verdict value, not a separate structure, and it is by far the largest bucket — it
absorbs most of the 7,695 proposals.

**No invalidation logic, deliberately.** A token's verdict does not change when new episodes
arrive; new tokens are simply absent from the cache. **Absence is the cache miss.** There is no
corpus fingerprint, no TTL, and no versioned key to get wrong — the failure mode of a stale
fingerprint (silently serving an old answer, or silently invalidating everything) is exactly the
class of bug this project keeps finding.

### 2.2 Junk is sticky, not permanent

Caching `junk` forever is a one-way door, and One Pace is the show that punishes it: a token
seen twice across 20 episodes may be a real name that recurs heavily 200 episodes later.

So the cache stores `count` with the verdict, and a `junk` token re-enters the queue when its
occurrence count grows materially past what it was when the verdict was made
(`count > cached_count * JUNK_RECHECK_GROWTH`, default 3). Cheap, deterministic, and it makes
the cache sticky without making it a trap.

`junk` for a *structural* reason (`english-word`) never recycles — that fact cannot change.
Only frequency-derived verdicts (`below-floor`) do.

### 2.3 Per-episode harvest cache — removes most of the remaining 27%

`harvest_candidates` and `context_lines` both walk every episode. Cache the per-episode harvest
keyed on `(path, size, mtime)` — the same triple `common.stamp_valid()` already uses for the
`.dubtitles.done` stamp, so the idiom is established and its failure modes are known.

`context_lines` then reads from the cached per-episode text rather than re-opening 462 files,
collapsing three corpus scans into one.

### 2.4 What does NOT change

- `propose`, `decide`, `source_gate`, `escalate` keep their current logic. This spec makes them
  run on the ~1% of tokens that are actually new; it does not re-tune what they decide.
- The human review queue is untouched. A `pending` verdict is the existing `flagged` rung.

## 3. Explicitly out of scope

**RAG.** Retrieving prior adjudications as few-shot examples for genuinely new terms is a real
idea and is recorded for a later session — but it belongs at the adjudication step and nowhere
near token matching, which is orthographic rather than semantic. Embeddings are actively bad at
the discrimination that matters here: `Raftel`/`Ratel`, `Kaido`/`Kaidou` and `Jabra`/`Jabari`
are near-identical in vector space, and separating them is the whole job. For a token that
already has a verdict, a dict lookup is O(1), exact, and needs no model.

The cache removes ~99% of the work; RAG could only improve accuracy on what survives it. Build
this first, then judge whether RAG earns its place on the remainder.

**Re-tuning `propose`'s 94% proposal rate.** 7,695 proposals from 8,199 tokens means `propose`
is close to a pass-through, and the expensive stages are being asked to reject what a cheap rule
should never have raised. That is worth its own investigation, but the cache makes it cost
nothing per sweep, so it stops being urgent.

## 4. Testing

| test | asserts |
|---|---|
| a cached verdict short-circuits the LLM | second run makes zero `escalate` calls for known tokens |
| a new token still reaches the pipeline | absence is a cache miss |
| junk recycles on material growth | `count` past `cached_count * 3` re-queues it |
| structural junk never recycles | `english-word` stays junk at any count |
| harvest cache keyed on (path, size, mtime) | an edited episode is re-read; an untouched one is not |
| a corrupt cache degrades to a full run | never raises, never blocks a sweep |
| cache write is atomic | temp + `os.replace`, group-writable per `common.SIDECAR_MODE` |
| second run is materially faster | end-to-end assertion, not a unit mock |
