# Adversarial review — per-episode glossary acquisition — 2026-09-01

## Review status

**Initial design pass begun.** The reviewed spec is
`.procoder/specs/per-episode-glossary-acquisition.md` (marked `Status: complete`, although
this prompt correctly says no implementation exists yet). I read the prompt, the complete
spec, the prior arc-scoped review/rebuttal, the implementation that this spec extends, and
the current acquisition/cache/glossary/wiki tests.

**Current decision: BLOCK pending the findings below.** The blocking items are not objections
to narrowing admission itself; they are places where the proposed state or fallback semantics
can produce a confident-looking result without proving the episode was mapped correctly. The
remaining items are measurement or sequencing requirements worth resolving before declaring the
feature complete.

## Executive summary

The per-token union is a real improvement over the rejected flat run-wide union, but it is
only as safe as the provenance attached to each token. It correctly prevents an unmapped
episode from widening unrelated tokens; it does **not** make an unmapped token precise. The
spec explicitly chooses full-allpages fallback for an unmapped contributor, and therefore
acceptance must demonstrate that mixed mapped/unmapped provenance is visible and that the
resulting permissiveness is an intentional review path rather than an indistinguishable normal
admission.

The highest-confidence build blockers are:

1. partial mappings create a systematic false-negative path and are only logged, not represented
   in the admission result or report contract;
2. absolute-before-relative is a policy assertion without a per-show validation/override model;
3. the per-episode `.nfo` filename convention is known to be unverified, yet it gates the main
   One Pace value proposition and currently degrades silently;
4. the planned redirect implementation needs an API-response contract, not just a single mocked
   fixture, before it can be trusted;
5. S-11 activates an uncached, unmeasured network traversal inside the apply path while the
   design explicitly declines concurrent fetching.

## Findings

### F1 — BLOCK: per-token provenance fixes cross-token leakage, but unmapped-only tokens still get the full noisy candidate universe

**Anchors:** spec [S-7] lines 101–110; [S-8] lines 111–119; edge-case paragraph lines
301–310; acceptance [S-8] lines 364–374.

The adopted fix is sufficient for one specific bug: a fallback episode cannot widen a token
that never occurred in that episode, because the union is built from that token's own
`contributing_stems`. It is not sufficient as a precision guarantee for the token itself.

Consider three cases:

- token `Caesar` occurs only in an unmapped episode: its contribution set contains only that
  stem, and S-7 supplies the complete 8,109-title franchise set;
- token `Caesar` occurs in one mapped and one unmapped episode: its union is the mapped tight
  set plus all 8,109 titles;
- token `Caesar` occurs only in mapped episodes: it receives only those tight sets.

The first two are deliberately permissive, but the report shape does not say whether a
proposal was admitted from a tight set, a fallback set, or a mixed union. `_provenance` in the
existing code records only aggregate `scope` and `episode_count`; the new spec does not define
an admission provenance field or a mixed/fallback severity. A reviewer can therefore see a
normal proposal with no indication that its precision guarantee was unavailable.

This is not a reason to reject fallback as a policy. It is a reason to make fallback provenance
first-class: proposal-level `admission_methods`, `fallback_stems`, and `partial_stems` (or an
equivalent typed report) should survive dry runs and apply runs. Add an acceptance case for a
single token occurring in both mapped and unmapped episodes and assert both the candidate set
and the emitted report. Without that, the per-token fix narrows the leak but leaves the most
important exception invisible.

**Disposition:** BLOCK until mixed provenance is specified and tested. The underlying policy
may remain permissive.

### F2 — BLOCK: partial mapping trades noise for a silent false-negative, and tier-B does not clearly rescue it

**Anchors:** spec [S-5] lines 91–95; [S-7] lines 101–110; edge case lines 287–294;
failure modes lines 313–321; acceptance [S-5] and [S-8] lines 354–374.

For a `.nfo` mapping `628–631`, if page 629 fails while 628/630/631 resolve, the spec keeps
the three-page union and merely logs `reason: "partial-mapping"`. A name present only in page
629's Plot section is then excluded from admission for every token contributed by that episode.
This is a deterministic false-negative, not an occasional ranking change. The page cache's
positive-only policy means the missing page is retried, but until it succeeds the candidate is
systematically absent; the design never says whether an old positive cache, a failed fetch, or a
known nonexistent page is distinguishable.

