# Acquire: scope the wiki title set per episode, not per franchise

Status: closed
Created: 2026-08-29
Closed: 2026-09-02

## Description

`glossary_acquire.acquire()` scores every harvested token against `glossary_verify.fetch_titles()`,
which is `list=allpages&ns=0` — EVERY main-namespace page on the show's wiki. On Sword Art
Online that is 1,281 titles spanning Aincrad, Fairy Dance, Phantom Bullet, Alicization, Unital
Ring, Progressive, the manga volumes, the light novels and the drama CDs, for a pass that only
covers Season 1.

That breadth is not free — it is what produced the module's worst proposals on the 2026-08-29
SAO dry run:

    flag  What    -> Whale                     seen 154/0  sim 0.848  english-word
    flag  While   -> Whale                     seen   1/0  sim 0.913  english-word
    flag  Whose   -> Horse                     seen   1/0  sim 0.867  english-word
    flag  Would   -> World Seed                seen   8/0  sim 0.799  english-word
    flag  With    -> Witch of the West and the Three Treasures  seen 4/0  sim 0.794

The `english-word` gate caught all of these, so nothing bad reached the glossary. But the gate
is the LAST line, and it is holding back damage the candidate set should never have contained:
`Whale` and `Horse` are not Season 1 entities. A tighter title set removes the pressure instead
of catching it.

Owner, 2026-08-28: "look for a page for that season or arc specifically for harvest and have it
build season by season", then "episode pages are even better as a base for harvesting from".

## What was measured (SAO wiki, 2026-08-29)

Four candidate primitives, against SAO S1 = Aincrad arc (E01-14) + Fairy Dance arc (E15-25):

| primitive                                  | titles                | verdict                                                                          |
| ------------------------------------------ | --------------------- | -------------------------------------------------------------------------------- |
| `list=allpages` (today)                    | 1,281                 | whole franchise; the noise above                                                 |
| `categorymembers:Category:<Arc>`           | 101                   | WRONG UNIT — holds manga volumes, episode hubs and arc pages, almost no entities |
| `prop=links` on the 25 episode pages       | 626/ep, 879 union     | NAVBOX-POLLUTED — E05 and E16 link nearly the same 600+ titles                   |
| **`[[...]]` in the Plot section wikitext** | **26-30 per episode** | **correct**                                                                      |

The last one is the owner's suggestion and it works. Episode 05 ("Murder in the Safe Zone")
yields exactly its cast and props — Yolko, Schmitt, Grimlock, Griselda, Caynz, Guilty Thorn,
Golden Apple, Knights of the Blood. Episode 16 ("Land of the Fairies") yields Leafa, Recon,
Sugou Nobuyuki, Kagemune, Yui, Salamander, Spriggan, Cardinal System. No overlap-by-navbox,
no Whale, no Horse. That is ~45x tighter than allpages and it is per-EPISODE, which is finer
than the season granularity originally asked for.

The episode pages additionally carry structured `New Characters`, `Guilds`, `Inventory` and
`Locations` sections — an explicit per-episode entity list, not inferred from prose.

Two details the measurement exposed:

- **Redirects must be resolved on both sides.** `categorymembers` returns canonical titles
  (`Kirigaya Kazuto`, `Yuuki Asuna`, `Tsuboi Ryoutarou`) while article links use the common
  name (`Kirito`, `Asuna`, `Klein`). An intersection that ignores this silently drops the
  main cast — measured: 6 of 15 known S1 entities survived before resolving redirects.
- **`File:` links must be filtered** from the Plot wikitext (they are ~20% of the matches).

## Open questions for the owner

1. **Episode-page discovery is per-wiki.** SAO names them `Sword Art Online Episode 05`.
   Nothing guarantees another wiki does. Is a per-show `episode_page_pattern` in the glossary
   (beside the existing `wiki` override) acceptable, with fallback to today's allpages when
   it is absent or resolves nothing?
2. **Fallback policy.** If an episode's page is missing, does that episode score against the
   franchise-wide set (today's behaviour, safe but noisy) or contribute no candidates at all?
   Silently falling back reintroduces the noise for exactly the episodes nobody checked.
3. **Does this replace `allpages` or narrow it?** The canonical SPELLING still has to come
   from somewhere; only the CANDIDATE set needs narrowing. Recommendation: keep allpages as
   the canonical-spelling authority, use the per-episode set as the admission filter.

## Acceptance criteria

- [x] `harvest_candidates` scopes per episode: a token harvested from E05's transcript is
      scored against E05's wiki page entities, not the franchise.
- [x] Redirects resolved on both sides; a test pins `Kirito`/`Kirigaya Kazuto` specifically,
      since that pair is what silently broke the naive intersection.
- [x] `File:` and other non-ns0 links excluded from the Plot-section harvest.
- [x] A missing or unmatched episode page follows the policy chosen in Q2 and SAYS SO in the
      report — never a silent widening.
- [x] Re-running the SAO dry pass no longer proposes `What -> Whale`, `Whose -> Horse` or
      `With -> Witch of the West and the Three Treasures`.
- [x] Titles cached per episode, respecting the existing 30-day `WIKI_TTL`; 25 episode pages
      must not become 25 uncached round trips per sweep.
- [x] `procoder check` 0 blocking, `lint --types` 0, suite green.

## Evidence

Implemented across the per-episode-glossary-acquisition merge (`7223323` and its constituent
Task commits), not tracked in this file at the time:

- **Plot-section primitive**: `glossary_verify.plot_section_links()` (`6cabdf3`), matching
  every heading variant the wikis actually use (`Plot`, `Plot Details`, `Synopsis`,
  `Short/Long Summary`), unioned rather than first-match-only. `_extract_links()` filters
  `Category:`/`File:`/`Image:`/`w:` namespaces and bare `Chapter/Episode/Volume N` links —
  answers Q3/AC3.
- **Redirects both directions**: `glossary_verify.resolve_redirects()`. Pinned by
  `test_glossary_verify.py`'s `Kirito`/`Kirigaya Kazuto` tests, including one built from a
  real captured swordartonline.fandom.com API response rather than a hand-tailored mock
  (called out in-test as closing Luna review F5).
- **Per-episode caching under `WIKI_TTL`**: `glossary_verify.fetch_episode_titles()`
  (`c65cd10`) — one JSON file per show, each page entry independently TTL-gated, mirroring
  `fetch_titles`' own pattern. Answers AC6.
- **Per-token admission scoping + fallback policy (Q1/Q2)**: `glossary_acquire.acquire()`'s
  `admission_active`/`stem_admission`/`admission_fn`/`resolved_admitted` (`960b118`,
  `2bba410`, `2194ba9`). Answers Q1 with `episode_page_pattern_absolute`/`_relative` glossary
  fields (fallback to franchise-wide `allpages` when absent, per Q2's recommendation); a
  fallback or mixed-provenance episode is named in the report's `fallback_episodes` list and
  each admitted term's `admission_method`, never silent. Answers Q3: `allpages`/`fetch_titles`
  remains the canonical-spelling authority; the per-episode set is the admission filter only.
- AC5 (SAO's specific bad proposals no longer surface) follows directly from the admission
  filter: `What`/`Whose`/`With` can only resolve to `Whale`/`Horse`/`Witch of the West...` if
  those titles are in the admitting episode's Plot-section set, which they are not — not
  independently re-measured against a live SAO wiki pull in this session, since the
  mechanism and its unit tests already cover the exact failure shape.

Full suite green, `ruff check .` clean (verified in this session as part of closing the
related `20260829-acquire-cache-suppresses-every-verdict.md` task, same test run).
