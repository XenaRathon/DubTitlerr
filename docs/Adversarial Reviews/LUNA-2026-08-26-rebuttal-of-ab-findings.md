# Luna rebuttal of the A/B findings — round 2, against the corrected file

Round 1 of this rebuttal is on the record and the author answered it: the findings file now
carries two CORRECTIONs and a scoped-down "defect that IS demonstrated", and the spec's
header has been rewritten around the measurement. This round attacks the file as it stands
now — including the corrections, which the brief instructs me to check as hard as the
things they corrected.

**How to read this document.** Every claim carries a file:line anchor or a measurement I
ran in this checkout. Measurements are marked "(verified here)". Anything depending on
VM102, the media library, the GPU, or `faster_whisper`'s source is marked "(unverifiable
from this box)" — `faster_whisper` is not installed in this environment (checked: neither
the system interpreter nor `.venv` imports it), so `transcribe.py` anchors are reasoned
from the lines the findings file quotes, and every media/GPU figure is treated as
unverified rather than accepted. I re-ran the numeric claims that are checkable: the
Dothamingo distances, the metaphone codes, the guard's behavior on the Dester and Rebecca
cases, the Samji admission chain, and the determinism of the hallucination gate.

## Verdict

| Findings-file claim | Disposition |
|---|---|
| "Two sharply different prompts produced **word-identical** transcripts" (R:5-8) | **OVERTURN.** The file's own diff lists five differing runs (R:50-54); the transcripts are not word-identical. Two of the five are first-window differences in the opening theme — which contradicts the correction's "nothing is primed" half. |
| "All five differences are hallucination-gate artifacts, **not decoder differences**" (R:48) | **OVERTURN.** The gate is deterministic (verified); the punctuation stage cannot add/delete/reorder words (verified). The five runs are decoder differences, and the attribution is not per-run verified. |
| "`initial_prompt` changes NOTHING" (R:1, 5-8) as a universal | **DOWNGRADE** to "no differential name-token effect detected in three theme-first episodes of one show." The metric is a divergence metric with a same-position blind spot the file concedes for counts but not for opcodes. |
| "in a real episode the first window is the OPENING THEME" (R:122-133) | **DOWNGRADE** to "measured on three episodes, unverifiable from a checkout, internally consistent." The correction's cascade numbers (Mihawk at 46.3 s, Dressrosa at 53.0 s) are **unattributed** — no arm table, transcript, or window-boundary record for that probe exists in the file (R:109-115). |
| "nothing is primed, so nothing cascades" (R:119, spec:15) | **OVERTURN in the letter.** The theme decode differed between arms (R:50, R:53) — the first window WAS primed and changed. The true claim is "window-1 change did not cascade here", which is an observation, not the mechanism. |
| The 180 s spike "fix/regression ratio has to be measured at scale before adoption" (R:201-202) | **DOWNGRADE.** The spike licenses the measurement (which the author then ran); the demanded ratio is not falsifiable as stated and the author abandoned it himself. Dester repairability: **OVERTURN** — already corrected in the file (R:176-186), and verified here: the guard admits the fix on an anchored card. |
| "the defect that IS demonstrated" (Dothamingo) (R:211-231) | **DOWNGRADE** to "one verified near-miss instance; correct numbers, wrong bucket, and fixed by the spec's own in-scope repair leg, measured." |
| The `stale_tier` adoption enumeration | **OVERTURN as moot.** There is no per-season stored state left to stale: `season_prompts` is dropped and `season_hotwords` was cut with [S-10] (spec:86-94). Only the intended show-level prompt edit stales anything. |
| The guard/prompt-only "deadlock" | **DOWNGRADE** to a finite, gate-dependent bootstrap window whose cure is in the spec. The guard compares against the glossary, not the reference — verified — and the loop closes in one acquisition cycle. |
| [S-11] split and truncation boundary | **DOWNGRADE** to "defensible; truncation claims hold per the quoted code; the first-window double structure is unmeasured and moot now that hotwords is cut." |
| Scope/ordering attacks | **NOT OVERTURNED.** [S-7] cannot degrade the common path by construction; the no-reference ordering is load-bearing. The findings' core — "the wrong prompt did not cause these mishears; a correct prompt did not fix them" (R:204-208) — **survives**. |

**The one finding I tried hardest to break** was the episode-geometry claim (finding 2) —
it is the single reason a three-episode null generalises, and the brief tells me to check
hardest the claims that look right. What stopped me is recorded at the end of section 2.

