# Review prompt — arc-scoped acquisition and per-season prompt

Fifth review on **DubTitlerr**. Your previous four are in this directory
(`GLM-2026-08-21-glossary-and-watchgate.md`, `GLM-2026-08-24-v5-two-tier-idempotency.md`,
and the VAD hang-trim round). Worth skimming for how this codebase fails: the recurring
mode is a defaulted value silently answering the question that was asked.

**Spec under review:** `.procoder/specs/arc-scoped-acquisition-and-per-season-prompt.md`

**Prior art in this repo, both load-bearing here:**

- `.procoder/adr/0001-idempotency-is-keyed-on-two-tiers-not-one-version.md` — the two-tier
  scheme this spec has to extend without breaking
- `docs/superpowers/specs/2026-08-19-glossary-name-acquisition-design.md` — the design of
  the stage being consolidated

## Deliverable

**Write your review to a markdown file in `docs/Adversarial Reviews/`** — named
`GLM-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md` if you are GLM, or
`LUNA-2026-08-26-arc-scoped-acquisition-and-per-season-prompt.md` if you are GPT-5.6 Luna.
Do not return it as chat output for copy-paste; the file is what gets read. Structure it
however serves the argument, but every finding needs a file:line anchor or a measurement,
and state plainly which findings you would block the build on versus merely note.

## The situation

A show glossary carries exactly ONE `initial_prompt`, and it is the only glossary-derived
input the decoder ever sees (`generate.py:893`). One Pace's live prompt primes whisper with
the Enies Lobby cast — Spandam, Lucci, Kaku, Kalifa, Blueno, Iceburg, CP9, Ohara, Pluton —
while Season 31 is the Dressrosa arc. The spec makes the prompt per-season, sourced from
the arc's wiki pages, and folds the prompt build into the existing acquisition stage.

Measured on the live system 2026-08-26 (VM102, GTX 1050 Ti 4 GB, NFS mount):

    One Pace S31 episodes                        48
    S31 stamps                                   48   all legacy single `version: 4`
    S31 accepted LLM repairs (v4 artifacts)       0
    S31 cards skipped `no_reference`          6,492
    S29 accepted LLM repairs, 23 episodes         0
    acquire --apply over 461 episodes         20 proposed / 0 applied / 19 flagged
    wiki titles, show-wide (`fetch_titles`)   8,109
    wiki titles, Dressrosa arc categories        96   union of 5 categories
    prompt candidates from arc page             206
    prompt terms that fit the budget             47   at 222 of 223 tokens
    season.nfo present                           35   of 35 One Pace seasons
    NFS sequential read                    4.5 MB/s   caused ffmpeg to hit generate.py:246's
                                                      hard-coded timeout=600 and fail

Of four sampled non-One-Pace shows (Chainsaw Man, Chainsmoker Cat, MARRIAGETOXIN, Reborn as
a Vending Machine) **three have no glossary at all** — they run the neutral fallback prompt
with `glossary.correct()` a complete no-op. Those shows run 8–13 episodes per season.

An A/B of the two prompts on the same three episodes (same model, beam, audio filter, and
identical glossary `names` — the prompt is the only variable) was run on local copies after
the NFS timeouts above. **Its results are in
`RESULTS-2026-08-26-ab-prompt-comparison.md` in this directory.** If that file is absent,
treat every claim about what the arc prompt BUYS as unmeasured and say so.

## The one rule

**Verify every factual claim against the source before accepting or attacking it.** When a
claim matches what you would expect, check it hardest. Two of this author's own claims
tonight were wrong in exactly that way: a complexity regression measured against `main`
instead of the branch point (there was no regression), and a "stalled" diagnosis that was a
misread clock. Both looked right.

Anchors worth confirming:
`glossary.prompt_for`, `glossary.stale_tier`, `glossary._fix_token` (the `_one_indel`
exclusions on BOTH the fuzzy and phonetic tiers), `glossary.load_dict`,
`generate.py:107-124` (where `INITIAL_PROMPT` is resolved), `generate.py:317` (what
`words.json` stores), `generate.partition_todo`, `common.py:130-155` (the tier comment
block), `glossary_verify.fetch_titles`, `glossary_acquire.acquire_show`, `repair.py:493`
(the no-reference skip), `repair.invents_name`, and
`faster_whisper/transcribe.py:1546-1550`.

## What changed after the spec was written — read this before the attacks

The spec was marked COMPLETE, then measured, and the measurement moved its delivery
mechanism. Results: `RESULTS-2026-08-26-ab-prompt-comparison.md`, same directory.

- An A/B on S31E01-E03 (same audio, same model, same glossary `names`, prompt the only
  variable) found `initial_prompt` changes NOTHING: word similarity 0.9984-0.9991, 5
  differing runs in 10,487 tokens all attributable to the hallucination gate, and identical
  counts for all 15 arc names.
- Mechanism: `condition_on_previous_text=False` (`generate.py:890`) empties
  `previous_tokens` after the first window; in a real episode that window is the opening
  theme. The author FIRST claimed effects were confined to that window, then refuted his own
  claim — on a mid-episode clip the prompt does change later text, via segmentation cascade.
  Both statements are in the results file; check which one the spec now relies on.
- A spike showed `hotwords` (`transcribe.py:1542`) applies on every window and fixed
  `do Flamingo` -> `Doflamingo` 57 s into a clip — but ALSO turned `jester` into `Dester`
  in the same 180 s. One fix, one regression.
