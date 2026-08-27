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

## Next — the one experiment that resolves it

Re-run arm D with hotwords derived from the FULL arc cast rather than 20 hand-picked terms,
sized to the token budget by the [S-10] ranking rather than by the author's judgement, and
check specifically whether `Kanjuro` survives. Two outcomes, both decisive:

- **Kanjuro survives and no new non-word regression appears** -> the regression was an
  artifact of an incomplete list, the rule returns net positive, and [S-10] proceeds with a
  requirement that the list be derived, never hand-picked.
- **Kanjuro still breaks, or a different name breaks** -> hotwords corrupts names it is not
  told about, which cannot be fixed by a longer list (the budget is finite and the arc has
  96+ entities), and [S-10] should be cut per the decision rule.

Until that runs, [S-1], [S-2], [S-5]-arc, [S-8] and [S-11] remain unbuilt per the build
order: they exist only to feed [S-10].