**Bottom line on [S-3]:** [S-3] **stays dead** for this pipeline and this show, but its
death certificate must be rewritten. It is dead on the mechanism (`condition_on_previous_text=False`
empties `previous_tokens` after window 1 — `generate.py:890`, code-verified) plus the
theme-first geometry (measured on three episodes, unverifiable here). It is **not** dead
on the strength of "changes NOTHING" — that headline does not survive contact with the
file's own diff. A dialogue-first show (cold open, recap) has a primed first window and
the cascade the author himself discovered is available to it; the A/B never tests that
class. The spec should re-scope its claim, not resurrect the mechanism.

---

## 1. The headline fails against the file's own diff

**The transcripts are not word-identical.** The Result says "Two sharply different prompts
produced word-identical transcripts" (R:5-8), and the spec's header repeats "word-identical
transcripts" (spec:6-8). The Word-level section then lists five differing runs (R:50-54).
A document cannot assert equality in the headline and five differences in the body. The
file's own "similarity 0.9984–0.9991" (R:41-43) is the honest number; the headline is not.

**"Hallucination-gate artifacts, not decoder differences" is not a possible
classification.** The gate is a pure function of the card text. `hallucination.drop_reason`
(`hallucination.py:133-141`) and `collapse_runs` (`hallucination.py:162-177`) contain no
randomness — verified by reading, and by running: the
`so let s wake up wake up wake up wake up` card trips `drop_reason = "repetition"`, and
five identical cards collapse to one, deterministically (verified here). A deterministic
gate fed identical input produces identical output. The only upstream stage that can
mutate words is `punctuation.restore` (`generate.py:941`), and its R4 guard requires the
restored text to have the **same words in the same order** — an accepted restoration
cannot add, delete, or reorder a token (`punctuation.py:134-146`, `accept_restoration`,
verified by reading). The comparison strips exactly the things R4
allows to change (case, punctuation). Therefore: **post-strip word differences can only
originate in whisper's decode.** The five runs are decoder differences, or they are nothing
at all. "The gate made them different" is not available as an explanation.

**Two of the five runs are first-window decoder differences.** The E01 and E03 runs
`A[so let s wake up wake up wake up wake up] -> B[]` (R:50, R:53) are in the opening theme
— the spec's own geometry table places the theme cards at 1.3–23.7 s (R:124-131), inside
window 1. The same run differing in both episodes is the same song decoded differently
under the two prompts — systematic, twice. This is direct evidence that the prompt changed
window-1 decoding of the full episode. It is exactly the "priming" the correction says does
not happen ("nothing is primed", R:119). Section 2 develops the consequences.

**The token accounting is plausible but not checkable.** Card counts differ by 8 cards
(586/586, 393/389, 500/496 — R:41-43) and total tokens by 28 (10,487 vs 10,459). My count
of the quoted run texts: 28 tokens on the A side (11+11 for the two theme runs, 2 for
`now what`, 3 for `karoo karoo oh huh`, 1 for `pipsqueak`) against 1 on the B side
(`grrgrrgrrrrrrghhh...`), net 27 of the measured 28 — so the five runs plausibly represent
the whole difference. But the file publishes no alignment, timestamps, or per-run
positions, so "each inspected, none a name" (R:86) is an unreproducible assertion. Note the
runs are not "none a name" in the interesting sense — they are the theme and two dropped
cards. The inspection conclusion is exactly what a name-free window-1 effect would look
like; it is the author's reading of his own diff, not a per-run protocol.

**The opcode comparison has the same blind spot the file concedes for counts.** The file
now admits count equality "cannot by itself distinguish 'both arms got it right' from 'both
arms got it wrong the same way'" (R:79-83) and relocates the load to the `SequenceMatcher`
opcodes: "a name misheard in different positions between arms would appear there as a
replace run even where counts matched" (R:85-87). True — and irrelevant. The failure class
this whole exercise is about is a name **misheard identically in both arms at the same
position**, which produces **zero opcodes**. The file's own admission at R:91 — "they do —
`Dothamingo` appears in both" — is the demonstrated instance of exactly that class. The
opcode comparison is a divergence metric, not a recall metric. It measures whether the
prompt made the arms *different*; it cannot measure whether the prompt made the output
*right*. A null of divergence is not a null of effect — it is a null of differential
effect, and the Dothamingo case shows the differential and the correctness questions are
decoupled in precisely the way the spec cared about.

