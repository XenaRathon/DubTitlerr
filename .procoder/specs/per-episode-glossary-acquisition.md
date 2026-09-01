# per-episode-glossary-acquisition

Status: complete

## Problem

`glossary_acquire.acquire()` (`glossary_acquire.py:829`) scores every token
harvested from a show's transcripts against **every** main-namespace page on
that show's wiki — `glossary_verify.fetch_titles()`'s `list=allpages`, 1,281
titles for Sword Art Online covering a pass over Season 1 alone, 8,109 for
One Pace. That breadth is not free: it is what produced the module's worst
proposals on the 2026-08-29 SAO dry run —

    flag  What    -> Whale                     seen 154/0  sim 0.848  english-word
    flag  While   -> Whale                     seen   1/0  sim 0.913  english-word
    flag  Whose   -> Horse                     seen   1/0  sim 0.867  english-word
    flag  Would   -> World Seed                seen   8/0  sim 0.799  english-word
    flag  With    -> Witch of the West and the Three Treasures  seen 4/0  sim 0.794

The `english-word` gate caught all five, so nothing bad reached the
glossary — but the gate is the _last_ line, absorbing damage the candidate
set should never have contained. `Whale` and `Horse` are not even Season 1
entities.

Measured 2026-08-29 (SAO wiki): the `[[...]]` links inside a wiki **episode**
page's Plot section give 26-30 correct, per-episode candidates instead of
1,281 franchise-wide — ~45x tighter, zero navbox pollution on the two
episodes tested (E05 "Murder in the Safe Zone" yields exactly its cast and
props; E16 "Land of the Fairies" yields exactly its own, no overlap). This is
the owner's own suggestion (2026-08-28: "look for a page for that season or
arc... episode pages are even better as a base for harvesting from").

Why now: yesterday's handoff (2026-08-31) named this the biggest gate on
both beta output quality and filling the subtitle repo — a name absent from
the glossary is both unfixable by `glossary.correct()` and unprotected by
`repair.invents_name`, which is exactly how the incumbent repair model
produced `Hey, Bonekichi! -> Hey, Buggy!` (substituting a vouched name for an
unknown one).

## Users

- **`glossary_acquire.acquire()`**, invoked by `gen_loop.sh`'s
  `mine_glossary -> glossary_acquire -> glossary_verify -> generate`
  sweep — needs the narrower title set as an additional admission gate,
  without its existing wiki-fetch/caching contract changing shape.
- **`repair.py`'s prompt builder** (`_glossary_terms`, `build_prompt`) —
  gains a new per-episode weighting dimension alongside the existing (but
  dormant in production) arc-level one, so a 1000-char-capped prompt spends
  its budget on names likely to actually appear in the episode being
  repaired.
- **The pipeline operator** (repository owner) — reads the acquire report's
  per-episode fallback/partial-mapping log lines to judge whether a show's
  wiki-mapping coverage needs attention, and inspects `episode_tags` /
  `arc_tags` in a glossary file when debugging a repair proposal.
- **Shows whose episodes are 1:1 with wiki pages** (SAO) and **shows whose
  episodes are re-cuts of a source series with no wiki page of their own**
  (One Pace) — both must resolve through this design; One Pace is the
  harder case and the one motivating it.

## In scope

- [S-1] `glossary.source_episodes(nfo_path) -> list[int]` — regex-only
  `.nfo` parse of `Covers anime episode(s): 628 - 631` into
  `[628, 629, 630, 631]`. Handles range, comma, single, and mixed
  (`628-630, 645`) forms; `[]` on an absent or malformed line. No XML
  parser, matching `glossary.arc_for()`'s existing precedent
  (`glossary.py:142-168`) — third-party `.nfo` files are untrusted input.
- [S-2] `glossary_verify.plot_section_links(wikitext) -> set[str]` — pure,
  no network. Slices wikitext to the `== Plot ==` section (through the next
  level-2+ heading), extracts `[[...]]` links, and reuses
  `arc_page_links`'s existing filter (`glossary_verify.py:312-325`) rather
  than reimplementing it: strips templates/refs, drops lowercase-first
  links, drops `Category:`/`File:`/`Image:`/`w:` namespaces and
  `^(Chapter|Episode|Volume)\s+\d+$`.
