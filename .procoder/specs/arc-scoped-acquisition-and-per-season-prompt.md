# arc-scoped-acquisition-and-per-season-prompt

Status: complete

> **DELIVERY MECHANISM CHANGED BY MEASUREMENT (2026-08-26). Read this before building.**
> An A/B on One Pace S31E01-E03 — same audio, same model, same glossary `names`, prompt as
> the only variable — found the Enies Lobby prompt and a purpose-built 47-term Dressrosa
> prompt produce word-identical transcripts (similarity 0.9984-0.9991; 5 differing runs in
> 10,487 tokens, all hallucination-gate artifacts) with IDENTICAL counts for all 15 arc
> names, Doflamingo 7/7 and Rebecca 2/2 included. `initial_prompt` is the wrong delivery
> mechanism: `condition_on_previous_text=False` (`generate.py:890`) empties
> `previous_tokens` after the first window (`transcribe.py:1372-1383`, `:1187`), and in a
> real episode that window is the OPENING THEME, which carries no character names.
> (Direct priming is first-window-only; its effects CAN cascade via segmentation, so on a
> mid-episode clip the prompt does change later text. On a whole episode nothing is primed,
> so nothing cascades.) The flag cannot be flipped back: `generate.py:897` records `True`
> OOMing this card.
>
> A spike found `hotwords` (`transcribe.py:1542`, public in faster-whisper 1.2.1, unused by
> this pipeline) DOES apply on every window and fixed `do Flamingo` -> `Doflamingo` 57 s
> into a clip, at no measurable VRAM or time cost with 12 terms, deterministically. It also
> caused one regression in the same 180 s — `jester` -> `Dester`, a correct English word
> turned into a capitalised non-word. That regression is repairable ONLY on an anchored
> card; on one of the 6,492 `no_reference` cards nothing can fix it. The name guard was
> widened the same day (`TEXT_VERSION` 7, commit `01382a8`) so a fabricated name is caught
> whether or not one was lost — but that does NOT mitigate this risk and must not be read
> as doing so: `invents_name` polices LLM repair proposals, never decoder output, so a
> `Dester` produced by hotwords priming is in the transcript before any guard sees it.
>
> Evidence: `docs/Adversarial Reviews/RESULTS-2026-08-26-ab-prompt-comparison.md`.
> [S-3] is therefore REPLACED by [S-10]. [S-1], [S-2], [S-4], [S-6], [S-7], [S-8] and [S-9]
> are unaffected. The Problem section below still describes a real gap in arc vocabulary,
> but its claim that the wrong PROMPT causes the mishears is not supported — the mishears
> survive a correct prompt, and the demonstrated defect is a near-miss in the correction
> tiers with no fallback (see below).

## Problem

A show's glossary carries exactly ONE `initial_prompt`, and that string is the only
glossary-derived input whisper's decoder ever sees (`generate.py:893`). For One Pace the
live prompt primes the decoder with the Enies Lobby / Water 7 cast -- Spandam, Lucci,
Kaku, Kalifa, Blueno, Iceburg, CP9, Ohara, Pluton, Going Merry -- while Season 31 is the
Dressrosa arc. Not one Dressrosa name is in it. So the decoder gets no priming for what it
is about to hear AND is actively biased toward names that cannot occur, which is two
distinct error sources manufacturing exactly the phonetic mishears the v6 name guard was
built to reject after the fact.

The gap cannot close itself. `glossary_acquire.py` harvests candidate tokens FROM EXISTING
TRANSCRIPTS and resolves them against wiki titles, so it can only ask the wiki about words
whisper already emitted. Measured 2026-08-26 over 461 One Pace episodes with `--apply`: 20
proposals, 0 applied, 19 flagged, and nothing resembling Rebecca, Kyros or Pica, because
the wrong-arc prompt meant those names were never transcribed in the first place. Wrong
prompt -> wrong transcript -> no arc tokens to harvest -> prompt never improves.

The same run showed the cost of doing it show-wide: acquire's own docstring names its
dominant cost as "8202 tokens x 8109 titles", and it re-walks all 461 episodes to learn
about the 48 that are queued. Meanwhile most of the library is worse off than One Pace --
of four sampled shows (Chainsaw Man, Chainsmoker Cat, MARRIAGETOXIN, Reborn as a Vending
Machine) THREE have no glossary at all and run on the neutral fallback prompt with
`glossary.correct()` a complete no-op.

