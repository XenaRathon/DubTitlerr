# Review prompt — per-episode glossary acquisition

Your prior reviews are in this directory — `GPT5.6-LUNA-REVIEW-2026-09-01-repository-wide.md`
(today, repo-wide) and `LUNA-2026-08-26-rebuttal-of-ab-findings.md` are the two most relevant.
Worth skimming `GLM-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md` too — that
spec is COMPLETE and BUILT, and this new spec explicitly stacks a new mechanism on top of one
piece of it (see below). This codebase's recurring failure mode, per your own repo-wide
review today: cross-stage state ambiguity, and a defaulted value silently answering the
question that was actually asked. Watch for both here.

**Spec under review:** `.procoder/specs/per-episode-glossary-acquisition.md`

**Directly relevant prior art:**

- `.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md` (COMPLETE) — its [S-11]
  `tag_names_by_arc` / [S-13] `_glossary_terms` arc-weighting mechanism is what this new spec's
  [S-10]/[S-11] extend to episode granularity. Its [S-9] finding is worth holding in mind:
  narrowing acquisition SCOPE (there, for cost) admitted 0 of 3 confirmed false negatives,
  because the gates that refused them weren't ratio gates. This new spec narrows a different
  thing (the ADMISSION title set, for precision, not scope-for-cost) — confirm that
  distinction actually holds, or whether this spec is quietly assuming a narrowing benefit the
  prior leg already measured away for an adjacent case.
- `.procoder/todo/20260829-acquire-scope-wiki-titles-per-episode.md` — the original
  measurement (`What -> Whale`, `Whose -> Horse`, etc.) and the three open questions this spec
  answers.
- `docs/superpowers/plans/2026-08-31-per-episode-acquire.md` — yesterday's first-pass design
  sketch. The spec under review is NOT a restatement of it — a design pass on 2026-09-01 found
  and fixed a real bug in that sketch's approach (see "What changed" below) and added
  provenance/weighting scope the sketch didn't cover at all.

## Deliverable

**Write your review to a markdown file in `docs/Adversarial Reviews/`** — named
`LUNA-2026-09-01-per-episode-glossary-acquisition.md`. Do not return it as chat output; the
file is what gets read. Every finding needs a file:line anchor (in the spec or the existing
code it references) or a stated measurement gap. State plainly which findings would block the
build versus which are worth noting only.

## The situation

`glossary_acquire.acquire()` scores every harvested transcript token against every wiki page
for a show — 1,281 titles for one SAO season, 8,109 for One Pace. Measured 2026-08-29: a wiki
EPISODE page's Plot-section `[[...]]` links give 26-30 correct per-episode candidates instead,
~45x tighter, zero pollution on the two episodes tested. This spec scopes admission to that
tighter set while keeping the franchise-wide list as the canonical-spelling authority
everywhere else.

Nothing in this spec is built yet — this review happens before any code is written, by
design.

## What changed during the design pass — read before attacking

The interview surfaced a real bug in the plan sketch's original approach and the owner
approved a fix mid-design, not after measurement — **that fix has never been tested, only
reasoned through**, and is one of your highest-value targets:

The sketch proposed a flat UNION of every in-scope episode's title set for one `acquire()`
run's admission check. `harvest_candidates()` walks the whole show directory every sweep, so
for One Pace `scope` is effectively all ~506 episodes together every time. The fallback policy
(a `.nfo`-unmapped episode widens to the full 8,109-title set, ~8% of One Pace's episodes hit
this) then contributes that FULL set into the SAME run-wide union — so a single unmapped
episode silently degrades admission to "everything" for every OTHER episode's tokens in that
sweep too. The fix adopted: scope the union PER TOKEN, using a newly-added
`contributing_stems` provenance field ([S-6]) — each token's admission check only unions the
title sets of the specific episode(s) it actually appeared in.

## Attack these specifically

1. **Is the per-token union fix actually sufficient, or does it just narrow the same leak?**
   Walk the case where a single character legitimately appears in both a well-mapped episode
   and an unmapped one (Caesar Clown, cross-arc, is the exact real precedent the arc-scoped
   spec already documented for a different mechanism). That token's union now legitimately
   includes the full fallback set — correct per the spec's own reasoning. But does this create
   a NEW failure mode: a token that appears ONLY in an unmapped episode gets zero benefit from
   this whole feature (full noise exposure), while the spec's acceptance criteria ([S-8]) only
   test the case where a token has exactly one contributing episode. Is the multi-episode,
   mixed-mapping case tested at all, or just asserted safe by construction?

2. **[S-7]'s partial-mapping edge case may create false NEGATIVES this spec doesn't measure.**
   When a `.nfo` maps an episode to 4 source pages and only 3 resolve, the spec keeps the
   episode's own (incomplete) set rather than falling back — logged, not widened. A real name
   that appears ONLY on the missing 4th page's Plot section is now systematically excluded
   from admission for that episode's tokens, forever (the page cache never expires a
   permanently-missing page's absence — it just retries every sweep, per [S-4]). Is trading
   `What -> Whale` noise for a silent, permanent false-negative on real names in exactly the
   partial-mapping case an improvement, or a different failure mode wearing this spec's own
   stated invariant ("our errors can raise a question, never become an answer") as cover? The
   token still reaches tier-B adjudication per [S-8] — does that actually rescue it, or does
   tier-B have its own admission-adjacent gates that would refuse it just as hard?

