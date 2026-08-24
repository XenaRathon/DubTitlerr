# Glossary integrity: stop the verifier deleting the terms it verifies

**Status:** design, awaiting review
**Found:** 2026-08-21, while diffing the live One Pace glossary against the repo seed
**Blocks:** the v4 regeneration (183 episodes from S30) — every episode would bake these in
**Related:** `docs/superpowers/plans/2026-08-22-observability-and-dead-path-cleanup.md`
(attack-name follow-up item), commit `4fe69c7` (the snapshot this was found in)

---

## 1. The runtime data model, measured

Reviewers should check this table first — every defect below is a consequence of it.
`glossary.load_dict()` (glossary.py:62-76) reads exactly five keys. Everything else in the
file is bookkeeping with **zero runtime effect**.

| key                                        | read by                                                                                                                             | what it actually does                                                      |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `names`                                    | `glossary.correct()` → `_fix_token()` (glossary.py:124-147); `name_suspect()` (164-180); `repair._glossary_terms()` (repair.py:120) | deterministic **single-token** correction: exact, guarded fuzzy, Metaphone |
| `phrases`                                  | `repair._glossary_terms()` (repair.py:120) **only**                                                                                 | term list in the repair LLM prompt                                         |
| `hard_fixes`                               | `correct()` — split into token vs phrase maps by `load_dict()`                                                                      | deterministic exact rewrite                                                |
| `initial_prompt`                           | whisper decoder bias                                                                                                                | biases **every** transcription                                             |
| `show`                                     | prompt assembly                                                                                                                     | —                                                                          |
| `verified`, `known`, `flagged`, `acquired` | `glossary_verify` / `glossary_acquire` only                                                                                         | **nothing at runtime**                                                     |

Two consequences that matter:

- A **multi-word** string in `names` can never match in `correct()`. `_TOKEN_RE`
  (glossary.py:96) matches one token; `_fix_token` compares a single token against the list.
  It still reaches the repair LLM via repair.py:120, so it is degraded, not inert.
- Moving a term into `verified` **removes it from service**. Nothing reads that key.

## 2. Three defects

### D1 — `apply_results()` replaces in place instead of adding alongside

`glossary_verify.py:133-140`:

```python
if conf == "high" and canon and canon != term:
    for lst in (names, phrases):
        for i, x in enumerate(lst):
            if x == term:
                lst[i] = canon          # <-- the short form is destroyed
```

The short form is the mishear target the fuzzy and Metaphone tiers need. The long canonical
form is what the repair LLM needs. The code treats them as alternatives; they are both
required, at different tiers.

Measured on the live One Pace glossary: **17 names and 6 phrases** were replaced this way.
All 23 survive in `verified`, which nothing reads, so 10 of 12 sampled bare dub forms are
absent from `names`, `phrases` and `hard_fixes` values alike:

    Doflamingo -> Donquixote Doflamingo    Hancock   -> Boa Hancock
    Kaido      -> Kaidou                   Lucci     -> Rob Lucci
    Alabasta   -> Arabasta                 Raftel    -> Ratel
    Jabra      -> Jabari                   Trafalgar -> Trafalgar Lami
    Rayleigh   -> Silvers Rayleigh         Montblanc -> Mont Blanc
    Straw Hats -> Straw Hat Pirates        Cricket   -> (Mont Blanc Cricket)

`Lucci` and `Jabra` remain in `initial_prompt`, so the decoder is still biased toward them;
the correction tiers are what was lost.

### D2 — the dub-preference is unenforced, and three adjudications are simply wrong

`apply_results`' docstring says "canonical (dub-preferred) spellings", but the preference
lives only in the adjudication prompt. Nothing checks the result. Two failure kinds:

- **Wiki-canon over dub:** `Kaidou` (dub: Kaido), `Arabasta` (dub: Alabasta). Same authority
  mismatch already recorded for techniques — the wiki records Japanese-derived romanisation.