S-8 says admission-rejected tokens still reach tier-B via the unfiltered `resolved`, but that
only helps tokens which already resolve to *some* franchise title. A token whose correct entity
is present only on the missing page can fail the allpages fuzzy resolution, enter `unmatched`,
and then be subject to tier-B's existing candidate/adjudication gates. The spec provides no
measurement of tier-B recall on this exact partial-mapping class, no requirement that its
canonical be drawn from the missing page, and no assertion that `unmatched` is retained when
an admission set is absent. “Still reaches tier-B” is therefore not equivalent to “rescued.”

Required before build completion:

- a fixture with one missing source page and a known name exclusive to it;
- measured outcomes for both a fuzzy-resolving token and an unmatched token;
- an explicit status distinguishing `partial`, `unmapped`, and `page-confirmed-empty`;
- a retry/backoff or operator-visible policy for a permanently nonexistent page.

**Disposition:** BLOCK. Logging alone does not prevent a silent, persistent false-negative.

### F3 — BLOCK: absolute-before-relative is a hard-coded precedence policy without a show-level contract

**Anchors:** spec [S-7] lines 101–110; Data lines 252–256; edge cases lines 279–286;
acceptance [S-7] lines 360–368.

The spec requires absolute mapping to win whenever it yields anything, even when both absolute
and relative fields are populated. That is a valid One Pace default but not a generally valid
rule. A show can be mostly 1:1 with a few recap, special, or re-cut episodes whose `.nfo`
contains source episode numbers. In that shape, both fields are legitimately declared and
relative may be the correct identity for ordinary episodes while absolute is correct only for
the exceptions—or vice versa.

The current design has no per-episode override, confidence check, consistency check, or way to
record that both mappings existed but one was discarded. “Absolute wins” is therefore not a
fallback; it is silent data loss whenever the show configuration is broader than the One Pace
example. The acceptance test only proves the precedence rule, not its correctness for a mixed
show.

Either narrow the contract explicitly (“absolute is authoritative for this show and relative
is forbidden/ignored”), or add a conflict policy: compare resolved sets, reject/log divergent
mappings, and permit a per-episode override. At minimum add a fixture where both patterns
resolve to different valid pages and require the report to expose the choice.

**Disposition:** BLOCK as a configuration/schema issue. A hard-coded precedence rule is not
safe for the stated goal of supporting both 1:1 shows and re-cuts.

### F4 — BLOCK: the per-episode `.nfo` path is a known unverified prerequisite, not a footnote

**Anchors:** spec Constraints lines 187–205; S-1 lines 62–67; S-7 lines 101–110; One Pace
Data example lines 239–249.

The spec openly says no existing code reads per-episode `.nfo` files and that deriving
`<video-basename>.nfo` is based on Kodi/Sonarr convention. If that derivation is wrong, every
One Pace episode silently falls through to relative/fallback. Because One Pace has no relative
pattern in the example, this converts the central feature into allpages admission while still
reporting a successful sweep unless logs are inspected.

The acceptance criteria test the parser with a synthetic path, not the caller's path derivation
against real library files. This is exactly the kind of “defaulted value answers the question”
failure identified in the repository-wide review: `source_episodes() == []` is treated as a
normal missing-metadata case, so a systemic naming mismatch is indistinguishable from a genuine
8% unmapped population.

Make path-convention verification phase 0 and blocking for the One Pace rollout. Add a startup
or run-level metric such as `nfo_present`, `nfo_parsed`, `nfo_missing`, and `nfo_parse_failed`,
with a threshold/abort or at least a loud “0 mapped episodes” warning. The spec should also
state the actual observed filename examples and define whether a nonzero fallback rate is
acceptable.

**Disposition:** BLOCK for One Pace deployment; note only for shows that explicitly supply a
verified metadata adapter.

### F5 — BLOCK: S-3's combined MediaWiki request is not sufficiently specified to trust

**Anchors:** spec [S-3] lines 75–80; redirect edge case lines 295–300; acceptance [S-3]
lines 351–354.

The requested `redirects=1&prop=redirects` call is plausible, but the spec conflates two
response jobs: resolving input redirects and enumerating incoming redirects. A robust
implementation must define how `query.pages`, `query.redirects`, and per-page `redirects`
are interpreted, including missing pages, normalized titles, duplicate/cyclic redirects, and
whether a redirect target's incoming redirects are included when the target was reached from an
input redirect.

