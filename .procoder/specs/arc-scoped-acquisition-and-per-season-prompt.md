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

Names come out of this pipeline wrong, and on releases with no fansub track nothing can fix
them. The exemplar, measured on One Pace S31E01: the dub says "Donquixote Doflamingo" and
the transcript ships `Dothamingo`.

`Doflamingo` IS in the glossary. `glossary.correct()` still cannot repair it -- the fuzzy
tier scores difflib 0.800 against a 0.84 cutoff and the phonetic tier scores metaphone
T0MNK against TFLMNK, so both miss by a margin. The LLM repair stage could fix it, but the
card has no fansub anchor, and `repair.py` skips every such card. Season 31 carries 6,492 of
them and accepted 0 repairs across all 48 episodes.

So the defect is a near-miss in the deterministic correction tiers with no fallback on
non-fansub releases. That is what this leg is for.

**Two mechanisms were tried against it and both failed, on measurement.** This section used
to argue that a wrong-arc `initial_prompt` manufactured these mishears; that causal story is
dead and is recorded here so nobody rebuilds it:

- **Per-season prompts ([S-3], withdrawn).** Two sharply different prompts produced
  word-identical transcripts over three episodes, with identical counts for all 15 arc
  names. `initial_prompt` reaches only the first decoding window, which in this show is the
  opening theme -- 8 cards of sung lyrics, no character names, verified on 10 of 10 sampled
  episodes.
- **Hotwords ([S-10], cut).** Measured at 72/110/138/150 tokens. It corrupts phonetically
  adjacent names it does NOT list -- listing `Kin'emon` turns `Kanjuro` into `Kanjudo` --
  and adds repetition runs the baseline never produces. Neither is tunable: the 223-token
  budget forces a subset of any real cast, and listing a subset is what damages the rest.

What survived is the repair stage itself, and it is TEXT tier, so experiments cost CPU
minutes against a saved `words.json` instead of GPU hours. Ungating the unanchored path on
S31E01 turned 161 refused targets into 21 repairs, 18 acceptable, `Dothamingo ->
Doflamingo` among them.

The remaining constraint is COVERAGE, not mechanism. The Dressrosa arc has 96 entities on
the wiki; the entire show's glossary has 92 names. Of 17 Dressrosa names tagged for a test,
4 existed in the glossary. That gap is why one measured regression happened at all --
`VIVRA -> Vivi`, where the correct term `Vivre Card` is simply absent and the model reached
for the nearest name present.

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

Status per item, so a cold reader can tell what exists. BUILT = in the tree and tested;
MEASURED = evidence exists; SPECIFIED = designed, not built; CUT/WITHDRAWN/MOOT = dead,
kept only so the decision is on the record.

    [S-1]  BUILT      glossary.arc_for, season.nfo -> arc name
    [S-2]  BUILT      arc-scoped wiki fetch (page links + discovered categories)
    [S-3]  WITHDRAWN  per-season initial_prompt: measured inert
    [S-4]  SPECIFIED  narrow acquisition to the queued season -- COST only, see [S-9]
    [S-5]  RE-SCOPED  one arc fetch, two consumers
    [S-6]  MOOT       nothing season-scoped reaches the decoder any more
    [S-7]  BUILT      empty arc titles on a non-arc season.nfo title (Gaimon -> 0)
    [S-8]  MOOT       no second wiki layer exists to de-duplicate
    [S-9]  DONE       scope narrowing admits 0 of 3 -- measured, hypothesis false
    [S-10] CUT        hotwords: corrupts unlisted neighbours, adds repetition
    [S-11] BUILT      arc tags on glossary names -- 64 of 92 tagged over 7 arcs
    [S-12] BUILT      conditional unanchored repair, DEFAULT CLOSED
    [S-13] BUILT      season-weighted repair glossary -- live once tags exist
    [S-14] BUILT      refuse a vouched-name swap where there is no reference
    [S-15] BUILT      phonetic-proximity gate, known false negative on vivra->vivi
    [S-16] DONE       coverage defence FALSIFIED -- Vivre Card changed nothing

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
  cards as context in place of a reference. `repair.py:622-624` already builds `prev_text`
  and `next_text` and passes them to `build_prompt`; unanchored cards simply never reach
  that code, hitting the `continue` at `repair.py:162 (skips_unanchored)`. The gate becomes conditional rather
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
- [S-14] BUILT 2026-08-26 (`752dd15`). `repair.substitutes_a_vouched_name` refuses a
  repair that replaces one KNOWN glossary name with another. Applied ONLY where the card
  has no fansub reference: the bake-off failure it guards against (`Oimo -> Zoro`) was the
  glossary-ONLY case, and a reference-backed swap is exactly the correction repair exists
  to make -- refusing those everywhere would lose real anchored repairs library-wide.
  The rule lives in its own function, NOT in `invents_name`, so the two name guards can be
  reasoned about separately; an earlier criterion naming `invents_name` was wrong about its
  own implementation and is corrected below.
