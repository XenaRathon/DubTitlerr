# Luna rebuttal of the A/B findings

## Verdict

I would **overturn the headline generalization** (the claim that `initial_prompt` changes
“NOTHING” without a scope qualifier), **overturn the claim that the Dester regression is
unrepairable**, and **downgrade rather than accept** the claims that the A/B disproves the
spec’s arc problem and that the Dothamingo observation is already a generalized defect.
I would **not reinstate [S-3] as the production mechanism yet**: the A/B is underpowered
and the first-window geometry is unverified, but the verified code does not justify calling
[S-3] dead. The correct disposition is “defer the choice pending a decisive full-episode
measurement,” not “replace it by default with hotwords.”

The author’s own correction is only half-validated. The repository confirms the mechanism
that makes a cascade possible: `generate.py:890` sets `condition_on_previous_text=False`,
while the repo’s comment at `generate.py:893-913` describes the prompt as decoder input and
`generate.py:949` persists the result. The installed `faster_whisper` source was not
available in this repository, so the quoted dependency line numbers and all VM102/audio
measurements remain **unverified here**. The findings therefore establish a measured
three-episode observation, not the universal causal conclusion attached to it.

## 1. The null result is weaker than its headline

The findings report only three episodes, one show, one model/configuration, 10,487 versus
10,459 tokens, five differing runs, and identical counts for 15 selected terms (RESULTS
§§Method, Word-level comparison, Arc-name recall, approximately lines 7–75). That is useful
negative evidence for this exact run, but it is not a sensitive test of recognition.

First, count equality is weak when terms occur between 1 and 28 times. A misrecognition can
occur at the same number of positions in both arms, and the findings do not publish
position-level recall, substitutions, confidence, or alignment against a reference
(RESULTS arc-name table, lines 58–75). Identical frequency is therefore compatible with
identical failure patterns.

Second, the comparison deliberately lowercases and strips punctuation and then compares
index-aligned token sequences (RESULTS lines 31–46). That is defensible for punctuation
noise, but it can hide segmentation and local structural changes. The card counts are
586/586, 393/389, and 500/496 while the report reduces the difference to five “runs”
(RESULTS lines 34–52). Without the actual alignment and a definition of “differing run,”
there is no demonstrated equivalence between five runs and all meaningful transcript
changes. The word-similarity range is near one precisely because it is a corpus-level
metric; it is not a name-recognition metric.

Third, “all five differences are hallucination-gate artifacts” is presented as a conclusion,
not a per-run verification protocol (RESULTS lines 48–56). Two entries are the same phrase,
`so let s wake up`, in E01 and E03. Repetition does not make the attribution independently
verified. The report needs per-run timestamps, segment boundaries, gate inputs, and a
re-run with the gate disabled or held constant before that causal label is accepted.

Finally, arm A’s Enies Lobby names appeared in neither transcript (RESULTS lines 77–80).
That does **not** show that the wrong prompt cannot inject wrong names. It shows only that
this audio/configuration supplied no observed opportunity. To test injection, the audio
must contain a spoken or acoustically ambiguous token at which an Enies name could compete,
and the arms must be compared against a trusted reference at that position. No Enies Lobby
dialogue means the injection hypothesis was not exercised.

**Disposition:** overturn “changes NOTHING” as an unqualified conclusion; retain only “no
material difference was detected by these reported aggregate metrics in these three files.”

## 2. The opening-theme generalization is unverified, and the correction exposes the gap

The load-bearing premise that the first window is a sung opening theme with no character
names is asserted in RESULTS lines 91–99 and repeated in the spec header (spec lines 5–15).
The media library is unavailable on this box, so I cannot verify that S31E01–E03 begin that
way, nor that VAD-off behavior at `generate.py:889` makes the first window speech-free.
The findings should not promote that premise to a fact.

The geometry is especially important because the spike deliberately starts at 600 seconds
and places the target around 57 seconds into that clip (RESULTS lines 108–124), whereas the
full-episode argument depends on the first window containing only theme material. The
asymmetry is evidence that the experiment selected a dialogue-rich first window; it is not
evidence that the full episodes selected a theme-only first window.