## Users

- **The pipeline operator** (repository owner) -- wants each season transcribed with its
  own arc's vocabulary primed, without a prompt edit silently re-queueing the whole library
  for the GPU.
- **`generate.py`'s decoder path** -- needs one prompt string per episode, resolved from
  that episode's season, within whisper's token budget.
- **`glossary.correct()` and the v6 phonetic name guard** -- both test membership against
  the glossary's `names`; every arc name acquired makes the guard more precise and the
  deterministic corrector able to fix more without the LLM.
- **Shows with no fansub track** -- the case acquire exists for, and the case where the
  prompt is currently the ONLY name signal available.

## In scope

- [S-1] Resolve a season's arc name from `season.nfo` (`<title>`), the metadata Plex,
  Jellyfin and Sonarr already write. Verified present for all 35 One Pace seasons;
  Season 31 reads `<title>Dressrosa</title>`.
- [S-2] Fetch an ARC-SCOPED wiki title set instead of the show-wide list, via category
  discovery (`list=search&srnamespace=14`) plus `list=categorymembers`, replacing the
  8,109-title show-wide fetch for this purpose.
- [S-3] WITHDRAWN 2026-08-26 — building a per-season `initial_prompt` was measured to
  change nothing. Replaced by [S-10]. Retained as an id so the withdrawal is on the record
  rather than silently vanishing.
- [S-10] CUT 2026-08-26 after measurement. Delivering arc vocabulary through `hotwords` was
  measured over three full episodes at four list sizes and compositions. It corrupts
  phonetically adjacent names it does NOT list (`Kin'emon` listed -> `Kanjuro` becomes
  `Kanjudo`), and it introduces repetition runs the baseline never produces (baseline 0,
  every derived arm 3-5). Neither is tunable: the 223-token budget forces a subset of any
  real cast, and listing a subset is what damages the rest. Retained as an id so the cut is
  on the record. Evidence:
  `docs/Adversarial Reviews/RESULTS-2026-08-26-hotwords-full-episode.md`.
- [S-11] Tag each acquired glossary name with the arc(s) it belongs to. The `names` list
  itself stays SHOW-WIDE and unchanged, so `glossary.correct()` and `repair.invents_name`
  keep recognising recurring characters everywhere. The tags' consumer is [S-13], not the
  cut [S-10]: they weight the glossary handed to the repair LLM, which is where arc scope
  survives contact with measurement.
- [S-12] Let cards with NO fansub anchor reach the LLM repair stage, using the surrounding
  cards as context in place of a reference. `repair.py:515-517` already builds `prev_text`
  and `next_text` and passes them to `build_prompt`; unanchored cards simply never reach
  that code, hitting the `continue` at `repair.py:512`. The gate becomes conditional rather
  than removed, so today's behaviour stays reachable.
- [S-13] Weight the glossary terms handed to the repair prompt by the current episode's
  arc, resolved from `season.nfo`. BUILT 2026-08-26. The earlier justification here was
  BACKWARDS and is withdrawn: it claimed weighting makes `Oimo -> Zoro` implausible because
  Oimo is out-of-arc. Dropping a name from the list does the opposite -- a name the model is
  not shown reads as unrecognised, and the documented failure is precisely a VALID name
  being "corrected" into a listed one. The real mechanism is the prompt's 1000-char cap:
  measured on the live One Pace glossary it holds 110 of 140 terms and silently discards 30,
  `Nico Robin` and `Rob Lucci` among them. Weighting REORDERS so the current arc's names win
  the budget; it never filters, and every term that still fits is still offered.
- [S-14] Refuse a repair that substitutes one KNOWN glossary name for another. Verified
  2026-08-26 that the v7 guard permits exactly this -- `invents_name` returns False for
  `Oimo -> Zoro` because the gained name IS known -- which is the precise failure that got
  unanchored repair disabled. The glossary already vouched for the original; a model with
  no reference has no standing to overrule it.
- [S-4] Narrow acquisition's transcript scope to the season(s) actually queued for
  transcription rather than the whole show.
- [S-5] Consolidate the prompt build and the raw acquire into ONE stage that fetches the
  arc title set once and uses it for both outputs.
