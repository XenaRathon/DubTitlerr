# Spec — Glossary wiki-verifier

> A tool that auto-verifies any glossary's proper-noun spellings against the show's wiki, so a
> freshly-mined glossary (or a stranger's submission to the future community repo) comes out as
> accurate as the hand-tuned One Pace one. Supersedes the manual "wiki-verify glossaries" step.
> Source-of-truth = wiki/publisher per [[feedback_glossary_canon_source]]; prefer the **dub** form.

## Context and problem

C1's One Pace glossary was hand-verified against the One Piece Wiki (Bon Clay not Bon Kurei,
Water 7 not Water Seven). That manual pass doesn't scale: mining auto-builds glossaries for any
show, and the planned community repo will take user submissions for shows nobody curated. Without
verification those are only as good as the mined/submitted spellings. This tool closes that gap
automatically: fetch the show's wiki, match each glossary term to a canonical entity, apply the
correct (dub-preferred) spelling for confident matches, and flag the rest.

## Acceptance criteria (verifiable)

- [ ] Given a glossary + a resolvable wiki, the tool fetches the wiki's main-namespace page index
      (Fandom `allpages`), pre-matches each term to top-K candidate titles by similarity, and an LLM
      picks the canonical entity (or "no match"), preferring the **dub** spelling.
- [ ] **High-confidence** matches are written into the glossary (corrected names/phrases + the
      `initial_prompt` regenerated); **low-confidence / no-match** terms are kept as-is and recorded
      in a `flagged` map for review. (Never silently apply an uncertain correction.)
- [ ] **Incremental + cached:** only un-verified terms are checked (a `verified` set in the glossary);
      the wiki page index is cached per show; re-running is a near-no-op.
- [ ] **Wiki resolution:** auto-resolve via Fandom cross-wiki search on the cleaned title (strip
      `(year)`/`{tvdb-…}`) + LLM pick; a per-glossary `wiki` override field is authoritative when set.
- [ ] **Reusable module + CLI:** a `verify(glossary, ...)` API callable from (a) the mining hook in
      `gen_loop`, (b) a standalone CLI, (c) future community-repo front-ends (auto-submit/web/bot).
- [ ] **Resilient:** wiki/LLM timeout or failure → leave the glossary unchanged, log, never stall the
      GPU loop or crash a sweep.
- [ ] **Local-first:** adjudication uses `qwen3:8b` via Ollama by default (`VERIFY_MODEL` override);
      wiki access via stdlib HTTP — no new runtime deps.
- [ ] Verifiable on real shows: re-deriving the One Pace glossary lands the same canon (Spandam,
      Enies Lobby, Water 7); a fresh JoJo/Reborn glossary gets correct character spellings.

## Out of scope (explicit)

- The **community repo** itself + its contribution front-ends (auto-submit, web form, PR-bot) —
  separate roadmap spec; this tool is the engine they call.
- Translating/También non-Fandom wikis beyond the override field (best-effort).
- Re-verifying on every sweep (only on build/modification of changed terms).

## Data contracts

- **Glossary additions** (`/config/glossaries/<show>.json`):
  - `wiki`: optional override — the wiki's API base or article-path (authoritative when set).
  - `verified`: list of terms already verified (so re-runs skip them).
  - `flagged`: `{term: reason}` for low-confidence / no-match (review queue).
- **Wiki cache:** `/config/wiki_cache/<show>.json` — `{resolved_wiki, fetched_at, titles: [...]}`.
- **Inputs:** the normalized glossary (names/phrases/hard_fixes), the show title, optional `wiki`.
- **Outputs:** the updated glossary (corrected + verified + flagged); a per-run report (applied /
  flagged / unmatched counts).
- **External:** Fandom MediaWiki API (`list=search` for resolution, `list=allpages` ns=0 for the
  index) over HTTPS; Ollama (`VERIFY_MODEL`).

## Components / changes

1. **New `glossary_verify.py`** (importable module + CLI):
   - `resolve_wiki(title, override)` → wiki API base (Fandom search + LLM pick; override wins).
   - `fetch_titles(wiki)` → cached main-namespace page-title list.
   - `candidates(term, titles, k)` → top-K similar titles (deterministic fuzzy; pure, testable).
   - `adjudicate(term, candidates, show)` → `{canonical, confidence, dub_note}` via the LLM (stubbable).
   - `verify(gloss, title, ...)` → orchestrate: skip `verified`, resolve, fetch, per term pre-match
     → adjudicate → apply high-confidence / flag the rest → mark `verified` → regen `initial_prompt`.
   - CLI: `python3 glossary_verify.py "<show.json>" [--wiki URL] [--force]`.
2. **`gen_loop.sh`:** after `mine_glossary.py`, call the verifier on the show's glossary (resilient:
   timeout + ignore failure) before generate.
3. **`Dockerfile.builder`:** `COPY glossary_verify.py` (stdlib only — no new apt/pip).
4. **Tests:** `tests/test_glossary_verify.py` — candidate pre-match, apply/flag by confidence,
   incremental skip via `verified`, schema round-trip, dub-preference in the apply step (LLM stubbed).

## Edge cases and failure modes

| Case | Expected |
|---|---|
| Wiki can't be resolved | Leave glossary unchanged; flag nothing applied; log; (community can add a `wiki` override). |
| Term has no good candidate | Kept as-is, added to `flagged` (no-match). |
| LLM low-confidence | Kept as-is, flagged (review). |
| Wiki/LLM timeout or HTTP error | No-op for that run; never crash the sweep. |
| Dub spelling differs from wiki primary | Prefer dub (LLM instructed); record `dub_note`. |
| Term already in `verified` | Skipped (incremental). |
| Huge wiki (1000s of titles) | Pre-match narrows to top-K before the LLM; index cached. |
| Community-submitted glossary, unknown show | Same flow via the module/CLI; override if needed. |

## Decisions taken

| Decision | Rejected | Why |
|---|---|---|
| Hybrid: fetch wiki + LLM adjudicate | deterministic-only; LLM-researcher | Authoritative data + judgment for dub-vs-manga; reproducible. |
| Local qwen3:8b, configurable | cloud-only; escalation | Local-first; wiki data does the heavy lifting; cheap (infrequent). |
| Mining hook + CLI + reusable module | hook-only; standalone-only | Build (mining) + modification (CLI/community front-ends) coverage. |
| Auto-apply high-confidence, flag rest | suggest-only; apply-all | Automatic accuracy without guessing on the uncertain. |
| Auto-resolve + `wiki` override | explicit-only; web-search | Zero-config for easy shows; override pins the tricky/community ones. |
| Full main-namespace index, LLM-filtered | character-cat-only; curated cats | Uniform coverage of names/places/ships/terms/attacks. |

## Constraints

- stdlib-only HTTP; runs in the subgen image; resilient (never stall the GPU loop).
- Per-show incremental + cached; deterministic pre-match is unit-tested; LLM/wiki are integration.

## Open questions (risks)

- [ ] Dub-vs-manga: the wiki title is usually the publisher (Viz) form; the dub variant may not be on
      the page — LLM/known-knowledge best-effort, flag when unsure. Acceptable (≥ current state).
- [ ] Fandom API rate limits — caching + top-K batching mitigate; add a small delay if needed.
- [ ] Confidence threshold tuned during implementation against the One Pace re-derivation.
