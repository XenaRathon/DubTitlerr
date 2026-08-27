# Review — round 2, after the leg changed shape

Sixth review on **DubTitlerr**, second on this leg. My round-1 review
(`GLM-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md`) was acted on, the
measurements demolished most of the leg, and this round reviews what replaced it. I checked
the current state on this box: the working tree is clean at `6fd8fb2`
("feat(repair): weight the prompt's reference spellings by the episode's arc"), which
implements [S-1] (`glossary.arc_for`) and [S-13] (`_glossary_terms(gloss, arc)`,
`build_prompt(..., arc)`) — so some of the brief's premises have moved since it was
written, and I say where. Everything below is verified against the committed code unless
marked unverifiable; the LLM runs, media, and `faster_whisper` internals are not reachable
from a checkout and are treated as unverified.

## Verdict first

**Do not cut the leg. Do not ship it as written.** The Dothamingo fix
(`RESULTS-2026-08-26-unanchored-repair.md`, lines 30-31) is the only positive evidence in
the entire round that any mechanism fixes the demonstrated defect — `glossary.correct()`
cannot reach it (difflib 0.800 vs 0.84, metaphone T0MNK/TFLMNK, verified), hotwords was cut
for corrupting neighbours, and unanchored repair fixed it in one pass. That is a real
result and it is the leg's reason to exist.

But the measurement that justifies ungating the LLM has three load-bearing gaps, and I
would **block the build** on all three:

- **F1 — the measurement's own regressions pass the production gate** (verified). Two of
  the three regressions — including both of the severe-class ones — are admitted by
  `accept_repair` as it exists today. On S31 every card is unanchored, so every such
  regression ships permanently with no downstream pass.
- **F2 — the guards that produced the "byte-identical" safety verdict are not in the code
  or the spec.** [S-14] is unimplemented (verified: the criterion fails against current
  code), and the phonetic gate (jaro-winkler 0.75) exists nowhere — not in the spec, not
  in `repair.py`. The measurement used throwaway patches; the acceptance criteria as
  written cannot pass.