The current `glossary_verify.py` has only generic `_http_json()` and no existing redirect
parser to reuse. The current tests are entirely mocked and do not establish the actual response
shape. The acceptance criterion “Kirito/Kirigaya Kazuto resolve to each other” can pass with a
fixture tailored to the implementation while real MediaWiki returns a different combination of
fields.

Before implementation, pin a captured response fixture from the target wiki (or a documented
MediaWiki API fixture) containing both directions, a missing title, and a normalized title.
Define whether the function returns canonical titles only, canonical plus aliases, or an
admission-equivalence set. Then test parse behavior independently of HTTP and test the live API
once on the target wiki.

**Disposition:** BLOCK until the response contract is fixture-backed. This is a high-impact
silent-miss risk: redirect failure removes core cast names from the admission set without
raising.

### F6 — P1: S-11 activates a dormant, uncached network traversal inside `--apply`

**Anchors:** spec [S-11] lines 121–129; Out of scope lines 167–171; Constraints lines 178–186;
Failure modes lines 329–332; current `glossary_verify.fetch_arc_titles()` lines 329–359 and
`arc_categories()` lines 254–276.

The existing `fetch_arc_titles()` performs an arc-page request, a category-search request, and
up to six paginated category-member requests per discovered category. It has no cache of its
own and returns an empty set for any failure. The new spec calls it only on `--apply`, after
proposals exist, while explicitly making concurrency optional.

This creates three problems:

1. dry runs and apply runs have different network behavior, so the dry-run acceptance pass does
   not exercise the path that writes `arc_tags`;
2. an arc fetch timeout or partial category traversal silently leaves old tags in place, which
   can make the new prompt weighting look current while being stale;
3. a large or pathological category set can consume the existing sweep timeout after the
   precision work succeeded, and because the result is fail-soft, the operator may not know
   whether tags were refreshed.

The current code's six-page cap is bounded per category, but the number of categories is driven
by search results (up to 25). This is potentially 151 HTTP calls per arc, multiplied by every
newly discovered arc. No measurement exists for the target wikis.

This should be split into a separate, cached/tag-refresh unit or made a blocking measured gate:
cache positive/negative attempts with explicit freshness, return typed status, and record
`arc_tags_refreshed`, `arc_tags_failed`, and `arc_tags_partial`. At minimum acceptance must run
`--apply` with a fake multi-category continuation fixture and assert the report distinguishes
successful tagging from fail-open retention.

**Disposition:** P1, not necessarily build-blocking if S-11 is deferred. If S-11 remains in this
spec, require explicit status and a cold-cache budget measurement.

### F7 — P1: cold-cache cost is acknowledged but not gated, so the first real One Pace sweep is unverified

**Anchors:** spec Constraints lines 178–186; Out of scope lines 167–171; Data cache lines
262–276; acceptance [S-4] lines 350–359.

The stated worst case is about 2,024 serial page fetches, with 20-second HTTP timeouts and an
existing shell timeout. The spec calls concurrency a recommended fast-follow while acceptance
only verifies cache reuse on a fixture. That proves warm-cache correctness, not first-run
viability.

A first run can spend approximately 40,480 seconds in worst-case socket timeout budget if
requests serialize and failures are slow. Even normal latency may exceed the sweep timeout or
leave a partially populated cache, causing repeated cold work on every subsequent sweep. The
failure mode says failed pages are retried next sweep, but provides no backoff, attempt budget,
or persistent “initial acquisition incomplete” status.

This is a named measurement gap rather than an argument that the worst-case number will occur.
Run a representative cold-cache benchmark against captured fixtures or the target wiki, under
the actual `ACQUIRE_TIMEOUT`, and set a completion criterion. If serial fetching cannot meet it,
concurrency or a separate prefetch command becomes required, not merely recommended.

**Disposition:** P1 measurement gate. It blocks One Pace rollout unless a measured serial run
fits the operational timeout; otherwise defer/parallelize.

### F8 — P2: tests cover the individual primitives but not the cross-stage state contract

**Anchors:** spec acceptance lines 338–386; current `tests/test_glossary_acquire.py` and
`tests/test_acquire_cache.py` (current tree contains no S-1–S-11 implementation tests); prior
repo-wide review F2/F3/F5.

