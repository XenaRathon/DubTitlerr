# Acquire decision cache — fix draft for Round 3 findings

**Status:** draft amendments to `2026-08-21-acquire-decision-cache-design.md`
**Raised:** 2026-08-21, after the Round 3 adversarial review
(`GLM-2026-08-21-glossary-and-watchgate.md`, §Round 3 + §Self-rebuttal)
**Scope:** only the gaps that _survived_ the self-rebuttal. The refuted/overstated
findings (the title-set hash, the `len(anchors)` recycle trigger, the `context_lines` #2
"not addressed" claim, the mtime-staleness-under-`cache=none` claim) are deliberately
absent — they were wrong and the spec should not absorb them.

The guiding constraint, restated from the spec's own §2.1: **no global fingerprint, no TTL,
no versioned key to maintain by hand.** Every fix below is _per-token_ and _per-entry_ —
the cache entry stores the denominator its verdict was conditional on, and a cache hit
re-checks exactly that denominator, never the whole cache. This is the spec's
"absence is the cache miss" principle applied to the _payload_ (canonical, floor), which
the original spec covered only for the _label_.

---

## Fix A — stale-canonical detection (closes Attack 1)

### The gap (after rebuttal)

The cache stores `canonical` verbatim (spec §2.1). `fetch_titles` has a 30-day TTL
(`glossary_verify.py:52`) and _will_ return a different title list. A wiki rename that
changes a title's _normalised_ form (rare — disambiguator-only renames are already absorbed
by `normalize_title()`, glossary_acquire.py:33–39) leaves the cached canonical pointing at a
title the wiki no longer ships. `apply_proposals` (glossary_acquire.py:438–470) then writes
that stale canonical into `hard_fixes` on the next `apply` verdict for that token.

Frequency is low (once per show per decade, and a human usually wants to re-litigate it
anyway). Blast radius is one token per renamed title. But the cache has _no_ detection path
at all, so the wrong canonical persists across sweeps until a human notices.

### The fix (per-token membership check)

`acquire()` already computes `norm_titles = {normalize_title(t) for t in titles ...}`
(glossary_acquire.py:799). On a cache hit, re-verify the stored canonical is still present:

```python
# In the cache-hit path (proposed code, inside the cache lookup the spec §2.1 introduces):
entry = cache.get(token)
if entry is not None:
    canon = entry.get("canonical")
    if canon and normalize_title(canon) not in norm_titles:
        # The wiki no longer ships this canonical under this name. Treat as a cache
        # miss: re-run the pipeline for this token. The new canonical lands in the
        # cache on this sweep, overwriting the stale entry.
        del cache[token]          # or: cache.pop(token, None); treat token as absent
        entry = None
    # ... else serve the cached verdict
```

**Why this and not a title-set hash:** a global hash (my original Attack 1 proposal) bumps
on _any_ rename across _any_ page and re-runs the entire 71% `escalate` cost for one show
— the exact "silently invalidating everything" failure the spec §2.1 rejects. The
membership check is O(1) per cached token, invalidates _only_ entries whose canonical
actually disappeared, and costs nothing on the common case (no renames).

**What it does NOT catch:** a rename that changes a title's normalised form _to a different
valid title that the token should now resolve to instead_. The membership check only detects
_disappearance_, not _re-resolution_. This is acceptable: the token's own count and the
`settled_target`/`source_gate` gates still run on a cache miss, and a genuine canonical
correction (Raftel → Laugh Tale) is the case a human wants to re-litigate. If full
re-resolution is wanted later, store the resolved-score on the entry and re-resolve only
tokens whose `best_title` changed — but that is a later optimisation, not needed for
correctness.

### Spec amendment

Add to §2.1, after the "No invalidation logic, deliberately" paragraph:

> **Exception: the `canonical` payload.** A verdict label is stable under new episodes,
> but the `canonical` an `apply` verdict writes into `hard_fixes` is resolved against
> today's wiki title set, which `fetch_titles` re-fetches on a ~30-day TTL. A wiki rename
> that changes a title's normalised form leaves the cached canonical pointing at a title
> the wiki no longer ships. On a cache hit, re-verify the stored canonical is still present
> in `norm_titles` (which `acquire()` already computes); if not, treat the entry as a miss
> and re-run the pipeline for that token. This is per-token and O(1), never a global
> fingerprint — only entries whose canonical actually disappeared are invalidated.

