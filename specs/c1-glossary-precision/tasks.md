# Tasks — C1: Glossary precision + recall

> Persistent memory between sessions. New session: read `spec.md` + this file, check out
> the branch below first. Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `feat/c1-glossary-precision` (base: `main`)

Rules: each task ≤ ~1h, dependency-ordered, verifiable. Test-first. Gates green
(ruff · pytest) before `[x]`. 1 task = 1 conventional commit.

## Tasks

- [x] **T1 — Scaffold.** `glossary.py` skeleton (`load`, `correct`, `name_suspect`,
      `is_english` signatures + constants), `common_words.txt` fallback (seed with the known
      offenders + common English), `tests/test_glossary.py`.
      — done when: ruff clean, pytest collects.

- [x] **T2 — `is_english` gate.** Load wordlist from `WORDLIST_PATH` ∪ bundled
      `common_words.txt`; `is_english(token)` case-insensitive. — done when: gate unit tests pass.

- [x] **T3 — `correct()` tiered.** phrase hard_fixes (word-boundary, case-insensitive) →
      exact-token hard_fixes → guarded fuzzy (skip real English words; length-scaled cutoff
      ~0.95 short; reject one-char add/drop). — done when: false-positive + hard_fix + phrase +
      guarded-fuzzy fire/refuse + phrase-before-token tests pass.

- [ ] **T4 — `name_suspect(text, gloss)`.** Flag a line with a token that near-matches a
      glossary name but isn't exact, or a capitalized non-glossary proper-noun-like token.
      — done when: flags suspect lines, ignores clean lines (unit tests).

- [ ] **T5 — Wire into `generate.py`.** Replace inline `fix_word`/`correct` with
      `glossary.correct`; load the glossary once. Keep A1's per-line application + wrap.
      — done when: ruff clean, full pytest green, `generate.py` ast-parses.

- [ ] **T6 — `repair.py` enhancements.** Targets = mid-confidence band OR `name_suspect`;
      inject glossary (names + phrases) into the prompt; glossary-only context when no fansub
      anchor (don't skip); `REPAIR_MODEL` from env. — done when: target-selection + prompt-build
      unit tests pass (LLM call stubbed).

- [ ] **T7 — `Dockerfile.builder`.** `apt-get install wamerican`; `COPY glossary.py
      common_words.txt`. — done when: grep shows both + the apt line.

- [ ] **T8 — Glossary curation (USER-GATED).** Draft cleaned + expanded `One Pace.json`
      (drop fragments, add canon + hard_fixes), **present to user for review/edits, apply only
      after approval**, then commit. — done when: user-approved glossary committed.

## Closing (the *close* phase of `dev-lifecycle` — always keep last)

- [ ] **Model bake-off (offline):** `tools/bakeoff.py` drives Ollama (`qwen3:8b`,
      `qwen3.5:4b`, `qwen2.5:7b`) on real S19E16 sample lines + glossary + fansub refs; compare
      correction quality + latency; user confirms; set `REPAIR_MODEL` in compose/.env.
      — done when: winner locked.
- [ ] **Integration verify:** run a repair pass on a sample (offline harness / live Ollama),
      confirm the S19E16 name errors are fixed and no over-correction. — done when: eyeball-pass.
- [ ] CI: extend ruff/pytest scope to `glossary.py` — done when: pipeline green.
- [ ] Push `feat/c1-glossary-precision`; merge to `main` (no PR, per the build's flow).
      — done when: merged + pushed.

## Done
<move [x] tasks here, preserving the done criterion>
