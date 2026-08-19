# Spec — Glossary name acquisition (wiki-first, transcript-filtered)

> Design doc for a new pipeline stage that *acquires* proper nouns, rather than only
> verifying ones the miner already found. Companion to
> `specs/glossary-wiki-verify/spec.md`, which built the verification half.

## Problem

A show's glossary is only as good as its name source, and today there is exactly one:
`mine_glossary.eng_sub_text()`, which reads **embedded English subtitle tracks**. When a
release ships no fansub track, the glossary for that stretch of the show is empty, and
every name in it is left to Whisper's phonetic guessing plus an LLM repair pass that has
no reference spellings to check against.

`glossary_verify.py` cannot close the gap. `verify()` runs over `pending_terms(gloss)` —
terms *already in* the glossary. It corrects spellings; it has no path to add a name that
was never mined. So the glossary records `wiki: https://onepiece.fandom.com/api.php`,
which knows every character in the series, and never asks it about a name it doesn't
already have.

### Measured evidence (2026-08-19)

One Pace Season 29 (Fishman Island) and Season 30 (Punk Hazard) ship **no non-Dubtitles
subtitle track** — 0/12 episodes sampled. Seasons 01/15/25 ship full
`English|Signs and Songs|CC` sets. The glossary's 83 names are consequently all early-arc
(Luffy, Zoro, Nami, Shanks, Garp); `Shirahoshi`, `Hody`, `Decken` and `Neptune` are absent.

Across the 45 episodes of those two seasons, the pipeline's own transcripts contain:

| token | count | correct? |
|---|---|---|
| Shirahoshi | 56 | yes |
| Jinbei | 61 | dub-vs-Viz variant |
| Neptune | 40 | yes |
| **Deccan** | **21** | **no** |
| Vanderdecken | 16 | unspaced |
| **Decken** | **8** | **yes** |
| Fukaboshi | 6 | yes |

Two facts follow, and they shape the whole design:

1. **Confidence does not separate right from wrong.** In S29E08 the botched `Syrahose`
   scores `avg_logprob -0.065`; the correct `Shirahoshi` scores `-0.173`. No threshold
   can split them.
2. **Frequency alone does not either.** `Deccan` (wrong) beats `Decken` (right) 21 to 8
   across the whole arc. Frequency can propose a *cluster*; only the wiki can pick the
   right member of it.

## Goals

- Acquire proper nouns for a show whose releases carry no mineable subtitle track.
- Emit deterministic `hard_fixes` so name correction happens before any LLM sees the line,
  independent of which repair model is configured.
- Never invent a spelling. Every canonical string must come from the show's wiki.
- Degrade to a no-op on any wiki/LLM failure, matching `glossary_verify`'s existing
  resilience contract.

## Non-goals

- Re-transcription. `conf.json` text is already glossary-corrected, but correction is a
  text-to-text mapping, so re-applying an improved glossary fixes names with no GPU. The
  separate benefit of a better Whisper `initial_prompt` requires re-transcribing and is
  explicitly out of scope here.
- Replacing `mine_glossary.py`. Where a fansub track exists it remains the better source:
  it is human-authored and not our own output.
- A repair-model change. Tracked separately; this stage is model-independent by design.
- Stripping embedded tracks. The mux already replaces the old `Dubtitles` track in the
  same pass that adds the new one.

## Approach: wiki-first, transcript-filtered

The wiki owns the candidate list and every canonical string. The transcript decides only
*which* wiki entities are worth asking about. Our own errors can raise a question; they
can never become an answer.

This inverts the join direction of the obvious design (cluster our transcripts, ask the
wiki what each cluster is). Inverting it buys four things:

- a candidate can never be a non-name, because every candidate is a real wiki article;
- no deny-list maintenance (the arc's most frequent capitalised tokens include `What` 459,
  `Those` 52, `Surrender` 22);
- correct multi-word spacing, because the canonical title carries it;
- structurally impossible to emit a spelling the wiki does not have.