Add to §4 (Testing):

| test                                                         | asserts                                                                                                                                   |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| a renamed wiki canonical invalidates only the affected entry | remove one title from `fetch_titles`'s output; only cache entries whose `canonical` normalised to that title miss; all others stay cached |

---

## Fix B — floor-flip detection (closes Attack 4)

### The gap (after rebuttal)

`propose`'s floor depends on `settled_target`: if a token's near-miss is in `anchor_terms`,
the floor is `NEAR_MISS_MIN_COUNT` (2); otherwise `MIN_COUNT` (3) (glossary_acquire.py:574–576).
`anchor_terms` = `names ∪ hard_fixes.values()` (glossary_acquire.py:430–436), and
`hard_fixes.values()` grows as `apply` verdicts accumulate. A token junked as `below-floor`
at count 2 (floor 3) would, once a near-miss of it lands in the anchor set, become
apply-eligible (floor 2) — but the cached `below-floor` verdict is served verbatim and the
floor change is never observed.

The spec's §2.2 recycle rule (`count > cached_count * 3`) does not catch this: the token's
_own_ count didn't change; the _anchor set_ did. After rebuttal this is a **recall gap**
(missed acquires of rare long-tail names), not a correctness gap — the re-evaluation would
mostly produce another `flag`, not an `apply`, because count-2 tokens are in the noise band
the floor was split to be cautious about (D4 comment, glossary_acquire.py). But it is still
a gap: the cache freezes the floor at its pre-anchor value.

### The fix (per-token anchor tracking)

Store the specific anchor (if any) the floor was conditional on, on the cache entry. On a
cache hit, re-check whether that anchor — or a _new_ near-miss anchor — is now present:

```python
# Cache entry shape (extends spec §2.1):
# {"verdict": "junk", "reason": "below-floor", "count": 2,
#  "floor_anchor": None}          # no anchor was near when this was decided

# On a cache hit for a below-floor / unseen-needs-evidence junk entry:
if entry["verdict"] == "junk" and entry["reason"] in FREQUENCY_REASONS:
    cached_anchor = entry.get("floor_anchor")
    current_anchor = settled_target(token, entry.get("canonical", ""), anchors)
    if current_anchor != cached_anchor:
        # The anchor landscape changed under this token. Re-run the pipeline for it.
        del cache[token]
        entry = None
```

where `FREQUENCY_REASONS` is the set from Fix C below.

**Why this and not `len(anchors)` growth:** `len(anchors)` grows on every `apply`, so a
global anchor-count trigger would invalidate _every_ `below-floor` junk entry on every
`apply` verdict — the same "silently invalidating everything" over-invalidation the spec
rejects. The per-token check invalidates only entries whose _specific_ near-miss anchor
landscape changed, which is the only change that could flip _this_ token's floor.

**What it does NOT catch:** the case where a token had no anchor near it at decision time
(`floor_anchor = None`) and still has none — that entry stays cached, correctly, because
its floor has not changed. The check fires only when `None → some anchor` or
`anchor A → anchor B`, which are exactly the floor-flipping transitions.

### Spec amendment

Add to §2.2, after the `count > cached_count * 3` paragraph:

> **Anchor-landscape recycle.** A `below-floor` verdict is conditional not only on the
> token's own count but on whether a near-miss of it is in `anchor_terms` — and the anchor
> set grows as `apply` verdicts accumulate. Store `floor_anchor` (the specific anchor, if
> any, the floor was based on) on the cache entry. On a cache hit for a frequency-derived
> junk entry, recompute `settled_target` against the current `anchor_terms`; if it differs
> from the cached `floor_anchor`, treat the entry as a miss. This is per-token — only
> entries whose own anchor landscape changed are invalidated, never the whole junk bucket.

Add to §4 (Testing):

