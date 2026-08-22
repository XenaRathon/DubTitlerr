# Acquire decision cache: stop re-deciding what was already decided

**Status:** design, reviewed (GLM round 3 + self-rebuttal), amendments folded in
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

**Exception, and the spec was wrong without it: the `canonical` payload.** The *verdict label*
is stable under new episodes. The `canonical` that an `apply` verdict writes into `hard_fixes`
is not — it is resolved against today's wiki title set, and `fetch_titles` re-fetches on a
30-day TTL (`WIKI_TTL`, glossary_verify.py:52). A page rename leaves the cached canonical
pointing at a title the wiki no longer ships, and because a cache hit never re-runs
`_resolve_tokens`, that wrong string would be written into `hard_fixes` **forever** — precisely
the silent-wrong-forever failure this design claims to avoid.

Guard, staying per-token: on a cache hit, check the stored canonical is still in `norm_titles`,
which `acquire()` already computes. If it is not, treat the entry as a miss and re-run the
pipeline for that token alone.

    entry = cache.get(token)
    if entry and entry.get("canonical") \
            and normalize_title(entry["canonical"]) not in norm_titles:
        entry = None                  # stale canonical -> re-resolve this token only

O(1) against a set that already exists, costs nothing when nothing was renamed, and invalidates
only the entries whose canonical actually disappeared. A title-set hash was considered and
rejected: it bumps on any rename anywhere and re-runs the whole 71% `escalate` cost, which is
the "silently invalidating everything" half of the failure this section rejects.

It detects *disappearance*, not *re-resolution* — a canonical that changes to a different valid
title is not caught. That is acceptable: a genuine canonical correction is a case a human should
re-litigate, not one the cache should quietly swap.

### 2.2 Junk is sticky, not permanent

Caching `junk` forever is a one-way door, and One Pace is the show that punishes it: a token
seen twice across 20 episodes may be a real name that recurs heavily 200 episodes later.

So the cache stores `count` with the verdict, and a `junk` token re-enters the queue when its
occurrence count grows materially past what it was when the verdict was made
(`count > cached_count * JUNK_RECHECK_GROWTH`, default 3). Cheap, deterministic, and it makes
the cache sticky without making it a trap.

A `junk` verdict recycles when its reason is **frequency-derived** — conditional on corpus size
or coverage, and therefore able to flip given more data. The structural reasons
(`english-word`, `already-canonical`, `sentence-initial-only`) never recycle: wordlist
membership, exact-match equality and positional distribution are stable under more episodes.
Everything else (`below-floor`, `unseen-needs-evidence`, `share-too-close`,
`transcript-new-term`, `growth-over-cap`) recycles. Naming only `below-floor` — as an earlier
draft did — would have permanently junked four other corpus-derived verdicts, defeating this
section's own purpose for exactly the long-tail names it exists to rescue.

**Anchor-landscape recycle.** A `below-floor` verdict depends not only on the token's own count
but on whether a near-miss of it sits in `anchor_terms`, and that set grows as `apply` verdicts
accumulate. Store `floor_anchor` (the anchor the floor was based on, if any) on the entry; on a
cache hit for frequency-derived junk, recompute `settled_target` against the current anchors and
treat a difference as a miss. Per-token, so only entries whose own anchor landscape moved are
invalidated — never the whole junk bucket. This fails toward `flag` rather than `apply`, so it
is a recall gap, not a correctness one.

### 2.3 Per-episode harvest cache — removes most of the remaining 27%

`harvest_candidates` and `context_lines` both walk every episode. Cache the per-episode harvest
keyed on `(path, size, mtime)` — the same triple `common.stamp_valid()` already uses for the
`.dubtitles.done` stamp.

**Correction (review, 2026-08-21):** an earlier draft of this spec described the mount as
`cache=none,nobrl,actimeo=1`. `actimeo` is an NFS option and is **not** in the CIFS mount; the
live options are `vers=3.0,uid=1000,gid=100,file_mode=0777,dir_mode=0777,nobrl,cache=none`. The
number was carried over from a *different* CIFS mount on the laptop. This project runs NFS on
fasc and CIFS on 3200g, and conflating them is the exact class of error the reviews keep
catching.

**The reuse is not as safe as "same triple" implies, and the reason is the direction of the
decision.** `stamp_valid()` uses the triple to decide whether to *redo expensive work*: a stale
mtime causes a needless re-transcription — wasteful, visible, correct. This cache would use it
to decide whether to *skip reading a file*: a stale mtime drops an episode from the corpus
silently. Fail-loud versus fail-silent, same key, same filesystem. The `size` component catches
most real edits, so the residual risk is a same-size content change, which for a regenerated
`conf.json` is possible but unlikely. Mitigation: on any `stat` error or ambiguity, re-read
rather than trusting the cache — the default must be the expensive branch.

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
| a renamed wiki canonical invalidates only that entry | drop one title from `fetch_titles`; only entries whose canonical normalised to it miss |
| a junk entry re-queues when its near-miss becomes an anchor | an unrelated `below-floor` token stays cached |
| structural junk never recycles at any count | `english-word`, `already-canonical`, `sentence-initial-only` |
| every non-structural junk reason recycles | not just `below-floor` |
| a stat error re-reads rather than trusting the cache | the default branch is the expensive one |
| second run is materially faster | end-to-end assertion, not a unit mock |
