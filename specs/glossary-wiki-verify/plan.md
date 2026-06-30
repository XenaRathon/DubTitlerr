# Plan — Glossary wiki-verifier

> After spec approval. Approving this triggers kickoff (branch).

## Branch and delivery

- **Branch:** `feat/glossary-wiki-verify` (base: `main`).
- **PR slicing:** single, direct-merge to main (build flow).

## Technical approach

New importable module `glossary_verify.py` (+ CLI), mirroring the project's pure-core pattern.
The deterministic, testable core — candidate pre-match, apply-high-confidence/flag, incremental
skip via `verified`, schema preservation, prompt-builders — is unit-tested without web/LLM. The
two I/O edges (Fandom HTTP via stdlib `urllib`; LLM adjudication via Ollama, same client style as
`repair.py`) are isolated behind thin functions, stubbed in tests and validated by the on-server
integration run. `gen_loop` calls it after `mine_glossary` (resilient: timeout + ignore failure).
Test-first.

## Affected files (by layer)

| Layer | File | Change |
|---|---|---|
| Core (new) | `glossary_verify.py` | `resolve_wiki`, `fetch_titles` (cached), `candidates` (pure top-K), `build_adjudication_prompt`, `adjudicate` (LLM), `apply_results` (pure), `verify` (orchestrate), CLI. |
| Orchestration | `gen_loop.sh` | After mine, run the verifier on the show glossary with a timeout; never fail the sweep. |
| Image | `Dockerfile.builder` | `COPY glossary_verify.py` (stdlib only). |
| Tests (new) | `tests/test_glossary_verify.py` | candidates, apply_results (apply/flag/dub), incremental skip, schema round-trip, prompt builder. |

## Risks and mitigation

| Risk | Mitigation |
|---|---|
| Wrong wiki auto-resolved | LLM-picked from Fandom search + per-glossary `wiki` override (authoritative); flag-not-apply when unresolved. |
| Fandom rate limits | Cache the page-title index per show; top-K batching; small delay if needed. |
| Local 8B mis-adjudicates | Confidence gate (only high-confidence auto-applies); low-conf flagged for review; `VERIFY_MODEL` escape hatch. |
| dub-vs-manga | LLM instructed dub-first; `dub_note` recorded; flag when unsure (≥ today's state). |
| Stalling the GPU loop | Hook is timeout-bounded + failure-swallowed; incremental cache makes steady-state a near-no-op. |
| Corrupting a good glossary | Pure `apply_results` only touches matched terms; preserves unknown JSON fields; unit-tested; idempotent. |

## Rollback and reversibility

- Revert PR + rebuild image. Glossary edits are data in git/`/config`; `flagged`/`verified` are
  additive. A bad auto-apply is correctable by hand (and flagged terms were never auto-changed).

## Testing strategy

- **Unit (pytest), the core:**
  | Rule | Assertion |
  |---|---|
  | `candidates` top-K | nearest titles by similarity; cutoff floors junk |
  | apply high-confidence | corrected name written; `verified` updated; prompt regen |
  | flag low/no-match | term unchanged, added to `flagged` with reason |
  | incremental | terms in `verified` are skipped |
  | dub preference | when adjudication returns a dub form, that's applied |
  | schema round-trip | unknown fields (e.g. curated hard_fixes) preserved |
  | prompt builder | includes the term + candidate titles + dub-first instruction |
- **Integration (on server):** run the verifier against the live Fandom wiki + qwen3:8b — (a)
  re-derive the One Pace glossary and confirm it lands the same canon (Spandam, Enies Lobby,
  Water 7); (b) a fresh show (e.g. Reborn / JoJo) gets correct character spellings; eyeball `flagged`.
- Coverage ≥90% on the pure core of `glossary_verify.py`.

## Observability

- Per-run report: resolved wiki, terms checked / applied / flagged / unmatched; logged by the
  gen_loop hook so a sweep shows what verification did.
