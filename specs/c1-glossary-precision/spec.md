# Spec — C1: Glossary precision + recall (name correction)

> Step C1 of the DubTitlerr quality build (A1 done). Grilled on top of the brainstorm
> diagnosis. North-star: the **definitive** English-dub subtitle — accuracy over cost;
> the user is willing to spend GPU/time for it.

## Context and problem

Name correction is broken in both directions. The blanket fuzzy matcher (`correct()`/
`fix_word`, difflib cutoff 0.86) **over-fires** — it capitalizes/rewrites ordinary words
(`pirates→Pirate`, `along→Arlong`, `frank→Franky`, `work→Works`) because the glossary is
polluted with common-word fragments (`Works`, `Seven`, `Line`, `Fruit`, `Pose`, `Pirate`…)
split out of multi-word names, and the 0.86 cutoff is too loose for short words. It also
**under-fires** — far mishears (`spondum→Spandam`) and phrases (`Eddie's Lobby→Enies Lobby`,
`cutting flam→Cutty Flam`) never match. Mining (`mine_glossary.py`) can't help the 250 mp4
One Pace episodes (no embedded subs), so for One Pace the curated glossary is the lever.

## Acceptance criteria (verifiable)

- [ ] **No false-capitalization of real English words:** `pirates` stays `pirates`, `along`
      stays `along`, `frank`/`work`/`seven`/`line`/`fruit` are never rewritten to a name
      fragment. (Regression test + check on real S19E16 output.)
- [ ] **Known mishears fixed deterministically** via `hard_fixes`: `spondum→Spandam`,
      `eddie's lobby`/`in his lobby→Enies Lobby`, `cutting flam→Cutty Flam`, `frankie→Franky`,
      `cypherpull→CP9`/Cypher Pol (final list set during glossary review).
- [ ] **Guarded fuzzy never rewrites a token that is a real English word**, requires a
      length-scaled cutoff (~0.95 for short tokens), and never makes a one-char add/drop.