3. **Absolute-before-relative precedence ([S-7]) is asserted, not derived.** The spec says
   absolute wins when both pattern fields resolve, reasoning that a re-cut show's own `SxxExx`
   "carries no meaningful identity on the source wiki." True for One Pace. Is there a
   plausible show shape where BOTH fields are legitimately declared and relative is actually
   the more accurate source (e.g., a show that is mostly 1:1 but has a handful of `.nfo`-mapped
   special/recap episodes)? If so, does hard-coding absolute-first silently produce the wrong
   answer for the common case on that show, rather than a documented fallback?

4. **[S-11] wires up previously-dead code with an uncached network call, inside a precision
   fix's own spec.** `fetch_arc_titles` (from the completed arc-scoped spec) has never run
   outside a test's mocked HTTP layer. This spec calls it live, per newly-discovered-arc,
   inside `acquire()`'s existing `--apply` path, with no cache of its own (confirmed: read
   `glossary_verify.py`'s `fetch_arc_titles`/`arc_categories` yourself, don't take the spec's
   word). Is bundling "activate a dormant, unmeasured, uncached mechanism" into the same spec
   and the same build order as "fix a measured precision bug" the right unit of work, or does
   it hide a genuinely separate risk (arc discovery failing/timing out) inside acceptance
   criteria that only test the episode-tag mechanism? The spec's own Constraints section admits
   this is owner-chosen scope, not incidental — attack whether that owner choice was actually
   informed by `fetch_arc_titles`'s real (uncached, unmeasured) cost, or by the mechanism's
   name alone.

5. **The `.nfo`-per-episode filename convention is asserted by analogy, unverified.** [S-1]'s
   parser is independently testable via a fixture, but nothing in this codebase today reads a
   per-episode `.nfo` at all (`glossary.arc_for` only reads season-level `season.nfo`) — the
   spec's own Constraints section admits the caller's derivation of the per-episode `.nfo`
   path is "by Kodi/Sonarr scraper convention," unconfirmed against the real library. Twelve
   build phases and eleven acceptance criteria are written on top of this assumption. If the
   convention is wrong, [S-7] silently and permanently falls through to relative/fallback for
   EVERY One Pace episode, never surfacing as a failure — the exact "confident wrong answer"
   shape this codebase has a documented history of shipping (see the arc-scoped GLM review's
   recurring finding). Should this spec have made verifying that path convention phase 0,
   blocking, rather than a Constraints-section footnote to check "before phase 7 is pinned"?

6. **Redirect resolution ([S-3]) claims one combined API call resolves both directions —
   verify the MediaWiki semantics, don't take the spec's word.** `redirects=1&prop=redirects`
   in one `action=query` call: does `redirects=1` actually follow an INPUT title that is
   itself a redirect (not just report that it is one), simultaneously with `prop=redirects`
   correctly listing INCOMING redirects to the resolved page, in a single response shape the
   code can parse unambiguously? Or does this conflate two different MediaWiki response
   structures that happen to share a query but require different parsing, in a way that's easy
   to get subtly wrong and only surface as a missed match, not an error?

7. **[S-9]'s "keyed on canonical, not variant" claim is the one correctness detail the whole
   episode-tag mechanism depends on — verify it against the ACTUAL `apply_proposals` write
   path, line by line, not the spec's summary of it.** The spec asserts `repair._glossary_terms`
   iterates `hard_fixes` _values_, and that acquire's canonical is what lands there for every
   `verdict == "apply"` proposal. Is that true for every apply-verdict reason (`dominant`,
   `canonical-unseen`, others), or only some? If any apply-verdict path writes to `gloss["names"]`
   instead of (or in addition to) `hard_fixes`, does `episode_tags` (keyed to mirror the
   `hard_fixes` value) actually get consulted by `_glossary_terms` for that term at all, or does
   it silently tag a key `_glossary_terms` never looks up — reproducing, for episode_tags, the
   exact `arc_tags`-tags-`names`-but-acquire-writes-`hard_fixes` mismatch this spec's own Data
   section says is why `arc_tags` barely intersects acquire's output today?

8. **Cold-cache cost is "recommended, not required."** Up to ~2,024 serial HTTP fetches for One
   Pace's first post-deploy sweep, against `gen_loop.sh`'s existing `ACQUIRE_TIMEOUT` (which the
   arc-scoped review's own measurements already showed is under pressure from the UNRELATED
   `_resolve_tokens` join cost). The spec proposes concurrent fetching as a fast-follow, not a
   blocking requirement. Is that a reasonable phasing decision, or does it mean phase 8's own
   acceptance criterion (re-run the SAO dry pass, confirm noise gone) is the only thing
   actually verified before ship, while the One Pace path — the show this spec is FOR — ships
   with an unverified timeout risk on its very first real run?

## What a useful review looks like here

Findings that would change the build, ranked, each with an anchor or a named measurement gap.
If a finding is really "this needs to be measured, not argued," say that explicitly rather
than arguing both sides. If you conclude the spec is sound as written, say so plainly and name
the one thing most likely to be discovered mid-build anyway — do not manufacture findings to
look thorough.