- **F3 — [S-13] is built, inert, and its acceptance criterion measures the gate, not the
  weighting.** The commit's own measurement shows the term set is unchanged (4 of 17
  tagged Dressrosa names exist in the glossary), and the criterion ("Oimo -> Zoro not
  accepted") is satisfiable only by the unbuilt [S-14] — the reorder cannot refuse
  anything.

Six notes follow (F4-F9). The honest remainder, after the cuts and this review: **[S-12] +
the guards, implemented, + glossary coverage ([S-2]/[S-11]/[S-4]) + [S-9]**. The arc
machinery survives only as coverage, not as priming — and the owner's own commit message
already says so.

## F1 — BLOCK. The measurement's regressions pass the production gate

The owner's bar is referent and sense, not word-for-word (`spec:180-199`). The bar's own
REGRESSION class is:

    "looking for a factory." -> "looking for a needle."   meaning destroyed   (spec:194)
    "It's a VIVRA card?"     -> "It's a Vivi card?"       wrong referent      (spec:195-196)

Both of these are in the measurement's own regression list (U:44-48), and both **pass
`accept_repair`** as written (verified here):

    accept_repair("We're looking for a factory.", "We're looking for a needle.",
                  ref, 3.0, gloss)                       -> True   (needle in ref OR not)
    accept_repair("It's a VIVRA card?", "It's a Vivi card?", "It's a Vivre card",
                  2.5, gloss)                            -> True

The mechanical gate checks length ratio, card fit, reference-borrow count, and name
invention (`repair.py:362-399`) — none of which can distinguish "same meaning" from
"meaning destroyed". The owner's bar has **no runtime counterpart**: nothing in the
pipeline judges referent or sense. The measurement caught its own regressions only because
a human read all 21 repaired lines against the bar — a procedure that does not exist in
production and does not scale.

The severity is structural, not hypothetical. Every S31 card is unanchored (6,492
`no_reference`), so every one of these repairs is applied and written to the shipped srt
(`repair.py:603`) with no later pass; the unresolved queue is post-hoc observability. At
the measured rate — 3 regressions in 21 repairs, two of them severe-class — a season of 48
episodes at ~161 targets each is roughly a thousand shipped regressions with no recovery
path.

The spec's decision rule (`spec:213-260`) has no repair analog: its SEVERE class
(`spec:215-224`) is written for decoder arms. Under a faithful extension — "meaning
destroyed" is to repair what the 30-second "Grr!" card is to the decoder — this sample
contains **two** severe regressions and the rule blocks adoption by the author's own
rubric. The spec must either extend the rule to repair or say plainly why the repair
leg's severe class is different. Until a meaning-level gate or a human adjudication loop
exists, [S-12] must not ungate.

## F2 — BLOCK. The safety story is measured on components that do not exist

The measurement's headline safety result — "[S-12] + [S-14] both guards ... identical set
... Zero regressions prevented, zero fixes lost" (U:50-55) — was produced with **both
guards enabled**. Neither is in the code:

- **[S-14] (known->known refusal) is unimplemented.** Verified here:
  `invents_name("Oimo", "Zoro", gloss)` → False — the current v7 guard *permits* the exact
  substitution [S-14] exists to refuse. The [S-14] acceptance criterion — "`invents_name`
  refuses a substitution whose ORIGINAL is a glossary name" (spec:452-454) — **fails
  against the current code**.
- **The phonetic proximity gate (jaro-winkler 0.75) is specified nowhere.** It appears
  only in the results file (U:52-53, 70-82). No S-item names it; grep of the spec and
  `repair.py` finds no jaro/winkler/0.75. The measurement's "phonetic proximity on the
  unknown->known path" is a throwaway patch with no home.
- Consequently the [S-13] criterion ("a proposed Oimo -> Zoro is not accepted",
  spec:450-451) also fails against current code: with no [S-14] and no phonetic gate,
  Oimo -> Zoro is admitted end to end (verified).

This is the round-1 F5 pattern repeated: the leg's safety story rides on components that
exist only in a measurement. The fix is not to remove the guards — it is to **implement
[S-14] and the phonetic gate (or explicitly cut them) before the ungate lands**, then
re-run the measurement on the real code so the "identical set" claim is about the thing
that ships.

## F3 — BLOCK. [S-13] is built, inert, and its criterion measures the wrong thing

[S-13] landed in `6fd8fb2`: `glossary.arc_for` (`glossary.py:93-125`),
`_glossary_terms(gloss, arc)` (`repair.py:122-158`), `build_prompt(..., arc)`
(`repair.py:162`), threaded from `process()` (`repair.py:493`). The implementation is
defensible — it reorders, never filters, and its docstring correctly retracts the
"makes Oimo -> Zoro implausible" story (spec:104-111 now says the same). The withdrawal of
the backwards justification is honest and welcome.

The problem is what the commit itself measures:

> the term SET is unchanged at 110 because only 4 of 17 tagged Dressrosa names exist in
> the glossary at all. The Dressrosa arc has 96 entities on the wiki against 92 names for
> the ENTIRE show, so [S-13]'s benefit is currently bounded by coverage.

So today [S-13] changes **nothing** about any prompt: no glossary in the library carries
`arc_tags` (the commit says so; the test asserts the no-arc prompt is byte-identical).
That is acceptable plumbing — but the spec presents it as the safety mechanism, and the
acceptance criterion is vacuous:

- The criterion (spec:450-451) tests the **gate** ("Oimo -> Zoro not accepted"), which the
  reorder cannot affect — reordering moves terms within a 1000-char cap (`repair.py:143-157`);
  it refuses nothing. The criterion is satisfiable only by the unbuilt [S-14] (F2).
- The real test of [S-13] is proposal quality: does a Dressrosa-weighted prompt make the
  LLM propose fewer out-of-arc substitutions than the unweighted one? That requires the
  tags, the coverage, and the LLM — none of which the criterion exercises.

There is also an ordering violation to record: the spec's own build-order rule says
"measure first, build after" (spec:206-212), and [S-1]/[S-13] were built before their
consumer effect was measured. The commit's own measurement is the evidence the rule
exists to force — it landed after the build, not before. That is the same reflex the spec
correctly identified in itself once already.

**Required:** rewrite the [S-13] criterion to measure proposal quality (or coverage
boundedness), and state in the spec that [S-1]/[S-13] are inert until [S-2]/[S-11]
populate tags — which is the actual gating constraint.

## F4 — NOTE. 21 repairs is not a documented-sweep-sized reversal

The bake-off that closed the unanchored path was a documented sweep — 3 shows × 40
targets, two models, measured prompt variants (`repair.py:163-201` documents it). The
reversal rests on **one episode, one model** (nanbeige4.2-3b, U:5), 21 repairs (U:11-13).
The prompt's question stands: one episode of one show with one model is not the same
evidence class as the decision it reverses. The asymmetry the brief names is real and
sharp: all 6,492 S31 cards are unanchored, so **every** regression on this show is
permanent — there is no anchored majority whose repair could dilute the damage.

That said, I do not recommend cutting on this ground alone. The sample's one genuine
success (the Dothamingo fix) is the class the whole round has been chasing, and the
regression rate is measurable rather than speculative. The bar is: multi-episode,
multi-model measurement, with the F1 meaning-level gate and the F2 guards implemented
first — then the 18/3 ratio means something.

## F5 — NOTE. [S-14] as unproven insurance: defensible in principle, unimplemented in fact

The results file is honest about what the guards did: "insurance against a documented
prior failure that did not recur in this sample, not an observed improvement" (U:65-68).
Keeping insurance against a **documented** failure — Oimo -> Zoro is the recorded reason
the unanchored path was closed (`repair.py:536-538`) — is defensible on this repo's own
rules: it is not speculative need, it is a known failure mode, and the guard is a pure
function.

Two corrections to the framing, though:

- The guard's invisible cost — a rejected good repair — is **not** as invisible as the
  brief fears: rejections are recorded to the unresolved queue with the proposal text
  (`repair.py:566`). The results file simply did not analyze them. In this run
  `rejected_guard=4`, all from the pre-existing length/borrow/fits gates (U:16-18), so the
  guard cost was zero in-sample — but that is because the sample never exercised the
  guard, which is the same reason its benefit was zero.
- "Keeping" an unbuilt guard is the speculative-need pattern dressed as prudence. The
  decision to keep [S-14] is not testable until it is implemented; the decision is being
  made on the measurement of a throwaway patch (F2).

**Disposition:** keep the guard in the spec, implement it with the [S-14] unit checks
(U:56-63) as its test suite, and count its rejections in the next measurement's analysis
rather than only its zero-effect headline.

## F6 — NOTE. The phonetic threshold: keep it, but specify it and test the coverage excuse

All five distances verify exactly (recomputed here with jellyfish):

    dothamingo -> doflamingo  0.893 GOOD        zolo -> zoro    0.867 GOOD
    vivra      -> vivi        0.848 BAD         syrahose -> shirahoshi  0.755 GOOD
    oimo       -> zoro        0.667 BAD
    metaphone: False for every pair (T0MNK/TFLMNK, SL/SR, FFR/FF, SRHS/XRHX, OM/SR)

The results file's conclusion is therefore correct: no threshold separates good from bad
(0.755 < 0.848), metaphone cannot help, and 0.75 is the optimum that blocks the documented
class while admitting the genuine fixes (U:70-82). The threshold is worth having — it is
not the problem.

The problems are two. First, **the gate has no home**: it is in the results file and
nowhere in the spec or code (F2). A load-bearing safety gate that exists only in a
measurement is one refactor away from being lost. Second, **"coverage gap" is an
explanation for this case and an excuse as a general defense**. For VIVRA -> Vivi it is
true: "Vivre Card" is a real One Piece term absent from the 92 names, and the model
reached for the nearest present name (U:84-91). But the gate's entire job is to be the
backstop when coverage fails, and every absent glossary term leaks the same way. The
defense is only as good as the test that would falsify it: add "Vivre Card" to the
glossary and re-run. If vivra -> vivi is still proposed and admitted, the coverage story
is dead and the gate needs a different mechanism; if it disappears, the gate is exactly as
good as its coverage, which is [S-2]'s job — the file's own conclusion (U:88-91) — and the
spec should say so in an S-item.

## F7 — NOTE. The acceptance bar: coherent, but review-time-only and docstring-inconsistent

The bar (spec:180-199) is a real standard, and recording the Mihawk call as the owner's
explicit judgment (spec:186-190) is the right kind of provenance. Three problems:

- **It was set after the data.** The 18/3 classification (U:21) was made against the bar,
  then the bar was written to fit the classification. That is circular — not necessarily
  wrong, but it means the "18 acceptable" number is not independent evidence for the bar.
- **It has no runtime counterpart** (F1). Nothing in `accept_repair` checks referent or
  sense, and there is no adjudication procedure for production — the pipeline ships
  automatically; there is no human in the loop per repair.
- **It contradicts the code's own contract.** `accept_repair`'s docstring says "A
  dubtitle must match the DUB AUDIO" (`repair.py:365`), and the owner's bar explicitly
  overrides that for the Mihawk case. The docstring is now wrong and should be updated to
  the owner's bar — or the next reader of `accept_repair` will "fix" the pipeline to
  enforce a contract the owner has already replaced.

**Disposition:** keep the bar, update the docstring, and define the adjudication procedure
before [S-12] ships — "a human reads the repaired lines" must be either a built loop or a
stated per-episode step, not an assumption.

## F8 — NOTE. The defect counters cannot see the bar's severe class

The symmetric defect counting the spec mandates (spec:455-457 — repetition runs,
gibberish cards, 12s+ cards, non-dictionary capitalised tokens) was written for the
decoder arms and worked there. For repair it has the same shape of blind spot that misled
the author twice in the hotwords round: it counts what the author chose to count.

What it cannot see:

- **Meaning-destroying repairs.** `factory -> needle` is real English on both sides; no
  shape fires. It is the bar's worst class and the counter is blind to it.
- **Known->known name swaps.** `Oimo -> Zoro`: both capitalised, both non-dictionary; a
  "non-dict caps" counter sees nothing unless one of them is absent from the baseline —
  and the documented failure is precisely a swap between two *present* names.
- **Errors shared with the baseline.** A repair that leaves a baseline mishear in place,
  or reproduces it, is invisible to every "absent from the baseline" comparison.

The [S-12] measurement caught its regressions only by human classification of 21 lines.
That does not scale to ~7,700 targets across S31 (161/episode × 48). The spec's combined
criterion (spec:455-457) would pass an episode whose repairs contained ten
`factory -> needle`-class changes, because none of its counters can see one.

**Required:** a repair-specific counter — at minimum, per-repaired-line name-token diffs
against the glossary, and a sampled human-review step inside the decision rule rather than
after it.

## F9 — NOTE. The spec's title and internal coherence are stale

The title is `arc-scoped-acquisition-and-per-season-prompt`. Per-season prompts are cut,
hotwords is cut, and the live proposal is unanchored LLM repair with a season-weighted
repair glossary. A reader arriving cold cannot tell what the leg is. Specific staleness:

- **Problem section** (spec:37-60) still blames the wrong-arc prompt for manufacturing
  mishears ("Wrong prompt -> wrong transcript -> no arc tokens to harvest -> prompt never
  improves", spec:52-54), although the header note retracts exactly that causal claim
  (spec:31-35) and the A/B killed it. The Problem section is the first thing a cold reader
  reads; it argues for the mechanism the spec already withdrew.
- **Build order** still says every arc-shaped item "exists only to feed [S-10]"
  (spec:206-212). [S-10] is cut; the consumer is [S-13], already built. The sequencing
  constraint was not updated when the leg changed shape, and F3 shows the cost of that.
- **"read 'per-season hotwords'"** (spec:178) — there is no per-season hotwords.
- **[S-6] is MOOT** (spec:421-425) but still sits in the In scope list as if it were
  buildable.
- Line numbers drifted: the [S-12] text cites `repair.py:512/515-517`; the skip is now at
  `repair.py:536` and the prev/next build at `repair.py:543-546`.

**Disposition:** rename the spec (suggest: "arc-scoped coverage and unanchored repair"),
rewrite the Problem section to the post-A/B state, update the build order to name [S-13]
as the consumer with its coverage constraint, and add a per-S-item status line (BUILT /
SPECIFIED / MEASURED / CUT / MOOT). The owner's commit already acts like such a status
line exists; the spec should catch up with it.

## What survives — and the honest remainder

After the cuts, the measurement, and this review:

- **[S-1] + [S-13]** — built, inert until coverage. Their only justification is the
  coverage number (4 of 17 tagged names; 92 glossary names vs 96 arc entities), which is
  [S-2]/[S-11]'s job. The commit says so; the spec should too.
- **[S-12]** — the one measured positive. Gated by F1/F2.
- **[S-2]** — justified by one observation (Vivre Card), but it is the exact class of the
  repair leg's leak, and coverage is now the binding constraint on the whole leg. The
  "one observation" criticism is real; the observation is at least the right one.
- **[S-9]** — unchanged, and still the only measured plan for the admission refusals.
- **[S-4]/[S-5]/[S-7]/[S-8]/[S-11]** — plumbing for coverage and admission. [S-5]/[S-8]
  stand or fall as ordinary de-duplication (round-1 F8); [S-7] is status-quo by
  construction; [S-11] is the tag store [S-13] reads.

The prosecution's "what survives" question has a sharper answer than the spec gives:
**the arc machinery survives only as glossary coverage, and its effect is currently zero
until that coverage exists.** That is not an argument to cut it — it is an argument to
stop presenting [S-13] as the safety mechanism and to present [S-2]/[S-11] as the
load-bearing remainder, with [S-12]'s guards as the safety mechanism that must be
implemented.

## Bottom line

The leg should be reshaped, not cut and not shipped:

1. **Implement the guards** — [S-14] and the phonetic gate — and re-run the unanchored
   measurement on the real code. The "identical set" result must be about what ships.
2. **Add a meaning-level gate or a human adjudication loop** before [S-12] un-gates. The
   production gate demonstrably admits the sample's own severe regressions (F1).
3. **Rewrite the [S-13] criterion** to measure proposal quality or coverage, not the gate
   (F3), and let the spec's status catch up with the build (F9).
4. Then measure across episodes and models with a repair-specific defect count (F8) and
   the decision rule extended to repair (F1).

**The one thing most likely discovered mid-build:** the F1 fact. Whoever wires the ungate
will find that `accept_repair` cannot tell "same meaning" from "meaning destroyed", and
that the fix is a new component — a human loop or a meaning-level check — that no S-item
specifies. Build that before the toggle, not after.

## What I verified vs could not

Verified here (running or reading the committed checkout): `accept_repair` admitting
`factory -> needle` and `VIVRA -> Vivi` (True in both cases); `invents_name("Oimo", "Zoro")`
→ False (the [S-14] gap) and `invents_name("Dothamingo", "Doflamingo")` → False (accepted);
all five jaro-winkler distances and metaphone codes in U:72-80; the absence of the
phonetic gate from the spec and `repair.py`; the [S-13] implementation (`arc_for`,
`_glossary_terms`, `build_prompt`, `process`) in HEAD `6fd8fb2`; the no-reference skip at
`repair.py:536`; the rejected-proposal recording at `repair.py:566`; the srt rewrite at
`repair.py:603`; the docstring contract at `repair.py:365`.

Could not verify from this box: the LLM runs themselves (nanbeige backend, temperature,
latency), the 161-target episode state, the byte-identical guard comparison, and the
[S-13] end-to-end coverage measurement (4 of 17) — the last is quoted from the commit
message and is the owner's own number, treated as unverified per the rule.

---

# Rebuttal of this review — the author's case

This section argues against everything above, in the author's voice, checked against the
same code. The one rule applies to me as well: I have re-run every number I attack. The
strongest hits are led, and where a finding survives I say so rather than manufacturing a
collapse.

## The review's own arithmetic is wrong, and that changes F1's severity

F1 extrapolates "a season of 48 episodes at ~161 targets each is roughly a thousand
shipped regressions with no recovery path." That is wrong twice:

- 48 episodes × 21 **repairs** ≈ 1,000 repairs. Regressions are 3 per 21, so the honest
  extrapolation is **~144 regressions, ~96 severe** — a real number, but an order of
  magnitude below the review's scare figure. The review conflated the repair count with
  the regression count in its own headline.
- "No recovery path" is false in the letter. `repair.py` regenerates the srt from
  `conf.json` on every pass (`repair.py:603`), the rejected and repaired lines are
  recorded to the unresolved queue with their proposal text (`repair.py:566`), and the
  repair stage is CPU-tier — a regression found in review is fixed by editing the
  glossary or context and re-running, no GPU. The path is **manual** (review → fix →
  re-run), which is a real cost and not an automatic one — the review should have said
  "no *automatic* recovery path" — but it is not the permanent loss the finding claims.

F1's residual point survives in a narrower form: nothing mechanical stops a
meaning-destroying repair from shipping between reviews. That is a review-loop design
question, not a one-way door.

## F1 and F7 are one requirement, and the design half-contains it

F1 demands "a meaning-level gate or a human adjudication loop." F7 demands "an
adjudication procedure." These are the same requirement stated twice, and the design
already has the surface: the unresolved queue records every proposal for human review
(`repair.py:566`, `unresolved.py`). What is missing is one sentence in the spec making the
review step a stated part of the acceptance procedure — "a human reads the repaired lines
of each measured episode before it is accepted" — not a new component. The owner read 21
lines for the measurement; reading ~1,000 repaired lines across a season at watch-gated
pace is a bounded workload, not an open-ended one. The review's "does not scale" (F8)
conflates **targets** (7,728/season) with **repairs** (21/episode, ~1,000/season) — a
second arithmetic slip in the same shape as F1's.

## F2: measuring before building is the method, not a flaw — but the phonetic gate needs a home

The review calls it a block that the guards "are not in the code." Of course they are
not: the measurement exists to decide whether to build them, and the spec marks [S-12]
and [S-14] as unbuilt S-items with no BUILT marker — the one S-item that *does* carry a
BUILT marker ([S-13], spec:105) is the one that was built. An acceptance criterion fails
against current code until its leg is built; that is definitional, not evidence. The
hotwords spike ran on a throwaway patch for the same reason, and nobody called that a
safety gap.

The one genuinely indefensible corner of F2 is the **phonetic gate**. It exists only in
the results file (U:52-53, 70-82), and I checked the claim that it is even implicit in the
[S-14] criterion: it is not. The criterion's "accepted" clauses — `Dothamingo -> Doflamingo
accepted (original unknown)`, `zolo -> Zoro accepted` (spec:452-454) — are satisfiable
without any phonetic distance check, because an unknown-original substitution is admitted
by default under the known->known rule. So the gate is a load-bearing design decision with
no S-item home, exactly the repo's recurring failure mode. **This survives.** The rest of
F2 reduces to an ordering contract the author already intends: implement the guards with
the ungate.

## F3: the review faults the author for disclosing his own measurement

The 4-of-17 coverage number is not a secret the review extracted — the author published it
in the commit message and the [S-13] docstring. Calling the built-and-proven-inert
plumbing a "block" restates a disclosure. And the ordering charge is a misapplication: the
spec's build-order rule says the arc items "exist only to feed [S-10]" (spec:206-212) —
[S-10] is dead, so the rule as written cannot bind anything that feeds the live leg, and
judging [S-1]/[S-13] against a stale rule is exactly the kind of stale-document charge F9
levels at the spec. The measure-first principle governs *adoption*; you cannot measure a
mechanism that is not built, and the byte-identical no-arc test (in the commit) bounds the
damage of building it early.

What survives: the [S-13] acceptance criterion (spec:450-451) tests the gate, which the
reorder cannot affect — that is a genuine criterion bug, and it is a one-sentence fix, not
three paragraphs. Downgrade from BLOCK to a criterion edit that must land before the
criterion is green-lit.

## F4: the reversal is defensible on guard-coverage, not on sample size

F4's comparison is not a category error I can honestly claim: the bake-off that closed the
gate ("glossary-only repair hallucinates names (Oimo->Zoro)", `repair.py:536-538`) tested
exactly the question [S-12] reopens — repair without a reference. So the reversal cannot
be defended as "21 samples out-evidence a documented sweep." The defensible reading is
different and stronger: the documented failure mode is now **covered by design** — [S-14]
and the phonetic gate exist to refuse the Oimo->Zoro class, the unit checks validate that
coverage (7 of 7, U:56-63), and the 21-sample run establishes that the ungated path
produces real fixes with guard-covered regressions. What 21 samples cannot establish is
the regression *rate* — which is precisely what the deciding run the spec already
schedules (spec:455-457) is for. F4 therefore downgrades to the same labeling point as
F9: the 21-sample is a **go/no-go for the measurement sequence, not a ship signal**, and
the spec should say that sentence instead of leaving the reader to infer it.

## F5: the "invisible cost" is visible

The review itself records that rejections are logged with proposal text (repair.py:566) —
so the guard's cost is *not* invisible, it is un-analyzed, and the sample had zero guard
rejections to analyze. The note reduces to "analyze the rejections in the next run," which
is trivially accepted and belongs in the decision-rule criteria, not as a finding about
whether to keep the guard.

## F6: the coverage-excuse distinction is fair, and the file already routes the fix

The "explanation vs excuse" framing is the review's strongest F6 point and it survives —
but the results file already assigns the cure: "That is the concrete job left for [S-2]'s
arc-scoped acquisition" (U:88-91). The falsifying test the review demands (add "Vivre
Card", re-run) is precisely what [S-2]/[S-11]'s build will exercise. So F6's demand
reduces to the same one as F2's surviving half: put the phonetic gate and the Vivre Card
test in the spec where the file already points.

## F7: the docstring is a chore, and the bar-after-data charge overreaches

Updating `accept_repair`'s docstring to the owner's bar is a two-line edit; calling it a
danger to future readers is drama. And "set after the data" is only a defect if the
18/3 split is used as evidence *for* the bar — the review itself says it is not
independent evidence, and nobody claims it is: the bar is the contract, the criteria are
its enforcement, and the bar will be applied to *future* repairs. What survives from F7 is
the same adjudication sentence as F1 — one requirement, not two findings.

## F8: the counters' blind spot is real, but the human step is the meaning-check

The symmetric defect count was written for decoder arms and the review is right that no
shape counter sees `factory -> needle`. But the meaning-check was never assigned to a
counter: it is the human review (F1/F7), which the measurement exercised and which the
spec must state as a step. F8's "does not scale" fails on the repairs-vs-targets
arithmetic above.

## F9: staleness conceded; the remedy should not be a rename

The title, Problem section, and build order are stale — no defense. But renaming the file
breaks every cross-reference (the findings files, this review, the acceptance criteria all
cite the filename), for no reader value that a status line and a corrected Problem section
do not capture. Fix the body; rename only if the author wants the churn.

## The strongest argument against the leg, and the answer

If F1 forces a human to review every repaired line, why have the LLM repair stage at all?
The human could just fix the low-confidence cards directly. That is the honest cut
argument, and it fails on two measured facts: the human cannot eyeball ~7,700 targets per
season but can review ~1,000 LLM-repaired lines; and the one repair that closed the day's
loop — `Dothamingo -> Doflamingo` — is a class nothing else in the pipeline reaches
(`glossary.correct()` structurally cannot, per F4 of the round-1 review, and hotwords was
cut). The LLM's value is focusing human review on a small repaired set; the leg survives
only if the guard set keeps that set small — which argues for implementing the guards
(F2), not for cutting the leg.

## Net disposition of the review's own findings

- **Retracted outright:** the F1 extrapolation arithmetic (~1,000 → ~144 regressions);
  "no recovery path" (manual recovery exists); the F8 "does not scale" framing; the F3
  ordering-violation charge (stale rule, cannot bind).
- **Downgraded to ordering requirements the author already intends:** F1 (review loop,
  stated in the spec), F2's [S-14] half, F4 (21-sample is a go/no-go label), F5, F7, F9
  (fix the body, don't rename).
- **Survives as load-bearing:** the phonetic gate has no S-item home and is not even
  implicit in the criteria — adopt it or drop it; the [S-13] criterion is vacuous and must
  be rewritten to measure proposal quality; the human-review step must be a stated part of
  the acceptance procedure.

The three BLOCKs were really three before-you-ship ordering requirements, and the
author's own sequence — measure, decide, build — already contains them. The review's
durable yield is narrower than its verdict claimed: two spec-text fixes and one explicit
S-item. That is the honest landing after the rebuttal, and it is what the author should
act on.