The correction says a prompt can alter first-window segmentation and thereby shift later
windows, producing changes at 46.3 and 53.0 seconds (RESULTS lines 87–105). That makes the
full-episode null more, not less, dependent on proving the first window’s content. If any
full-episode first window contains dialogue, the cascade is available. If it contains only
music, the prompt may indeed be inert there. Both cases must be measured, not inferred.

The decisive experiment is straightforward: retain the A/B arms, dump first-window audio
boundaries and decoded segments for S31E01–E03, and run a second matched A/B on an episode
whose first window demonstrably contains dialogue. Compare position-level name edits,
segment boundaries, and downstream window starts. That experiment decides whether the
null is an audio-geometry artifact or a decoder-level null.

**Disposition:** overturn the attempted generalization; downgrade the narrower observation
“these three measured episodes showed no detected name difference.” [S-3] remains unproven,
not disproven.

## 3. The spike supports investigation of [S-10], not default adoption—but the demand for a
ratio is not logically sufficient either

The spike is the strongest positive evidence in the findings: the target at 657.3 seconds
was corrected by `hotwords`, deterministically across two runs, with reported equal VRAM and
near-equal runtime (RESULTS lines 108–129). That is exactly the position where the purpose-
built `initial_prompt` failed, so it is evidence that the delivery mechanism can matter.
The findings undersell this by treating one fix and one regression as a reason to discount
the mechanism entirely.

At the same time, one 180-second clip cannot license default enablement. The correct action
is not necessarily “measure a ratio over one full episode and then trust it.” A ratio can
hide severity, location, and category: one catastrophic regression may outweigh many minor
spelling improvements, and a regression on an anchored versus unanchored card has different
repairability. The acceptance criterion’s requirement for a full episode (spec lines
196–204) is a useful minimum, but it needs position-level error classes and a decision rule,
not merely a scalar count.

The “no later stage can repair Dester” statement is factually too broad. `repair.py:493–518`
skips only cards without a reference. On an anchored card, the LLM path proceeds through
`glossary.correct(new, gloss)` at `repair.py:512–513` and then `accept_repair()` at
`repair.py:522` onward. `invents_name()` is substitution-scoped: it computes proper-noun
loss and unknown proper-noun gain (repair.py:276–335). `Dester` is capitalized but
`jester` is an English word, and a proposed `Dester` → `jester` edit loses the invented
noun rather than replacing a real proper noun with another unknown proper noun. The guard
therefore need not reject it. The findings’ own quoted code path supports the GLM review’s
narrower conclusion: deterministic correction cannot fix it, and no-reference cards cannot
reach the LLM, but anchored cards may.

**Disposition:** downgrade the regression from “irreparable” to “potentially repairable
when anchored, irreparable under the current no-reference policy.” Overturn any requirement
that [S-10] be rejected solely because the 180-second spike has a 1:1 fix/regression count;
require a full-episode, position-level safety measurement before default enablement.

## 4. Dothamingo is a valid bug report, not yet a generalized defect

The observed `Dothamingo` miss is credible as a single failure: the results say it survived
an explicit `Doflamingo` prompt and remained unchanged through `glossary.correct()`
(RESULTS lines 151–166). The repository confirms why: `_fix_token()` first applies hard
fixes and exact names, then fuzzy matching and phonetic matching, with `_one_indel()`
exclusions on both tiers (`glossary.py:167–189`). But one token and one distance do not
establish prevalence across the glossary or across episodes. No miss-rate denominator,
near-distance sample, or comparison against other names is reported.

The recommendation also exceeds scope. The spec explicitly leaves changes to the phonetic
name guard and unanchored repair out of scope (spec lines 49–53). Thus Dothamingo identifies
a real gap in the existing correction stack, but it does not by itself invalidate the
in-scope season machinery. Conversely, the spike is the only reported evidence of any
mechanism changing an arc-name token past the first window (RESULTS lines 108–129), so it
should not be treated as less relevant merely because it is inconveniently small.