- [S-3] `glossary_verify.resolve_redirects(wiki_api, titles) -> set[str]` —
  one chunked (≤50 titles/call) `redirects=1&prop=redirects` MediaWiki call
  resolves both directions in a single round trip: an input title that is
  itself a redirect resolves to its target, and other pages redirecting
  _to_ a resolved target are pulled in too. Fails open to the unresolved
  input set on any HTTP/parse error.
- [S-4] `glossary_verify.fetch_episode_titles(wiki_api, show_key,
page_title) -> list[str]` — cached single-page fetch (S-2 + S-3
  composed). New cache, one JSON file per show (not per page) under the
  existing `WIKI_CACHE_DIR`, each page entry independently `WIKI_TTL`-gated
  — following `fetch_titles`'s existing TTL-file pattern
  (`glossary_verify.py:361-384`), not `acquire_cache.py`'s (a distinct
  flat token-verdict cache with no episode dimension and different
  invalidation semantics — count-growth/membership heuristics, no TTL).
  Only positive results are cached, mirroring `fetch_titles`'s own
  asymmetry.
- [S-5] `glossary_verify.episode_page_titles(wiki_api, show_key,
page_titles) -> (union, resolved_pages, failed_pages)` — orchestrates
  S-4 over a list of page titles. The `failed_pages` split is what makes a
  partial mapping (some source episodes resolve, some don't) loggable
  without a second pass.
- [S-6] `harvest_candidates()` (`glossary_acquire.py:263-294`) gains one
  field on each candidate record: `contributing_stems: set()`, populated by
  one added line (`c["contributing_stems"].add(stem)`) inside the existing
  per-episode loop. No other change to harvest's shape, aggregation, or
  cost.
- [S-7] `glossary_acquire.episode_admission_titles(video, gloss, wiki_api,
show, norm_titles) -> (titles_or_None, method, detail)` — per-episode
  resolution and fallback orchestrator. Tries
  `episode_page_pattern_absolute` (via `source_episodes()` + S-5) first,
  then `episode_page_pattern_relative` (via the episode's own `SxxExx` +
  S-5) when absolute yields nothing; falls back to the franchise-wide
  `allpages` set — logged, never silent — when neither resolves, when the
  episode has no `SxxExx` at all, or when neither pattern field is
  declared on the show (`method="unscoped"`, today's behavior, byte-for-
  byte unchanged).
- [S-8] Per-**token** (not per-run) admission-union filtering wired into
  `acquire()`. For each harvested token, the admission set is the union of
  the per-episode title sets (S-7) of _only that token's own_
  `contributing_stems` (S-6) — not a single union across every episode in
  the sweep's `scope`. `resolved` (from `_resolve_tokens`, computed
  against the full, unfiltered `allpages` list — admission narrows what
  is _accepted_ from that resolution, never the resolution itself) is
  filtered into `resolved_admitted` before `propose()`. **Both**
  `propose()` **and** `unmatched()` are called with `resolved_admitted`,
  not the raw `resolved` — this is corrected from an earlier draft of
  this spec, which said `unmatched()` should keep receiving the
  unfiltered dict. Verified against the real code
  (`glossary_acquire.py:629-639`): `unmatched()`'s own exclusion test is
  `t not in resolved` (its `resolved` parameter, whatever the caller
  passes), so a token that resolves against `allpages` but is
  admission-rejected is, by construction, present in the unfiltered
  `resolved` and therefore invisible to `unmatched()` too — it would
  satisfy neither `propose()`'s nor `unmatched()`'s inclusion test and
  vanish from the run entirely, the opposite of the stated invariant
  that "our errors can raise a question; they can never become an
  answer." Passing `resolved_admitted` to both closes that gap: an
  admission-rejected token is, from `unmatched()`'s point of view,
  indistinguishable from one that never resolved at all, and correctly
  falls through to tier-B LLM adjudication.