- [S-15] BUILT 2026-08-26 (`752dd15`). The phonetic-proximity gate, previously load-bearing
  with no home in this spec -- the round-2 review's one surviving BLOCK. On the
  UNKNOWN -> KNOWN path a substitution must clear `repair.PHONETIC_MIN` (jaro-winkler,
  default 0.75, `REPAIR_PHONETIC_MIN`). Measured: it admits `dothamingo -> doflamingo`
  0.893, `zolo -> zoro` 0.867 and `syrahose -> shirahoshi` 0.755, and blocks `oimo -> zoro`
  0.667. It is KNOWINGLY imperfect -- `vivra -> vivi` scores 0.848 and passes -- and no
  threshold can separate that case, because the genuine syrahose fix scores LOWER than it.
  Metaphone cannot discriminate either: False for every pair. That residue was attributed
  to glossary COVERAGE; [S-16] tested that and FALSIFIED it 2026-08-27 -- adding
  `Vivre Card` changed nothing, the same repair was proposed and admitted. So the gap is
  [S-15]'s own and has no assigned cure; it must not be routed to [S-2].
- [S-16] DONE 2026-08-27, and the answer is the unwelcome one. Adding `Vivre Card` to the
  glossary and re-running S31E01 on the real code produced an IDENTICAL set of 21 repairs,
  `VIVRA -> Vivi` among them. The coverage story is dead: the model did not reach for the
  correct term when it was present. [S-15] needs a different mechanism, and the three
  untested candidates -- a frequency prior over the reference list, the prompt's
  person-name framing, or `VIVRA` simply being nearer `Vivi` internally -- are recorded in
  `docs/Adversarial Reviews/RESULTS-2026-08-27-s16-coverage-falsified.md`.
- [S-4] Narrow acquisition's transcript scope to the season(s) actually queued for
  transcription rather than the whole show. Justified on COST only: acquire's dominant cost
  is documented as 8202 tokens x 8109 titles and it re-walks 461 episodes to learn about the
  48 queued. It must NOT be presented as also fixing admission -- [S-9] measured that and it
  admits 0 of 3.

  Scoping needs NO Python change. `_iter_episode_texts` is `os.walk(show_dir)`, so passing a
  SEASON directory already restricts the harvest -- verified 2026-08-27. What is missing is
  only the caller knowing which seasons have queued work: `gen_loop.sh` passes `$ANIME/$show`
  and has no per-season staleness signal, while `generate.py` computes exactly that in
  `partition_todo` and does not report it. So the work is plumbing a signal that already
  exists to a caller that already accepts it, not new harvesting logic.

  Deliberately NOT built 2026-08-27: acquire applied 0 of 20 proposals on its last run, so
  this optimises the cost of a stage currently producing nothing. Worth doing when the
  admission gates change; not before.