- [S-6] Make decoder-input staleness season-aware so a per-season HOTWORDS string marks
  only that season's episodes transcribe-stale, never the whole show. Hotwords is a decoder
  input on every window, so it must be stored in `words.json` alongside `initial_prompt`
  and compared by `stale_tier` — today that comparison sees only the prompt, which is the
  input measured to have no effect.
- [S-7] Degrade to today's behaviour when the arc cannot be resolved, without failing the
  sweep. The trigger is CATEGORY-DISCOVERY EMPTINESS, not page resolution: `season.nfo`
  titles are not uniformly arc names — `Romance Dawn` is an arc, `Gaimon` is a character,
  `Orange Town` and `Syrup Village` are locations — so a title can resolve to a real wiki
  page that is not an arc at all and yield a plausible-looking cast that is wrong. A
  wrong-but-resolved page must not count as resolution.
- [S-8] Extract wiki access -- fetching, continuation, caching -- out of
  `glossary_verify.py` into a module both the verifier and the consolidated stage consume,
  so the arc logic is built on one wiki layer rather than a second copy of it.
- [S-9] Establish whether narrowing acquisition scope to a single season ([S-4]) is by
  itself enough to admit the three confirmed false negatives, by re-measuring their
  frequency ratios within one season BEFORE any threshold is altered.

## Out of scope

- Changing the phonetic name guard (`repair.invents_name`) itself -- it ships at v6 and is
  unchanged by this leg.
- Unanchored (no-fansub) LLM card repair. `repair.py:493` still skips cards with no fansub
  reference; making the LLM run there is a separate leg with its own risks.
- Context-aware phonetic correction using surrounding cards.
- Re-transcribing the existing library in one pass. Adoption is season-by-season -- see
  Constraints.
- Writing names into the glossary from the wiki WITHOUT transcript evidence. The arc title
  set primes the decoder only. A name enters `names`/`hard_fixes` only once a transcript
  token corroborates it, preserving acquire's invariant that "our errors can raise a
  question; they can never become an answer". Priming alone is sufficient to break the
  feedback loop, because the next transcript then contains the arc's names for acquire to
  harvest normally.
- Any change to `TRANSCRIBE_VERSION` / `TEXT_VERSION` semantics beyond what [S-6] requires.

## The show prompt stays broad and stable — decided 2026-08-26

`initial_prompt` reaches only the first decoding window, and in this show that window is
the opening theme on every episode (10 of 10 sampled S31 sidecars, plus all three A/B
episodes: 7-8 cards of sung lyrics, no character names). So the prompt's content does not
influence dialogue at all, and a per-season prompt cannot help.

What the prompt DOES control is staleness: `stale_tier` compares the stored string against
the derived one, so changing it re-transcribes everything that used it. Its content is
inert; its STABILITY is the only property with value. Two consequences, both counter to
what the first draft of this spec proposed:

- **`season_prompts` is dropped.** Per-season prompts would churn the library through the
  GPU for no measurable quality gain. The show keeps ONE broad `initial_prompt`.
- **One Pace's existing Enies Lobby prompt is NOT to be "fixed".** It looks wrong for
  Dressrosa and is wrong for Dressrosa, and rewriting it would restale 813 stamps to change
  how a song is transcribed. Leave it. Accuracy of an inert string is worth less than not
  paying two GPU-days for it.

Season scoping survives ONLY where it reaches the decoder on every window — that is
`hotwords` ([S-10]) and the tags that select it ([S-11]). Where this spec still says
"per-season prompt", read "per-season hotwords".

## What counts as an acceptable repair — owner's bar, 2026-08-26

Perfect output is not reachable without human intervention, so the standard is not
fidelity to the audio's exact wording. **A deviation that still carries the same meaning is
acceptable; one that changes the meaning is not.**

    ACCEPTABLE
      "Hawkeye Dracule Mihawk."  ->  "Mihawk."
        Shorter than what the dub speaks, and `accept_repair`'s docstring does say a
        dubtitle must match the DUB AUDIO -- but the referent is unchanged and a viewer
        gets the same information. Owner's explicit call.
      punctuation, capitalisation, run-together splits, phrasing that preserves sense.

    REGRESSION
      "looking for a factory."   ->  "looking for a needle."      meaning destroyed
      "It's a VIVRA card?"       ->  "It's a Vivi card?"          wrong referent -- Vivi is
        a character, a Vivre Card is an item. Not a near-miss, a different thing.
      any correct word decoded into a non-word.

