# [S-10] measurement — hotwords over three full episodes

Measured 2026-08-26 on VM102 (GTX 1050 Ti 4 GB), One Pace S31E01–E03, local copies.

**Arm A** = the existing baseline (live glossary, Enies Lobby `initial_prompt`, no hotwords).
**Arm D** = arm A exactly, plus `hotwords`. Same audio (hardlinked), same model
(`large-v3-turbo` int8), same beam, same audio filter, same glossary. **Hotwords is the only
variable.** `generate.py` has no hotwords support; a throwaway copy was patched to read
`$HOTWORDS` and mounted over it, so the full pipeline (reflow, punctuation, gate) ran
identically in both arms.

Hotwords, 20 terms, hand-picked from the arc's prominence ranking:

    Doflamingo, Dressrosa, Rebecca, Kyros, Pica, Corrida Colosseum, Bartolomeo, Cavendish,
    Sabo, Diamante, Viola, Trebol, Bellamy, Kin emon, Caesar Clown, Sugar, Gladius,
    Chinjao, Green Bit, Maynard

    72 tokens of the 223 cap -- no truncation, so ordering did not bind at this size.
    On window 1, hotwords (72) + initial_prompt (~120) = ~192, still under the cap. The
    first-window budget contention predicted in review is real but does not bite here.

## Name outcomes — separating spelling from recall

The first cut of this table counted only CANONICAL spellings and reported +38%. That
overstated it: arm A was often producing the name with a different spelling, which a
canonical-only regex does not see. Counting both:

    term          canonical A->D     any variant A->D    reading
    Colosseum         3 -> 13            14 -> 14        spelling only
    Green Bit         3 ->  6             6 ->  6        spelling only
    Corrida           1 ->  2             2 ->  2        spelling only
    Chopper           0 ->  1             1 ->  1        spelling only
    Doflamingo        7 -> 13             9 -> 13        +4 REAL recall
    Dressrosa        12 -> 18            15 -> 18        +3 REAL recall
    Kanjuro           2 ->  1             3 ->  1        -2 REGRESSION

So: substantial canonical-spelling normalisation, +7 genuine new recall, one name lost.

Both exemplar mishears are fixed. `Dothamingo` appears in arm A and is ABSENT from arm D;
`do Flamingo` likewise. `Corridor Coliseum` -> `Corrida Colosseum`.

The spelling normalisation is not cosmetic and not reachable by existing machinery:
`glossary.correct()` cannot fix `Coliseum` -> `Colosseum` because `Coliseum` is a real
English word and `_fix_token`'s `is_english` gate blocks the fuzzy tier from touching it
(`glossary.py:177`). Hotwords fixed at the decoder what no later stage can reach.

## The regression

    588.9s   A: "You're a real bro, Kanjuro."      D: "Kajudo Kajudo!"
    592.1s   A: "Kanjuro!"                         D: "Kajudo Kajudo!"
    1356.4s  A: "...your buddy Conjuro..."         D: (line content diverges entirely)

`Kajudo` is exactly the shape the 180 s spike produced as `Dester`: a correct name decoded
into a capitalised non-word. The spike's specific `jester` -> `Dester` did NOT reproduce
here — `jester` is unchanged in both arms — but the CLASS did.

It is unrepairable. Every S31 card is unanchored (6,492 `no_reference` across the season,
0 accepted repairs), so `repair.py:493` skips it and no LLM ever sees it. The v7 name guard
does not help: `invents_name` polices repair proposals, never decoder output.

**`Kanjuro` was not in the 20-term hotwords list.** `Kurozumi Kanjuro` WAS in the wiki
extraction for this arc; the 20 terms were hand-picked by the author and omitted him. So the
regression fell on a name the mechanism was not told about, which is a testable hypothesis
rather than an indictment of hotwords — see Next.

