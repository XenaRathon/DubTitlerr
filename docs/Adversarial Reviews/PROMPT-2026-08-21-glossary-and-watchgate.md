# Review prompt — glossary integrity + watch-gated regeneration

You are reviewing two design specs for **DubTitlerr**, a self-hosted pipeline that generates
English "dubtitle" subtitle tracks from an anime library's English dub audio. Stages:
transcribe (faster-whisper) -> punctuation restoration (LLM) -> reflow into timed cards ->
glossary name correction (deterministic) -> hallucination gate -> repair (LLM, anchored to an
embedded fansub track where one exists) -> signs/songs merge -> mux.

The repo is at the path you have been given. Read it.

## The two specs

1. `docs/superpowers/specs/2026-08-21-glossary-integrity-design.md`
2. `docs/superpowers/specs/2026-08-21-watch-gated-regeneration-design.md`

Spec 1 is the priority — it blocks a 183-episode regeneration. Spec 2 is secondary.

## The one rule that matters

**Verify every factual claim against the source before you accept or attack it.** These specs
assert measured facts about code behaviour, and the author has been wrong about exactly this
kind of claim before — twice in one day, both times because a _default value_ silently
produced the expected answer:

- A test used `c.get("source_end", c["end"])` on cards that lacked `source_end`, so the
  fallback made the measured difference zero **by construction**. A reviewer's finding was
  wrongly declared refuted on that basis.
- A `grep '*.py'` in the repo root silently excluded `tools/`, producing "nothing reads this
  field" twice as a stated fact, when `tools/timing_compare.py` reads it on two lines.

So: when a claim in these specs matches what you would expect, that is when to check it
hardest. Ask "what would this return if the input were missing?" before believing any number.

## Anchors to check in source

Spec 1's argument rests on these. Confirm or refute each:

- `glossary.py:62-76` — `load_dict()`. Which keys does the runtime actually read? The spec
  claims `verified`, `known`, `flagged` and `acquired` have **zero** runtime effect.
- `glossary.py:124-147` (`_fix_token`) and `glossary.py:164-180` (`name_suspect`) — the spec
  claims `names` is a **single-token** matching list and that a multi-word entry there can
  never match. Check `_TOKEN_RE` at line 96.
- `repair.py:120` (`_glossary_terms`) — the spec claims this is the **only** consumer of
  `phrases`, making it an LLM-prompt list rather than a deterministic correction source.
- `glossary_verify.py:123-145` (`apply_results`) — the claimed root cause: `lst[i] = canon`
  replaces a term in place rather than adding alongside.

## What I want from you

Answer these directly. Disagreement is more useful than agreement.

1. **Is the root-cause diagnosis correct and complete?** Is replace-in-place really the bug,
   or a symptom of something structurally wrong in how this glossary separates tiers?

2. **Attack the proposed fix.** Spec 1 §3.2 argues no deterministic guard can separate a
   _correct_ canonicalisation (`Doflamingo` -> `Donquixote Doflamingo`, `Kaido` -> `Kaidou`)
   from a _wrong_ one (`Raftel` -> `Ratel`, `Trafalgar` -> `Trafalgar Lami`), because both
   shapes are identical under edit distance and containment — so any changed term escalates to
   a human review queue. **Is that giving up too early?** The pipeline has access to the show's
   own transcripts and, for many releases, an embedded fansub track. Is there a signal there
   that separates the two cases deterministically? If yes, describe it concretely enough to
   implement, including how it fails.

3. **Does §3.1's routing rule hold?** Canonical goes to `names` if single-token, `phrases` if
   multi-word. Name a case where that is wrong.

4. **Is the §3.4 invariant** — "every term in `verified` is reachable at runtime" — the right
   invariant, or is there a weaker/stronger one that catches more? Would it produce false
   alarms on a legitimately-flagged term?

5. **§3.3 backfill:** the repair mutates a live production glossary. What can it corrupt, and
   what ordering or idempotency hazard is the spec missing?

6. **Spec 2, briefly:** the design queries WatchState rather than Plex/Jellyfin directly,
   because Plex's `lastViewedAt` was measured 40.0 days stale for the show in question. Is
   depending on a third-party sync daemon for queue selection sound, and is the
   "unreachable -> refuse to write" rule sufficient, or does it have a failure mode where
   WatchState is reachable but its data is silently wrong?

7. **What did both specs miss entirely?**

## Output

Write your review to `docs/Adversarial Reviews/GLM-2026-08-21-glossary-and-watchgate.md`.

Structure it as: one line per finding, each tagged `[CONFIRMED]` (you checked it in source),
`[REFUTED]` (with the file:line that disproves it), or `[UNVERIFIABLE]` (you could not check
it and why). Then the design critique. Rank findings by what would cost the most to get wrong.

Do not soften. If a spec is right, say so in one line and move on to what is wrong.
