# Review prompt — round 2, after the leg changed shape

Sixth review on **DubTitlerr**, and the second on this leg. Your round-1 review is in this
directory (`GLM-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md`) and it was
acted on: F1 (build order + decision rule), F2 (season tags as a set), F3 (class-wide
criterion), F5 (wiki-driven staleness logging), F6 (fallback on category emptiness), F8
([S-8] justification withdrawn) all landed, and your F4 and F7 corrections were applied to
the findings file. The Luna rebuttal (`LUNA-2026-08-26-rebuttal-of-ab-findings.md`) also
landed.

**Then the measurements demolished most of the leg**, and it now proposes something
different. That is what you are reviewing.

**Spec:** `.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md`
(the title is now WRONG -- per-season prompts are cut. Say whether it should be renamed.)

**Evidence files, all in this directory:**

- `RESULTS-2026-08-26-ab-prompt-comparison.md` -- `initial_prompt` is inert
- `RESULTS-2026-08-26-hotwords-full-episode.md` -- hotwords measured and cut
- `RESULTS-2026-08-26-unanchored-repair.md` -- the new proposal, measured

## What changed since round 1

    [S-3]  per-season initial_prompt      WITHDRAWN. Two sharply different prompts produced
                                          word-identical transcripts across three episodes;
                                          all 15 arc names identical counts.
    [S-10] hotwords                       CUT. Measured at 72/110/138/150 tokens. It
                                          corrupts phonetically adjacent names it does NOT
                                          list (Kin'emon listed -> Kanjuro becomes Kanjudo)
                                          and adds repetition runs the baseline never
                                          produces (baseline 0, derived arms 3-5).
    [S-6]  season-aware staleness         MOOT. Nothing season-scoped reaches the decoder.
    [S-12] ungate unanchored LLM repair   NEW, measured: targets=161 repaired=0 -> 21.
    [S-13] season-weighted repair glossary NEW, unmeasured (needs [S-11] tags).
    [S-14] known->known + phonetic guards  NEW, measured: blocked NOTHING.

The author was wrong three times in a row about one regression -- first "hotwords corrupts
unlisted names", then "the list was incomplete", then "a malformed term I introduced" --
and each explanation looked clean until the next arm refuted it. Assume the current
explanation is the fourth in that series until you have checked it.

## The one rule

**Verify every factual claim against the source before accepting or attacking it**,
including the findings files' own claims. `faster_whisper` is an installed dependency, not
in the repo; if you cannot read it, say so rather than reasoning from the quotes. All
VM102, NFS, GPU and media figures are unverifiable from a checkout -- treat them as
unverified and say which of your conclusions depend on them.

Anchors: `repair.py:461-530` (`process`, the `no_reference` skip, the accept path),
`repair.build_prompt` (note it already degrades correctly with `sub=""`),
`repair.invents_name`, `repair.accept_repair`, `glossary._fix_token` (the `is_english` and
`_one_indel` gates), `glossary.correct`, `glossary.prompt_for`, `glossary.stale_tier`,
`common.py:130-160` (the tier block, now at TEXT_VERSION 7), `generate.py:890-913`.

## Attack these

1. **[S-12] is the whole leg now, and it reverses a documented decision.**
   `repair.py:512` skips unanchored cards because "the bake-off showed glossary-only repair
   hallucinates names (Oimo->Zoro) even on qwen3:8b". The measurement ungating it reports 18
   of 21 acceptable on ONE episode of ONE show with ONE model (nanbeige4.2-3b). Is one
   episode remotely sufficient to reverse a decision taken on a documented sweep? What
   would you require, and does the fact that all 6,492 S31 cards are unanchored (so every
   regression is permanent) change the bar?

2. **[S-14] blocked nothing and is being kept anyway.** Both guards produced a set
   byte-identical to ungated: zero regressions prevented, zero fixes lost. The spec keeps
   them as "insurance against a documented prior failure". Is keeping an unproven guard
   defensible, or is it the same speculative-need this repo's rules forbid? Note the
   asymmetry: the guard's cost is a rejected good repair, which is invisible in the
   measurement because it never reaches the CSV.

3. **The phonetic threshold is knowingly wrong.** 0.75 jaro-winkler admits
   `syrahose -> shirahoshi` (0.755) and blocks `oimo -> zoro` (0.667), but the BAD
   `vivra -> vivi` scores 0.848 and gets through. The spec accepts this and blames glossary
   coverage. Is a threshold with a known false-negative on its own example set worth having,
   and is "it is really a coverage gap" an explanation or an excuse?

4. **The acceptance bar was set by the owner AFTER seeing the results.** It reads: a
   deviation carrying the same meaning is acceptable; one changing the meaning is not.
   `Mihawk` for `Hawkeye Dracule Mihawk` was ruled acceptable, though `accept_repair`'s own
   docstring says a dubtitle must match the DUB AUDIO. Is the bar coherent, is it applied
   consistently in the results file's 18/3 split, and does it silently license the
   information loss the docstring was written to prevent?

5. **[S-13] is unmeasured and load-bearing.** Season weighting is the thing that is supposed
   to make `Oimo -> Zoro` implausible in a Dressrosa episode, but it does not exist yet and
   the guards that DO exist blocked nothing. Is the leg shipping its safety story on an
   unbuilt component?

6. **What survives, and should it?** After the cuts, [S-1], [S-2], [S-4], [S-5], [S-7],
   [S-8], [S-9], [S-11] all exist to feed... what, exactly? [S-11]'s tags feed the unbuilt
   [S-13]. [S-2]'s arc fetch is justified by ONE observation -- that "Vivre Card" is absent
   from the glossary and its absence caused one bad repair. Is that enough to justify arc
   scoping, category discovery, a shared wiki layer and season tagging? Or is the honest
   remainder just [S-12] plus glossary coverage by any means?

7. **Measurement methodology.** The author's metrics misled him twice: `collapsed=0` hid
   two uncollapsed repetition cards, and a name tally of "+32 gained, 0 lost" hid
   `Dellinger -> Dallinger` because Dellinger was not on the list being counted. The current
   defect counting (repetition runs, gibberish cards, 12s+ cards, non-dictionary capitalised
   tokens) was written after those failures. Does it have the same shape of blind spot? What
   does it still not see?

8. **The title and the spec's coherence.** It is named
   `arc-scoped-acquisition-and-per-season-prompt`; per-season prompts are cut, hotwords are
   cut, and the live proposal is unanchored LLM repair. Should this be split into two specs,
   renamed, or closed and reopened? Say plainly whether a reader who arrives cold could
   build from this document as it stands.

## Deliverable

Write to `GLM-2026-08-26-round2-repair-leg.md` in this directory. Rank findings, anchor each
to a file:line or a number, and mark clearly which you would block the build on. If the leg
should be cut entirely rather than reshaped again, say so -- twice tonight the honest answer
was "this mechanism does not work", and both times acting on it was cheaper than defending
it.