The proposed feature crosses glossary JSON, wiki cache, candidate provenance, admission
filtering, tier-B fallback, arc/episode tags, and repair prompt ordering. Existing tests cover
old acquisition, cache heuristics, and old arc helpers, but the current worktree contains no
implementation for the new spec. The criteria are mostly isolated fixtures; none pins a full
flow from multiple episode files through `acquire()` to `apply_proposals()` and then into
`repair._glossary_terms()` on restart.

Add one integration fixture with:

- two mapped episodes and one unmapped episode;
- a shared token and episode-exclusive tokens;
- one partial mapping and one redirect;
- dry run, apply run, and second run using warm caches;
- glossary reload followed by repair prompt ordering;
- injected failure between cache write, glossary write, and tag write.

Assert no unrelated token is widened, fallback/partial status survives, canonical-keyed tags are
consumed, and a failed apply cannot leave a glossary that claims the tags were refreshed.

**Disposition:** P2 test confidence gap; not independently a build blocker if F1–F5 are fixed.

## Findings that currently survive the strongest rebuttal

- F1’s narrow claim survives: per-token union prevents cross-token fallback leakage, but it
  cannot make fallback-derived tokens precise. The policy can be intentional only if provenance
  is durable and visible.
- F2 survives: partial mapping has a deterministic false-negative path; tier-B rescue is an
  unmeasured assertion, not an invariant.
- F3 survives unless the schema is explicitly One-Pace-only: precedence is policy, not a
  derivation from evidence.
- F4 survives directly from the spec’s own admission that the path convention is unverified.
- F5 survives until a real/captured API response pins the parser contract.
- F6/F7 are operationally serious but can be split or measured without rejecting the core
  precision mechanism.

## What is verified versus a measurement gap

**Verified by source reading:**

- existing `fetch_arc_titles()` is uncached and fail-soft (`glossary_verify.py:254–359`);
- existing `arc_categories()` can return up to 25 searched categories, while each category
  traversal is capped at six pages;
- the current worktree has no S-1–S-11 implementation yet;
- the spec explicitly chooses per-token unions and full-allpages fallback for unmapped stems;
- the spec explicitly marks the per-episode `.nfo` convention unverified;
- current `acquire_cache` is a separate token-verdict cache with no episode dimension or TTL.

**Not verified from this checkout:**

- the real One Pace per-episode `.nfo` filenames and contents;
- the measured 2,024-page cold-cache count and actual target-wiki latency;
- real MediaWiki redirect response semantics for the exact combined query;
- tier-B recall for names exclusive to a missing partial-mapping page;
- whether both pattern fields are needed for any real target show and which precedence is correct;
- the claimed 26–30 Plot links and zero-pollution result beyond the cited prior measurements.

## Build decision

**Do not ship S-1–S-11 as “complete” yet.** The core direction is promising and the per-token
fix is materially better than the original flat union, but F1–F5 are contract gaps in the
precision and provenance story, not polish. F6/F7 should either be split from the precision
change or acquire explicit cold-cache/status acceptance criteria. The next review should be
run after the implementation exists, with the mixed-provenance integration fixture and captured
wiki fixtures in place.

## Rebuttal — strongest case against the findings

This section argues against each finding as if defending the design for the owner. It does not
remove the findings; it tests whether each is a release blocker, a policy disagreement, or a
measurement request.

### F1 rebuttal — the fallback is intentionally scoped, and per-token provenance is exactly the fix

The finding's strongest claim is conceded: an unmapped-only token still receives the allpages
universe, and a token occurring in both mapped and unmapped episodes receives the union including
allpages. That is not an accidental leak; it is the explicit fallback policy in the spec
([S-7], [S-8], edge case). The alternative—dropping the token—would violate the invariant that
a missing mapping may reduce precision but must not silently erase a possible real name. A
fallback candidate is still gated by the existing structural, frequency, dominance, and human
review rules; admission is not equivalent to auto-application.

The cross-token failure that motivated the fix is actually prevented by construction: the
fallback stem is consulted only for tokens whose `contributing_stems` include it. The report
already returns per-proposal data, and a caller can derive the relevant stems from the candidate
records; adding more persisted fields may duplicate the same state and enlarge the glossary
schema before the policy has been measured. The requested mixed fixture is valuable, but it
tests a deliberate conservative choice rather than a correctness invariant.

