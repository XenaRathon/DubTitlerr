# Review prompt — human review of LLM repair, and a decision store that ships

Fifth review on **DubTitlerr**. Your previous four are in this directory
(`GLM-2026-08-21-glossary-and-watchgate.md`, `GLM-2026-08-24-v5-two-tier-idempotency.md`,
`GLM-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md`,
`GLM-2026-08-26-round2-repair-leg.md`). **The last one is directly upstream of this spec** —
you argued that `accept_repair` cannot enforce the acceptance bar it documents, that every
S31 card is unanchored so every regression there is permanent, and that the guards should be
built and the unanchored set re-measured before the gate opens. That happened. This spec is
what the answer turned into, so you are reviewing the consequence of your own finding.

**Spec under review:** `.procoder/specs/repair-review-and-decision-store.md`

**Prior art, all in this repo:**

- `.procoder/adr/0001-idempotency-is-keyed-on-two-tiers-not-one-version.md` — load-bearing
- `.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md` — `[S-12]`/`[S-14]`/`[S-15]`
- `docs/Adversarial Reviews/RESULTS-2026-08-26-unanchored-repair.md` — the 21-repair measurement
- `docs/Adversarial Reviews/RESULTS-2026-08-27-s16-coverage-falsified.md` — a hypothesis of
  the author's, recorded as fact, then falsified by the test you demanded
- `docs/Adversarial Reviews/REVIEW-2026-08-27-unanchored-repair-45-lines.md` — the owner's
  actual verdicts, and the reason this spec exists

## Deliverable

**Write your review to a markdown file in `docs/Adversarial Reviews/` named
`GLM-2026-08-27-repair-review-and-decision-store.md`.** Do not return it as chat output for
copy-paste — the file is what gets read. Structure it however serves the argument, but every
finding needs a file:line anchor or a measurement, and state plainly which findings you
would block the build on versus merely note.

## The situation

`repair.accept_repair` decides whether an LLM repair replaces a transcribed subtitle line.
Its docstring states the bar — same referent, same sense — and then says in as many words
that nothing below it enforces that. This is measured, not feared. `factory -> needle` and
`VIVRA card -> Vivi card` both pass every gate. So does the class found on 2026-08-27:

    "deserves the flame flame fruit."  ->  "deserves the flame fruit."

Length ratio 0.88, inside the 0.6-1.5 band. Shorter, so `fits_card` passes. No reference to
borrow from. No new token, so `invents_name` sees nothing. It was caught only because the
owner knew the term.

Measured on One Pace S31E01, replayed from sidecars, `REPAIR_UNANCHORED=1`, both guards
active, nanbeige4.2-3b:

    repair targets                    161
    LLM proposals                      25
    accepted by accept_repair          21
    refused (rejected_guard)            4

Across E01-E03: 393 targets -> 45 accepted repairs. The owner read all 45 on 2026-08-27:

    checked (approved)                 41
    rejected outright                   4
    of the 41, silently hand-corrected  5
    clean, untouched pass rate      36/45   (80%, not the 91% the checkboxes suggest)

Every S31 card is unanchored — 6,492 `no_reference` across the season — so a regression
shipped there has no downstream repair path. `REPAIR_UNANCHORED` is still default-off, and
the owner's read is the only thing standing between the gate and the library.

That read currently happens by hand-annotating a Markdown file that an agent generated and
an agent parsed back. The verdicts live as prose in `docs/Adversarial Reviews/`. They cannot
be applied to the episodes, cannot survive a re-run, and cannot reach anyone else running
this pipeline. **This spec builds the missing rung and makes the verdicts a shippable
artifact, keyed on the text pair, committed to git the way the 15 glossaries already are.**

Environment: three runtime dependencies (`pysubs2`, `faster-whisper`, `jellyfish`); there
has never been a web framework here. The container runs as root so `generate.py` can chown
sidecars. `unresolved.record` already fires ~86x per episode.

## The one rule

**Verify every factual claim against the source before accepting or attacking it.** This
author's failure mode is a hypothesis that sounds right being recorded as fact — two were
falsified overnight on 2026-08-26/27 (`[S-16]` glossary coverage, `[S-9]` scope narrowing),
both the author's own, and the Kanjuro regression had three wrong explanations before the
right one. In this session the author also asserted "there is no procoder tdd" from the
wrong source and was corrected by the user. **When a claim matches what you would expect,
check it hardest.**

Two claims in particular were verified by the author while writing the spec and are exactly
the shape that has been wrong before. Re-derive both:

- **`hard_fixes` does not reach the decoder.** `glossary.stale_tier` compares only the
  `initial_prompt` STRING, and `glossary.prompt_for` reads `gloss["initial_prompt"]`, so
  `[S-3]`'s promotion is text-tier work. If ANY path lets a promoted `hard_fix` alter
  `initial_prompt`, `[S-3]` silently marks episodes transcription-stale — the GPU tier —
  and the spec's "no `TEXT_VERSION` bump needed" claim collapses with it.
- **`repair.py` never rewrites `conf.json`.** `[S-5]` restores ASR text by rebuilding the
  srt from `conf.json`, which requires that file to still hold PRE-repair text. If any
  stage rewrites it, a `reject` verdict cannot restore anything and `[S-5]` is unbuildable
  as written.