Its one weakness — blindness to a name absent from the wiki — is acceptable for anime, and
is backstopped by flagging high-frequency clusters that matched nothing.

### Localised names (Ash / Satoshi)

A dub that renames a character outright is a real case: Pokémon's `Satoshi` is `Ash` in
English, and no phonetic distance connects them. Two things handle it:

1. **English fandoms title pages with the dub name.** `pokemon.fandom.com` titles the page
   `Ash Ketchum`, not `Satoshi`. Title matching works unmodified.
2. **Full-text search bridges a romaji-titled wiki.** `list=search` for `Kasumi` returns
   `Misty (anime)`. That is tier B below.

A localised rename that matches nothing produces *no* correction — a miss, never a
corruption. That is the correct failure direction.

## Architecture

New module `glossary_acquire.py`, run per show, four stages.

### 1. Harvest

Walk the show's `<stem>.dubtitles.conf.json` files (falling back to
`<stem>.eng.dubtitles.srt` where the conf is gone), counting capitalised tokens and
recording which ever appear mid-sentence. Reuses `mine_glossary.mine_text()`'s counting
logic against a different source.

**This is the one place the acquisition stage reads our own output**, and it is deliberate.
`tools/recover_dub_srt.py` already sets this precedent and states the condition under which
it is safe: nothing read here is treated as a fansub reference. The transcript contributes
frequency evidence only.

### 2. Score against titles (**[v2]** replaces phonetic bucketing)

Every harvested token is scored directly against every normalised wiki title. Clusters are
not built up front; they *emerge* as the set of tokens that resolve to the same canonical.

**[v2] The original design bucketed tokens by exact metaphone key and compared only within
a bucket. Measurement killed it** — metaphone is built for English phonotactics and splits
precisely the Japanese romanisation variance this feature exists to fix:

| variant | metaphone | Jaro-Winkler vs canonical |
|---|---|---|
| Shirahoshi | `XRHX` | — |
| Syrahose | `SRHS` | 0.755 |
| Hirohoshi | `HRHX` | 0.855 |
| Decken | `TKN` | — |
| Deccan | `TKKN` | 0.844 |

Both motivating cases land in different buckets, so an exact-key gate would discard them
while still passing the easy cases (`Kinemon`/`Kin'emon`/`Kinnemon` all share `KNMN`;
`Brook`/`Brooke` share `BRK`). The mistake was using a phonetic key as a **gate** rather
than as one **signal**.

Scoring instead uses Jaro-Winkler as primary, with a metaphone/soundex agreement as a
confidence bonus, never a precondition. Comparison is done on a *reduced* form — lowercased,
apostrophes/hyphens/spaces removed — which is what lets the token `Vanderdecken` match the
title `Van der Decken` exactly, recovering the correct spacing from the title.

Cost is trivial: ~400 candidate tokens x 8,114 titles is a few million string comparisons,
seconds in pure Python, so no bucketing is needed for performance either.

### 3. Match

Match harvested tokens against the cached wiki title index from
`glossary_verify.fetch_titles()` (8,114 main-namespace articles for the One Piece wiki).
Tokens resolving to the same title form a cluster.

**Titles are normalised before any comparison or emission:** strip parenthetical
disambiguators and `/Subpage` paths. `Misty (anime)` normalises to `Misty`;
`Ash Ketchum/Sun & Moon` to `Ash Ketchum`. Skipping this would write a `hard_fix` mapping
every mention of Misty to the literal string `Misty (anime)`.

- **Tier A — phonetic title match.** Deterministic, no LLM, covers the common case.
- **Tier B — full-text search.** For a cluster above the frequency floor that matched no
  title, `list=search` on its dominant variant, then the existing
  `glossary_verify.adjudicate()` picks the entity and prefers the dub spelling.

### 4. Apply

Write `hard_fixes` mapping **every** variant in the cluster to the canonical form, so
`glossary.correct()` fixes them deterministically. Anything failing the safety rules goes
to `flagged` with a reason, never applied.

## Safety rules