| test                                                        | asserts                                                                                                                                            |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| a junk entry re-queues when its near-miss becomes an anchor | add a canonical to `hard_fixes` that is a near-miss of a cached `below-floor` token; that token re-runs, an unrelated `below-floor` token does not |

---

## Fix C — broaden the recycle-reason filter (closes Attack 3)

### The gap (after rebuttal)

The spec §2.2 names only `below-floor` as the frequency-derived junk reason that recycles.
`decide()` (glossary_acquire.py:494–528) and `source_gate` (glossary_acquire.py:438–455)
emit several `flag`-reasoned verdicts whose verdict _could_ flip on a larger corpus:
`below-floor`, `unseen-needs-evidence`, `share-too-close` (post-escalate failure),
`transcript-new-term`, `growth-over-cap`. The spec's `junk` bucket (§2.1 schema:
`{verdict: "junk", reason: ...}`) would absorb all of these under one `junk` verdict, then
recycle only `below-floor` — leaving the others permanently junked even though their
verdict is frequency/corpus-derived and could flip.

This is a **completeness gap, not a wrong-answer risk** (after rebuttal): under-recycling
fails towards `junk` (safe), never towards a wrong `apply`. But it defeats the cache's
own purpose for the long-tail-recurrence names that are the whole reason §2.2 exists.

### The fix (explicit reason allowlist)

Define the set of reasons that recycle, rather than special-casing `below-floor`:

```python
# Reasons whose verdict is conditional on corpus size / coverage and could flip
# given more data. These recycle on count growth (Fix B's anchor check) and on
# anchor-landscape change (Fix B).
STRUCTURAL_JUNK_REASONS = {"english-word", "already-canonical", "sentence-initial-only"}
# sentence-initial-only is structural-ish: a token's positional distribution is
# stable across more episodes in the common case, though a token seen only
# sentence-initially in 3 episodes may appear mid-sentence in 200. If that
# turns out to bite, move it to the frequency set; defaulting it structural
# is the cautious reading (under-recycle, fails safe).

def _recycles(reason: str) -> bool:
    return reason not in STRUCTURAL_JUNK_REASONS
```

Then §2.2's recycle rule becomes: _a `junk` token recycles on count growth OR
anchor-landscape change IF `_recycles(entry["reason"])`_. The `english-word` exemption the
spec already names falls out of this for free (`english-word ∈ STRUCTURAL_JUNK_REASONS`).

### Spec amendment

Replace §2.2's "`junk` for a _structural_ reason (`english-word`) never recycles — that
fact cannot change. Only frequency-derived verdicts (`below-floor`) do." with:

> A `junk` verdict recycles when its reason is **frequency-derived** — conditional on
> corpus size or coverage, and thus able to flip given more data. The structural reasons
> (`english-word`, `already-canonical`, `sentence-initial-only`) never recycle: the facts
> they rest on (wordlist membership, exact-match equality, positional distribution) are
> stable under more episodes. All other `junk` reasons (`below-floor`,
> `unseen-needs-evidence`, `share-too-close`, `transcript-new-term`, `growth-over-cap`)
> recycle, on count growth (§2.2) and on anchor-landscape change (Fix B).

Add to §4 (Testing):

| test                                                        | asserts                                                                                                 |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| structural junk never recycles at any count                 | an `english-word` / `already-canonical` entry stays cached regardless of count growth or anchor changes |
| a `transcript-new-term` junk entry recycles on count growth | a `transcript-new-term` entry at count 2 re-queues at count 7, where `below-floor` already did          |

---

## Fix D — the `actimeo=1` correction (closes Attack 2)

### The gap (after rebuttal)

The spec §2.3 says the library is mounted over CIFS with `cache=none,nobrl,actimeo=1`.
**`actimeo=1` is not in the mount** (docker/compose/dubtitles-3200g.yaml:128); it is an NFS
option smuggled into a CIFS string. The actual option string is
`vers=3.0,...,file_mode=0777,dir_mode=0777,nobrl,cache=none`. This is a factual error in
the spec, not a design flaw — the harvest cache's reuse of `stamp_valid`'s `(path, size,
mtime)` triple is, after rebuttal, defensible (the `size` component catches edits; the
mtime-staleness-during-recovery case is [UNVERIFIABLE] and lower-cost than Round 3 implied).

