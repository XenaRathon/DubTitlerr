# Plan — V2: Models, Ops & Remaining Polish

> Only write this after `spec.md` is approved.
> An approved plan triggers the **kickoff** phase of the `dev-lifecycle` skill (branch creation).

## Branch and delivery

- **Branch:** `feat/v2-models-ops` (base: `main`, **after V1 merged**)
- **PR slicing:** 2 PRs recommended due to scope (~35 items across 20+ files).
  - **PR 1:** Phase A (Models & Accuracy) + Phase B (Shell & Ops Cleanup).
    These are the highest-impact and touch the most files; reviewing them
    together catches cross-phase interactions (e.g., env vars used in both
    Python and shell).
  - **PR 2:** Phase C (Python Polish) + Phase D (Signs/Songs Low-Priority).
    These are smaller, self-contained, and lower risk. Can be reviewed quickly.

## Technical approach

Execute in phase order (A → B → C → D). Phases A and B are independent of each
other and could be developed in parallel by separate contributors, but sequential
within a single developer is simpler.

**Phase A (Models & Accuracy):** The `repair.py:llm()` function is refactored into
a dispatch pattern — `if REPAIR_BACKEND == "llamacpp": llm_llamacpp(prompt) else:
llm_ollama(prompt)`. The llama.cpp path builds a different JSON body and parses a
different response schema. The two-pass repair wraps this: `process()` calls
`llm()` for each target, then for lines that changed significantly, calls
`llm(prompt, model=REPAIR_MODEL_SECONDARY)`. The phonetic tier in `glossary.py`
wraps `jellyfish.metaphone()` in a try/except ImportError so it degrades
gracefully. The `word_probs` field is added to `generate.py`'s conf.json writer
(collect per-word probabilities during the whisper→dict adaptation loop) and
checked in `repair.is_target()` with a `has_low_prob_word()` helper.

**Phase B (Shell & Ops Cleanup):** Shell scripts get deprecation comments (no
functional changes). `gen_loop.sh` gets `set -e` + `|| true` on the
mine/verify/generate timeout-or-fail lines. `merge_pass.sh` drops the
apt-get blocks. `data/extras.txt` is created from the existing inline
lists; `common.py` gains `load_extras()` reading it; a new `shell/lib.sh`
exports a function `extras_grep_pattern` that reads the same file and
emits a `|`-delimited regex. All consumers updated.