- [S-5] RE-SCOPED 2026-08-27. Was: consolidate the prompt build and the raw acquire into
  one stage. The prompt build is gone -- [S-3] withdrawn, [S-10] cut -- so there are no
  longer two outputs to consolidate. What survives is narrower and still worth doing: ONE
  arc fetch per season serving both consumers, [S-11]'s tagging and acquire's candidate
  resolution, rather than each fetching independently.
- [S-6] MOOT 2026-08-26, kept for the record. Was: make decoder-input staleness
  season-aware so a per-season HOTWORDS string marks
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
- [S-8] MOOT 2026-08-27, by construction. It existed to stop two modules deriving wiki
  state independently. [S-2] landed the arc fetch INSIDE `glossary_verify.py`, sharing its
  `_http_json`, `normalize_api` and continuation handling, so there is no second copy and
  the drift it guarded against cannot occur. Extracting a layer now would be migrating
  working code for symmetry, which the round-1 review's F8 argued against and this repo's
  own rules forbid.
- [S-9] DONE 2026-08-27. Narrowing acquisition scope admits 0 of the 3 confirmed false
  negatives. The denominators DO move -- `Samji -> Sanji` is 1/811 show-wide and 1/34 within
  Season 30 -- but the gates that refused them are not ratio gates. `Samji` was refused by
  `variant_count < NEAR_MISS_MIN_COUNT` (`glossary_acquire.py:479-481`), which tests the
  MISHEAR's own recurrence: it appears exactly once in either scope, and narrowing cannot
  change a count of one. `Shadron` and `Uggh` were refused `sentence-initial-only`
  (`:520`), which is positional and has no scope dimension at all. The hypothesis assumed
  the refusals were about the ratio between mishear and canonical; two are positional and
  the third is about the mishear alone.

## Out of scope

- Changing the phonetic name guard (`repair.invents_name`) itself -- it ships at v6 and is
  unchanged by this leg.
- Unanchored (no-fansub) LLM card repair. `repair.py:622` still skips cards with no fansub
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

Season scoping survives ONLY in the repair prompt ([S-13]) and the tags that weight it
([S-11]). Nothing season-scoped reaches the DECODER any more: per-season `initial_prompt`
was measured inert and hotwords was cut.

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

## The bar has no runtime enforcement — human review is a required step

The round-2 review's deepest finding, verified on current code 2026-08-26: `accept_repair`
admits BOTH of the acceptance bar's own regression examples.

    accept_repair("We're looking for a factory.", "We're looking for a needle.", ...) -> True
    accept_repair("It is a VIVRA card", "It is a Vivi card", ...)                     -> True

The gate is mechanical -- length ratio, card fit, reference borrowing, invented names --
and none of those can tell "same meaning" from "meaning destroyed". The owner's bar is a
contract with NO runtime counterpart, and pretending otherwise is how a thousand quiet
regressions ship.

So the review step is part of the acceptance procedure, not an optional courtesy:

**No measured episode is accepted until a human has read its repaired lines against the
bar.** The measurement on S31E01 did exactly this -- 21 lines read, 18 acceptable, 3
regressions identified, one of which turned out to be a coverage gap rather than a repair
defect. That procedure is the enforcement mechanism; it is not scaffolding around one.

The workload is bounded, and the arithmetic matters because the review got it wrong first:
the burden is REPAIRED LINES, not targets. S31E01 produced 21 repairs from 161 targets, so
a 48-episode season is roughly 1,000 lines to read, not 7,700. At the measured 3-in-21 rate
that is ~144 regressions per season -- a real cost, an order of magnitude below the
review's "roughly a thousand", and the arithmetic error was conceded in its own rebuttal.

Recovery is MANUAL but it exists: the srt is regenerated from `conf.json` on every pass,
every proposal is recorded to the unresolved queue with its text, and repair is text-tier,
so a regression found in review is fixed by editing the glossary and re-running on CPU. The
review's "no recovery path" was withdrawn; "no AUTOMATIC recovery path" is the accurate
claim and is the reason the human step is mandatory rather than advisory.