**The injection claim is scoped correctly but weaker than it reads.** The file says arm A's
Enies Lobby names "appeared in EITHER transcript" (R:96-99) and that "the injection
hypothesis was not exercised — only unsupported by opportunity" (R:92-95). The scope note
is honest. What it undersells: the injection *mechanism* is demonstrably live — the theme
runs prove the prompt changes window-1 decode. What would demonstrate injection is an
acoustically ambiguous position where an Enies name could win the beam over the true
token — e.g. an audio position where `Spandam` and a real word compete. This audio offers
no such position, so the claim "the wrong prompt did not inject wrong names" is true
vacuously: the mechanism is active (measured, twice), the opportunity was absent. On any
show whose first window contains dialogue, both the injection and the fix are untested and
mechanism-live. That is precisely why the null must not be generalised.

**Disposition:** overturn the headline and the gate-artifact attribution; downgrade the
null to a scoped differential null for three theme-first episodes.

## 2. The correction's two halves cannot both be load-bearing

**The cascade numbers are not in the file.** The CORRECTION asserts that with
`initial_prompt` set, "`Mihawk` was fixed at 46.3 s and `Dressrosa` at 53.0 s of a 180 s
clip" via a segmentation cascade (R:109-115). This is the load-bearing half of the whole
document — it is what reconciles the clip result with the episode null — and it cites a
measurement nowhere published: no arm table, no transcript lines, no window boundaries for
that probe, no determinism check. The brief's rule applies: a claim that looks exactly
like what the author would want is the one to check hardest. The claim is *plausible* —
the mechanism is coherent and the quoted code supports it — but as presented it has the
same shape as the "asserted" episode geometry the author was forced to measure. A number in
a correction is not a measurement.

**The theme runs falsify "nothing is primed" in the letter.** The correction's
reconciliation is: "On a clip starting at 600 s the first window is dialogue, so there is
something for the prompt to change and the cascade starts. On a real episode the first
window is the opening theme, so nothing is primed and nothing cascades" (R:118-119; spec:14-16).
The A/B's own data show the episode's first window **did** change under the prompt — the
theme decode differed in E01 and E03 (R:50, R:53). "Nothing is primed" is false; the theme
was primed and its hallucination shape changed. What did not happen is a cascade to later
windows. The corrected file's own logic therefore forces the narrower claim: *a prompt
effect in window 1 did not cascade here*. The distinction between "changed the theme
decode" and "changed segmentation" is doing all the work, and the file never shows it.

**The reconciliation variable is untested.** The author's story — speech in window 1 →
segmentation change → cascade; music in window 1 → no segmentation change → no cascade —
is a hypothesis that happens to fit both observations. The A/B never varies window-1
content, so it cannot test it. A rival hypothesis fits the same data: cascade propagation
is fragile and run-dependent — the clip showed it once, the episodes showed it absent, and
neither is a controlled comparison of window-1 content. The clip and the episodes also
differ in something else entirely: duration (180 s vs full episodes), start position, and
the surrounding audio. The brief's demand is right: **both results cannot be treated as
robust.** Which measurement decides: a matched pair on the *same* audio — clip starting at
0 s (window 1 = theme) vs the identical clip starting at 600 s (window 1 = dialogue) —
with window boundaries recorded, not just output equality. If the 0-start arm cascades,
the "music window is inert" story dies. If it does not, the dialogue-window story has its
first real evidence. Either way the file's current reconciliation is an assertion dressed
in the other result's clothing.

**The geometry itself: measured, unverifiable, but design-consistent.** The corrected file
replaces the assertion with "Every card decoded before 30 s in arm A" and five quoted theme
lines with timestamps (R:122-133). From this box I cannot check it — no media, no sidecars
— and the round-1 "unverified" label stands. Two things I can say. First, the spike's
600 s start is evidence-by-design: the author needed window 1 to contain dialogue to get
any effect, which only makes sense if he already knew the full episode's window 1 was not
dialogue. The behavior is consistent with the belief. Second, that consistency is not
independent verification — it is the author's prior, now backed by a measurement I cannot
see. The honest status is "measured where the author says, consistent with his experiment
design, unverifiable from a checkout."

**Disposition:** downgrade the geometry to scoped-and-unverifiable; overturn "nothing is
primed"; demote the cascade reconciliation to an untested hypothesis with a named decisive
experiment.

## 3. The spike licensed the measurement; the ratio demand was never falsifiable; Dester is dead