Unlisted names in aggregate did NOT degrade: of 13 unlisted names present, 3 fewer in D
(Luffy 16->15, Sanji 3->2, Kanjuro 2->1), 7 unchanged, 3 more (Zoro, Nami, Robin). No
systematic suppression; one name broke.

## Confidence degraded, materially

    metric              arm A    arm D
    flagged                39       93
    low_conf               25       60
    mean logprob     -0.11/-0.13/-0.10   -0.16/-0.19/-0.18
    cards                1479     1428

Flagged and low-confidence cards both ~2.4x. The decoder is measurably less certain across
the whole episode, not only at primed names.

Operationally this does not by itself change shipped text: a flagged card is retained and
flagged, and low-confidence cards become repair targets that, on this unanchored show, are
never repaired. But it is a real signal that hotwords perturbs decoding broadly, and it is
the strongest argument for keeping the hotwords list small.

## Applying the decision rule

The rule, written before this measurement: net positive requires "arc-name mishears
reduced, no regression on an unanchored card that a human would call worse than the mishear
it replaced." Also: "regressions concentrated on unanchored cards -> net negative
regardless of the raw ratio."

Arc-name mishears ARE reduced. But `Kanjuro` -> `Kajudo` is a regression on an unanchored
card that a human would call worse than what it replaced, and every card in this show is
unanchored. **The rule therefore does not return net positive, and hotwords must not be
enabled by default on this evidence.**

It is close, and the failing case has an obvious candidate cause. This is a "measure once
more", not a "cut the leg".

## Arm E — the deciding re-run, with a DERIVED list

Arm E = arm A plus hotwords, 37 terms derived from the arc prominence ranking (not
hand-picked), most-important-first, 150 tokens. `Kurozumi Kanjuro` included.

**The Kanjuro regression was an artifact of my hand-picked list, and fixing the list beat
the baseline:**

    S31E01 @589s   A: "You're a real bro, Kanjuro."   |  "Kanjuro!"
                   D: "Kajudo Kajudo!"                            <- regression
                   E: "You're a real pro, Kanjuro!"   |  "Kanjuro!"

    canonical Kanjuro    A=2   D=0   E=4
    Kajudo               A=0   D=2   E=0

Arm E does not merely avoid D's regression: `Kanjino`, a mishear present in BOTH A and D,
is gone in E, so E has 4 correct occurrences against the baseline's 2.

Arc names across all three episodes, canonical / any-variant:

    term          A          D          E
    Doflamingo    7/9       13/13      12/12
    Dressrosa    12/15      18/18      18/18
    Colosseum     3/14      13/14      13/14
    Kanjuro       2/4        1/4        4/4     <- E best, beats baseline
    Bartolomeo    4/5        4/5        5/6     <- E best
    Cavendish     3/3        3/3        3/3
    Rebecca       2/2        2/2        2/2
    Kyros         0/0        1/1        0/0     <- only D found it

Quality of what each arm newly introduced, judged against the container's 100k-word
dictionary (capitalised tokens present in the arm but not in the baseline):

    arm D  28 distinct.  Kajudo, Dressnana, Tophie, Batdog, Yerusha, Malachok, Doki...
                         predominantly non-words.
    arm E  32 distinct.  Donquixote x3, Sabaody, Fujitora, Kuma, Dracul  -- REAL names the
                         baseline missed -- alongside Dressnana, Jamaika, Molinosuke,
                         Dester x1.

So E introduces MORE new tokens than D but a much higher proportion of them are correct
names. The spike's `Dester` does appear once in arm E.

### E's own cost: repetition loops

    S31E02       cards   collapsed   max_dur   flagged
    A              393           0      6.2s        14
    D              381           0      6.9s        27
    E              411          38     30.0s        25

Arm E induced 38 runaway repeat runs that the hallucination gate had to collapse; 37 were
handled cleanly and one survived as a 30-second card reading "Grr!" on a non-speech
stretch. A 30 s card violates the display profile outright. Neither A nor D produced any.
E03 showed none of this (`collapsed=0`), so it is stretch-dependent, not universal.