**The 21-sample result is a go/no-go for continuing the measurement sequence. It is not a
ship signal**, and no S-item should be read as one.

## Build order and the decision rule

**This is a sequencing constraint, not advice. [S-10] is measured FIRST.**

Every arc-shaped item in this leg — [S-1] season resolution, [S-2] arc-scoped fetch,
[S-5]'s arc fetch, [S-8] the wiki layer, [S-11] arc tags — now feeds [S-13], the
season-weighted repair glossary. [S-10] was its original consumer and is cut, so this rule
was rewritten after the round-2 review pointed out it still named a dead item.

The constraint it expresses is unchanged and still binds: [S-13] is BUILT and provably
INERT — measured 2026-08-26, the term set did not move because only 4 of 17 tagged names
exist in the glossary. So the arc machinery's whole remaining value is COVERAGE, and
building more of it before [S-2]/[S-11] demonstrate coverage gain is how it gets built and
then abandoned.

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
- [ ] [S-9] DONE. Re-measured with season-scoped denominators: narrowing admits 0 of 3,
      because two were refused positionally (`sentence-initial-only`) and the third by the
      mishear's own recurrence (`variant_count < 2`), which scope cannot change. Recorded in
      `docs/Adversarial Reviews/RESULTS-2026-08-27-s9-scope-narrowing.md`. Admitting them
      needs a gate change, which stays UNMADE until the opposite measurement exists: how
      many BAD terms each gate currently refuses.
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
      `repair.py:162 (skips_unanchored)`. After [S-12] that episode reports a non-zero repaired count, and the
      reference-anchored path is unchanged.
- [ ] [S-12] The gate is conditional, not deleted: with the new path disabled the same
      episode reproduces `targets=161 repaired=0` exactly.
- [ ] [S-13] Measured on PROPOSAL QUALITY, not on the gate. The reorder refuses nothing --
      it moves terms inside a 1000-char cap -- so an acceptance test phrased as "X is not
      accepted" is vacuous for it and was rewritten after the round-2 review said so. The
      test: a Dressrosa-weighted prompt makes the LLM propose fewer out-of-arc name
      substitutions than the unweighted prompt on the same cards.
- [ ] [S-13] Its effect is bounded by coverage and the spec says so: measured 2026-08-26,
      the term set was UNCHANGED at 110 because only 4 of 17 tagged Dressrosa names exist
      in the glossary. [S-13] is inert until [S-2]/[S-11] populate tags, and that -- not the
      weighting -- is the gating constraint.
- [ ] [S-14] `substitutes_a_vouched_name` refuses a substitution whose ORIGINAL is a
      glossary name, and `accept_repair` applies it only when `ref` is empty. Unanchored
      `Oimo -> Zoro` is refused; the same swap WITH a reference is accepted; and both
      `Dothamingo -> Doflamingo` and `zolo -> Zoro` stay accepted, their originals unknown.
- [ ] [S-14] The vouched-name rule still fires when `jellyfish` is absent. Only the [S-15]
      half may degrade with the optional dependency; degrading both would let the exact
      documented failure through on a box without it.
- [ ] [S-15] The phonetic gate blocks `oimo -> zoro` at 0.667 and admits
      `syrahose -> shirahoshi` at 0.755, the tightest genuine fix in the set. A threshold
      that rejects the syrahose case is wrong regardless of what else it blocks.
- [ ] [S-16] With `Vivre Card` added to the glossary, the S31E01 re-run either stops
      proposing `VIVRA -> Vivi` (coverage confirmed) or still admits it (coverage defence
      falsified, [S-15] needs rework). The result is recorded either way.
- [ ] [S-12] [S-13] [S-14] Measured on the ~161 targets per episode already on disk, on CPU,
      against the arms captured 2026-08-26, counted by the same symmetric defect shapes that
      cut [S-10] — repetition runs, gibberish cards, cards over 12s, capitalised
      non-dictionary tokens absent from the baseline — not by a name list chosen afterwards.

## Open questions