**The spike is the file's best evidence and it undersells itself.** Arm C fixed
"Don Quixote do Flamingo" → "Don Quixote Doflamingo" at 57 s into the clip — the exact
position (657.3 s into the episode, R:150) and the exact phrase the withdrawn [S-10]
criterion named (the pre-cut criterion, quoted in the GLM review: "renders 'Donquixote
Doflamingo' rather than 'Don Quixote do Flamingo' at 657.3s") — where a 47-term
`initial_prompt` at 222/223 tokens demonstrably failed (R:151-160). It was deterministic
across two runs at word similarity 1.0000 (R:158-159), at identical VRAM and equal time
(R:154-156). This is the only measurement in the file of **any** mechanism
moving the exact arc-name token at the exact position past window 1. "One fix and one
regression in 180 seconds" (R:201) is a description, not a verdict.

**The demanded ratio is not falsifiable, and the author abandoned it himself.** The file's
demand — "the fix/regression ratio has to be measured at scale before it is adopted"
(R:201-202) — has no passing criterion attached, and none is possible at the demanded
granularity: a full episode is one episode of one season of one show, so a "ratio" is a
sample of one at every level. When is a ratio ever enough? The author's own follow-up
measurement answers: never — `RESULTS-2026-08-26-hotwords-full-episode.md` records "the
rule as I wrote it is close to unsatisfiable" and rewrites it as severity-class counting.
The A/B file's caution instrument was unsound and was discarded by its author within hours.
What the spike did license — and what actually happened — is the full-episode measurement.
That measurement then decided: every derived arm produced repetition runs the baseline
never produces, `Kanjuro` was corrupted by a listed `Kin'emon`, and [S-10] was cut
(spec:86-94). I am not arguing hotwords should ship; the full-episode evidence is decisive
against it. I am arguing the A/B file's *reasoning* about its own spike — "measure a ratio
first" — was neither satisfiable nor the instrument that decided anything.

**The Dester claim is fully dead, and the residual is a scope decision.** The file's own
CORRECTION (R:176-186) already concedes "no later stage can repair" was too broad. I
re-verified the guard from the code, all four links in the chain:

- `invents_name("The Genius Dester, Bucky", "the genius jester, Bucky")` → False — the fix
  direction loses the invented noun and gains nothing unknown (verified here);
- `name_suspect("The Genius Dester, Bucky")` → True — the card is a repair target
  (verified here; `glossary.py:235-252`);
- `is_target` on that card → True (verified here; `repair.py:114-117`);
- `accept_repair("The Genius Dester, Bucky", "The genius jester, Bucky", ref, dur, gloss)`
  → True (verified here; `repair.py:362-399`).

So on an **anchored** card the LLM repair fixes the Dester-class regression and every guard
admits it. The residual — 6,492 `no_reference` cards that never reach the LLM
(`repair.py:533-537`) — is true today, but it is the exact class the spec's in-scope [S-12]
opens (spec:99-103), and that leg has its own measurement: 21 repairs on one episode,
including the Dothamingo fix (`RESULTS-2026-08-26-unanchored-repair.md`). A regression's
repairability differs by anchorability class — the file now says this (R:185-186) — so any
hotwords regression count must record the class. That is the correct end state of this
finding.

**Disposition:** the spike's mechanism-level evidence stands and licensed the deciding
measurement; the ratio demand is unfalsifiable as stated; the repairability claim is
overturned (already conceded) with the residual owned by [S-12].

## 4. Dothamingo: the numbers are right, the bucket is wrong, and the spec's own leg fixes it

**Every number verifies.** Re-ran in this checkout: `difflib.SequenceMatcher(None,
"Dothamingo", "Doflamingo").ratio()` = 0.800 against `fuzzy_cutoff(10)` = 0.84
(`glossary.py:35-36`); metaphone `T0MNK` vs `TFLMNK`; `glossary.correct("...Dothamingo.",
gloss)` returns it unchanged; Doflamingo is in the glossary's 92 names. The near-miss is
real and the tier math is exact.

**But it is one instance, and the file says so** (R:225-231: "ONE demonstrated instance,
not a measured prevalence" — no miss-rate denominator, no other names' distances). The
file's own scope note is now correct.

**The bucket is wrong in a way that matters.** The finding indicts the correction tiers —
"no stage in the pipeline can fix a name whose correct spelling was already in the
glossary" (R:222). The correction tiers are **out of scope** for this spec (spec:136-141:
"Changing the phonetic name guard (`repair.invents_name`) itself -- it ships at v6 and is
unchanged by this leg"; nothing touches `glossary.correct`). So the headline defect attacks
a leg the spec is not building. And the in-scope leg fixes the exact case:
`RESULTS-2026-08-26-unanchored-repair.md` shows
"The heavenly demon, Don Quixote Dothamingo." → "...Doflamingo." repaired in one pass by
ungated surrounding-context repair — the [S-12] path — with `invents_name("Dothamingo",
"Doflamingo")` returning False (accepted; verified here). "No stage in the pipeline can
fix" is true only of the *current* pipeline, and the spec's whole point is to change the
pipeline. The A/B file's demonstrated defect is an argument **for** the spec's repair leg,
not against it.

**The Samji admission refusal is acquire's gate, not `correct()`'s — verified end to
end.** The appendix says `Samji -> Sanji seen 1/721 sim 0.913 bound 0.992 below-floor`
(R:243). I re-derived the chain in the code: `decide("samji", 1, "sanji", 721, 0.913,
midsentence=True)` returns **apply/dominant** with `bound 0.9922` (= `wilson_lower(721,
722)`, `glossary_acquire.py:55`), and `source_gate` then downgrades it to **flag /
below-floor** because `variant_count(1) < NEAR_MISS_MIN_COUNT(2)`
(`glossary_acquire.py:480-481`).
The appendix's numbers are internally coherent with the code, the refusal is acquire's
admission gates, and it belongs in the [S-9] bucket (season-scoped denominators), **not**
the correction-tier near-miss bucket. The file's appendix places it correctly; the one
remaining hearsay is "the repository owner confirmed" (R:251) — the owner's judgment is
not in this repo. Note also what the chain shows the file's own headline defect is *not*:
the tier miss (0.800 vs 0.84) and the admission refusal (bound 0.992, below-floor) are two
different failure classes with two different fixes, and conflating them is how a rebuttal
of one gets misread as a rebuttal of the other.

**Disposition:** downgrade to "one verified near-miss instance, out of the spec's
correction scope, fixed by the spec's in-scope repair leg (measured), no prevalence
established." The Samji datum is correctly re-bucketed to [S-9].

## 5. The adoption enumeration is moot — there is no per-season state left to stale

The prosecution enumerated five states against a `season_prompts` design. The spec no
longer has one: `season_prompts` was dropped, and `season_hotwords` — the only
season-scoped decoder input that replaced it — was cut with [S-10] (spec:86-94). [S-6] is
marked MOOT in the acceptance criteria: "no season-scoped decoder input exists to go
stale." The enumeration attacks a structure the spec deleted, and the findings that killed
the structure (the A/B null, the hotwords full-episode cut) are the same evidence the
prosecution's "silently re-transcribes the library" claim was supposed to ride on. You
cannot argue both that the prompt is inert and that a wrong or missing per-season prompt
would silently re-transcribe the library with real harm.

State by state, against the current design:

- **Entry added then removed** — no per-season entries exist. In the dropped design,
  removal re-derives the show prompt; the season either matches (fresh) or stales once.
  Cannot stale more than one season.
- **Byte-identical entry** — no-op by construction: `stale_tier` compares the stored
  string against the derived one (`glossary.py:140-158`); identical strings return None.
  Verified by reading.
- **Season renumbered** — the prosecution's "dangerous one." In the current design there
  is no season-keyed stored state to orphan, so the case is vacuous. In the dropped
  design, the harm of falling back to the show prompt is bounded by the A/B's own result:
  a wrong or missing per-season prompt changes nothing measurable on this pipeline. What
  can actually renumber a season in Plex/Sonarr: nothing routine. The season number is
  the directory name; renaming the folder moves `season.nfo` with it; Sonarr renames
  files, not season directories; Plex does not renumber. A renumber is a deliberate manual
  act with a visible diff — not a silent library event.
- **`words.json` predating the entries** — a missing stored prompt is explicitly stale
  (`glossary.py:155-158`: "unknown provenance is not evidence of freshness"), so this is a
  self-healing one-time re-transcribe, not a silent miss.
- **`initial_prompt` edited later** — stales every episode that used it, and it should:
  the prompt is the only glossary-derived decoder input (ADR 0001; the two-tier block at
  `common.py:100-155`; `glossary.stale_tier`). That is the mechanism the two-tier split
  exists to keep expensive, and it is human-intended.

Which states stale **more than one season**: only the show-level prompt edit, by design.
Which stale **nothing that should stale**: in the current design, none — the renumber case,
the prosecution's best candidate, has no per-season state left to orphan. The
prosecution's "both classes exist" is vacuous after the cut. The one residual the file
itself identifies — wiki-driven derivation changes at `WIKI_TTL` expiry
(`glossary_verify.py:260`) — was deleted along with the mechanism that would have consumed
it; with nothing season-scoped reaching the decoder, there is nothing for the wiki to
stale. The logging requirement in the spec's "Third-party control of a GPU trigger"
section is now belt-and-braces over an empty loop, which is the right shape.

**Disposition:** overturn the "silent library re-transcription" claim outright; the
enumeration is moot by the spec's own cuts, and the surviving states behave as designed.

## 6. The guard fights the loop, but the fight is finite and the spec owns the cure

**The guard's evidence base is the glossary, never the reference — verified.** `invents_name`
builds `known` from `gloss["names"]` and `token_fixes` values (`repair.py:358`), and
`accept_repair` invokes it at `repair.py:392`. The fansub reference is used
for borrowing detection (`borrowed_from_ref`, `repair.py:261-273`) and never for the
proper-noun verdict. The prosecution's construction hinged on a reference-membership
comparison that does not exist; a reference-supported edit toward `Rebecca` is admitted or
rejected purely on glossary membership. The file's round-1 rebuttal already said this; I
re-verified it by running the guard:

- `invents_name("Rebekah", "Rebecca", gloss)` with Rebecca absent from `names` → **True
  (rejected)**;
- with Rebecca in `names` → **False (admitted)**.

Both verified here. So the over-rejection is real, and v7's widening (`TEXT_VERSION` 7,
commit `01382a8`, `common.py:146-147`) makes it sharper: a gained name is now judged on
its own, so an edit that *adds* an unknown-but-on-screen name is refused even when nothing
was lost. That is a deliberate cost, stated in the guard's own docstring
(`repair.py:328-330`).

**The loop closes, and the failure point is named and measured.** whisper emits the name →
a transcript token exists → acquire harvests it (`glossary_acquire.py`, harvest from
existing transcripts) → resolves against wiki titles → admitted or flagged. Measured on
461 episodes: 20 proposed, 0 applied, 19 flagged — including three confirmed-correct
refusals (R:234-258). The guard's over-rejection window is therefore **one acquisition
cycle** for any name the decoder actually emits, and the acquisition admission gates are
precisely what [S-9] re-measures with season-scoped denominators (spec:131-134) — the
spec's in-scope answer to the failure point. The spec's invariant — a name enters
`names`/`hard_fixes` only with transcript corroboration — is what makes the guard's
evidence base converge instead of rot: it guarantees that whatever the guard admits is
grounded in something the decoder actually said.

**Is the window finite and is the cure in the spec?** Yes to both. The prosecution's
"permanent deadlock" requires the emitted name to *never* be admitted, which contradicts
the measured acquire pipeline (it flags, it does not destroy) and the [S-9] remeasure. The
residual risk — a name the gates refuse on first sight (the `Samji -> Sanji` shape,
section 4) — is bounded: the name is already transcribed correctly on screen; the refusal
delays repair coverage, it does not corrupt output. The spec's answer to "where does the
first correct name come from?" is the only coherent one on offer: it comes from the
decoder, and acquisition decides whether the evidence is good enough. That is the
prompt-only rule and the guard working as designed, not a deadlock.

**Disposition:** downgrade the "deadlock" to a finite, gate-dependent bootstrap window;
the guard's comparison target (glossary, not reference) is verified; the cure is [S-9] +
the acquisition loop, both in scope.

## 7. The split survives; the truncation boundary is per-component and moot

**Correction-broad is by design, and the alias case is out of scope.** `glossary.correct(text,
gloss)` takes no season or context argument (`glossary.py:221-232`) — verified. The
broad-correction half is therefore not a choice the spec makes per-episode; it is the
existing contract, and [S-11] explicitly keeps `names` show-wide so recurring characters
are corrected everywhere (spec:95-98). The narrow-correction case the brief asks for — a
name whose canonical form changes across arcs, an alias, a title-as-name — is real, and
`correct()` has no mechanism to bound it: no parse priority, no case rules beyond the
token tiers, `hard_fixes` ordered only by phrase length (`glossary.py:221-232`). But
"narrowing correction" is not on the table in this spec, and neither the GLM review nor I
found a reading of [S-11] that narrows `correct()`. The alias case is a different leg, not
a defect in this one.

**Priming-broad is moot.** Hotwords is cut (spec:86-94), so there is no per-season decoder
priming to be broad or narrow. The tags' consumer is [S-13], the season-weighted repair
glossary (spec:95-98, 104-108). The cross-arc push-out case — Caesar Clown in both Punk
Hazard and `Category:Dressrosa Saga Antagonists` — is in the [S-11] acceptance criteria
("a name belonging to two arcs weights BOTH seasons"), and the tag is a SET of arcs
sourced from wiki membership, not a single season (spec Data section). The round-1
objection (single-season provenance contradicting cross-arc presence) was fixed before this
rebuttal; nothing in the current design keeps a recurring name out of a season it appears
in. The "tag's absence from names keeps a name out of hotwords" construction dies with
hotwords: the tag's absence keeps a name out of a *repair glossary weighting*, which
costs a repair the guard might reject — the finite window of section 6 — not decoder
coverage.

**The truncation boundary, reasoned from the quoted lines.** `faster_whisper` is not
readable from this box, so everything here is conditional on the file's quotes being
accurate. As quoted: `transcribe.py:1547` slices `[: max_length // 2 - 1]` for hotwords
**only in the branch** `len(hotwords_tokens) >= self.max_length // 2`; with `max_length =
448`, that branch fires at ≥ 224 tokens and keeps the front 223. So the hotwords ceiling
is 223 tokens — matching the spec's Constraint (spec:264-267) — and at exactly 223 there
is no truncation (223 < 224); at 224+ the 224th and later tokens are dropped. The
`initial_prompt` slice at `:1550` keeps the tail 223. The spec's "223 tokens" is therefore
a **per-component** ceiling; window 1 carries both (prompt tail + hotwords front, up to
~446 combined), and the spec's own Constraint records that the first-window double
structure is unmeasured (spec:278-283). With hotwords cut, the question is moot for the
current build; if hotwords ever returns, the boundary to measure first is window 1's
combined budget, exactly as the spec already says.

**Disposition:** the split is defensible and the tag is now read by [S-13]; the alias
narrow-correction case is out of scope by the existing contract; the 223 claim holds per
the quoted code with the first-window interaction unmeasured.

## 8. The ordering is load-bearing, and [S-7] cannot degrade the common path

**Three of four sampled shows having no glossary does not make [S-7] the common degradation.**
[S-7]'s promise is "degrade to today's behaviour when the arc cannot be resolved, without
failing the sweep" (spec:122-127). Today's behaviour is a no-glossary run: `glossary.load("")`
returns an empty glossary, `prompt_for` falls back to the neutral prompt, and
`glossary.correct()` is a no-op (verified — `glossary.py:83-91`, `:122-138`, `:221-232`;
`generate.py:107-124` loads and resolves exactly this way). The acceptance criteria assert
the fallback leaves the glossary byte-identical and `gen_loop.sh` proceeds to GENERATE
(spec:420-424). A path that is, by assertion, byte-identical to today cannot make the
common path worse "by construction" in the pejorative sense — it can only be worse if the
fallback itself is wrong, and the [S-7] bullet itself forbids a wrong-but-resolved page
from counting as resolution (spec:127). The prosecution's "degradation is the common path"
conflates "the common path runs the fallback" (true, harmless) with "the fallback
degrades" (false, it is the status quo).

**The no-reference ordering is load-bearing, and the author's own comment carries it.**
`repair.py:533-537` skips unanchored cards with the recorded reason: "The bake-off showed
glossary-only repair hallucinates names (Oimo->Zoro) even on qwen3:8b; without a reference
the deterministic layer (hard_fixes) is the safe ceiling." The ordering is: the LLM can
only be opened up after the glossary knows the arc's names ([S-13]'s weighting is the
guard), and the glossary can only learn them after they are on screen (the invariant). The
A/B does not touch this chain: whatever `initial_prompt` does or does not do, the only
evidence in the findings file of any mechanism changing an arc-name token past window 1 is
hotwords (the spike), and the only measured fix of the demonstrated defect is the repair
leg ([S-12], `RESULTS-2026-08-26-unanchored-repair.md`). The prosecution's demand to name
the leg that grows `names` without a transcript has no answer because the spec's invariant
forbids the question: names grow from transcripts, transcripts come from the decoder, and
the decoder's arc vocabulary is the thing every in-scope leg improves. That is a coherent
answer to "where does the first correct name come from?"; the prosecution's side has no
answer that does not violate the invariant that keeps the guard sound.