- [S-9] `ordering.episode_key(path) -> str | None` (`f"S{s:02d}E{e:02d}"`
  from the existing `season_ep()`, `ordering.py:31-36`, or `None` on
  `NO_SEASON`) plus `glossary.add_episode_tag(gloss, term, episode_keys)`,
  writing `gloss["episode_tags"][term.lower()]` (unioned, sorted — same
  shape as `arc_tags`). Wired into `apply_proposals` via a new optional
  `episode_keys_by_stem` parameter: every `verdict == "apply"` proposal
  gets tagged with the `SxxExx` of its `contributing_stems`, keyed on the
  **canonical** spelling (`p["canonical"]`), not the harvested variant —
  load-bearing, since `repair._glossary_terms` iterates `hard_fixes`
  _values_, which is what the canonical becomes.
- [S-10] `repair._glossary_terms(gloss, arc=None, episode=None)`
  (`repair.py:151-193`) becomes a 3-tier stable partition: episode-tagged
  terms first, then arc-tagged terms not already placed, then everything
  else — same untagged-defaults-IN semantics independently for both tiers,
  same 1000-char whole-term cap, same de-dup-preserving-order pass.
  `episode = ordering.episode_key(video)` resolved once per episode in
  `repair.py:process()`, alongside the existing
  `arc = glossary.arc_for(video)` call (`~:702`), threaded through
  `build_prompt`.