A `hard_fix` is emitted only when all four hold. These are derived from real failures in
the Punk Hazard data, not from caution in the abstract.

1. **Wiki-sourced canonical.** The canonical string is a normalised wiki title.

2. **No expansion.** Variant and canonical must be within a tight phonetic + edit distance,
   and a canonical that merely *contains* the variant is not a match. Punk Hazard says
   `Warlords` 10 times; the wiki title is `Seven Warlords of the Sea`. Rewriting the word
   into the phrase would corrupt dialogue.

3. **Dominance, measured with a small-count-aware estimator.** The discriminator is how
   lopsided the split is: `Syrahose` (2) against `Shirahoshi` (56) is 28:1 and plainly a
   mis-hearing; `Smokey` (16) against `Smoker` (21) is 1.3:1 and both are correct
   (`Smokey` is the nickname the dub uses). Neither the wiki nor raw frequency provides
   this signal.

   **[v2] A bare ratio is the wrong estimator at small counts** — 3-vs-0 and 60-vs-0 both
   read as "infinity", and 5-vs-1 clears a 5:1 bar on almost no evidence. Use the **Wilson
   score lower bound** on the canonical's share of the cluster at 95% confidence, and
   require it to exceed `ACQUIRE_MIN_SHARE` (default 0.80). Wilson penalises small samples
   automatically: 5-vs-1 gives a lower bound near 0.42 and is held back, while 56-vs-2
   gives ~0.90 and applies. A canonical that never appears at all is still auto-applied,
   since there is no competing spelling to be wrong about.

4. **Frequency floor.** A cluster must reach `ACQUIRE_MIN_COUNT` (default 3, matching
   `MINE_MIN_COUNT`) and appear mid-sentence at least once.

Everything else is `flagged`. Never silently apply an uncertain correction — the same rule
`glossary-wiki-verify` already commits to.

## Data contract

No schema break; old glossaries load unchanged.

- `hard_fixes` — existing key. Gains `{variant: canonical}` entries.
- `flagged` — existing key. Gains entries with a reason
  (`no-wiki-match`, `share-too-close`, `would-expand`, `below-similarity`).
- `acquired` — **new**, a list mirroring `verified`, so re-runs skip settled clusters.

**Dependency on existing substitution semantics.** `glossary.correct()` applies
`hard_fixes` per whitespace-split token (`_fix_token`), and phrase fixes under `\b`
word boundaries — it is *not* a naive substring replace. This design relies on that: a
fix for `Hoshi` must never fire inside `Shirahoshi`. A regression test pins the behaviour
so a future refactor of `correct()` cannot silently turn these fixes into substring edits.
- Wiki cache — reuses `/config/wiki_cache/<show>.json` unchanged.

Env: `ACQUIRE_MIN_COUNT` (default 3), `ACQUIRE_MIN_SHARE` (default 0.80),
`ACQUIRE_MIN_SIM` (Jaro-Winkler floor, default 0.88), `GLOSSARY_DIR` (existing).

## Failure modes

| Case | Behaviour |
|---|---|
| Wiki unresolvable / down | No-op, nothing applied, logged. Matches `verify()`. |
| LLM unreachable (tier B) | Tier A results still apply; tier B clusters go to `flagged`. |
| Cluster matches no title | `flagged` as `no-wiki-match` — the review queue for dub-only names. |
| Two clusters map to one canonical | Merge; emit fixes for the union of variants. |
| Show has no `conf.json` or sidecars | Nothing to harvest; no-op. |
| Canonical equals variant | No-op, not written as a fix. |

## Testing

Unit tests use fixture glossaries and a stubbed wiki/LLM, so CI needs no network and no
GPU — the pattern `glossary_verify`'s tests already use.

- Normalisation strips `(anime)` and `/Subpage`.
- Clustering groups `{Shirahoshi, Syrahose, Hirohoshi}` and does not merge unrelated names.
- Rule 2 rejects `Warlords` → `Seven Warlords of the Sea`.
- Rule 3 applies `Syrahose` → `Shirahoshi` (56-vs-2) and rejects `Smokey` → `Smoker`
  (21-vs-16); a 5-vs-1 split is held back by the Wilson bound despite clearing 5:1.