**Revised disposition: WEAKENED to P2 / observability and test debt.** Keep the per-token union
and fallback policy; require at least a dry-run log or report counter for fallback-derived
proposals, but do not block the core build solely because fallback is permissive.

### F2 rebuttal — false negatives are an accepted temporary consequence of incomplete metadata

A partial mapping is not claimed to be complete. Keeping the union of successfully resolved
pages is a conservative precision choice: adding the whole franchise on every partial failure
would recreate exactly the noise this feature is intended to remove. The missing page is retried
on the next sweep, and the incomplete result is explicitly logged as `partial-mapping`; an
operator can repair the wiki mapping or wait for the page to recover.

The tier-B path is not promised to recover every name; it is a human/LLM escalation path that
preserves the “question, never answer” invariant. Treating “not guaranteed to rescue” as a
blocking defect would make any precision filter impossible to ship, because every filter can
exclude a true candidate. The right acceptance criterion is to prove that partial failures are
visible and retryable, not to demand zero false negatives.

**Revised disposition: P1 measurement/quality risk, not an unconditional block.** It becomes a
blocker only if the owner requires recall over precision or if real-library measurement shows
partial pages are common and remain unavailable. Add the exclusive-name fixture and metrics,
but the chosen behavior is internally coherent.

### F3 rebuttal — absolute precedence is an explicit per-show policy, not an accidental inference

The spec’s stated targets are two concrete shapes: SAO-like 1:1 episodes and One Pace-like
re-cuts. For One Pace, absolute source-episode mapping is the only meaningful identity and the
example deliberately sets relative to null. “Absolute wins” is therefore a deterministic rule
that makes configuration behavior predictable; it is not pretending to infer the correct source
from ambiguous metadata.

A hypothetical mixed show can choose one pattern field, leave the other absent, or use a separate
show glossary/configuration. Supporting every possible hybrid metadata convention is not required
for the first rollout. If both fields are declared, the owner has already supplied conflicting
claims and absolute-first is a documented tie-break rather than silent nondeterminism. The
acceptance test pins that contract.

**Revised disposition: P2 configuration limitation, not a core blocker**, provided the spec
explicitly scopes the precedence rule to configurations that declare both fields. A conflict
fixture remains worthwhile, but adding per-episode overrides before any real hybrid show is
observed would be premature design.

### F4 rebuttal — the spec does not claim the convention is verified, and fallback is safe by design

The unverified `.nfo` convention is plainly disclosed in Constraints, and the fallback is
explicitly fail-safe: a missing or malformed file cannot inject a wrong episode page; it widens
to the existing allpages behavior. This is materially safer than guessing a source episode or
using a wrong page's cast, and it preserves current behavior for installations whose metadata
layout differs.

The acceptance criterion for S-1 is intentionally unit-level because the parser is independent
of the caller. Real-library path verification belongs to deployment validation, not necessarily
to the code feature's implementation. The One Pace plan contains a measured claim that 466/506
`.nfo` files carry the mapping line, which is evidence that the metadata itself exists; the
remaining gap is filename convention, not an unbounded correctness claim.

**Revised disposition: BLOCK only for the One Pace rollout, not for implementation.** Require a
phase-0 deployment check and an explicit fallback-rate alert, but do not reject the generic
feature or SAO path while that operational check is pending.

### F5 rebuttal — the API behavior is standard and the acceptance fixture can be made faithful

MediaWiki’s query API intentionally supports combining `redirects=1` with page properties in
one request. The implementation need not claim that one response “magically” resolves every
alias; it can normalize `query.redirects` and `query.pages[*].title`, then add incoming
redirect titles from each page’s `redirects` property. The spec names the exact pair and requires
both directions, which is a better contract than the existing code has for most wiki parsing.

A captured fixture is still prudent, but the absence of one in the pre-build design is not proof
that the query is wrong. The API is deterministic and publicly documented; a small parser with
fail-open behavior can return the original set on unfamiliar response shapes. In the worst case
redirects are missed and the candidate set becomes narrower, not a model-generated canonical or
an unsafe hard-fix.

**Revised disposition: P1 implementation-validation requirement, not necessarily a design
block.** Keep the captured-response fixture and a live smoke check, but do not block the whole
feature before confirming a standard API contract can be parsed.