- **Wrong entity:** `Raftel -> Ratel` (a different word entirely), `Trafalgar -> Trafalgar
Lami` (Lami is Law's sister; the bare surname belongs to Law), `Jabra -> Jabari`.

D1 makes D2 destructive rather than merely additive: a wrong adjudication does not sit
beside the right term, it replaces it.

### D3 — ten unverified attack names are live in production

The eleven model-memory attack names were pulled from the working copy on 2026-08-21 after
**0 of 11 wiki-verified**, but the revert never reached the host bind mount. Live now in
both `initial_prompt` and `phrases`:

    Gum-Gum Bazooka, Gatling, Rocket, Balloon, Whip, Axe, Stamp, Storm, Gear Second, Gear Third

Only `Gum-Gum Pistol` is human-confirmed. `Gear Second` is worse than unverified — the dub
says **"Second Gear"** — and `initial_prompt` is the highest-leverage place to be wrong.

## 3. Design

### 3.1 Add, never replace (fixes D1)

`apply_results()` keeps the original term and **adds** the canonical form, routed by shape:

- canonical is one token -> append to `names`
- canonical is multi-word -> append to `phrases`

The original term stays where it was. Both tiers keep what they need, and a bad adjudication
becomes an extra term rather than a deletion.

### 3.2 A changed term escalates instead of auto-applying (fixes D2)

Adding alongside stops D2 destroying data but still admits `Ratel` and `Trafalgar Lami` into
the dictionary. Deterministic guards do not separate them — `Raftel/Ratel` is one indel and
`Trafalgar/Trafalgar Lami` is containment, exactly like the correct cases.

So this follows the project's standing architecture — deterministic, then LLM, then human:

- The adjudicator proposing a canonical **different from an existing term** is not settled.
  Record it to `flagged` with both strings and the `dub_note`, and do not write it into
  `names`/`phrases`.
- Genuinely **new** terms (not already present) with `confidence == "high"` auto-apply as today.
- `glossary_acquire.py --review` already walks `flagged` with evidence; these join that queue.

This is the same rung `unresolved.py` added for repair and punctuation. Rejecting a proposal
is durable information — it stops the next sweep re-proposing it.

### 3.3 Backfill the damage already done

A one-shot repair over the live glossary, run before the v4 regeneration:

1. For every term in `verified` absent from `names`/`phrases`/`hard_fixes` values, restore it
   — single token to `names`, multi-word to `phrases`.
2. Move every multi-word entry currently in `names` to `phrases` (it cannot match in `correct()`).
3. Move the three wrong adjudications (`Ratel`, `Trafalgar Lami`, `Jabari`) and the two
   wiki-over-dub forms (`Kaidou`, `Arabasta`) into `flagged` for review.
4. Delete the ten unconfirmed attack names from `initial_prompt` and `phrases`. Keep
   `Gum-Gum Pistol`.
5. Re-deploy to the host bind mount **and** commit, so the two cannot diverge again.

### 3.4 The invariant that would have caught this

A term promoted to `verified` must remain reachable at runtime. As a test:

> every string in `verified` appears in `names`, `phrases`, `hard_fixes` values, or `flagged`

plus a shape check:

> no multi-word string in `names`

Both are cheap, both fail today on the live file, and both are the "zero activation is not an
error" lesson applied to data instead of counters: the acquisition run reported 129 verified,
105 known, 7 flagged — every counter moved the right way while the dictionary lost 23 terms.

## 4. Out of scope

- Attack/technique names generally — deferred, see the follow-up item in the plan doc.
- Re-adjudicating the other 14 shows' glossaries. They drifted the same way (all are June
  seeds in the repo); One Pace is the one the v4 regeneration is about to consume.

## 5. Testing

| test                                    | asserts                                                                       |
| --------------------------------------- | ----------------------------------------------------------------------------- |
| `apply_results` keeps the original term | `Doflamingo` still in `names` after a high-confidence `Donquixote Doflamingo` |
| canonical routed by shape               | single token -> `names`, multi-word -> `phrases`                              |
| a changed term does not auto-apply      | `Raftel` -> `Ratel` lands in `flagged`, not `names`                           |
| a genuinely new term still auto-applies | unchanged behaviour for the normal path                                       |
| verified-reachability invariant         | every `verified` term reachable at runtime                                    |
| no multi-word entry in `names`          | shape check                                                                   |
| backfill is idempotent                  | running it twice is a no-op                                                   |
