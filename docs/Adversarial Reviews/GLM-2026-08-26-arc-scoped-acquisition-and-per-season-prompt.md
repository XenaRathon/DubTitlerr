# Review — arc-scoped acquisition and per-season prompt (post-measurement)

Fifth review on **DubTitlerr**, after the measurement moved the spec's delivery mechanism.
Spec: `.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md`.
Delivery evidence: `RESULTS-2026-08-26-ab-prompt-comparison.md` (this directory).

Everything below was checked against source on this box unless explicitly marked
unverifiable. `faster_whisper/transcribe.py` is an installed dependency, not in this repo
— its quoted lines hold the same status as the findings file's quotes of it. Numbers
labelled "re-verified here" I recomputed in the repo venv (jellyfish 1.2.1 is a real dep,
per `uv.lock`).

## Verdict first

The spec is honest and buildable as a document — the header edit, the on-record [S-3]
withdrawal, the measurement-gated criteria, and the season-by-season adoption are all the
right reflexes. But the A/B rearranged the load-bearing structure and the spec did not
follow: **every arc-specific item ([S-1], [S-2], [S-5]'s arc fetch, [S-8], [S-11]) exists
only to feed [S-10], and [S-10] rests on one 180-second clip.** The leg now has a
measurement gate but no decision rule, a delivery mechanism whose acceptance criterion
checks one phrase against the demonstrated defect's class, and a tag design that
contradicts its own cross-arc edge case. I would block the build on three spec-text
changes (F1–F3) and note five more (F4–F8).

## What the A/B actually established

Before the findings: the null result is real for what it tested. `generate.py:890` passes
`condition_on_previous_text=False`; `generate.py:897-902` records that `True` OOMs this
card (measured 2026-08-20, 6 GB 1060, GPU otherwise idle). `generate.py:317` confirms
`words.json` stores the literal prompt string, which is what `glossary.stale_tier`
(`glossary.py:111-129`) compares — so both the A/B's per-arm prompt verification and the
spec's [S-6] adoption semantics rest on verified machinery. The five differing runs in
10,487 tokens (0.04% of ~5 per 10k tokens) is a real null, and the 0.9984–0.9991
similarity is computed honestly (index-aligned cards, punctuation stripped because
`punctuation.restore` at `generate.py:941` differs between any two runs anyway).

The findings file's headline claim — "`initial_prompt` changes NOTHING" — is accurate for
**three episodes of one show**, and the spec's "both halves are unsupported" admission in
the results file's `Bearing on the spec` section is the correct takeaway. What the results
file does NOT establish, and the spec leans on anyway: that prompts in general are inert
(F7), and that hotwords is net-positive (F1/F2).

## Blocking findings

### F1 — Build order inverts the spec's own gate. BLOCK.

`[S-10]` is the only mechanism with positive evidence, and its own acceptance criterion
requires a full-episode fix/regression ratio that does not exist yet by design. Everything
else arc-shaped — [S-1] `season.nfo` resolution, [S-2] category discovery, [S-5]'s arc
fetch, [S-8] wiki layer, [S-11] season tags — feeds only hotwords. [S-4], [S-6], [S-9]
are season machinery and survive regardless.

The spec does not sequence this. If the full-episode ratio is not positive — and the
evidence base says that is a live possibility: the strongest bias tested (a 47-term,
222/223-token `initial_prompt`) failed to fix the very token [S-10] targets at 657.3 s —
then [S-1]/[S-2]/[S-5]-arc/[S-8]/[S-11] become dead weight built on the author's own
sequencing. The fix is textual: run the full-episode hotwords spike FIRST, and write the
decision rule for a non-positive ratio (my recommendation: the leg ships as
[S-4]+[S-6]+[S-9], and the arc machinery is cut or deferred — not built-then-abandoned).
The spec already contains the gate; it does not contain the rule.

### F2 — [S-11]'s single-season tag contradicts the spec's own cross-arc edge case. BLOCK.

The Data section records each acquired name's provenance as THE season that produced it:
"Each acquired entry additionally records the season that produced it as PROVENANCE".
[S-11] selects a season's hotwords by that tag. The Edge cases section then says: "Caesar
Clown is a Punk Hazard antagonist present in Dressrosa … Cross-arc presence is CORRECT
and must not be filtered out as pollution."

Those two sentences disagree. Caesar is acquired (if at all) with provenance Punk
Hazard — Season ~18 — so Dressrosa's hotwords, filtered by tag==31, exclude him. The
spec's own load-bearing breadth argument says Caesar must be correctable in every arc he
appears in — correct() stays show-wide, fine — but the PRIMING half excludes exactly the
recurring character the spec names. The [S-11] acceptance criterion only pulls in one
direction: "a name tagged to season 31 appears in season 31's hotwords AND is still
corrected … in a season-29 episode". It never tests the push-out direction, which is the
one that contradicts the edge case.

The fix is small and material to the Data format: the tag must be a SET of seasons
(union of every season that produced/confirmed the name), and hotwords membership must be
"name's season set intersects the current season" — with a rule for what a name acquired
before tagging began (the existing 92 names, all un-tagged) does: I would default them
IN with provenance "legacy" so the first hotwords run after adoption isn't a strict
subset of what whisper already heard. As written, the tag design fails the spec's own
test case; fix the Data section before building.

### F3 — [S-10]'s criterion checks one phrase; the demonstrated defect is class-wide. BLOCK.

The demonstrated-defect math re-verifies exactly on this box (jellyfish 1.2.1):

    Dothamingo -> Doflamingo
      difflib.get_close_matches ratio 0.800   vs fuzzy_cutoff(10) = 0.84  MISS  (verified)
      metaphone T0MNK vs TFLMNK                                             MISS  (verified)
      soundex    D355  vs D145                                              MISS  (verified)

`glossary.py:35-36` (=cutoff 0.95/0.90/0.84), `:167-189` (tiers, `_one_indel` on both
fuzzy and phonetic, `is_english` gate). Doflamingo was IN arm B's prompt — "Donquixote
Doflamingo" listed explicitly — and the decoder misheard it anyway. So the class
"name in glossary, name in prompt, still misheard, no tier can repair" is demonstrated,
and the 6,492 `no_reference` cards (skipped at `repair.py:493-518`) close the LLM path
for them. [S-10]'s acceptance criterion ("renders 'Donquixote Doflamingo' rather than
'Don Quixote do Flamingo' at 657.3s") can PASS while the same episode ships
`Dothamingo` at other positions — the criterion validates a position, not the defect.

Change the criterion to count every arc-name mishear over the full measured episode (all
15 terms, not one), and record where each regression lands (anchored vs `no_reference`),
because F4's correction makes repairability differ by an order of magnitude between those
two classes.

## Noted findings

### F4 — "No later stage can repair it" is true only for `no_reference` cards; the results file overstates, and the correction is cheap. NOTE.

`repair.invents_name` (`repair.py:276-335`) is substitution-scoped: `lost = orig_counts -
new_counts`; the guard fires only when a capitalized core DISAPPEARS and an unknown
capitalized core takes its place. "Dester" → "jester" loses the invented noun and gains
nothing capitalized — `invents_name` returns False, by its own docstring's escape-hatch
design. And `name_suspect` (`glossary.py:206+`) flags "Dester" as a repair target in the
first place. So on an ANCHORED card the LLM repair can fix the Dester-class regression and
the guard does not object. The results file's "no later stage can repair it" is correct
only for the deterministic corrector and for the 6,492-card `no_reference` class — which
is exactly why F3's "record where regressions land" matters: the Dester risk is not one
number, it is two different numbers depending on anchorability.

### F5 — [S-6] converts a human-controlled staleness trigger into a third-party-controlled one. NOTE.

`stale_tier` compares the STORED string (`words.json`, `generate.py:317`) against the
derived one (`glossary.py:111-129`). Today the derived string changes only when a human
edits the glossary file. After [S-6] it changes when the live wiki changes — arc page
renamed, category re-organized — at the next `WIKI_TTL` expiry (`glossary_verify.py:260`).
No human intent, no version bump, 48 episodes re-queued. It is bounded (cache TTL,
per-season cost, and the A/B's own null result caps the harm of re-running under a wrong
prompt at near-zero), so I would not block on it, but the spec should journal the diff
when the derived prompt changes and add a criterion: "wiki membership changes between
runs are logged, never silent."

I walked the brief's enumeration against the code anyway: entry added-then-removed
re-derives the show prompt (fresh, correct); byte-identical entry is a no-op by string
comparison; renumbering makes stored ≠ derived so it re-transcribes ONCE then sits fresh
under the show prompt (bounded); words.json predating `season_prompts` is the migration
trigger, by design; an `initial_prompt` edit staling the whole show is the two-tier
design (`common.py:133-142`) and is wanted. No unbounded silent re-transcribe survives;
the wiki drift above is the only silent MISS, and the `if not stored_prompt` branch
(`glossary.py:127-128`) is a self-healing transient. The brief's "which silently
re-transcribes the library, and which silently DOESN'T re-transcribe something it
should" — answer: none in the first class; wiki drift (partial) in the second.

### F6 — Arc discovery is proven on one arc, and [S-1]'s key is not an arc key for S01–S04. NOTE, bounded by the null result.

The brief's claim stands: `Gaimon` is a character, `Romance Dawn` is an arc, `Orange
Town`/`Syrup Village` are locations — the `<title>` field is not a uniform arc key even
inside One Pace. The failure mode "resolves to the WRONG arc rather than to nothing" is
real: "Gaimon" plausibly resolves to the character page and category discovery returns
whatever the character's categories are, not an arc cast. But the A/B caps the harm of a
wrong arc prompt at near-zero, so this is a note: add a non-Dressrosa arc to [S-2]'s
acceptance criteria (Romance Dawn is the natural second sample, and it sits in the same
S01–S04 range where the key misbehaves), and make [S-7]'s fallback trigger on
category-discovery emptiness, not on page resolution — a wrong-but-resolved page must not
count as resolution.

### F7 — The null result's generalization rests on an unverified episode-geometry claim. NOTE.

The results file's "in a real episode the first window is the OPENING THEME — sung, no
character names" is the single load-bearing reason three episodes of null generalize, and
it is asserted, not shown. It is also load-bearing in two directions: if the first window
contains dialogue after all (a recap), then the prompt was actively primed and changed
nothing — `initial_prompt` dead by STRONGER evidence. If it is truly the sung theme, the
prompt was primed by silence and the correction's segmentation cascade remains a live
possibility for dialogue-starting shows. Both kill [S-3]; they have opposite implications
for whether a per-season prompt could ever matter on a show with no opening theme. Cheap
to settle: S31E01's `words.json`/conf on the A/B machine shows what the first window
decoded. State it on the record.

Also unverifiable from this box (say so when quoting): the `faster_whisper` line numbers
itself (`:1372-1383`, `:1542`, `:1547`, `:1550`), the 35/35 `season.nfo` presence, the
spike transcripts, all VM102/NFS figures. The "Samji -> Sanji at seen 1/721" datum
appears ONLY in the review brief — no source in this repo — treat it as hearsay until
anchored to `glossary_acquire`'s admission gates.

### F8 — [S-8]'s justification is a different drift class than the one it cites. NOTE, keep it separable.

The spec justifies extracting the wiki layer by "the exact drift `prompt_for`'s docstring
already warns about" (`glossary.py:94-99`). That warning is about two DERIVATIONS of the
PROMPT drifting, which reads as "the prompt changed" — a SILENT GPU QUEUE. Two title-set
copies drifting produces different acquire candidates — a CPU-tier, visible, logged
difference that ends in text work, not a library re-transcribe. Different severity class;
the analogy overstates. The refactor itself is low-risk if executed mechanically, so keep
it as ONE separate commit behind `pytest` green, and if it wiggles any `glossary_verify`
behavior, drop it and let the arc module stand alone — the "best code is code never
written" rule applies to migrating working code for symmetry.

## The one thing most likely discovered mid-build

The per-episode prompt resolution the spec already sees coming (`generate.py:110-119`
resolves `INITIAL_PROMPT` once per process; the spec says "a run may span seasons"). The
part it does not see: **whisper's hotwords budget interacts with `previous_tokens` on the
FIRST window.** `condition_on_previous_text=False` empties `previous_tokens` after
window 1 — but window 1 still carries the prompt (that is the whole mechanism), so on the
first window the hotwords + prompt both contend for the 223-token cap, and the spec's
Constraint section describes `initial_prompt` truncation only. The [S-10] VRAM/budget
numbers were measured at 12 terms on mid-episode windows; the first window's
double-structure is unmeasured. Builders will hit this in the first full-episode ratio
run; say what the budget interaction is before then.

## What I verified vs. could not

Verified on this box: Dothamingo distances and phonetic codes (recomputed above);
`fuzzy_cutoff` (`glossary.py:35-36`); the two-tier `_one_indel` exclusions
(`glossary.py:180`, `:183`); `prompt_for`/`stale_tier` mechanics and the string-compare
design (`glossary.py:93-129`); `invents_name` substitution scoping and its known-set
(`repair.py:276-335`); the `no_reference` skip (`repair.py:493-518`); the OOM record and
`condition_on_previous_text=False` (`generate.py:890-913`); once-per-process prompt
resolution (`generate.py:110-119`); literal prompt in `words.json` (`generate.py:311-318`);
wiki cache/TTL (`glossary_verify.py:254-266`); `acquire`'s show-wide harvest
(`glossary_acquire.py:829-841`); the tier comment block including v6 (`common.py:133-142`).

Could not verify from this box: every `faster_whisper/transcribe.py` line quoted in both
documents; the opening-theme geometry; all media/NFS/GPU figures; the Samji→Sanji datum;
the spike transcripts themselves. All are marked or stated as such above rather than
treated as verified.

## Bottom line

The spec is one honest measurement away from being right, and its criteria mostly know
it. Fix the three blocks (decision rule + ordering for [S-10], season-tag semantics, and
a class-wide [S-10] criterion), record F7's geometry finding, and this leg builds. What
should NOT happen: building the arc machinery in parallel with the very measurement that
decides whether it should exist.