The distinction is REFERENT AND SENSE, not word-for-word match. This bar applies to repair
output; it does not license the decoder-level hallucination that cut [S-10], where the
failures were repetition runs and invented non-words rather than looser phrasing.

Measured against this bar on S31E01 ([S-12], 161 targets, 21 repairs): 18 acceptable,
3 regressions, of which one is a glossary coverage gap rather than a repair defect.

## Build order and the decision rule

**This is a sequencing constraint, not advice. [S-10] is measured FIRST.**

Every arc-shaped item in this leg — [S-1] season resolution, [S-2] arc-scoped fetch,
[S-5]'s arc fetch, [S-8] the wiki layer, [S-11] season tags — exists only to feed [S-10].
[S-10] currently rests on one 180-second clip that produced one fix AND one regression.
Building the arc machinery in parallel with the measurement that decides whether it should
exist is how it gets built and then abandoned.

Order:

1. Measure [S-10] over at least one FULL episode with hotwords, position-level, recording
   every arc-name outcome and every regression with its anchorability class.
2. Apply the decision rule below.
3. Only then build whatever survives it.

Decision rule, REWRITTEN 2026-08-26 after the first measurement. The original demanded
"no regression on an unanchored card that a human would call worse". That is close to
unsatisfiable: any change to decoder conditioning perturbs a 1,400-card transcript
somewhere, so a zero-regression gate can never pass regardless of net benefit. That was a
defect in the rule, not evidence about hotwords. The replacement weighs severity and
compares against the baseline, and it is written before the deciding numbers arrive:

**SEVERE regressions — any single one blocks adoption.**

- A card whose duration breaks the display profile (arm E produced a 30-second card
  reading "Grr!" after a runaway repeat run). A viewer sees this; a mis-spelled name they
  may not.
- A runaway repetition run that the hallucination gate has to collapse, where the baseline
  produced none. Count them: arm E had 38 on one episode, arms A, D and F had zero.
- A correct English word decoded into a capitalised non-word (`jester` -> `Dester`), which
  `glossary.correct()` cannot repair and which on an unanchored card nothing can.

**ORDINARY regressions — counted, and weighed against fixes.**

- A name rendered less correctly than the baseline rendered it.
- Adoption requires ordinary fixes to exceed ordinary regressions by a clear margin, not a
  coin-flip one, counted per name occurrence across all measured episodes.

**NOT regressions — do not count these.**

- Punctuation and casing differences. `punctuation.py` calls an LLM, so two runs differ
  with no help from hotwords; counting them inflates both columns with noise.
- Canonical spelling changes that match the glossary or wiki title (`Coliseum` ->
  `Colosseum`). These are fixes even though a naive diff shows them as changes.
- Confidence metrics on their own. `flagged` and `low_conf` roughly doubled in every
  hotwords arm and did not improve with a better list, so they measure priming itself
  rather than list quality. They are recorded as context; they do not block, because a
  flagged card still ships the same text.

**Term integrity is a precondition, not a criterion.** Arm D corrupted `Kanjuro` into
`Kajudo` and the only thing distinguishing it from a clean arm was a malformed hotword,
`Kin emon` with the apostrophe stripped. Terms are canonical wiki titles used verbatim; any
term that does not round-trip against the fetched title set is rejected before it reaches
the decoder. A malformed term is worse than a missing one -- arm F omitted Kanjuro entirely
and still rendered him correctly three times.

If the rule returns net positive the leg proceeds; if not it ships as [S-4] + [S-6] +
[S-9] and the arc machinery is CUT, not deferred.

## Constraints

- **Whisper prompt budget is 223 tokens** and truncation keeps the TAIL:
  `faster_whisper/transcribe.py:1550` does `previous_tokens[-(self.max_length // 2 - 1):]`
  with `max_length` 448. Overflow silently drops the FRONT of the prompt, so ordering is
  load-bearing, not cosmetic.
- One Pace is the worst case for budget pressure -- a 48-episode season spanning a
  118-episode arc yielded 206 candidate terms of which 47 fit at 222 tokens. Typical library
  shows run 8-13 episodes per season, where a full cast fits with room spare.
