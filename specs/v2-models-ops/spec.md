# Spec — V2: Models, Ops & Remaining Polish

> Comprehensive implementation spec covering all ~35 review recommendations deferred
> from the V1 polish spec, plus the original review's medium/low-priority items that
> didn't fit in V1's scope. Organized into 4 phases by area: Models & Accuracy,
> Shell & Ops Cleanup, Python Polish, and Signs/Songs Low-Priority. See `REVIEW.md`
> for full rationale on each item. Depends on V1 being merged first (this spec
> assumes `common.py` exists).

## Context and problem

V1 Polish (spec `v1-polish`) addressed the highest-leverage items: `common.py`
extraction, two signs/songs visual-corruption bugs, context-aware LLM repair, and
test coverage for load-bearing gaps. That left ~35 items across two review passes
ranging from model upgrades and shell script fixes to single-line Python cleanups
and docs improvements.

This spec packages the remaining items into a coherent delivery, grouped by area
so each phase is independently reviewable and reversible. The model/accuracy
phase (A) is the highest-impact remaining work; the shell/ops phase (B) cleans
up the orchestration layer; the Python polish phase (C) fixes bugs and adds
observability; the signs/songs phase (D) covers the lower-priority formatting items.

## Acceptance criteria (verifiable)

### Phase A — Models & Accuracy (items #41, #44, #45, #46, #47, #48)

- [ ] `WHISPER_MODEL` env var is tested with `large-v3-turbo` on the GTX 1060 6GB.
      Either adopted (env default changed) or documented as rejected with reason.
- [ ] `repair.py` supports a configurable `REPAIR_BACKEND` env var (`ollama` |
      `llamacpp`) with separate HTTP client paths. A `llamacpp` backend sends to
      `REPAIR_LLAMACPP_URL` (default `http://192.168.1.232:8080/completion`)
      using llama.cpp's `/completion` JSON schema.
- [ ] `glossary.py:_fix_token()` has a tier 4 phonetic matching pass using
      `jellyfish.metaphone()` — fires only when phonetic codes match AND the
      token is NOT a known English word.
- [ ] `dubtitles.conf.json` includes a `word_probs` field (list of per-word
      linear probabilities) for each card. `repair.is_target()` checks for any
      word with prob < 0.25 as an additional targeting gate.
- [ ] Two-pass repair is implemented: `qwen3:8b` runs first on all targets;
      lines whose output differs significantly (length ratio < 0.6 or > 1.5,
      or contains glossary names not in the original) are re-sent to the
      secondary model (`REPAIR_MODEL_SECONDARY`, defaults to same as primary).
      NOTE: the "contains a glossary name not in the original" trigger fires on
      essentially _every_ successful name repair (inserting the correct glossary
      name is the whole point of repair), so this is best understood as
      "re-verify all name-changing repairs with the stronger model," NOT a
      "only ambiguous lines go to the slow model, keep 90% fast" optimization.
      That is acceptable (name fixes are exactly what you want double-checked)
      but the latency budget must assume most name-changing lines hit the
      secondary model, not a small fraction — guard total per-episode latency
      accordingly (see Open questions).
- [ ] `generate.py:extract_wav()` adds an ffmpeg high-pass filter (80 Hz) +
      mild dynamic range compression to the audio extraction pipe.

### Phase B — Shell & Ops Cleanup (items #20–25, #34, #36)

- [ ] `anime_library.sh` and `all_seasons.sh` have a deprecation comment at the
      top pointing to `container_run.sh`. `merge_watcher.sh` updated to reference
      `dubtitle-builder:latest` or deprecated with comment.
- [ ] `Dockerfile` (old, signs-only) has a deprecation comment pointing to
      `Dockerfile.builder`. README "Quick start" updated to reference the builder.
- [ ] `gen_loop.sh` has `set -e` added with explicit `|| true` on intentional
      fallthroughs (glossary_verify, mine, generate).
- [ ] `merge_pass.sh` self-healing `apt-get install` blocks removed; if
      ffmpeg/mkvmerge/pysubs2 are missing, the script fails loudly with a
      clear error message.
