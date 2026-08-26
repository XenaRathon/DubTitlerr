# Rebuttal prompt — argue against the A/B findings

Fifth round on **DubTitlerr**, and this one is yours: you are GPT-5.6 Luna, playing the
other side. A prosecution prompt already exists in this directory
(`PROMPT-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md`) and the review it
elicited attacks the spec. Your job is the mirror image: **attack the FINDINGS file the
author wrote, not the spec** — `RESULTS-2026-08-26-ab-prompt-comparison.md`, same
directory. The author withdrew [S-3] and rewrote the spec's delivery mechanism on the
strength of that file. If its conclusions are wrong, [S-3] should come back. If they are
right, the rewrite stands. Those are the stakes; say which way you land.

**Spec under attack-by-finding:** `.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md`

**Files to read before writing anything:**
- `docs/Adversarial Reviews/RESULTS-2026-08-26-ab-prompt-comparison.md` — the findings you
  are arguing against
- `docs/Adversarial Reviews/PROMPT-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md` —
  the prosecution's case; you are not bound by it, but you are answering it
- `.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md` — the thing the
  findings indict; where the findings overshoot, the spec is what you defend

## Deliverable

**Write your rebuttal to a markdown file in `docs/Adversarial Reviews/` named
`LUNA-2026-08-26-rebuttal-of-ab-findings.md`.** Do not return it as chat output; the file
is what gets read. Structure it however serves the argument, but every claim needs a
file:line anchor or a measurement, and state plainly which of the author's findings you
would overturn outright versus merely downgrade.

## The one rule

**Verify every factual claim against the source before accepting or attacking it — the
findings file's claims included.** The author has already been wrong twice in this round:
the PROMPT file records a complexity regression that was measured against the wrong base,
and a "stalled" diagnosis that was a misread clock. The findings file contains its own
"CORRECTION", in which the author refutes his own earlier claim — that correction is
itself a claim, check it as hard as the thing it corrected. When a claim matches what you
would expect, check it hardest.

You have the repo: `generate.py`, `repair.py`, `glossary.py`, `common.py`,
`tools/glossary_acquire.py`, `tools/glossary_verify.py` are all here. `faster_whisper` is
NOT in the repo — it is the installed dependency (1.2.1), so `faster_whisper/transcribe.py`
anchors (`:1187`, `:1372-1383`, `:1542`, `:1547`, `:1550`) can only be checked if the
package is readable from your environment; if it is not, say so and reason from the lines
the findings file quotes. The media library (VM102, NFS) is not on this box: anything
about episodes, `season.nfo`, or GPU behavior is either in the findings file or
unverifiable — treat unverifiable as unverified, per the rule above.

## The findings to attack

1. **The headline: "`initial_prompt` changes NOTHING."** Three episodes, one show, one
   model (`large-v3-turbo` int8), one audio filter. Attack the measurement, not just the
   conclusion: arc-name counts run 1–28 occurrences per term, so equality of counts is
   weak evidence — a name misheard in both arms at different positions yields identical
   counts. Word similarity 0.9984–0.9991 is computed on lowercased, punctuation-stripped
  , index-aligned token sequences, yet the episode card counts themselves differ between
   arms (586/586, 393/389, 500/496) — 16 words of structural difference that the
   "differing runs" count of 5 may or may not represent. Is the metric built to miss
   exactly what a prompt changes? And the five differing runs are "all attributable to the
   hallucination gate" — is that verified per run, or asserted? Note two of the five are
   the SAME run ("so let s wake up") in E01 and E03. Finally: arm A's Enies Lobby names
   never appeared in EITHER transcript, so "the wrong prompt did not inject wrong names"
   is a claim about something that never happened — say plainly what would have to occur
   for arm A to demonstrate injection, and whether it is even testable on audio with no
   Enies Lobby dialogue.