Confidence degraded in BOTH hotwords arms and did not improve with the better list:
flagged 38 (A) -> 93 (D) -> 85 (E); low_conf 24 -> 60 -> 56; mean logprob ~-0.11 -> ~-0.18.
That is a property of hotwords priming, not of list composition.

## Verdict, and a flaw in my own decision rule

The rule required "no regression on an unanchored card that a human would call worse". Arm
E still produces some (`Dester`, `Jamaika`, `Molinosuke`, the 30 s "Grr!" card), so by the
letter of the rule hotwords fails again.

**But the rule as I wrote it is close to unsatisfiable.** Any change to decoder conditioning
perturbs a 1,400-card transcript somewhere; demanding zero regressions makes the gate
impossible to pass regardless of net benefit. That is a defect in the rule, not evidence
about hotwords. A rule that can be met needs to compare weighted fixes against weighted
regressions, with the 30 s card class treated as severe because it is visible to a viewer
in a way a mis-spelled name is not.

What the evidence actually supports:

- Hotwords fixes things nothing else in the pipeline can reach. `Coliseum` -> `Colosseum`
  is blocked from `glossary.correct()` by the `is_english` gate; `Kanjino` -> `Kanjuro`
  and `do Flamingo` -> `Doflamingo` were never repairable on an unanchored card.
- A DERIVED list strictly dominates a hand-picked one. Every omission is a regression
  waiting to happen; [S-10] must forbid hand-picked lists.
- List SIZE is the live risk, separately from composition. 150 tokens induced loops that 72
  tokens did not. The two arms failed for different reasons — D by omission, E by size.
- The untested configuration is the obvious one: DERIVED and SMALL, ~72 tokens. It would
  have E's coverage of the names that matter without 150 tokens of perturbation.

## Next

Run arm F: derived ranking, truncated to ~72 tokens, most-important-first. If it keeps
Kanjuro and produces no repetition collapses, that is the configuration to ship and the
decision rule should be rewritten to a weighted comparison before it is applied. If it
loses Kanjuro again, coverage and perturbation are in direct conflict at this budget and
[S-10] should be cut.

## CORRECTION — arm D's regression was a malformed term I introduced

Arm F (72 tokens, DERIVED, 16 terms) does not contain Kanjuro either, and gets him right:

    arm                  Kanjuro   Kajudo   Kanjino
    A baseline                 2        0         1
    D 72 hand-picked           0        2         1
    F 72 derived               3        0         0
    E 150 derived              3        0         0

F omits Kanjuro from its hotwords and still produces him correctly three times, beating the
baseline's two AND fixing the baseline's `Kanjino` mishear. **So the regression was not
caused by omission.** The "incomplete list" explanation recorded above is WRONG, and so was
the earlier "hotwords corrupts names it is not told about".