- [ ] `EXTRA_DIRS` consolidated into a single source of truth:
      `data/extras.txt` (one directory name per line), read by both
      `common.py::load_extras()` and a new `shell/lib.sh::extras_grep_pattern()`.
      All 4 consumers (`generate.py`, `mine_glossary.py`, `merge_pass.sh`,
      `post_show.sh`) updated to use the shared data.
- [ ] `.gitignore` includes all 8 pipeline artefact patterns
      (`*.eng.dubtitles.*`, `*.dubtitles.*`, `*.muxtmp.mkv`).
- [ ] `plex_refresh.py` uses `os.environ.get()` with clear error messages
      instead of bare `os.environ[]` KeyError.

### Phase C — Python Polish (items #2, #4, #5, #6, #7, #8, #10, #13, #14, #15, #16, #17, #18, #19, #28, #29, #30, #32)

- [ ] `repair.llm()` supports a `REPAIR_TIMEOUT` env var (connect + read
      timeouts split) and writes per-line latency into the repair CSV.
- [ ] Per-show run summary artefacts: `generate.py` writes
      `glossaries/<show>.lastrun.json` with cards_written, dropped, fixed,
      flagged, elapsed_s; `repair.py` writes `repair-summary.json` per show
      with totals + p95 latency.
- [ ] `glossary_verify.adjudicate()` uses `concurrent.futures.ThreadPoolExecutor`
      with `max_workers=4` (env: `VERIFY_WORKERS`) for parallel term verification.
- [ ] `mux.partners()` cached by inode within a process lifetime (simple dict).
- [ ] `ordering.read_start()` default path is `None`; resolves from
      `SEASON_PRIORITY_FILE` env var with explicit "no config = disabled" path.
      Non-integer values in the priority file log a warning instead of silently
      returning 0.
- [ ] `mux.verify()` caches `identify(orig)` result, reusing it instead of
      calling `mkvmerge -J` twice on the same file.
- [ ] `mux.HL_ROOTS` default logic made explicit: `val = os.environ.get("HARDLINK_ROOTS"); HL_ROOTS = val.split(":") if val else ROOTS`.
- [ ] `anime_library.sh` supports `--dry-run` flag: prints "would generate N,
      repair M, mux K" and exits.
- [ ] Hardcoded pattern lists moved to data files: `mine_glossary.COMMON` →
      `data/common_proper_noun_deny.txt`; `hallucination.BLOCKLIST` →
      `data/hallucination_blocklist.txt`. Both read at module load, fall back
      to inline defaults if file missing (backward-compatible).
- [ ] `repair.build_prompt()` wraps the fansub reference in
      `<official_subtitle_reference>...</official_subtitle_reference>` XML tags
      as a prompt-injection guard.
- [ ] All `os.chown(...) except OSError: pass` blocks log the path on failure.
- [ ] `_template/spec.md` `Authorization` section populated for each existing
      spec file (auth for generate, repair, mux, merge).
- [ ] `_glossary_terms()` string cap truncates on whole-term boundaries (not
      mid-name).
- [ ] `reflow.wrap_balance()` fallback tracking uses a separate named variable
      `best_max_len` instead of embedding it in a tuple's first element.
- [ ] `mux.partners()` drops the redundant `os.path.samefile()` call (inode+dev
      is the identity).
- [ ] `generate.py` CUDA error gating uses exception type (`RuntimeError` from
      ctranslate2), not substring match on `"cuda"`. Non-CUDA errors let the
      episode retry (remove `.fail` marker) instead of being falsely poisoned.
      Persists a JSON log of retried episodes (`{path, exc_type, msg}`).
- [ ] `mux.verify()` removes the half-size heuristic
      (`os.path.getsize(out) > os.path.getsize(orig) * 0.5`). The existing
      track-presence + duration tolerance + Dubtitles-track checks are sufficient.
      PRECONDITION: before deleting the size gate, confirm the duration-tolerance
      check runs **unconditionally on every success path** — it is the real
      truncation canary (the size ratio was only a crude proxy). If any code
      path can return "ok" without comparing output duration to the source
      within tolerance, fix that first, or a silently truncated mux ships.

### Phase D — Signs/Songs Low-Priority (items #52, #53, #54, #55, #56)

- [ ] `build()` in `dub_signs_merge.py` logs when a style name collision occurs
      and the font/size differ between tracks.
