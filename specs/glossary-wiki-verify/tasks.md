# Tasks — Glossary wiki-verifier

> Persistent memory. New session: read `spec.md` + this file, check out the branch first.
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `feat/glossary-wiki-verify` (base: `main`)

Rules: ≤~1h each, dependency-ordered, verifiable, test-first, gates green (ruff · pytest),
1 task = 1 conventional commit.

## Tasks

- [x] **T1 — Scaffold.** `glossary_verify.py` skeleton (signatures + constants: top-K, cutoffs,
      `VERIFY_MODEL`, cache dir) + `tests/test_glossary_verify.py`. — done when: ruff clean, pytest collects.
- [x] **T2 — `candidates`.** deterministic top-K title pre-match by similarity (cutoff floors junk).
      — done when: top-K + cutoff unit tests pass.
- [x] **T3 — `apply_results`.** given per-term adjudications, write high-confidence corrections to
      names/phrases, add low/no-match to `flagged`, mark `verified`, regen `initial_prompt`; prefer
      the dub form; preserve unknown JSON fields. — done when: apply/flag/dub/preserve tests pass.
- [x] **T4 — incremental skip.** terms already in `verified` are not re-checked. — done when: skip test passes.
- [x] **T5 — `build_adjudication_prompt`.** term + candidate titles + dub-first instruction + JSON
      output contract. — done when: prompt-content unit tests pass.
- [x] **T6 — wiki I/O (`resolve_wiki`, `fetch_titles`).** Fandom search-resolve + cached allpages
      via stdlib urllib; URL/parse logic unit-tested with stubbed HTTP. — done when: url/parse tests pass.
- [ ] **T7 — `adjudicate` + `verify` orchestration + CLI.** wire pre-match→LLM→apply; resilient
      (timeout/failure → no-op); `python3 glossary_verify.py <show.json> [--wiki] [--force]`.
      — done when: ruff clean, full pytest green, module imports.
- [ ] **T8 — `gen_loop.sh` hook.** run verifier after mine (timeout, swallow failure). — done when: grep shows it.
- [ ] **T9 — `Dockerfile.builder` COPY `glossary_verify.py`.** — done when: grep shows it.

## Closing (the *close* phase — always keep last)

- [ ] **Integration (server):** verifier vs live Fandom + qwen3:8b — re-derive One Pace canon
      (Spandam/Enies Lobby/Water 7) + a fresh show (Reborn/JoJo) gets correct names; eyeball `flagged`.
- [ ] CI: add `glossary_verify.py` to the ruff scope — done when: pipeline green.
- [ ] Push `feat/glossary-wiki-verify`; merge to `main`. — done when: merged + pushed.

## Done
<move [x] tasks here, preserving the done criterion>