2. **The load-bearing unverified fact: "in a real episode the first window is the OPENING
   THEME — sung, no character names."** This one claim is the entire reason the
   three-episode null result is believed to generalise, and the findings file does not
   show it being verified. One Pace is a fan re-cut — do S31E01–E03 actually open with a
   theme, and does the first whisper window (VAD off, per `generate.py:889`) actually
   cover pre-dialogue audio with no speech? The clip spike started at 600 s precisely
   because the author wanted dialogue in window 1 — the episode geometry is checkable from
   that asymmetry alone. Then attack the CORRECTION for internal consistency: if a 600 s
   clip shows prompt effects at 46.3 s and 53.0 s via a segmentation cascade, the same
   cascade should appear in the A/B the moment ANY window boundary shifts; the A/B claims
   full-episode silence in three hours of audio. Both cannot be robust. Which measurement
   decides, and what experiment settles it?

3. **The spike is read too cautiously: argue one fix + one regression in 180 s DOES
   license [S-10].** The fix lands at the exact position and phrase the acceptance
   criterion names (`657.3 s`, "Don Quixote do Flamingo") — the position where a 47-term
   `initial_prompt` demonstrably failed. It is deterministic across two runs, at no
   measurable VRAM or time cost. The author demands a full-episode fix/regression ratio
   before enabling; attack that demand: one episode is one season of one show — when is a
   ratio ever enough, and is the demanded measurement even capable of falsifying [S-10]?
   Then attack the regression's severity: "Dester" is "near no glossary name", so
   `glossary.correct()` cannot repair it — but the findings file asserts NO STAGE can.
   Check `repair.py:493-534` before letting that stand: is the LLM repair path actually
   closed to an anchored card containing "Dester", or only the deterministic one? If an
   anchored card reaches the LLM and the edit moves AWAY from the invented noun, does
   `repair.invents_name` fire at all? The author's own evidence may show the regression is
   cheaper than he claims.

4. **Attack "the defect that IS demonstrated" — the Dothamingo near-miss.** It is ONE
   name, ONE string distance: difflib 0.800 vs cutoff 0.84 (four points), metaphone T0MNK
   vs TFLMNK (one phoneme). Is that a demonstrated defect or a bug report? The findings
   file does not report how often `glossary.correct()` misses at this distance across the
   library, nor whether the same near-miss pattern holds for other names. Then attack the
   recommended action: the correction tiers and the no-fallback repair hole are OUT of the
   spec's scope — so the author's own headline defect indicts a leg the spec is not
   building, while the in-scope leg ([S-10]) is the only mechanism with any evidence of
   moving the exact token at the exact position. Argue the results file undersells its own
   spike and over-generalises its own null result. And check the Samji -> Sanji admission
   refusal the prosecution cited: was that refusal `correct()` or acquire's admission
   gates, and does it belong in the same defect bucket at all?

5. **The adoption mechanism survives the enumeration — defend `stale_tier` against the
   state list.** The prosecution enumerated: entry added then removed; entry byte-identical
   to the show prompt; season renumbered; `words.json` predating `season_prompts`;
   `initial_prompt` edited later. Argue each state to its actual consequence: a removed
   entry re-derives the show-level prompt (fresh, correct); a byte-identical entry is a
   no-op by construction; an `initial_prompt` edit SHOULD stale the whole show — that is
   the two-tier design (check which ADR governs prompt changes and what tier it belongs
   to). The dangerous one is the renumber — a season whose number changes leaves its entry
   orphaned and falls back silently to the show prompt. Defend it: what can actually
   renumber a season in Plex/Sonarr metadata, and — the key move — what does the fallback
   COST, given finding 1? If `initial_prompt` is measured inert on this pipeline, a wrong
   or missing per-season prompt is bounded in harm by that result, and the prosecution's
   "silently re-transcribes the library" claim dies on the same evidence that killed [S-3].
   Enumerate precisely which of those states can stale MORE than one season, and which can
   stale NOTHING that should stale — the prosecution says both classes exist; say whether
   either actually does.