- [ ] `mux.verify()` checks font attachment count matches source (and MIME type
      is a font format, not `application/octet-stream`).
- [ ] `build()` logs the `WrapStyle` value from each source track; if they
      differ, emits a warning.
- [ ] `build()` forces `ScaledBorderAndShadow: yes` in the merged output's
      Script Info for consistent cross-player rendering.
- [ ] Resolution mismatch check: `build()` verifies all source tracks share the
      same `PlayResX`/`PlayResY`; if not, logs a loud warning (WARN-ONLY — do NOT
      skip or transform the track; full coordinate handling is deferred to V3, per
      the "Decisions taken" table and tasks.md D5). Skipping a mismatched track
      would drop its signs entirely, which is worse than a warning.

## Out of scope (explicit)

- **#12 Web UI data layer** — requires a design spec for the Web UI itself;
  `state.json` schema design belongs there, not here.
- **#37 bakeoff.py docs** — single README paragraph, do anytime.
- **#38 container_run coordination comment** — single comment, do anytime.
- **#39 Glossary JSON schema** — requires community-repo design decisions. Defer
  to a future "Community Glossary Repo" spec.
- **#40 common_words.txt comment** — single comment, do anytime.- **#53 Resolution normalization (pixel transform)** — the full coordinate
  transform is complex; this spec only adds the warning (Phase D). Actual
  normalization is deferred to V3.

### Summary: now covers all 56 review items

- **V1 spec:** #1, #3, #9, #26, #27, #31, #33, #35, #42, #43, #49, #50, #51
- **V2 spec (this doc):** #2, #4, #5, #6, #7, #8, #10, #11, #13, #14, #15, #16,
  #17, #18, #19, #20, #21, #22, #23, #24, #25, #28, #29, #30, #32, #34, #36,
  #41, #44, #45, #46, #47, #48, #52, #53, #54, #55, #56
- **Deferred to future:** #12, #37, #38, #39, #40 (docs / comments / community
  repo — don't need an implementation spec)

## Data contracts

- **New data files:**
  - `data/extras.txt` — one directory name per line, `#` comments allowed.
  - `data/common_proper_noun_deny.txt` — one English word per line.
  - `data/hallucination_blocklist.txt` — one regex pattern per line.
- **New env vars:**
  - `REPAIR_BACKEND` (ollama | llamacpp, default ollama)
  - `REPAIR_LLAMACPP_URL` (default `http://192.168.1.232:8080/completion`)
  - `REPAIR_MODEL_SECONDARY` (default same as `REPAIR_MODEL`)
  - `REPAIR_TIMEOUT_CONNECT` (default 10), `REPAIR_TIMEOUT_READ` (default 120)
  - `VERIFY_WORKERS` (default 4)
  - `WHISPER_AUDIO_FILTER` (default `"highpass=f=80,compand=attacks=0.001:decays=0.2:points=-80/-80|-30/-15|0/-3|20/-3"`)
- **Modified data contracts:**
  - `dubtitles.conf.json` gains optional `word_probs` field per card:
    `[0.9, 0.95, 0.2, 0.88, 0.91]` (linear probs, same order as words in text).
  - `dubtitles.repair.csv` gains `latency_ms` column.
- **New output files:**
  - `glossaries/<show>.lastrun.json` — per-show run stats.
  - `<stem>.dubtitles.repair-summary.json` — per-show repair summary.
- **External dependencies:**
  - `jellyfish` (pure Python, Metaphone) — added to `pyproject.toml` deps and
    `Dockerfile.builder` pip install.

## Edge cases and failure modes

