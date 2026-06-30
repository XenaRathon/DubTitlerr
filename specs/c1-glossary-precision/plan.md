# Plan — C1: Glossary precision + recall

> Written after `spec.md` approval. Approving this plan triggers kickoff (branch).

## Branch and delivery

- **Branch:** `feat/c1-glossary-precision` (base: `main`).
- **PR slicing:** single PR. The model bake-off is an internal task that only sets a
  default (`REPAIR_MODEL`); it doesn't block the code.

## Technical approach

Extract the correction logic into a new pure-ish module `glossary.py` (mirrors `reflow.py`):
load a glossary, expose `correct(text)` (tiered: phrase hard_fixes → exact hard_fixes →
guarded fuzzy with an English-word gate) and `name_suspect(text)` (for repair targeting).
`generate.py` and `repair.py` both import it — one source of correction truth, fully unit
testable without CUDA/LLM. The English-word gate loads a wordlist from `WORDLIST_PATH`
(the apt `wamerican` dict in the image) with a small bundled fallback for tests. `repair.py`
broadens its target gate and injects the glossary into the LLM prompt; the model is chosen by
an offline bake-off. Built test-first.

## Affected files (by layer)

| Layer | File | Change |
|---|---|---|
| Core (new) | `glossary.py` | `load(path)`; `correct(text, gloss)` tiered + guarded fuzzy w/ English gate (no one-char edits, length-scaled cutoff, skip real words); `name_suspect(text, gloss)`; `is_english(tok)`. Stdlib only. |
| Data (new) | `common_words.txt` | Compact common-English fallback wordlist (covers along/frank/work/seven/line/pirate…); production augments from `WORDLIST_PATH`. |
| Orchestration | `generate.py` | Replace inline `fix_word`/`correct` with `glossary.correct` (still per-line, preserving A1's wrap). Remove the polluted-glossary behavior. |
| LLM repair | `repair.py` | Targets = mid-confidence (raise `LOGPROB_MIN`/add a mid band) OR `glossary.name_suspect`; inject glossary names/phrases into the prompt; run glossary-only when no fansub anchor (don't skip); `REPAIR_MODEL` from env. |
| Glossary | `glossaries/One Pace.json` | Cleaned (drop fragments) + expanded (canon + hard_fixes). **Drafted, shown to user, approved, then committed.** |
| Image | `Dockerfile.builder` | `apt-get install wamerican`; `COPY glossary.py common_words.txt`. |
| Tests (new) | `tests/test_glossary.py` | Deterministic correction + gate + name_suspect (table-driven). |
| Tools (new) | `tools/bakeoff.py` | Offline: drive Ollama (3 models) on real S19E16 sample lines w/ glossary + fansub refs; emit a comparison for judging. |

## Risks and mitigation

| Risk | Mitigation |
|---|---|
| Wordlist misses a word → a real word still gets fuzzed | Comprehensive `wamerican` in prod; guarded fuzzy also needs length-scaled high cutoff + no one-char edits, so misses are rare and small. Regression tests on the known offenders. |
| A canonical name that's also an English word (Robin, Law, Brook) | Names are corrected only via exact glossary/hard_fixes; the fuzzy never *targets* a real word, so it won't mangle them. Tested. |
| Glossary canon errors | User reviews `One Pace.json` before commit (acceptance criterion). |
| Ollama down / slow | Repair degrades gracefully (keep deterministic text); broadened scope is bounded by the mid-confidence gate. |
| Bake-off subjectivity | Judge on the concrete S19E16 error set (names fixed, no over-correction); user confirms the winner. |

## Rollback and reversibility

- Fully reversible: revert the PR + rebuild image. Glossary changes are data; the old
  `One Pace.json` is in git history. No schema/migration.

## Testing strategy

- **Unit (pytest), the bulk — `glossary.py`:**
  | Rule | Assertion |
  |---|---|
  | False positives gone | `pirates`→`pirates`, `along`→`along`, `frank`/`work`/`seven` unchanged |
  | Exact hard_fix | `spondum`→`Spandam`, `frankie`→`Franky` |
  | Phrase hard_fix | `eddie's lobby`→`Enies Lobby` (word-boundary, case-insensitive) |
  | Guarded fuzzy fires | a non-English near-miss (`Spandm`→`Spandam`) at high cutoff |
  | Guarded fuzzy refuses | real English word never rewritten; no one-char add/drop |
  | name_suspect | flags a line with a near-glossary token; clean line not flagged |
  | Phrase-before-token order | `Enies Lobby` wins over stray `lobby` |
  | No glossary | `correct` is a no-op |
- **Unit — `repair.py` target selection:** mid-conf + name_suspect picks the right rows;
  prompt includes the glossary; glossary-only path when no anchor (LLM call stubbed).
- **Integration (offline, real Ollama):** bake-off over the 3 models on S19E16 samples →
  pick `REPAIR_MODEL`. Then a full repair pass on a sample to eyeball.
- Coverage ≥90% on `glossary.py`.

## Observability / performance (LLM)

- Repair logs per-episode targets/repaired counts (exists) + the chosen model.
- Mid-confidence gate bounds LLM calls; bake-off records latency per model so the
  accuracy/throughput trade is explicit when locking `REPAIR_MODEL`.