6. **The prompt-only rule does not fight the v6 name guard — or if it does, the fight is
   bounded.** The prosecution's construction: hotwords makes whisper emit `Rebecca`
   correctly -> `Rebecca` is on screen but absent from `names` -> any LLM repair moving a
   mishear TOWARD `Rebecca` is rejected by `repair.invents_name` as a fabrication. Attack
   the construction at its hinges: read `repair.invents_name` and `repair.accept_repair`
   and say what the guard actually compares against — the reference or the glossary. If
   the guard's evidence base is the fansub REFERENCE, a reference-supported edit toward
   Rebecca is admitted or rejected on grounds the prosecution never checked. Then close
   the loop the prosecution calls a deadlock: whisper emits the name -> a transcript token
   exists -> acquire harvests it -> the name enters `names` -> the guard admits subsequent
   repairs. The loop's only failure point is acquire's admission gates, which [S-9] is the
   leg that re-measures. Say whether the guard's window of over-rejection is finite and
   whether the spec already contains its cure.

7. **The [S-11] split and the truncation boundary — argue both halves of each.** The
   split: correction broad, priming narrow. The prosecution asked for a correction-NARROW
   case and a priming-BROAD case. Supply them or refute them from the code: a name that
   changes form across arcs (an alias, a title-as-name) is a case where show-wide
   correction is WRONG, not broad — does `glossary.correct()` have any mechanism (parse
   priority, `hard_fixes` ordering, case rules) that bounds the damage, and does the
   season tag ([S-11]) actually get read anywhere that could narrow correction without
   hurting recurring characters? For priming-BROAD: is there a name so recurring that
   omitting it from a season's hotwords costs more than the Dester-class regression, and
   does the tag's absence from `names` (show-wide) keep such a name out of hotwords
   exactly when it would matter? And check the boundary the prosecution flagged:
   `transcribe.py:1547` slices `[: max_length // 2 - 1]` only in the branch where
   `len(hotwords_tokens) >= self.max_length // 2` — say what the effective hotwords budget
   is in THIS pipeline (where `previous_tokens` is empty every window), whether 223 is
   actually the ceiling the spec's Constraint section claims, and what happens if the
   selection lands exactly on the cap.

8. **Scope: the spec is attacking the right problem first — defend the order.** The
   prosecution's cheapest hit is "three of four sampled shows have no glossary, so [S-7]
   degradation is the COMMON path, not the edge case." Argue that [S-7] is defined as
   "today's behaviour" — the spec cannot make the common path worse than the status quo by
   construction, and the arc machinery being One-Pace-first is a sequencing choice, not a
   degradation. Then the no_reference hole (`repair.py:493`, 6,492 cards in S31): argue
   the ordering the author chose is the load-bearing one. `repair.py`'s own comment says
   glossary-only repair hallucinates names (Oimo -> Zoro) — the LLM repair can only be
   opened up safely AFTER the glossary knows the arc's names, and the glossary can only
   learn them after they are on screen. Whatever the A/B says about `initial_prompt`, the
   only evidence in the findings file of ANY mechanism changing any arc-name token at any
   position past the first window is hotwords. Challenge the prosecution to name the leg
   that grows `names` without a transcript — and note the spec's invariant forbids exactly
   that, so its side, not the guard, is the one with the coherent answer to "where does
   the first correct name come from?"

## What a useful rebuttal looks like

Refute, don't validate — but the direction is inverted from the review round: the
findings file is the thing that must justify itself, and the spec is innocent until the
findings prove otherwise. If the findings survive your attack, say so plainly and name
the one finding you tried hardest to break and what stopped you. If you overturn any of
them, say what the spec must do about it — most importantly, whether [S-3] (per-season
`initial_prompt`) is rehabilitated by your argument or stays dead. Prior rounds in this
directory show the author acts on reviews that go against him; a rebuttal that proves the
A/B was underpowered will be treated as an accusation, not a courtesy. Make it true.