- [ ] **LLM repair runs on mid-confidence-and-lower AND name-suspect lines** (broader than
      today's low-only gate); uses the **time-aligned embedded fansub line as a reference
      anchor when present**, glossary-only context otherwise; preserves the dub's wording
      (never copies the fansub verbatim); the **glossary is in the prompt**.
- [ ] **Repair model locked by an A/B/C bake-off** (`qwen3:8b` vs `qwen3.5:4b` vs
      `qwen2.5:7b`) on real sample lines from S19E16, judged for correction quality.
- [ ] **`One Pace.json` cleaned + expanded and approved by the user before commit** (no
      common-word fragments; multi-word names handled as phrases / hard_fixes).
- [ ] Cross-show isolation preserved (correction is opt-in per `GLOSSARY_FILE`); clean lines
      pass through unchanged.

## Out of scope (explicit)

- **Community glossary repo** (TCM-blueprints-style sharing/submission) — its own future
  spec after the quality build. See `## Future`.
- B1 hallucination gate; D1 mux/fonts.
- Changing the `mine_glossary.py` mining algorithm (only its mp4 starvation is noted; fixed
  here by curated seeding, not by re-mining).

## Data contracts

- **Glossary JSON** (`/config/glossaries/<Show>.json`), cleaned shape:
  - `names`: single-token canonical proper nouns only (no common-word fragments).
  - `phrases`: multi-word canonical names (new; for phrase detection/prompting).
  - `hard_fixes`: `{ "misspelling or phrase" (lowercased): "Canonical" }` — exact token
    AND multi-word phrase keys, applied case-insensitively at word boundaries.
  - `initial_prompt`: curated whisper bias prompt (unchanged mechanism).
- **English wordlist:** a static list bundled into the image (no new pip dep); used by the
  guarded fuzzy to refuse rewriting real words. Source baked at build time.
- **`conf.json`** (from A1): per-card `avg_logprob`, `no_speech_prob`, `text` — repair reads
  these to pick targets.
- **LLM prompt inputs:** ASR line, optional fansub reference line, the show's glossary
  (names + phrases + canonical hard-fix targets). Output: corrected dub line only.

## Components / changes

1. **`generate.py` deterministic correction (rewrite `correct`/`fix_word`):** tiered —
   (a) phrase hard_fixes (multi-word, word-boundary), (b) exact-token hard_fixes,
   (c) guarded fuzzy: skip if token is a real English word; cutoff scales with length
   (short → ~0.95); reject one-char add/drop edits. No common-word fragments to match against.
2. **English-word gate:** bundled wordlist loaded once; `is_english(token)` helper.
3. **`repair.py` (LLM) enhancements:** broaden target selection to mid-confidence
   (`avg_logprob` threshold raised) + name-suspect lines (token near a glossary name but not
   exact, or capitalized non-glossary token); inject the glossary into the prompt; run with a
   glossary-only context when no fansub anchor exists (don't skip); model from env (locked
   by the bake-off).
4. **`One Pace.json` curation:** remove fragments, add canon + hard_fixes — drafted, shown to
   the user, approved, then committed.
5. **Bake-off harness:** offline, drives Ollama on the PC with real S19E16 sample lines
   (using the captured raw data + fansub refs) across the three models; results judged →
   lock `REPAIR_MODEL`.

## Edge cases and failure modes

| Case | Expected behavior |
|---|---|
| Token is a real English word that's also a name (e.g. "Robin", "Law", "Brook") | hard_fixes/exact-name still allowed; guarded fuzzy refuses (exact match needs no fuzz). Names that are English words are corrected only via exact glossary/hard_fixes, never fuzzed onto. |
| mp4 episode (no embedded fansub) | LLM repair runs with glossary-only context; deterministic layer still applies. |
| LLM unreachable / Ollama down | Repair leaves the deterministic text untouched (graceful); logged. |
| LLM returns verbatim fansub or wildly different length | Rejected by the existing length-ratio guard; keep ASR text. |
| Phrase hard_fix overlaps a token hard_fix | Apply phrases first, then tokens, so "Enies Lobby" wins over a stray "lobby". |
| Show with no glossary file | Deterministic layer is a no-op (as today); LLM uses generic prompt. |

## Decisions taken

| Decision | Rejected | Why |
|---|---|---|
| Hybrid: hard_fixes + very guarded fuzzy + heavy LLM lean | Curated-only; fuzzy-only | Max accuracy for the definitive goal; guards kill false positives; LLM covers recall. |
| LLM on mid-confidence-and-lower + name-suspect lines | All lines; low-only | Most of the accuracy gain without LLM-ing every clean line; still broad. |
| A/B/C bake-off (qwen3:8b / qwen3.5:4b / qwen2.5:7b) then lock | Pick one blind | Definitive answer on the user's actual 2070/Ollama. |
| Fansub anchor when present, glossary-only fallback | Glossary-only everywhere | Fansub is the strongest available name/spelling signal on mkv. |
| Glossary show-before-apply | Auto-curate | User is the One Piece authority; catch canon errors pre-commit. |

## Constraints

- Deterministic layer: stdlib only, runs in the subgen image (bundle the wordlist, no pip dep).
- LLM repair: Ollama on the PC (`192.168.1.196:11434`), model fits the 8 GB 2070.
- Per-show opt-in correction; no cross-show leakage.

## Open questions (risks)

- [ ] Exact mid-confidence threshold + name-suspect heuristic tuned during implementation
      against real conf.json data (low risk; measurable on S19E16).
- [ ] Bundled wordlist choice (size vs false-negatives) decided in plan.

## Future (logged, not this spec)

- **Community glossary repo** (TCM-blueprints style): public repo of per-show glossaries;
  DubTitlerr fetches/updates on startup and offers a PR-based submission of instance-mined
  glossaries, keyed by show + tvdb-id, with dedup/merge. Own spec after A1–D1.