The Samji → Sanji datum cannot be placed in this bucket without source verification. It is
mentioned in the prosecution prompt/spec acceptance material, but no repository source here
anchors the claimed `seen 1/721` result or proves whether `correct()` or acquire’s admission
gates refused it. The results file does not establish that diagnosis.

**Disposition:** downgrade “the defect that IS demonstrated” to “one demonstrated bug
instance requiring a prevalence measurement.” Do not use it alone either to expand scope or
to dismiss [S-10].

## 5. `stale_tier` survives most of the enumeration; the renumber case is bounded

The verified current implementation compares the stored prompt string with the derived
prompt (`glossary.py:93–129`). A hard-fix or names-only edit does not alter the derived
prompt, while an `initial_prompt` edit does; the tests explicitly encode those distinctions
(`tests/test_glossary.py:198–226`). The two-tier rationale is also explicit in `common.py:133–142`:
transcription-affecting prompt changes belong to the transcribe tier, while downstream text
changes belong to the text tier.

That means:

- Removing a season entry makes that season derive the fallback show prompt; if its stored
  prompt is already the fallback, it is fresh, otherwise only that season becomes stale.
- A byte-identical season entry is a string-comparison no-op.
- A season renumber can orphan the old entry and make the new season fall back silently.
  That is a correctness miss, but its immediate cost is a fallback prompt, not a guaranteed
  full-library re-transcription.
- Missing stored prompt is explicitly stale (`glossary.py:125–129`), so old `words.json`
  artifacts are not silently treated as fresh.
- Editing the show’s `initial_prompt` changes the derived string for every episode using it,
  which is exactly the transcribe-tier behavior documented in `common.py:139–142`.

Only changes to a shared show-level prompt can stale more than one season. A season-specific
entry, removal, or renumber affects the season whose derived prompt changes; a byte-identical
entry affects none. The prosecution’s “silently re-transcribes the library” framing is
therefore too strong. The main unresolved risk is silent semantic fallback after metadata
renumbering, not an unbounded GPU storm. Given the narrow A/B evidence, fallback harm is
unknown but plausibly bounded; it must not be claimed near-zero until the prompt experiment
is settled.

**Disposition:** overturn the claim that the listed states generally cause silent whole-
library retranscription; downgrade renumbering to a bounded correctness risk and require
logging of fallback/entry changes.

## 6. The prompt-only rule does not create the claimed permanent guard deadlock

The prosecution’s construction assumes that a correct prompt-induced `Rebecca` token is
still absent from the glossary when repair runs. That is possible, but the guard does not
compare only against a fansub reference. `invents_name()` builds its known set from
`gloss["names"]` and token-fix values (repair.py:276–335), and `accept_repair()` invokes it
at the guarded acceptance point (repair.py:522–523). A reference can justify an edit for
ordinary repair, but the proper-noun guard’s known-name comparison is glossary-based, not
reference-membership-based. So the prosecution’s claim that a reference-supported move
must be admitted is also not established; nor is the claim that it must be rejected in all
cases.

More importantly, the proposed deadlock is not permanent by design. The spec forbids adding
wiki names without transcript evidence (spec lines 45–53), while acquire harvests from
existing transcripts and resolves candidates against wiki titles (`glossary_acquire.py:829–
899`). If whisper emits `Rebecca`, the token is transcript evidence; whether it is admitted
is governed by acquire’s gates. After admission, it is in the show-wide `names` set used by
both correction and the guard. The only unverified part is the gate outcome, including the
Samji claim.

**Disposition:** overturn “the design necessarily deadlocks”; downgrade it to a finite,
gate-dependent bootstrap risk that [S-9] is specifically tasked to measure. The spec’s
invariant is coherent: prompt-only priming supplies evidence; acquisition decides whether
that evidence is good enough.

## 7. [S-11] is directionally defensible, but its edge cases need tests

The split between broad correction and narrow priming follows actual code boundaries.
`glossary.correct()` consumes the show-wide `names` and fixes each card (`glossary.py:192–203`),
while the proposed season tags are intended only to select hotwords. A recurring character
such as Caesar should remain available to correction across arcs; filtering it out of the
show-wide list would make correction worse. The prosecution is right that a name acquired in
one season may recur in another, and the current acceptance criterion tests only one direction
(spec lines 186–190). That is a missing test, not proof the split is wrong.