- The wiki is a third-party service (`https://onepiece.fandom.com/api.php`). It must never
  stall or fail a sweep; `gen_loop.sh` already wraps acquire in `timeout` + failure
  swallowing and that contract must hold.
- `stale_tier()` compares the STORED prompt string against the derived one. Any prompt
  change is therefore a transcribe-tier event by construction -- the mechanism the
  two-tier split exists to keep expensive.
- No new runtime dependencies; `jellyfish` and the stdlib are what acquire already uses.
- **On the FIRST window, hotwords and `initial_prompt` contend for the same budget.**
  `previous_tokens` is empty from window 2 onward, but window 1 still carries the prompt —
  that is the whole mechanism — so `get_prompt` extends BOTH (`transcribe.py:1542-1550`).
  The [S-10] spike measured 12 terms on mid-episode windows only; the first window's
  double structure is unmeasured. Measure it before choosing a hotwords size, or window 1
  silently truncates in a way no later window does.
- **Adoption is incremental and deliberate, one season at a time.** The full re-transcribe
  is accepted as the eventual end state, but it is paid season by season as each is worked
  on and tested -- Dressrosa first -- so the transcription debt is spread rather than taken
  as a single ~2 GPU-day hit. This falls out of the storage decision at no extra cost: a
  season with no `season_hotwords` entry decodes exactly as it does today and therefore
  stays fresh, so writing a season's hotwords IS the act that stales that season and
  nothing else.

## Interfaces

- `glossary.prompt_for(gloss, show)` -- must gain a season dimension.
- `glossary.stale_tier(stored_prompt, gloss, show)` -- must compare against the prompt for
  the EPISODE'S season.
- `generate.py:120` `INITIAL_PROMPT` -- currently resolved once per process; becomes
  per-episode because a run may span seasons.
- `gen_loop.sh` -- the ACQUIRE stage invocation changes shape ([S-5]).
- The glossary JSON file format -- see Data.
- A new shared wiki module ([S-8]) owning `fetch_titles` and arc-scoped fetches.
  `glossary_verify.fetch_titles` moves behind it. The earlier justification here cited
  `prompt_for`'s drift warning; that overstated the case and is withdrawn. `prompt_for`
  warns about two derivations of the PROMPT drifting, which reads as "the prompt changed"
  and silently queues the GPU. Two title-set copies drifting produces different acquire
  CANDIDATES -- CPU-tier, logged, visible, ending in text work. Different severity class
  entirely. [S-8] is therefore justified only as ordinary de-duplication, which by this
  repo's own rules is weak grounds for migrating working code: it stands or falls as ONE
  separate mechanical commit behind a green suite, and if it perturbs any `glossary_verify`
  behaviour it is dropped and the arc module keeps its own fetch.

## Data

- Read: `<show>/Season NN/season.nfo`, `<seasonnumber>` and `<title>`.
- Read: wiki category members per arc, cached like `fetch_titles` already caches
  (`WIKI_TTL`, keyed under `WIKI_CACHE_DIR`).
- Written: a `season_hotwords` map inside the EXISTING show glossary file --
  `"season_hotwords": {"31": "Doflamingo, Dressrosa, Rebecca, ..."}`. The storage shape is
  the one decided for prompts; the key and the consumer changed when the measurement showed
  prompts are inert. `initial_prompt` stays a single broad show-level string and is not
  season-scoped.
- A season is MIGRATED exactly when it has a `season_hotwords` entry. Presence of the entry
  is the migration flag; no separate opt-in field exists. A season with no entry decodes
  with no hotwords, exactly as today.
- **The tag is a SET of arcs, not one season, and it is sourced from WIKI ARC MEMBERSHIP
  rather than from acquisition order.** Recording "the season that produced it" is wrong and
  contradicts this spec's own edge case: Caesar Clown is acquired from Punk Hazard, so a
  single-valued tag excludes him from Dressrosa's hotwords — while the Edge cases section
  says his cross-arc presence is CORRECT. Wiki membership already carries the multi-arc
  truth: he appears in `Category:Dressrosa Saga Antagonists`, measured 2026-08-26. So the
  tag is the union of (a) every arc category the name belongs to, and (b) every season whose
  transcript corroborated it. Hotwords membership for season N is "N intersects the name's
  arc set".