- [S-3] is withdrawn and replaced by [S-10] (hotwords) and [S-11] (season-tagged names).

**Attack the new mechanism at least as hard as the old one.** In particular: is one fix and
one regression in 180 seconds evidence of anything, or is the spike too small to license
[S-10] at all? The author thinks the ratio must be measured over a full episode before
hotwords is enabled; say whether even that is sufficient.

## Attack these specifically

1. **Is `season.nfo`'s `<title>` a sound arc key, or does it only look like one?** It reads
   `Dressrosa` for S31 and `Romance Dawn`, `Orange Town`, `Syrup Village`, `Gaimon` for
   S01–S04. Some of those are arcs; at least one is a character. One Pace also re-cuts a
   118-episode wiki arc into a 48-episode season, so the mapping is not one-to-one in
   either direction. Decide whether this key is load-bearing enough to gate GPU work on,
   and what the spec's fallback actually does when it silently resolves to the wrong arc
   rather than to nothing.

2. **The adoption mechanism is the whole safety argument — break it.** The spec claims a
   season is migrated exactly when it has a `season_prompts` entry, so writing that entry
   is the only thing that stales that season. `stale_tier` compares the STORED prompt
   string against the derived one. Enumerate the states where that equivalence fails:
   an entry added then removed; an entry whose value is byte-identical to the show prompt;
   a season renumbered; an episode whose `words.json` predates `season_prompts` existing;
   a show where `initial_prompt` itself is later edited. Which of those silently
   re-transcribes the library, and which silently DOESN'T re-transcribe something it should?

3. **The prompt-only rule may fight the v6 name guard.** The spec forbids writing names to
   the glossary without transcript evidence. But `repair.invents_name` rejects an LLM edit
   whose gained proper noun is not in `gloss["names"]`. So once the arc prompt makes whisper
   emit `Rebecca` correctly, `Rebecca` is on screen and still absent from `names` — and any
   LLM repair moving a mishear TOWARD `Rebecca` is rejected as a fabrication. Does this
   design make the guard worse exactly where the prompt makes the decoder better? Check
   `repair.py:522` and `glossary.correct` before answering.

4. **Is the feedback-loop claim actually true?** The spec asserts that priming alone breaks
   the cycle, because the next transcript will contain the arc's names for acquire to
   harvest normally. That is an untested causal claim standing in for the rejected
   alternative (seeding names directly). What has to hold for it to be true, and what
   happens if whisper emits the name in a form acquire's admission gates refuse — which is
   precisely what they did to `Samji -> Sanji` at seen 1/721?

5. **`[S-8]`, extracting the wiki layer, refactors working code.** `glossary_verify` is not
   broken. The stated justification is avoiding two modules deriving the same wiki state.
   Is that justification real, or is it the kind of structural tidiness this codebase's own
   engineering rules ("the best code is the code never written") tell it to skip? If it IS
   justified, name the specific drift it prevents.

6. **[S-11] makes the season tag load-bearing — is the split it assumes correct?** The
   design keeps ONE show-wide `names` list, tags each name with the season that acquired it,
   and uses the tags only to select that season's `hotwords`. The claim is that correction
   needs breadth (a recurring character must be corrected in every arc — Caesar Clown is a
   Punk Hazard antagonist present in Dressrosa) while priming needs narrowness (hotwords
   grows the decoder prompt on every window, and the spike suggests a bigger bias corrupts
   more ordinary words). Attack both halves: is there a case where correction should be
   NARROW, and one where priming should be BROAD? What happens to a character introduced
   mid-arc, or one whose name is a common English word? Note this also answers an earlier
   objection — the tag is now read, not decoration like the `stages` field `mux.py:354`
   writes and nothing reads — so do not re-litigate that; litigate whether the split is
   right.

7. **The truncation direction inverts, and the spec depends on getting it right.**
   Verified: `initial_prompt` reaches `previous_tokens` (`:1147` -> `:1187` -> `:1202`) and
   is truncated `[-(max_length // 2 - 1):]` at `:1550`, keeping the TAIL. `hotwords` is
   truncated `[: max_length // 2 - 1]` at `:1547`, keeping the FRONT. [S-10] therefore
   orders most-important-FIRST, the reverse of the withdrawn [S-3]. Confirm both readings,
   and say what happens at the boundary — `if len(hotwords_tokens) >= self.max_length // 2`
   — when the selection is exactly at or just under the cap.

8. **Arc category discovery is proven on one arc.** `Category:Dressrosa Arc` does not exist;
   the useful categories are `Dressrosa Residents` / `Locations` / `Saga Antagonists`, found
   via `list=search&srnamespace=14`. `prop=links` on the arc page returns navbox pollution
   and is unusable. Nothing establishes that this generalises to another arc, let alone
   another wiki — and three of four sampled shows have no glossary, so the fallback path is
   the COMMON path, not the edge case. Is the spec's [S-7] degradation good enough to ship
   as the default experience?

9. **Scope question the spec deliberately leaves out.** S31 has 6,492 cards no LLM ever
   touches because `repair.py:493` skips unanchored cards. A better prompt improves the
   decoder but leaves that hole exactly as wide. Say whether this spec is attacking the
   right problem first, or whether it is the cheaper problem being done because it is
   tractable.

## What a useful review looks like here

Findings that change the build, ranked, each with an anchor or a number. If you conclude
the spec is sound, say that plainly and name the one thing most likely to be discovered
mid-build — do not manufacture findings to look thorough. Previous rounds where you
recommended dropping a feature outright were correct and were acted on.