Other anchors worth confirming: `repair.accept_repair`, `repair.skips_unanchored`,
`repair.glossary_for`, `repair.py:685-697` (srt + `repair.csv` writing), `unresolved.record`
/ `resolve` / `_EVIDENCE` and that module's never-raise contract,
`glossary_acquire.apply_proposals` (the I3 and C2 invariants), `glossary_acquire.revert`
(R4), `glossary_acquire.review_items`, `common.stamp_valid`, `common.TEXT_VERSION`,
`mux.py`'s `.dubtitles.done` skip guard, `container_run.sh`.

## Attack these specifically

1. **The portability premise is unmeasured, and everything rests on it.** `[S-2]` keys
   decisions on the normalised `(orig, proposed)` text pair so they survive a re-run and
   mean something in another library. That requires ASR text to recur byte-identically. The
   author flagged this as unmeasured and did not measure it. If the hit rate across a model
   or `TRANSCRIBE_VERSION` change is near zero, then `[S-2]`, `[S-9]` and the entire
   shipping premise degrade to "a file only its author can use," and the collaborative goal
   is dead on arrival. State the experiment that settles this, predict its result, and say
   whether the design has any fallback if the answer is bad. **This is the review's highest
   priority — answer it well even if you answer nothing else.**

2. **`force` reintroduces the exact class the guards were built for.** The owner decided a
   human may force-accept a repair `accept_repair` refused, overriding `invents_name` and
   the `[S-15]` phonetic guard. Those guards exist because of measured failures — `Oimo ->
Zoro` in the bake-off, and hotwords turning `Kanjuro` into `Kanjudo` by listing a
   phonetically adjacent name. The human exercising `force` is reading TEXT in a web queue.
   The stated bar is that a dubtitle must match the DUB AUDIO, which the reviewer is not
   listening to. Argue as strongly as you can that `force` should not exist. Then argue the
   other side. Say which wins and what evidence would change your mind.

3. **The queue asks two incompatible questions with one vocabulary.** `[S-1]` puts
   `repair_applied/accepted` entries ("was this repair right?") in the same queue as
   `rejected_guard` entries ("was the GATE right?"). One verdict set — accept / reject /
   correct / force — spans both. What does `reject` mean on a `rejected_guard` entry: the
   gate was right, or the proposal was bad? Is the data model coherent, or does this need
   two verdict vocabularies and the spec has quietly merged them?

4. **`[S-6]` has no escape.** A show in `REVIEW_GATE_SHOWS` holds any episode with a pending
   entry out of the mux stage. There is no timeout, no bypass, no alert, and the human
   reviews in evening batches. What is the state of the library after two weeks away? The
   Failure modes section names "a gate that silently holds every episode forever" as the
   thing to avoid and then does not prevent it. Design the escape or argue the gate should
   not ship at all.

5. **`[S-7]`/`[S-8]` put an unauthenticated write endpoint inside a root container.**
   `container_run.sh` runs as root so `generate.py` can chown into the media tree. The spec
   adds an HTTP server to that process tree whose write routes rewrite subtitle files and
   trigger re-muxes, with `REVIEW_TOKEN` unset by default and "LAN-only, documented" as the
   justification. Is that defensible for software intended to be run by downstream users who
   may use host networking? If not, say what the default must be.

6. **Which acceptance criteria pass while the behaviour is broken?** There are 23. Prior
   rounds found the highest-value items this way. Two the author already suspects are weak:
   "an empty store produces byte-identical output" is trivially satisfiable by a consult
   point that is never reached, and "`DECISIONS_APPLY=0` produces byte-identical output"
   proves the flag works without proving the flag is read at the right moment. Find the
   others.

7. **Is the two-store split right, or does it just move the problem?** `[S-3]` promotes
   term-level verdicts into the glossary and leaves line-level verdicts in the decision
   store. On the owner's own 11 judgments the split was roughly even. Who decides which a
   verdict is — the human, at review time, or the code? The spec does not say clearly. Is
   that classification decidable at all, and what happens to a verdict misfiled in either
   direction?

8. **What is missing from the spec entirely.** Prior rounds found the most valuable items
   here — you identified the successor item when the topic was hang trimming. Explicitly out
   of scope: the contribution channel, tightening `accept_repair`, the `REPAIR_UNANCHORED`
   flip, and the `WHISPER_MODEL` default. Say whether any of those is load-bearing for
   THIS change rather than merely related.

## What a useful review looks like

Refute, don't validate. If the design is sound, say which specific claim you tried hardest
to break and what stopped you — a review that agrees without naming its strongest attempted
counter-argument is not evidence.

Answer the numbered items IN ORDER and go as deep as you can on each. If you are running
short, STOP and say so rather than padding the later items: item 1 answered well is worth
more than all eight answered thinly. Mark anywhere you are speculating rather than reasoning
from the source.

One piece of context the spec assumes: the maintainer's standing architectural default is
deterministic rules first, LLM only for what rules cannot settle, human only for what the
LLM cannot — with each layer recording why it escalated. Flag anywhere this design violates
that ladder, and anywhere it claims to implement a rung it does not actually implement.