**What the findings do kill, I concede plainly.** The spec's Problem section claimed the
wrong-arc prompt *manufactures* the mishears and that the gap cannot close because the
names were "never transcribed in the first place". The A/B falsifies that: Dressrosa 12,
Doflamingo 7, Rebecca 2 in **both** arms (R:61-75) — the names appear without any
Dressrosa priming. "The wrong-arc prompt cost nothing measurable and the right-arc prompt
bought nothing measurable" (R:206-208) is the correct reading of the differential, and the
spec's header already says so (spec:31-35). The causal story is dead; the mechanism
question is the one that survives, and it is the one the file answers least rigorously.

**Disposition:** the scope/ordering attack is not overturned; [S-7] is status-quo by
construction, and the repair-first ordering is the load-bearing one.

---

## Final decision on [S-3]

[S-3] **stays dead** — but on the mechanism and the geometry, not on the headline.

1. The mechanism is code-verified: `condition_on_previous_text=False`
   (`generate.py:890`) empties `previous_tokens` after window 1 (per the quoted
   `transcribe.py:1372-1383`, `:1187` — unverifiable here but uncontested), so direct
   priming is first-window-only. That is a property of this pipeline, not of the
   measurement.
2. The geometry is measured on three episodes (theme cards before 30 s, R:122-133),
   unverifiable from a checkout, and consistent with the author's experiment design. A
   per-season prompt on a theme-first show can only change the theme decode — and the A/B
   shows it *does* change the theme decode (R:50, R:53) without reaching dialogue.