| Case                                                     | Expected behavior                                                                                |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `llamacpp` backend unreachable                           | Log warning, fall back to returning empty string (same as current Ollama failure path)           |
| `REPAIR_MODEL_SECONDARY` same as primary                 | Two-pass becomes a no-op (same model, skip redundant second call)                                |
| `jellyfish` not installed                                | Phonetic tier skipped gracefully (try/except ImportError); degrade to existing 3-tier correction |
| `word_probs` missing in older conf.json files            | `is_target()` treats missing field as "all probs ok" — backward-compatible                       |
| `data/extras.txt` missing or unreadable                  | Fall back to inline defaults (current hardcoded set)                                             |
| `anime_library.sh --dry-run` with no files               | Prints "would generate 0, repair 0, mux 0"                                                       |
| `gen_loop.sh` with `set -e` and a `find` returning empty | `find ... \|\| true` prevents exit; stall detection `$after -le $before` still works with both 0 |
| Style collision log in `build()` for identical styles    | No-op (don't log if fontname AND fontsize match)                                                 |
| Font MIME type is `application/octet-stream`             | Log warning but don't fail verify — some valid fonts have generic MIME                           |

## Decisions taken

| Decision                                                                   | Rejected alternative                   | Why                                                                                                                                                                                                          |
| -------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Phonetic matching uses `jellyfish.metaphone()`, not Soundex                | Soundex                                | Metaphone handles non-English names better (anime character names are Japanese → English transliterations). Jellyfish is pure Python, no C deps.                                                             |
| `REPAIR_BACKEND` env var with separate HTTP paths                          | Single URL with format detection       | Ollama API (`/api/generate`) and llama.cpp API (`/completion`) have fundamentally different request/response schemas. Separate code paths are cleaner than format-sniffing.                                  |
| Two-pass repair uses same model by default (no-op)                         | Always requires a secondary            | Makes the feature opt-in. Most users have one model; the two-pass is for the homelab's specific dual-model setup.                                                                                            |
| `data/` files with inline fallbacks                                        | Only data files, no fallbacks          | Keeps the project runnable without the data files (dev/test environments). The Dockerfile can COPY them for production.                                                                                      |
| `EXTRA_DIRS` consolidation uses a data file + common.py loader + shell lib | Single Python source, shell duplicates | The shell scripts (`merge_pass.sh`, `post_show.sh`) need the list in grep-compatible form. A data file + shell function is the only way to have a single source of truth.                                    |
| `set -e` in `gen_loop.sh` with explicit `\|\| true`                        | No `set -e` (current)                  | The existing stall-detection logic (`$after -le $before`) is load-bearing. `set -e` prevents silent failures in the mine/verify/generate sequence; explicit fallthroughs preserve the crash-resume behavior. |
| Phase D resolution check: warn only, don't transform                       | Full coordinate transform              | Coordinate transform requires parsing `\pos` tags and scaling by ratio — ~50 lines of regex math with edge cases. The mismatch is rare; a loud warning is sufficient for now. Full transform deferred to V3. |

## Constraints

- **No regression:** All existing tests pass. `ruff check` clean on all changed
  files. V1 must be merged first (this spec assumes `common.py` exists).
- **Backward-compatible:** All new env vars have defaults matching current
  behavior. `word_probs` field is optional in conf.json. `data/` files fall
  back to inline defaults. Old `anime_library.sh` still works (deprecation
  comment only, no functional change).
- **No new heavy dependencies:** `jellyfish` is ~50KB pure Python. All other
  changes are stdlib or already-present packages.
- **Shell changes must not break container_run.sh:** The long-running container
  is the active deployment path. Shell changes are tested in the context of
  `Dockerfile.builder`.

## Open questions (risks)

- [ ] **`large-v3-turbo` on GTX 1060 6GB at int8** — needs a real test on the
      hardware. If it OOMs, the spec's acceptance criterion is satisfied by
      documenting the rejection. Low risk (turbo is architecturally identical,
      just distilled).
- [ ] **llama.cpp `/completion` API stability** — the endpoint and JSON schema
      may differ between llama.cpp versions. The spec targets the version
      running on VM102 as of 2026-07-24. If the API changes, the adapter is
      isolated in `repair.py:llm_llamacpp()` and easy to update.
- [ ] **Two-pass repair latency** — if the secondary model is the 35B MoE on
      VM102, ambiguous lines add ~3–5s each. For a typical episode with 2–5
      targets, worst-case is ~25s extra. Acceptable for a background batch
      process; flag if observed latency exceeds 60s per episode.
- [ ] **`anime_library.sh --dry-run` accuracy** — the dry run can only count
      files with sidecars/stamps to estimate "would process N". It can't know
      how many need repair vs generate without running the full pre-filter.
      Accept as approximate.