**Phase C (Python Polish):** Mostly single-function changes across many files.
`mux.py` gets identify caching + HL_ROOTS fix + partners cleanup.
`generate.py` gets `lastrun.json` writer + data file loading + CUDA error gating fix (#2).
`mux.py` gets the half-size verification heuristic removed (#5).
`repair.py` gets timeout env vars + `repair-summary.json`.
`glossary_verify.py` gets ThreadPoolExecutor.
`ordering.py` gets default-path fix + warning log.
`reflow.py` gets readability cleanup.
`_template/spec.md` gets Authorization section populated.

**Phase D (Signs/Songs Low-Priority):** Style collision logging in `build()`,
font audit in `mux.verify()`, WrapStyle warning, ScaledBorderAndShadow force,
resolution mismatch check. All self-contained within `dub_signs_merge.py`
and `mux.py`.

## Affected files (by layer)

### Phase A — Models & Accuracy

| Layer | File | Change |
|---|---|---|
| Transcription | `generate.py` | Add `word_probs` to conf.json; add `WHISPER_AUDIO_FILTER` to ffmpeg extract_wav; default `WHISPER_MODEL` test |
| Repair | `repair.py` | Refactor `llm()` → dispatch; add `llm_ollama()`, `llm_llamacpp()`; add two-pass logic; add `REPAIR_TIMEOUT_*`; add latency to CSV; add `repair-summary.json` writer |
| Glossary | `glossary.py` | Add tier 4 phonetic matching via `jellyfish.metaphone()` |
| Config | `pyproject.toml` | Add `jellyfish` to dependencies |
| Docker | `Dockerfile.builder` | Add `pip install jellyfish` |

### Phase B — Shell & Ops Cleanup

| Layer | File | Change |
|---|---|---|
| Orchestration | `anime_library.sh` | Add deprecation comment header |
| Orchestration | `all_seasons.sh` | Add deprecation comment header |
| Orchestration | `merge_watcher.sh` | Fix image reference or deprecate |
| Docker | `Dockerfile` | Add deprecation comment header |
| Docs | `README.md` | Update "Quick start" to reference `Dockerfile.builder` |
| Orchestration | `gen_loop.sh` | Add `set -e` + `\|\| true` on fallthroughs |
| Orchestration | `merge_pass.sh` | Remove self-healing apt-get blocks |
| New | `data/extras.txt` | One directory name per line, `#` comments |
| New | `shell/lib.sh` | `extras_grep_pattern()` function |
| Python | `common.py` | Add `load_extras(path="data/extras.txt")` with inline fallback |
| Python | `generate.py` | Use `load_extras()` instead of inline `EXTRA_DIRS` |
| Python | `mine_glossary.py` | Use `load_extras()` instead of inline `EXTRA_DIRS` |
| Shell | `merge_pass.sh` | Use `extras_grep_pattern` instead of inline regex |
| Shell | `post_show.sh` | Use `extras_grep_pattern` instead of inline regex |
| Config | `.gitignore` | Add 8 pipeline artefact patterns |
| Python | `plex_refresh.py` | `os.environ.get()` + clear error messages |

### Phase C — Python Polish

| Layer | File | Change |
|---|---|---|
| Transcription | `generate.py` | Write `glossaries/<show>.lastrun.json` after processing |
| Repair | `repair.py` | Write `repair-summary.json`; `REPAIR_TIMEOUT_*` env vars |
| Glossary verify | `glossary_verify.py` | `ThreadPoolExecutor` for `adjudicate()` |
| Mux | `mux.py` | Cache `identify()`; fix `HL_ROOTS` default; drop redundant `samefile()`; pass cached identify through `process()` |
| Ordering | `ordering.py` | Default path `None`; resolve from env; warn on non-integer |
| Reflow | `reflow.py` | `wrap_balance()` readability: separate `best_max_len` variable |
| Orchestration | `anime_library.sh` | Add `--dry-run` flag support |
| Data | `data/common_proper_noun_deny.txt` | Extract from `mine_glossary.py:COMMON` |
| Data | `data/hallucination_blocklist.txt` | Extract from `hallucination.py:BLOCKLIST` |
| Mining | `mine_glossary.py` | Load COMMON from data file, fall back to inline |
| Hallucination | `hallucination.py` | Load BLOCKLIST from data file, fall back to inline |
| Transcription | `generate.py` | Fix CUDA error gating: gate on exception type not substring; persist retry log (#2) |
| Mux | `mux.py` | Remove half-size heuristic from `verify()` (#5) |
| Repair | `repair.py` | Wrap sub ref in XML tags (prompt injection guard) |
| All Python | All `.py` files | `os.chown(...) except OSError: pass` → log the path |
| Specs | `specs/*/spec.md` | Populate Authorization sections |
| Repair | `repair.py` | `_glossary_terms()` truncate on whole-term boundary |

### Phase D — Signs/Songs Low-Priority

| Layer | File | Change |
|---|---|---|
| Signs merge | `dub_signs_merge.py` | Style collision logging in `build()`; WrapStyle check + warning; force `ScaledBorderAndShadow: yes`; resolution mismatch check |
| Mux | `mux.py` | Font attachment count + MIME type check in `verify()` |

## Risks and mitigation

| Risk | Mitigation |
|---|---|
| V1 not merged when V2 starts | V2 branch is based on `main` AFTER V1 merge. If V1 is in review, V2 waits. Spec is explicit about this dependency. |
| `jellyfish` import fails in subgen image | `Dockerfile.builder` adds `pip install jellyfish`. `glossary.py` has try/except ImportError → phonetic tier skipped gracefully. |
| llama.cpp API changes between now and deployment | The adapter (`llm_llamacpp()`) is a single function ~30 lines. Easy to update. |
| `data/` files not copied into Docker image | `Dockerfile.builder` COPY line updated to include `data/` directory. |
| EXTRA_DIRS grep regex escaping edge cases | The shell function `extras_grep_pattern` joins with `|` and uses `grep -iE`. Directory names with regex-special chars are escaped. |
| `set -e` breaks gen_loop crash-resume | Every command that CAN fail intentionally (mine, verify, generate) already has `|| echo` or `|| { ... }`. `set -e` only catches UNEXPECTED failures (oops). |

## Rollback and reversibility

- Reverting either PR is sufficient. Phases are additive and independent.
- Data files (`data/`) have inline fallbacks — removing them doesn't break
  functionality, just reverts to hardcoded defaults.
- `word_probs` field in conf.json is optional on both write and read — old
  conf files work fine with new code and vice versa.
- Shell script deprecation comments are non-functional — reverting the PR
  removes the comments.

## Testing strategy

- **Unit:** Phase A phonetic matching: add `test_phonetic_matching` to
  `test_glossary.py`. Phase A `word_probs` targeting: add cases to
  `test_repair.py`. Phase C `_glossary_terms` boundary: add test. Phase C
  `ordering.read_start` warning: add test. Phase D keep_event additions: add
  to the V1-created `test_dub_signs_merge.py`.
- **Integration:** Phase A llama.cpp adapter: manual test against VM102
  (can't unit-test without a running llama.cpp). Phase B shell changes:
  manual test in the Dockerfile.builder container.
- **Target coverage:** Add ~15 new unit tests across the 4 phases. Existing
  88 tests remain green (plus the ~15 added in V1).

## Observability / performance

- **Phase A:** Phonetic matching adds ~1ms per token (Metaphone is fast).
  Two-pass repair adds ~3–5s (35B MoE) for every line that hits the secondary
  model. Because the "contains a glossary name not in the original" trigger
  fires on essentially every name-changing repair, budget for *most* repaired
  name-lines going through the second pass, not a small "ambiguous" fraction.
  `repair-summary.json` makes the real second-pass hit rate visible; watch it
  after rollout and tighten the trigger if per-episode latency exceeds budget.
- **Phase B:** No runtime perf change. EXTRA_DIRS file read is once at
  startup (<1ms).
- **Phase C:** Removing the half-size heuristic (#5) eliminates false rejections on compact releases (no perf change, correctness fix). CUDA error gating fix (#2) prevents falsely poisoning episodes.
- **Phase C:** `identify()` caching saves ~100ms per muxed file.
  ThreadPoolExecutor cuts glossary verification from 7min to ~2min.
  `lastrun.json` writes are <1ms.
- **Phase D:** Font MIME check adds one `mkvmerge -J` field read (already
  in the verify call). WrapStyle check is a dict lookup. No perf impact.