3. What is **not** established is "prompts are inert everywhere." The cascade the author
   discovered on the clip is available to any show whose first window contains speech, and
   the A/B never samples that class. The spec's "The show prompt stays broad and stable"
   section should say "on this show", not "in general" — the file's own corollary
   (R:135-138) already does, and the spec header should match it.
4. Therefore: do not reinstate [S-3]; do not re-enable [S-10] (the full-episode
   measurement cut it on severe regressions); do re-scope the claim. If the library ever
   holds a show whose first 30 s is dialogue, run the matched-pair experiment of section 2
   there before pronouncing on prompts again.

**What the spec must do, concretely:** (a) the header's "word-identical transcripts"
becomes "near-identical (5 differing runs in 10,487 tokens)"; (b) "nothing is primed"
becomes "the theme decode changed; dialogue did not"; (c) the "inert" language is scoped to
theme-first shows; (d) the [S-12]/[S-13] repair leg — the only mechanism with a measured
fix of the demonstrated defect — is treated as the leg the arc machinery feeds, not a
footnote.

## The finding I tried hardest to break

The episode-geometry claim (finding 2). It is the load-bearing reason the null
generalises, it now claims to be measured, and the brief tells me to check hardest exactly
the claims that look right. I attacked it three ways: the cascade numbers are unattributed
(they are — and that is a real defect in the correction); the reconciliation variable is
untested (it is); and "nothing is primed" is falsified by the file's own theme runs (it
is). But the geometry itself — theme-first first window on these three episodes — I could
not break. What stopped me: the author's experiment design only makes sense if the
full-episode window 1 was known to be inert (why else clip at 600 s instead of 0 s?); the
corrected file publishes first-window card texts with timestamps; and the media and
sidecars that could falsify it are not on this box. The claim survives as "unverifiable
from here, internally consistent, and consistent with the author's own prior." That is
enough to keep [S-3] dead — and it is exactly why the *generalisation* must stay scoped:
the load-bearing fact of this whole round is one I cannot see, and the file's own
corrected text still does not let a reader check it.