- **[v2]** Scoring groups `Syrahose`/`Hirohoshi` with `Shirahoshi` and `Deccan` with
  `Decken` — the cases exact metaphone bucketing dropped.
- **[v2]** A `hard_fix` for a short variant never fires inside a longer token.
- A consistent mis-hearing with no correct form present (`Brooke`, canonical `Brook`) is
  applied.
- Wiki failure and LLM failure are each a no-op, not a crash.

## Verification plan

`--dry-run` is the default; `--apply` writes. The dry run prints every proposed fix with
both counts, the similarity score and the Wilson lower bound, so a human can audit the
decision rather than only the result.

**First real run: One Pace Season 30 (Punk Hazard, 22 episodes)** — chosen because it has
no fansub track, its glossary is starved, and its transcripts contain every failure mode
at once.

Acceptance:

| Cluster | Counts | Required behaviour |
|---|---|---|
| `Kinemon` | 12 | applied → `Kin'emon` |
| `Brooke` | 9 | applied → `Brook` |
| `Smokey` / `Smoker` | 16 / 21 | **not** applied (Wilson bound far below 0.80) |
| `Warlords` | 10 | **not** applied (would expand) |
| `Surrender`, `Maybe`, `Hurry`, `Listen` | 10–22 | ignored (no wiki match) |

## Rollout

1. Land the module + tests behind `--dry-run`.
2. Dry-run Punk Hazard; confirm the table above.
3. `--apply` to the One Pace glossary.
4. Re-correct pass over existing `conf.json` files (separate work): re-apply the glossary,
   re-repair where confidences survive, re-mux. No Whisper.

**Ordering hazard, recorded here because it is easy to get wrong:** 103 of 696 stamped
episodes have neither a `conf.json` nor a sidecar — their only surviving copy is the muxed
`Dubtitles` track (Pokémon 41, Vending Machine 17, Slime 14, Fire Force 13, Trigun Stampede
7, JJK 6, Speed Racer 5). Any bulk operation that removes embedded tracks must run
`tools/recover_dub_srt.py --apply` first, or those episodes require full re-transcription.

## Panel review (2026-08-19)

Consulted via `salyut`. Only Cloudflare (llama-3.3-70b) and a truncated Gemini response
returned; Cerebras/GLM/Groq/GitHub/llama70b were rate-limited or erroring, so this was a
two-voice review rather than the usual panel — weight it accordingly.

**Acted on:**

- *"What breaks phonetic clustering for Japanese names transliterated by an English ASR?"*
  prompted the measurement that killed metaphone bucketing (see **[v2]** in *Score against
  titles*). This was the single most valuable outcome — the original design would have
  silently failed on both motivating cases.
- *"With low counts the ratio is heavily influenced by random chance; use a binomial test"*
  → R3 now uses a Wilson score lower bound.
- *"Substituting inside a larger word would corrupt output"* → checked, not applicable
  (`correct()` is token-level), but now recorded as an explicit dependency plus a
  regression test.

**Considered and rejected:**

- *"The wiki itself may contain a fan-created page for the wrong spelling."* Possible in
  principle, but a Fandom article titled with an ASR mis-hearing is vanishingly unlikely,
  and R2's distance bound plus R3's dominance test would both have to fail simultaneously.
  Not worth engineering against.
- *"Add a dedicated NER component."* The wiki title index already *is* the entity list, and
  a better one than a general-purpose NER would produce for a fictional universe.
- *"Add a feedback loop so the pipeline learns from its own errors."* This is precisely the
  self-reinforcement the design is built to avoid.

**Unresolved:** the self-read question (panel Q1) got no substantive answer from either
model. The claim that the wiki gate makes self-reading safe is argued in *Approach* but
has not been adversarially stress-tested. Worth revisiting if a future run produces a
wrong `hard_fix`.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