There are legitimate narrow-correction cases—aliases, titles, and names whose canonical
form changes by context—but the current `correct()` implementation has no season argument
and no contextual parse priority (`glossary.py:192–203`). [S-11] cannot solve those without
changing the correction contract, so they are outside this leg rather than evidence that
season tags should be used to narrow correction accidentally.

Likewise, a recurring name may be worth broad priming, but the hotword list must be bounded
because the reported spike also produced a regression (RESULTS lines 130–145). The right
policy is to test recurring cross-season names and rank them, not to infer from one edge case
that every tagged name must be globally hotworded.

The truncation boundary is not verifiable from this checkout because `faster_whisper` is an
installed dependency and its source was not found here. The findings quote a branch at
`transcribe.py:1547` that keeps the front when `len(hotwords_tokens) >= max_length // 2`,
while the spec quotes `:1550` for prompt-tail truncation (spec lines 63–65). On the quoted
logic, with `max_length=448`, the half-budget is 224 and the retained slice is 223 tokens;
exactly 224 hotword tokens enter the truncation branch and are reduced to 223, while 223
or fewer remain intact. But the claimed “previous_tokens is empty every window” does not
by itself prove the effective combined first-window budget; that interaction must be measured
in the installed version.

**Disposition:** downgrade the contradiction to an acceptance-test gap. Defend the broad-
correction/narrow-priming architecture, but require bidirectional recurrence tests and a
first-window budget probe.

## 8. Scope and ordering: the spec attacks a real upstream bottleneck first

The prosecution is right that three of four sampled shows lack glossaries, but the spec’s
[S-7] promise is to preserve today’s behavior when arc resolution or a glossary is absent
(spec lines 42–47 and 153–160). `generate.py:107–124` loads an empty glossary and derives a
neutral prompt when no glossary file exists; `glossary.correct()` has no names to act on.
Arc machinery cannot make that fallback worse by construction unless it changes the fallback
path, which the acceptance criteria explicitly prohibit.

The no-reference hole is real and large: `repair.py:493–518` skips unanchored cards before
the LLM call, and the code comment explains that glossary-only repair hallucinated names.
That ordering is load-bearing. Without transcript evidence, the spec’s invariant forbids
writing wiki names into `names`; without names, the guard cannot safely admit arbitrary LLM
proper nouns. The prosecution has not named a coherent alternative that grows the glossary
without either transcript evidence or a new safety mechanism.

This does not prove the arc leg is sufficient, but it does defend its order: first improve
what can supply correct transcript evidence, then measure acquire admission ([S-9]), then
consider unanchored repair as a separate risk. The A/B null does not erase that architecture;
it only says the original prompt delivery route was not demonstrated in the tested slice.

**Disposition:** overturn the claim that the spec is merely choosing a cheap problem instead
of the right upstream problem. Downgrade the scope criticism to “the next leg remains
necessary.”

## Final decision on [S-3]

[S-3] should **not return as an enabled production requirement on this rebuttal alone**;
the full-episode measurement and dependency-source verification are still missing. But it
should not remain marked dead on the strength of the findings file. The honest state is:

1. The three-episode A/B does not measure position-level recognition sensitivity well enough
to prove universal inertness.
2. The author’s own clip correction demonstrates a plausible segmentation cascade, making
first-window geometry decisive and currently unverified.
3. Hotwords has one positive targeted result and one regression, so [S-10] is promising but
not ready for default enablement.
4. [S-9] and [S-10] should be retained as measurement work, with a full-episode,
position-level evaluation and explicit severity/anchorability accounting.
5. After that experiment, [S-3] can be reinstated if dialogue-first episodes show a stable
benefit, or retired if matched dialogue-first and theme-first tests remain null.

The findings successfully challenge the original causal story (“the wrong prompt caused
these mishears”), but they do not justify the stronger replacement story (“per-season
`initial_prompt` is inert everywhere, while hotwords is the established answer”).