## What I verified vs could not

Verified here (by running or reading this checkout): all Dothamingo distances and codes
(0.800 / 0.84 / T0MNK / TFLMNK); `correct()` no-op on Dothamingo; `invents_name` on the
Dester fix (False), the fabrication direction (True), Oimo→Zoro (False — the [S-14] gap),
Dothamingo→Doflamingo (False), and Rebekah→Rebecca (True unknown, False known); `name_suspect`
and `is_target` on the Dester card (both True); `accept_repair` admitting the Dester fix
on an anchored card; gate determinism (drop_reason / collapse_runs); the punctuation R4
same-words-same-order guard; the Samji chain (`decide` → apply/dominant bound 0.9922 →
`source_gate` → below-floor at variant_count 1 < 2); `stale_tier` string comparison and
missing-prompt staleness; `correct()`'s lack of a season argument; `generate.py:890/897-902/941/949/246/317`;
the `repair.py:533-537` no-reference comment; `glossary_verify.py:260` WIKI_TTL; the
ADR-0001 two-tier rationale; the tier block at `common.py:100-155`.

Module line numbers are cited against the current working tree (the owner's in-flight
[S-1]/[S-13] implementation shifted `glossary.py` and `repair.py` line numbers mid-session;
the quoted behaviour is unchanged).

Could not verify from this box: every `faster_whisper/transcribe.py` line; the spike
transcripts and determinism runs; the geometry card texts; the Mihawk/Dressrosa cascade
numbers; all VM102/NFS/GPU figures; `season.nfo` counts; the acquire `--apply` log; the
"repository owner confirmed" judgment. Each is marked above or treated as unverified
rather than accepted.