- The 92 names already in the glossary predate tagging and have no arc set. They default to
  ALL arcs, tagged `legacy`. Defaulting them OUT would make the first hotwords run a strict
  subset of what whisper already recognises, which is a regression dressed as a rollout.
- The season tag is the JOIN between the two halves of this leg: correction wants BREADTH
  (a recurring character must be corrected in every arc he appears in), priming wants
  NARROWNESS (hotwords must stay small — it grows the decoder prompt on every window, which
  is what OOMs this card, and the spike showed a larger bias also corrupts ordinary words).
  One tagged show-wide list serves both: unfiltered for `correct()`, filtered by season for
  `hotwords`. This also means the tag is READ, not merely recorded.
- Written: acquired names/hard_fixes into the SHOW-WIDE glossary as today, so
  `glossary.correct()` and the v7 name guard recognise the name across the whole show -- correct
  because characters legitimately recur across arcs. Each acquired entry additionally
  records the season that produced it as PROVENANCE, so a bad arc mapping can be traced to
  its source and reverted without re-deriving the whole glossary. Provenance is recorded
  data only; it changes no lookup behaviour in this leg.
- Stored per episode already: `words.json` records `initial_prompt` as the literal string
  (`generate.py:317`), which is what staleness compares against. That does not change.

## Third-party control of a GPU trigger

[S-6] changes who can trigger transcription. Today `stale_tier` compares the stored prompt
against a derived one that changes only when a human edits the glossary. Once the derived
string is built from wiki categories, it changes when the WIKI changes — an arc page
renamed, a category reorganised — at the next `WIKI_TTL` expiry
(`glossary_verify.py:260`), with no human intent and no version bump. For a One Pace season
that is 48 episodes re-queued because someone edited a fandom wiki.

It is bounded (cache TTL, per-season blast radius, and the A/B caps the harm of running
under a wrong prompt at near-zero), so it does not block. But it must never be silent: when
the derived prompt or hotwords string changes, the diff is logged with what changed and
why, so a re-transcribe always has a traceable cause.

## Edge cases

- A season whose `season.nfo` title does not match any wiki page ("Gaimon", "The First").
- A show whose seasons are not arcs at all (cour-based numbering) -- season IS the arc, so
  the mapping is identity, which must not be treated as a failure.
- One Pace re-cuts a 118-episode wiki arc into a 48-episode season; the arc spans multiple
  One Pace seasons in other places, so the mapping is not one-to-one in either direction.
- Characters legitimately carry across arcs -- Caesar Clown is a Punk Hazard antagonist
  present in Dressrosa as the Straw Hats' captive. Cross-arc presence is CORRECT and must
  not be filtered out as pollution.
- Arc category naming is not uniform: `Category:Dressrosa Arc` does not exist; the useful
  ones are `Dressrosa Residents` / `Dressrosa Locations` / `Dressrosa Saga Antagonists`.
- `prop=links` on an arc page returns navbox pollution (500 alphabetical franchise-wide
  links) and is unusable as an arc signal. Verified 2026-08-26.
- A show with no glossary file at all -- three of four sampled library shows.
- Specials / `Season 00` / `Scenes` / `Trailers` directories that are not arcs.

## Failure modes

- **Wiki unreachable or slow** -> keep the existing prompt, log, continue. Never stall the
  sweep, never write a partial prompt.
- **Arc page found but category discovery yields nothing** -> fall back to the show-wide
  title list, i.e. today's behaviour ([S-7]).
- **`season.nfo` missing or unparseable** -> fall back to the show-level prompt.
- **Prompt exceeds budget** -> deterministic truncation by rank with the tail preserved;
  the count kept and dropped must be logged, never silently capped.
- **NFS/storage slow** -- observed 2026-08-26 at 4.5 MB/s, causing `generate.py:246`'s
  hard-coded `timeout=600` ffmpeg extraction to fail. Out of scope to fix here, recorded
  because it blocks measurement.

## Acceptance criteria

- [ ] [S-1] Given `One Pace/Season 31/season.nfo` containing `<title>Dressrosa</title>`, the
      resolver returns "Dressrosa"; a season directory with no `season.nfo` returns None
      without raising.