No code change. Just correct the spec's restatement of the mount options.

### Spec amendment

In §2.3, replace:

> keyed on `(path, size, mtime)` — the same triple `common.stamp_valid()` already uses for
> the `.dubtitles.done` stamp, so the idiom is established and its failure modes are known.

with:

> keyed on `(path, size, mtime)` — the same triple `common.stamp_valid()` already uses for
> the `.dubtitles.done` stamp, so the idiom is established and its failure modes are known.
> The 3200g worker reaches the library over CIFS
> (`vers=3.0,...,nobrl,cache=none` — _not_ `actimeo=1`, which is an NFS option; an earlier
> draft of this spec conflated the two filesystems). `cache=none` disables client-side
> attribute caching, so `os.stat` reflects the server's current state at call time. The
> triple's `size` component is what catches an edited episode in practice (subtitle text
> edits almost always change byte size); `mtime` is the secondary check. The one residual
> case — a same-byte-size edit during a CIFS handle-recovery window returning a stale mtime
> — is [UNVERIFIABLE] without a reproduction and is lower-cost than it sounds (it serves
> stale _context lines_ to a human reviewer, not a wrong canonical to `hard_fixes`).
> `stamp_valid` uses the same triple to fail-_safe_ (regenerate); the harvest cache uses
> it to fail-_silent_ (skip a read), so the harvest cache's cache-miss path must default
> to re-reading on any `stat` ambiguity rather than trusting the triple absolutely.

No new test — the existing §4 "an edited episode is re-read; an untouched one is not" test
covers the `size`-change case. The same-byte-size-edit case is not worth a test (vanishingly
rare for subtitle text).

---

## What this draft deliberately does NOT include

- **A title-set signature / global hash.** My Round 3 Attack 1 proposed this; the
  self-rebuttal showed it is the over-invalidation the spec §2.1 explicitly rejects. Fix A
  replaces it with a per-token membership check.
- **`len(anchors)` growth as a recycle trigger.** My Round 3 Attack 4 proposed this; the
  self-rebuttal showed it over-invalidates the whole junk bucket on every `apply`. Fix B
  replaces it with per-token `floor_anchor` tracking.
- **A content hash for the harvest cache.** My Round 3 Attack 2 implied the harvest cache
  needs more than the `(path, size, mtime)` triple; the self-rebuttal showed the `size`
  component already catches edits and the mtime-staleness case is [UNVERIFIABLE]. Fix D
  corrects only the spec's `actimeo=1` typo and adds a fail-safe-default note, no hash.
- **Anything for `context_lines` #2.** My Round 3 Attack 6.4 claimed the decision cache
  doesn't shrink it; the self-rebuttal refuted that (a cached `flag` is _absent_ from the
  next sweep's flagged set). No fix needed.

---

## Implementation order

1. **Fix D** (correct the `actimeo=1` typo in the spec). Zero code, zero risk. Do first so
   the spec stops restating a wrong mount option.
2. **Fix C** (broaden the recycle-reason filter). Pure logic, no I/O, unit-testable in
   isolation. Do second because Fix B depends on `FREQUENCY_REASONS` / the
   `STRUCTURAL_JUNK_REASONS` distinction it introduces.
3. **Fix A** (stale-canonical membership check). One `in` check per cache hit, depends only
   on `norm_titles` which `acquire()` already computes. Do third.
4. **Fix B** (per-token `floor_anchor` tracking). The most involved — requires
   `settled_target` to be recomputed on cache hits, which means the cache-hit path needs
   access to `anchors`. Do last, after the cache's basic shape (spec §2.1) is implemented,
   so this is an additive guard on a working cache rather than a prerequisite for it.

Fixes A and B both follow the spec's own philosophy: **store the denominator the verdict
was conditional on, re-check it on a hit, never invalidate globally.** Fix A stores the
canonical (re-checked against `norm_titles`); Fix B stores the floor anchor (re-checked
against `anchor_terms`). Fix C widens the set of reasons those two guards apply to. Fix D
is a typo correction.