- [S-11] RETIRED 2026-09-01, moved to a separate follow-on spec — see Out
  of scope. (Was: wire the dormant `glossary.tag_names_by_arc()` /
  `glossary_verify.fetch_arc_titles()` into `acquire()`'s apply path so
  S-10's arc-tagged tier had live data.) S-10's 3-tier partition degrades
  gracefully to its episode-tagged-vs-everything-else behavior with
  `arc_tags` empty — exactly today's state — so nothing in S-1..S-10/
  S-12..S-15 depends on S-11 landing.
- [S-12] Admission provenance surfaces on every proposal and in the
  report, not just in a per-episode fallback log line. Each proposal
  gains an `admission_method` — `"tight"` (every contributing episode
  resolved its own title set), `"fallback"` (every contributing episode
  fell back to franchise-wide), or `"mixed"` (some of each) — derived
  from the per-token union built in S-8. A reviewer reading `acquired`/
  `flagged` must be able to tell a precision-backed proposal from a
  fallback-backed one without cross-referencing the run's log output.
  (Luna review 2026-09-01, F1: the per-token union fix prevents
  cross-token leakage but does not make a fallback-derived token
  precise — that must be visible, not just true.)
- [S-13] Partial mapping ([S-5]'s `failed_pages`) gets a 3-way status
  distinguishing `partial` (some source pages resolved, some are known
  missing), `unmapped` (no `.nfo` mapping or pattern resolved at all —
  today's `fallback-allpages` case), and `page-confirmed-empty` (a page
  resolved but its Plot section yielded no links) — these are different
  facts today collapsed into one `"partial-mapping"` log reason. A fixture
  with one missing source page and a name exclusive to that page's Plot
  section must exist, with the outcome measured for both a token that
  still fuzzy-resolves against `allpages` and one that lands in
  `unmatched()`. (Luna review 2026-09-01, F2: a partial mapping is a
  deterministic, not occasional, false negative for names exclusive to
  the missing page, and "reaches tier-B" is not the same claim as
  "tier-B rescues it" — that must be measured, not assumed.)
- [S-14] `.nfo` mapping-health metrics on every acquire report:
  `nfo_present`, `nfo_parsed`, `nfo_missing`, `nfo_parse_failed` counts
  across the run's `scope`. A run where `nfo_present > 0` but
  `nfo_parsed == 0` (every `.nfo` found but none yielded episode numbers
  — the signature of a wrong filename-derivation convention) must log a
  loud, explicit warning distinct from the ordinary per-episode fallback
  line. (Luna review 2026-09-01, F4: the `.nfo`-per-episode filename
  convention is unverified against the real library, and today's design
  lets a systemic naming mismatch look identical to a genuine 8%
  unmapped population — this metric is what makes the two distinguishable
  without reading source.)
- [S-15] One integration fixture exercising the full flow end to end:
  two mapped episodes and one unmapped episode sharing a token, one
  partial mapping, one redirect pair, a dry run followed by an `--apply`
  run followed by a second run against the warm cache, then a glossary
  reload feeding `repair._glossary_terms`. Asserts no unrelated token is
  widened by the unmapped episode's fallback, `admission_method`/partial
  status survive into the written glossary, and episode-tags are
  actually consulted by the reload. (Luna review 2026-09-01, F8: S-1
  through S-10's acceptance criteria are otherwise isolated fixtures with
  no test pinning the cross-stage contract between them.)
- [S-16] `glossary.load_dict()` (`glossary.py:66-84`) gains `arc_tags`
  and `episode_tags` in its returned dict. **Discovered during
  implementation planning, not by adversarial review**: `load_dict`'s
  return value today lists exactly `show`, `names`, `phrases`,
  `token_fixes`, `phrase_fixes`, `initial_prompt`, `unanchored_repair` —
  `arc_tags` is not among them. `repair.py:process()` resolves its
  working `gloss` via `glossary_for(video)` -> `glossary.load(path)` ->
  `load_dict(...)`, and that is the exact `gloss` passed to
  `_glossary_terms`, whose weighting reads `gloss.get("arc_tags")`. So
  in production, `_glossary_terms` NEVER sees a populated `arc_tags`,
  regardless of what the glossary JSON file on disk holds — every
  existing arc-tag test (`tests/test_repair.py`'s `_tagged_gloss()`)
  hand-constructs its `gloss` dict with `g["arc_tags"] = {...}` set
  directly, bypassing `load_dict` entirely, which is why this has never
  failed a test. This means the arc-scoped spec's S-13 (season-weighted
  repair prompt, marked BUILT and already shipped) has been unreachable
  in production since it landed — not merely "inert due to coverage," as
  that spec's own measurement concluded, but structurally unable to
  receive tags at all. Without this fix, S-9's `episode_tags` would ship
  with the identical defect. S-15's integration fixture is written
  specifically to catch this: it is the one criterion in this spec that
  goes through the real `glossary.load()` path rather than a
  hand-built dict, and it fails without S-16.

## Out of scope

- Rewriting `harvest_candidates` to track full per-occurrence (not
  per-episode-set) provenance. S-6's `contributing_stems` is deliberately
  the lighter of two options considered.
- Fixing `_resolve_tokens`'s documented `O(tokens x titles)` dominant cost
  (`glossary_acquire.py:535-549`). Admission filtering happens on the
  join's _output_; the join's shape and cost are unchanged. This spec is a
  precision fix, not a performance fix.
- Changing `allpages`'s role as the canonical-spelling authority anywhere
  outside the new admission check (`settled_target`, tier-B adjudication
  unaffected).
- Retroactively re-tagging or re-scoping glossary entries acquired before
  this feature ships. `episode_tags`/`arc_tags` populate going forward,
  from `--apply` runs only (see Data).
- Applying this to the `unresolved.jsonl` review backlog, or to forcing a
  repair re-run against already-held episodes. Separate, explicitly
  deferred leg (raised in conversation 2026-09-01, not part of this spec).
- A concurrent/parallel wiki-fetch implementation. Recommended in
  Constraints as a mitigation for the cold-cache cost, but not required for
  S-1..S-10/S-12..S-15 to be considered complete — may ship as a
  fast-follow, gated per the cold-cache Constraint below.
- Wiring `tag_names_by_arc()`/`fetch_arc_titles()` into `acquire()`'s
  apply path (formerly [S-11]). `fetch_arc_titles` is uncached, its cost
  is undriven by the search-result-bounded category count (up to ~151
  HTTP calls per newly-discovered arc per the existing code, unmeasured
  against any target wiki), and activating it changes dry-run/apply-run
  network behavior asymmetrically. Retired to its own follow-on spec
  after adversarial review (Luna, 2026-09-01,
  `docs/Adversarial Reviews/LUNA-2026-09-01-per-episode-glossary-acquisition.md`,
  F6) so it can carry its own cost/status accounting
  (`arc_tags_refreshed`/`arc_tags_failed`/`arc_tags_partial`) rather than
  riding along inside a precision fix's acceptance bar.

## Constraints

- **Wiki is third-party and must never stall a sweep.** `gen_loop.sh`
  already wraps acquire in `timeout` + failure swallowing; every new HTTP
  call (S-3, S-4) must fail open (log, continue, never raise past
  `acquire()`'s existing resilience contract).
- **Rate/latency budget — measured rollout gate, not a recommendation.**
  One Pace: up to 506 episodes x up to 4 source episodes = ~2,024
  potential page fetches on a cold cache, each with a 20s HTTP timeout —
  a worst-case serial budget the review measured at ~40,480s if requests
  serialize and fail slow. The per-show, per-page TTL cache (S-4) makes a
  warm sweep near-zero-cost; the _first_ post-deploy sweep per show is
  not mitigated by caching alone. **Before this feature is enabled for
  One Pace (or any show whose cold-cache page count is comparably large),
  a cold-cache benchmark must be run against the real target wiki (or a
  captured-response fixture standing in for it) under the actual
  `ACQUIRE_TIMEOUT`, and the result recorded.** If serial fetching does
  not fit, concurrent fetching (mirroring the existing
  `ThreadPoolExecutor`/`VERIFY_WORKERS` pattern already used for
  `adjudicate()` calls, `glossary_verify.py:419-421`) becomes required,
  not optional, before that show's rollout — implementing S-1..S-10/
  S-12..S-15 does not itself require this measurement, enabling them for
  a large show does. (Luna review 2026-09-01, F7.)
- **No new runtime dependencies.** Everything above uses only what
  `glossary_verify.py`/`glossary_acquire.py` already import (`jellyfish`,
  stdlib, `urllib`).
- **`.nfo`-per-episode filename convention is unverified against the real
  library — a phase-0 rollout gate for One Pace, not a footnote.**
  `source_episodes(nfo_path)` (S-1) itself is independently testable via
  a fixture, but the _caller's_ derivation of `nfo_path` from a video path
  (`<video-basename>.nfo`, by Kodi/Sonarr scraper convention — `arc_for`
  only ever reads season-level `season.nfo`, no existing per-episode
  `.nfo` precedent exists in this codebase) must be confirmed against
  real One Pace library files before the feature is enabled there. A
  wrong convention degrades silently to `source_episodes() == []` and
  therefore to permanent fallback for every episode — indistinguishable
  from a genuine 8% unmapped population without S-14's `nfo_present` vs.
  `nfo_parsed` metrics, which is why S-14 exists: the generic parser and
  the SAO (season-relative) path do not depend on this convention and are
  not blocked by it, only One Pace's absolute-mapping path is. (Luna
  review 2026-09-01, F4.)
- **Dry-run contract unchanged.** `ACQUIRE_APPLY` unset (today's default)
  means `episode_tags` is never written, exactly like `acquired`/
  `hard_fixes` today — S-9 is gated on `apply` with no special case.
- **Absolute-before-relative precedence ([S-7]) is scoped to
  configurations that declare both pattern fields; it is not a claim
  that absolute mapping is universally more correct.** A show that
  declares only one field never exercises the precedence rule at all.
  A show declaring both is asserting that when both resolve, absolute is
  authoritative and relative is discarded for that episode — a documented
  tie-break the operator opts into by setting both fields, not an
  inference this design makes on the operator's behalf. (Luna review
  2026-09-01, F3.)

## Interfaces

- Two new optional glossary JSON fields: `episode_page_pattern_relative`,
  `episode_page_pattern_absolute` (see Data for exact shape and example).
- `glossary_acquire.apply_proposals()` gains one new optional parameter,
  `episode_keys_by_stem: dict[str, str] | None = None` — additive, default
  preserves today's call signature for any other caller.
- `repair._glossary_terms()` and `repair.build_prompt()` gain one new
  optional parameter, `episode=None` — additive, default preserves
  today's arc-only weighting for any caller that doesn't pass it.
- No CLI flag changes; no change to `gen_loop.sh`'s invocation shape.
- New cache file per show: `<WIKI_CACHE_DIR>/<show_key>_episodes.json`
  (see Data).
- Every proposal dict (from `propose()`/`apply_proposals()`) gains
  `admission_method: "tight" | "fallback" | "mixed" | None` (S-12; `None`
  when admission scoping is inactive for the run, i.e. `method=
"unscoped"`).
- The acquire report gains `nfo_present`/`nfo_parsed`/`nfo_missing`/
  `nfo_parse_failed` integer counts (S-14) and a `partial_pages: {episode
stem: [missing page title, ...]}` map (S-13).

## Data

Glossary JSON — four additive top-level keys, all optional:

```json
{
  "show": "Sword Art Online",
  "wiki": "https://swordartonline.fandom.com/api.php",
  "episode_page_pattern_relative": "Sword Art Online Episode {e:02d}",
  "episode_page_pattern_absolute": null,
  "episode_tags": {
    "kirigaya kazuto": ["S01E01", "S01E02", "S01E05"]
  },
  "arc_tags": {
    "kirigaya kazuto": ["Aincrad", "Fairy Dance"]
  }
}
```

One Pace (absolute pattern only — a re-cut show's own `SxxExx` carries no
meaningful identity on the source wiki):

```json
{
  "episode_page_pattern_absolute": "Episode {n}",
  "episode_page_pattern_relative": null,
  "episode_tags": {
    "donquixote doflamingo": ["S31E01", "S31E02", "S31E03", "S31E04"]
  }
}
```

`episode_page_pattern_relative` substitutes `{s}`/`{e}` (Python format-spec
zero-padding supported, e.g. `{e:02d}`) from the episode's own `SxxExx`.
`episode_page_pattern_absolute` substitutes `{n}` from `source_episodes()`.
Both `None`/absent by default (today's behavior). Malformed pattern strings
degrade to `None` (S-7's `_format_episode_page` guard), never raise.

`episode_tags` / `arc_tags`: flat dict,
`{canonical_term.lower(): [key, ...]}`, sorted, append-only via union
(never shrinks on a subsequent run). Written only from `--apply` runs,
only for `verdict == "apply"` proposals.

New cache file, `<WIKI_CACHE_DIR>/<show_key>_episodes.json`:

```json
{
  "api": "https://onepiece.fandom.com/api.php",
  "pages": {
    "Episode 628": { "fetched_at": 1234567890.0, "titles": ["Kirito", "..."] }
  }
}
```

Each page entry independently checked against `WIKI_TTL` (existing 30-day
default, `WIKI_CACHE_TTL` env override).

`admission_method` (S-12) is derived per proposal from the per-token union
built in S-8: `"tight"` when every stem in `contributing_stems` resolved
its own title set, `"fallback"` when every stem fell back to `allpages`,
`"mixed"` when some did and some didn't. Not persisted separately —
computed at proposal time and carried on the same dict that becomes an
`acquired`/`flagged` entry, so it survives into the written glossary
exactly like `episode_count`/`scope` already do via `_provenance()`.

`partial_pages` (S-13) is built directly from S-5's `failed_pages` per
episode, keyed on episode stem: `{"One Pace/.../S31E01": ["Episode 629"]}`.
Distinct from a `fallback-allpages` episode (nothing resolved at all) and
from a `page-confirmed-empty` page (resolved but its Plot section had no
links) — the report must be able to tell all three apart, not fold them
into one `"partial-mapping"` string.

## Edge cases

- A show with neither pattern field declared: `episode_admission_titles`
  returns `method="unscoped"` for its first episode, which short-circuits
  the whole run's admission-union step to inactive
  (`admission_union = None`) — behavior is bit-for-bit identical to today,
  not "a union that happens to equal allpages."
- One Pace episodes with no `Covers anime episode(s)` line (~8%, ~40/506):
  `source_episodes()` returns `[]`; falls through to relative (also
  unset for a re-cut show) then to `fallback-allpages`, logged per episode.
- An episode whose absolute mapping _partially_ resolves (e.g. `.nfo` says
  `628-631` but 629's wiki page doesn't exist): not treated as a full
  fallback — the episode's own set (from the 3 that resolved) is still
  used — and recorded in `partial_pages` (S-13) so a human can see which
  source episodes silently contributed nothing. A name that exists only
  on the missing page's Plot section is a deterministic false negative for
  that episode's admission, not merely a ranking change — S-13's fixture
  measures whether such a name still fuzzy-resolves against `allpages`
  and reaches `unmatched()`, rather than assuming tier-B rescues it.
- Redirect resolution on both sides: `Kirito` (linked in prose, itself a
  redirect) resolving to `Kirigaya Kazuto`, and `Kirigaya Kazuto` (linked
  directly) needing `Kirito` pulled in as an incoming redirect. Both
  handled by S-3's single combined API call.
- `File:`/`Image:` links inside a Plot section (~20% of raw matches,
  per the 2026-08-29 measurement) — filtered by S-2's reuse of
  `arc_page_links`'s existing filter.
- A token appearing in multiple episodes, only some of which have
  resolvable per-episode sets: S-8's per-token union naturally combines
  whatever sets those specific contributing episodes produced — a token
  seen in both a mapped and an unmapped episode gets the union of the
  mapped episode's tight set and the unmapped episode's franchise-wide
  fallback (correctly permissive for that token only, per S-4/owner
  decision, not leaked to unrelated tokens).
- A show with a glossary file but no `wiki` override and no resolvable
  wiki at all: `acquire()`'s existing `if not api: return ...note...`
  short-circuit (`:846-847`) fires before any S-7/S-8 code runs —
  unchanged.

## Failure modes

- **Wiki unreachable/slow during S-3/S-4** -> fail open: `resolve_redirects`
  returns the unresolved input set, `fetch_episode_titles` returns `[]`
  for that page (uncached, retried next sweep) — episode falls through to
  fallback-allpages, logged, sweep continues.
- **`.nfo` missing, unparseable, or wrong convention** ->
  `source_episodes() == []` (S-1's contract: never raises) -> falls
  through exactly like a page that doesn't exist.
- **Malformed `episode_page_pattern_*` string** (hand-edited glossary) ->
  `_format_episode_page` returns `None`, treated as pattern-absent for
  that resolution attempt, never raises past `acquire()`.
- **`ordering.episode_key()` returns `None`** (no `SxxExx` in the video
  filename at all) -> `episode_admission_titles` reports
  `method="no-episode-tag"`, treated as a fallback case; S-9's tagging
  step simply tags nothing for that episode's contributions (no crash, no
  stem excluded from `episode_keys_by_stem` — it's absent from the dict,
  and the set-comprehension in S-9 already filters on membership).

## Acceptance criteria

- [ ] [S-1] Given `.nfo` text containing
      `Covers anime episode(s): 628 - 631`, `source_episodes` returns
      `[628, 629, 630, 631]`; a comma form (`628, 630, 645`), a single form
      (`628`), a mixed form (`628-630, 645`), an absent line, and a
      truncated/malformed file each behave as specified without raising.
- [ ] [S-2] A fixture wikitext page with a `== Plot ==` section containing
      character links, a `File:`/`Image:` link, and a trailing
      `== Trivia ==` section (which must NOT contribute) yields exactly
      the Plot-section character links, no file links, no trivia-section
      links.
- [ ] [S-3] `Kirito`/`Kirigaya Kazuto` resolve to each other regardless of
      which one the Plot-section prose actually links (both directions
      pinned by name, mirroring the 2026-08-29 measurement's explicit
      regression case). The test fixture is a captured or documented real
      MediaWiki `action=query&redirects=1&prop=redirects` response shape
      (including a missing title and a normalized title), not a synthetic
      mock shaped to fit the parser — a hand-tailored mock can pass while
      the real API returns a different field combination (Luna review
      2026-09-01, F5). A live smoke check against the target wiki is run
      at least once before this criterion is considered satisfied.
- [ ] [S-4] A second call for the same show+page within `WIKI_TTL` makes no
      HTTP request; a call past `WIKI_TTL` does; a page with no titles
      found is not cached (retried on the next call, mirroring
      `fetch_titles`'s existing asymmetry).
- [ ] [S-5] Given one resolvable and one unresolvable page title,
      `episode_page_titles` returns the resolvable page's titles in
      `union` and names the unresolvable one in `failed_pages`.
- [ ] [S-6] A token seen in two episode stems carries both stems in
      `contributing_stems`; a token seen in one carries exactly one.
- [ ] [S-7] With both pattern fields set and the absolute mapping
      resolving, `method="absolute"` wins. With only relative resolving,
      `method="relative"`. With neither resolving (or the .nfo/pattern
      absent) and the wiki otherwise reachable, `method="fallback-allpages"`,
      logged. With neither pattern field declared on the show at all,
      `method="unscoped"` for every episode in the run.
- [ ] [S-8] Re-running the SAO dry pass no longer proposes `What -> Whale`,
      `Whose -> Horse`, or
      `With -> Witch of the West and the Three Treasures`. A token whose
      sole contributing episode is unmapped (fallback) is admitted against
      the full title set; a DIFFERENT token, harvested only from mapped
      episodes elsewhere in the same run, is NOT widened by that unrelated
      episode's fallback — the specific regression this spec's design
      phase found in the original per-run-union approach.
- [ ] [S-8] A token eligible under one episode's admission set and
      ineligible under a different episode's, when each is that token's
      _only_ contributing episode in two separate runs, resolves
      per-episode rather than identically in both.
- [ ] [S-9] An applied proposal's `episode_tags` entry is keyed on the
      **canonical** spelling and contains exactly the `SxxExx` of its
      `contributing_stems` that had a resolvable `episode_key`.
- [ ] [S-10] For an episode carrying both an episode-tagged and an
      arc-tagged (but not episode-tagged) term, the episode-tagged term
      ranks ahead of the arc-tagged one in `_glossary_terms`'s output
      order. An untagged term still appears (defaults IN, never dropped).
      The 1000-char cap and de-dup behavior are unchanged from today's
      2-tier version when `episode=None`.
- [ ] [S-11] RETIRED. No code in S-1..S-10/S-12..S-15 calls
      `tag_names_by_arc`/`fetch_arc_titles`; `arc_tags` stays exactly as
      populated (or unpopulated) by any process outside this spec, and
      S-10's arc-tagged tier is exercised in tests with `arc_tags` both
      present (pre-seeded fixture) and absent, confirming the 3-tier
      partition degrades cleanly to a 2-tier one either way. Moved to a
      follow-on spec per Out of scope.
- [ ] [S-12] A token whose `contributing_stems` are all mapped episodes
      gets `admission_method="tight"`; all-unmapped gets `"fallback"`; a
      mix of both gets `"mixed"`. `admission_method` is present on the
      written `acquired`/`flagged` glossary entry, not only in transient
      run output — a reviewer opening the glossary file alone can tell a
      fallback-backed proposal from a tight one.
- [ ] [S-13] A fixture with one missing source page (of several mapped)
      and a name appearing exclusively in that page's Plot section
      demonstrates: the episode's `partial_pages` entry names the missing
      page; the exclusive name is measurably absent from that episode's
      admission set; and the outcome is recorded for both a variant of
      that name that still fuzzy-resolves against `allpages` (reaches
      `propose()`, rejected or flagged there) and one that does not
      (reaches `unmatched()`) — "reaches tier-B" and "tier-B accepts it"
      are verified as separate, not conflated, claims.
- [ ] [S-14] A run where every episode's `.nfo` is present but none parse
      (`nfo_present > 0`, `nfo_parsed == 0`) emits the loud warning
      distinct from ordinary per-episode fallback logging. A run with a
      normal mix of present/absent `.nfo` files reports accurate counts
      for all four metrics.
- [ ] [S-15] The end-to-end fixture (two mapped + one unmapped episode
      sharing a token, one partial mapping, one redirect pair; dry run ->
      `--apply` -> warm-cache re-run -> glossary reload -> `repair.
_glossary_terms`) passes with: no unrelated token widened by the
      unmapped episode's fallback; `admission_method`/`partial_pages`
      present and correct in the written glossary; and the reloaded
      glossary's `episode_tags` measurably changing `_glossary_terms`'s
      term order on the next `repair.py` invocation.
- [ ] [S-16] A glossary JSON file on disk with `arc_tags`/`episode_tags`
      populated, loaded via the real `glossary.load(path)` (not a
      hand-built dict), produces a `gloss` whose `arc_tags`/
      `episode_tags` are non-empty and identical to what was on disk.
      Every existing `tests/test_repair.py` arc-tag test that currently
      constructs its `gloss` by hand continues to pass unchanged (this
      fix only adds keys `load_dict` returns; it removes nothing).
- [ ] `procoder check` 0 blocking, `lint --types` 0, suite green — inherited
      from the todo's own acceptance bar.

## Open questions

<!-- none — resolved during the 2026-09-01 interview; see plan
     /home/xenarathon/.claude/plans/eager-stirring-pike.md for the
     discussion trail behind each decision above. -->