- [ ] [S-2] For arc "Dressrosa" the arc-scoped fetch returns a title set containing Rebecca,
      Kyros, Pica, Cavendish, Viola and Trebol, at least an order of magnitude smaller than
      the 8,109-title show-wide list.
- [ ] [S-2] A SECOND arc is exercised — `Romance Dawn` (season 1), in the S01-S04 range where
      `season.nfo` titles are least reliable as arc keys. Category discovery returns that
      arc's cast or nothing; returning some other page's cast is a failure.
- [ ] [S-3] WITHDRAWN with [S-10]. No per-season `initial_prompt` is built; the show keeps
      one broad stable prompt, and editing it is recorded as a cost with no measured
      quality benefit.
- [ ] [S-4] Acquisition for a single queued season reads only that season's transcripts; the
      reported scope count equals that season's episode count, not the show's.
- [ ] [S-4] An acquired name carries the arc(s) it belongs to, and removing one season's
      contributions leaves names acquired from other seasons intact.
- [ ] [S-5] One invocation fetches the arc title set once and uses it for both consumers,
      demonstrated by a single fetch recorded for two readers.
- [ ] [S-6] MOOT with [S-10]. Nothing season-scoped reaches the decoder any more, so there
      is no per-season transcribe-tier staleness to model. The repair changes ([S-12]-[S-14])
      are TEXT tier and carry a `TEXT_VERSION` bump instead; the criterion is that no
      season-scoped decoder input exists to go stale.
- [ ] [S-7] With the wiki unreachable, the stage exits non-fatally, leaves the glossary
      byte-identical, and `gen_loop.sh` proceeds to GENERATE.
- [ ] [S-7] A `season.nfo` title resolving to a non-arc wiki page (`Gaimon`, a character)
      falls back to today's behaviour rather than tagging from that page's categories.
- [ ] [S-7] A show with no glossary file and no `season.nfo` behaves exactly as today.
- [ ] [S-8] `glossary_verify` fetches titles through the shared wiki module and no longer
      defines its own fetch; its existing tests pass untouched.
- [ ] [S-9] `Samji -> Sanji` (seen 1/721), `Shadron -> Shandora` (1/42) and `Uggh -> Buggy`
      (1/152) are re-measured with season-scoped denominators and the result recorded. No
      threshold constant changes unless that measurement shows narrowing is insufficient.
- [ ] [S-10] The cut is recorded with its evidence and NO arc machinery is built to feed it:
      no `season_hotwords`, no `hotwords` argument to `transcribe()`, nothing selecting terms
      for the decoder.
- [ ] [S-11] A name tagged to season 31 weights that season's repair glossary AND is still
      corrected by `glossary.correct()` in a season-29 episode — breadth for correction,
      narrowness for weighting, from one tagged list.
- [ ] [S-11] The push-OUT direction is tested: a name belonging to two arcs (Caesar Clown, in
      both Punk Hazard and `Category:Dressrosa Saga Antagonists`) weights BOTH seasons, and a
      legacy untagged name weights every season rather than none.
- [ ] [S-12] An episode with zero fansub anchors reaches the LLM repair stage. Measured
      2026-08-26 on S31E01: `targets=161 repaired=0`, every target refused at
      `repair.py:512`. After [S-12] that episode reports a non-zero repaired count, and the
      reference-anchored path is unchanged.
- [ ] [S-12] The gate is conditional, not deleted: with the new path disabled the same
      episode reproduces `targets=161 repaired=0` exactly.
- [ ] [S-13] With season weighting applied to a Dressrosa episode, a proposed `Oimo -> Zoro`
      is not accepted, while `Dothamingo -> Doflamingo` still is.
- [ ] [S-14] `invents_name` refuses a substitution whose ORIGINAL is a glossary name, in both
      directions: `Oimo -> Zoro` refused (both known), `Dothamingo -> Doflamingo` accepted
      (original unknown), `zolo -> Zoro` accepted.
- [ ] [S-12] [S-13] [S-14] Measured on the ~161 targets per episode already on disk, on CPU,
      against the arms captured 2026-08-26, counted by the same symmetric defect shapes that
      cut [S-10] — repetition runs, gibberish cards, cards over 12s, capitalised
      non-dictionary tokens absent from the baseline — not by a name list chosen afterwards.

## Open questions