What actually distinguishes D is a malformed term. The three lists:

    D  "... Bellamy, Kin emon, Caesar Clown, ..."    <- apostrophe stripped, split in two
    F  (contains no Kin'emon at all)
    E  "... Kin'emon, ..."                           <- correct

The only arm carrying a malformed term is the only arm that corrupted a name, and
`Kin'emon` and `Kanjuro` are phonetically adjacent Wano names. `Kin emon` as two tokens
plausibly primes a `Kin...emon` pattern that pulled `Kanjuro` into `Kajudo`. The
malformation was introduced by the author stripping the apostrophe for shell quoting, not
by any part of the pipeline.

This is circumstantial, not isolated: proving it needs a 72-token arm containing a correct
`Kin'emon`. But the correlation holds across three arms, and it changes what [S-10] must
require. "Derived, never hand-picked" stands, but for a different reason than first stated:
not because hand-picking OMITS names, but because hand-editing CORRUPTS terms. The spec
needs a validation rule — hotword terms are canonical wiki titles used verbatim, with
apostrophes and diacritics preserved, and a term that does not round-trip against the title
set is rejected rather than passed to the decoder.

It also means **arm D's numbers should carry little weight**: it measured a corrupted list.
The meaningful comparison is A vs F vs G110 vs G138 vs E.

Perturbation at equal budget also favours the derived list, which the omission theory does
not explain but term quality does:

    S31E01           flagged   low_conf   meanlp
    A baseline            16          9    -0.11
    F 72 derived          24         15    -0.13
    D 72 hand-picked      32         18    -0.16
    E 150 derived         30         24    -0.18

## Arm F (72 tokens, derived) and the symmetric defect count

Arm F looked clean on the pipeline's own counters -- `collapsed=0` on all three episodes,
no card over 6.9s, and a name tally of +32 occurrences gained against 0 lost. Both of those
readings were wrong, for the same reason: they measured what I had chosen to count.

The name tally counted only names on MY list, and it counted OCCURRENCES rather than
correctness. `Dellinger`, which the BASELINE rendered correctly, was broken to `Dallinger`
by arm F and never appeared in the tally because I had not listed it.

Inspecting what each arm introduced that the baseline did not:

    693.7s   A: "The genius jester, Bucky."       F: "The Genius Dester Bucky."
    230.8s   A: "It's"                            F: "Badabada Badabada Badabada Badabada Badabada"
    234.4s   A: (no card)                         F: "Badabada Badabada Badabada Badabada Badabada."
    591.5s   A: "Senor Pink, then Dellinger,"     F: "Dan Dallinger."
    290.2s   A: "I accept the duel and I look..." F: "Shuswinawano to the place it rightfully belongs!"

`jester` -> `Dester` is the severe class exactly. The two `Badabada` cards are repetition
runs that the hallucination gate did NOT collapse (`collapsed=0`), so unlike arm E's loop
they shipped verbatim.

Counting defect SHAPES symmetrically across arms, with no arm privileged as the reference
(cards containing a token repeated 4+ times and making up 60%+ of the card; cards whose
long tokens are all non-dictionary; cards over 12s; distinct capitalised non-dictionary
tokens):

    arm   cards   repetition   gibberish   12s+ cards   non-dict caps
    A      1479            0           1            0              43
    D      1428            0           3            0              51
    F      1455            3           4            0              48
    E      1501            5           1            1              55

**The baseline produces zero repetition runs. Every derived-hotwords arm produces them.**
F at 72 tokens and E at 150 both do, so this is not a size artifact and cannot be tuned
away by shrinking the list. All hotwords arms also carry more non-dictionary capitalised
tokens than the baseline.

### What hotwords actually trades

For, measured on arm F against baseline:

- canonical spelling the pipeline cannot otherwise reach: Colosseum 3 -> 14 occurrences
  in canonical form (`glossary.correct()` is blocked by the `is_english` gate here)
- Doflamingo +5, Dressrosa +6, Kanjuro +2 in canonical form
- `Dothamingo`, `do Flamingo` and `Kanjino` all eliminated

Against:

- 3 repetition runs and 4 gibberish cards where the baseline had 0 and 1
- `jester` -> `Dester`, `Dellinger` -> `Dallinger`: correct baseline output destroyed
- ~5 more non-dictionary capitalised tokens

Per the rewritten decision rule, repetition runs where the baseline produced none are
SEVERE and block adoption on their own. **Arms D, E and F all fail. On this evidence
hotwords should not be enabled**, and the honest summary is that it buys name accuracy and
pays in hallucination, consistently, at every size tested.

Arms G138 (138 tokens, the smallest that covers Kanjuro) and H (arm F plus a correctly
apostrophised `Kin'emon`, isolating the malformed-term question) were still running when
this was written. Neither can overturn the repetition finding, which is present at both 72
and 150 tokens; they can only refine it.