### F6 rebuttal — S-11 is optional weighting and can be deferred without harming admission precision

The episode-admission fix does not depend on arc tags. S-11 is explicitly owner-chosen scope and
runs only on `--apply`; if it fails, it leaves the existing tags unchanged and does not alter the
new admission candidate set. The core precision path therefore remains safe even when the
arc-weighting enhancement is unavailable.

The existing traversal is bounded per category and fail-soft. Applying tags only after proposals
exist limits the work to runs that would mutate the glossary, and the arc tag is merely a prompt
ordering optimization, not a spelling authority. Dry runs intentionally avoid all mutations, so
different dry/apply network behavior is consistent with the repository’s existing contract.

**Revised disposition: P1 operational debt, but not a blocker if S-11 is split or explicitly
labeled best-effort.** If S-11 stays in the same release, add status counters and a cold-cache
measurement; otherwise defer it and ship S-1–S-10 independently.

### F7 rebuttal — worst-case timeout multiplication is a bound, not an expected runtime

The 2,024 figure is a maximum potential page count, not necessarily 2,024 serial requests:
positive page caches collapse repeated source pages, many pages may resolve quickly, and the
existing outer timeout already bounds the sweep. A timeout causes fail-open fallback and the next
sweep retries, so the failure is availability/latency debt rather than corruption. Making
concurrency a hard requirement before observing target-wiki latency adds complexity and rate-limit
risk to the first implementation.

The correct decision can be measurement-gated after the primitive exists: run a captured or
staged cold-cache benchmark under the actual `ACQUIRE_TIMEOUT`, then choose serial, bounded
concurrency, or a separate prefetch. The acceptance criterion need not pretend a unit test proves
production latency.

**Revised disposition: P1 rollout gate, not a reason to reject the design.** Do not ship the
One Pace configuration until the cold-cache path fits its timeout or is deliberately parallelized.

### F8 rebuttal — unit tests are appropriate before implementation; integration can follow

The spec is explicitly pre-build, so the absence of S-1–S-11 implementation tests is expected,
not a regression. Each acceptance item maps to a small pure helper or a narrow mocked boundary;
that keeps the feature deterministic and makes failures attributable. A full integration fixture
with multiple filesystem trees, cache files, redirects, and injected crashes is valuable but
should not be required before the primitives exist.

The existing project has a strong unit-test culture and a deliberate fail-soft contract. The
feature can land incrementally with tests for each phase, then gain one end-to-end test before
rollout. The lack of that integration test today is a confidence limitation, not evidence the
design is unsound.

**Revised disposition: P2 test debt, not a build blocker.** Require the integration fixture
before production rollout, not before writing the implementation.

## Final assessment after rebuttal

The rebuttal changes the release posture materially:

- **The per-token union itself survives.** It fixes the original cross-token fallback leak by
  construction. Its unmapped/mixed behavior is intentionally permissive, but must be visible in
  reports so operators can distinguish precision-backed proposals from fallback-backed ones.
- **Partial mappings remain the most important quality risk.** They are a deliberate precision/
  recall trade, not an outright design contradiction; measure the exclusive-name case and make
  retry/status visible.
- **Absolute precedence is acceptable for a first, explicitly configured rollout**, but the
  spec must scope it to supported show configurations rather than imply universal correctness.
- **The `.nfo` convention is a deployment blocker for One Pace**, because the spec itself says
  it is unverified. It is not a blocker for implementing the generic parser or SAO-like path.
- **Redirect parsing needs faithful fixtures and a live smoke check**, but fail-open behavior
  limits the likely harm to missed admission candidates rather than unsafe writes.
- **S-11 should be split or clearly best-effort**, and the One Pace cold-cache path must be
  measured before rollout.

### Revised build decision

**Do not call the complete feature production-ready yet.** The core direction is sound enough
to implement in phases. The implementation may proceed with S-1–S-10, provided it adds the
mixed-provenance/partial-mapping tests and report status during the build. S-11 should either be
moved to a separate change or carry explicit failure/status accounting. Before enabling One Pace,
verify the real `.nfo` filename convention and measure cold-cache runtime under the actual sweep
timeout. The findings no longer justify rejecting the design outright; they justify a staged,
measurement-gated rollout.
