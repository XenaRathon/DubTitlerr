# Tasks — V2: Models, Ops & Remaining Polish

> Persistent memory between sessions. New session: read `spec.md` + this file and
> check out the branch below before anything else.
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `feat/v2-models-ops` (base: `main`, **after V1 merged**)

Rules: each task ≤ ~1h, dependency-ordered, verifiable done criterion. Before
`[x]`: gates green (ruff · pytest). 1 task = 1 conventional commit.

---

## Phase A — Models & Accuracy

- [ ] **A1 — Refactor `repair.llm()` into dispatch pattern.**
      Rename current `llm()` to `llm_ollama(prompt, model=None)` (model defaults
      to `REPAIR_MODEL`). Add `llm_llamacpp(prompt, model)` — builds llama.cpp
      `/completion` JSON body (`prompt`, `temperature: 0`, `n_predict: 50`,
      `stop: ["\n"]`), parses `{"content": "..."}` response. New `llm(prompt,
      model=None)` dispatches on `REPAIR_BACKEND` env var. Add `REPAIR_LLAMACPP_URL`
      env var defaulting to `http://192.168.1.232:8080/completion`.
      — done when: existing repair tests pass; new `test_llm_dispatch` checks
      env var routing (monkeypatch).

- [ ] **A2 — Add `REPAIR_TIMEOUT` + per-line latency to repair.**
      Add `REPAIR_TIMEOUT_CONNECT` (default 10) and `REPAIR_TIMEOUT_READ`
      (default 120). `llm_ollama()` uses separate `urllib.request.urlopen` with
      explicit connect/read timeouts (or switch to `requests` if available).
      Record `time.monotonic()` before/after each LLM call; add `latency_ms`
      column to `dubtitles.repair.csv`.
      — done when: `test_repair.py` verifies timeout env vars are used; CSV
      output checked for `latency_ms` column.

- [ ] **A3 — Implement two-pass repair.**
      Add `REPAIR_MODEL_SECONDARY` env var (defaults to `REPAIR_MODEL` — no-op
      if same). In `process()`, after the first LLM pass: for each repaired
      line where `len(new)/len(orig) < 0.6 or > 1.5` OR `new` contains a
      glossary name not in `orig`, re-send to `llm(prompt,
      model=REPAIR_MODEL_SECONDARY)`. If secondary model is same as primary,
      skip (no-op).
      — done when: test with monkeypatched `REPAIR_MODEL_SECONDARY` showing
      second call for divergent lines.

- [ ] **A4 — Add tier 4 phonetic matching to `glossary.py`.**
      Add `_phonetic_match(token, names)` using `jellyfish.metaphone()`. In
      `_fix_token()`, after the fuzzy tier: if the token's Metaphone code
      matches a name's Metaphone code AND the token is NOT a known English
      word → return the canonical name. Wrap in `try/except ImportError` so
      missing `jellyfish` degrades gracefully.
      — done when: `test_glossary.py` tests `test_phonetic_matches_spondum`,
      `test_phonetic_does_not_match_english_word`, `test_phonetic_graceful_if_jellyfish_missing`.

- [ ] **A5 — Add `jellyfish` to deps + Dockerfile.**
      `pyproject.toml`: add `"jellyfish>=1.0"` to dependencies.
      `Dockerfile.builder`: add `jellyfish` to `pip install` line.
      — done when: `pip install -e .` succeeds; `python -c "import jellyfish"` ok.

- [ ] **A6 — Add `word_probs` field to dubtitles.conf.json.**
      In `generate.py:process()`, during the whisper→dict adaptation loop,
      collect per-word probabilities from `getattr(w, "probability", 1.0)`.
      In the conf.json writer (`conf.append({...})`), add
      `"word_probs": [round(w["prob"], 3) for w in card_words]` referencing
      the card's words. The field is optional for backward compat.
      — done when: conf.json output checked for `word_probs` array matching
      card word count.

- [ ] **A7 — Add per-word confidence check to `repair.is_target()`.**
      Add `has_low_prob_word(c)` helper: returns True if any value in
      `c.get("word_probs", [])` is < 0.25. Add to `is_target()` as an OR
      condition alongside the existing `avg_logprob` check.
      — done when: `test_repair.py` tests `test_is_target_by_word_prob`,
      `test_is_target_no_word_probs_field`.

- [ ] **A8 — Add high-pass audio filter to `extract_wav()`.**
      Add `WHISPER_AUDIO_FILTER` env var (default `"highpass=f=80,..."` per
      the spec). `extract_wav()` appends `-af "$WHISPER_AUDIO_FILTER"` to
      the ffmpeg command. Empty string = no filter (backward-compat).
      — done when: `python -c "import ast; ast.parse(open('generate.py').read())"` ok.

- [ ] **A9 — Test `large-v3-turbo` on GTX 1060 6GB.**
      Set `WHISPER_MODEL=large-v3-turbo` env var. Transcribe one short
      episode. Check: no OOM, inference time vs `large-v3`, VRAM usage.
      If it works: update default `WHISPER_MODEL` in `generate.py` to
      `large-v3-turbo`. If it OOMs: document in a code comment why the
      default stays `large-v3`.
      — done when: decision recorded in `generate.py` docstring or comment.

- [ ] **A10 — Write `repair-summary.json` per show.**
      In `repair.process()`, after processing all targets: write
      `out_for(stem + ".dubtitles.repair-summary.json")` with
      `{targets, repaired, skipped_no_ref, mean_latency_ms, p95_latency_ms,
      model, model_secondary, repaired_lines: [...]}`.
      — done when: summary JSON validated; `ruff check repair.py` clean.

---

## Phase B — Shell & Ops Cleanup

- [ ] **B1 — Deprecate old orchestrators.**
      Add comment header to `anime_library.sh`, `all_seasons.sh`:
      ```sh
      # DEPRECATED as of 2026-07-24: use container_run.sh instead.
      # This script reloads the Whisper model per show (~40s × N shows).
      # container_run.sh loads it once and keeps it resident.
      # This file is retained for reference; no functional changes.
      ```
      Same for `merge_watcher.sh` (reference `container_run.sh` merge loop).
      — done when: grep shows deprecation comment at line 2 of each file.

- [ ] **B2 — Deprecate old `Dockerfile`, update README.**
      Add deprecation comment to `Dockerfile` pointing to `Dockerfile.builder`.
      README "Quick start": change `docker build -t dub-signs-merge .` to
      reference `Dockerfile.builder` and `dubtitle-builder:latest`.
      — done when: README build command matches builder image.

- [ ] **B3 — Add `set -e` to `gen_loop.sh`.**
      Add `set -e` after `set -u`. On every line that intentionally tolerates
      failure (mine, verify, generate), ensure `|| echo "..."` or `|| true`
      is present. Test: introduce a deliberate typo in a non-fallthrough
      command → script exits; typo in a `|| echo` line → continues.
      — done when: `shellcheck gen_loop.sh` passes (or manual review).

- [ ] **B4 — Remove self-healing installs from `merge_pass.sh`.**
      Delete the `command -v ffmpeg ... || apt-get install ...` blocks.
      Replace with: `command -v ffmpeg >/dev/null 2>&1 || { echo "FATAL: ffmpeg not found — image is misbuilt"; exit 1; }`
      Same for `mkvmerge` and `pysubs2`.
      — done when: `grep apt-get merge_pass.sh` returns nothing.

- [ ] **B5 — Create `data/extras.txt`.**
      One directory name per line, `#` comments allowed:
      ```
      behind the scenes
      deleted scenes
      featurettes
      interviews
      scenes
      shorts
      trailers
      other
      extras
      ```
      — done when: file exists with all 9 entries.

- [ ] **B6 — Add `load_extras()` to `common.py`.**
      ```python
      def load_extras(path="data/extras.txt"):
          try:
              with open(path) as f:
                  return {ln.strip().lower() for ln in f
                          if ln.strip() and not ln.startswith("#")}
          except OSError:
              return { ... inline fallback ... }  # current hardcoded set
      ```
      — done when: `python -c "from common import load_extras; assert len(load_extras()) >= 9"`.

- [ ] **B7 — Create `shell/lib.sh` with `extras_grep_pattern()`.**
      ```sh
      extras_grep_pattern() {
          # reads data/extras.txt, emits a grep -iE pattern like
          # '(Behind The Scenes|Deleted Scenes|...)'
          local dir="${1:-data/extras.txt}"
          ...
      }
      ```
      — done when: `source shell/lib.sh && extras_grep_pattern` outputs valid regex.

- [ ] **B8 — Update Python consumers of EXTRA_DIRS.**
      `generate.py`: replace inline `EXTRA_DIRS` with `from common import load_extras; EXTRA_DIRS = load_extras()`.
      `mine_glossary.py`: same.
      — done when: `ruff check` clean; existing behavior unchanged.

- [ ] **B9 — Update shell consumers of EXTRA_DIRS.**
      `merge_pass.sh`: replace inline grep regex with:
      ```sh
      source /app/shell/lib.sh 2>/dev/null || true
      PATTERN=$(extras_grep_pattern /app/data/extras.txt 2>/dev/null || echo '...fallback...')
      find ... | grep -ivE "$PATTERN"
      ```
      `post_show.sh`: same pattern.
      — done when: manual test in container; `grep -ivE` still filters extras.

- [ ] **B10 — Update `.gitignore` with pipeline artefacts.**
      Add 8 patterns: `*.eng.dubtitles.srt`, `*.eng.dubtitles.ass`,
      `*.dubtitles.conf.json`, `*.dubtitles.done`, `*.dubtitles.fail`,
      `*.dubtitles.repair.csv`, `*.dubtitles.mux.log`, `*.muxtmp.mkv`.
      — done when: `git status` doesn't show these as untracked after a pipeline run.

- [ ] **B11 — Fix `plex_refresh.py` error handling.**
      Replace `os.environ["PLEX_URL"]` with `os.environ.get("PLEX_URL", "").rstrip("/")`.
      Add `if not base: sys.exit("PLEX_URL not set")`. Same for `PLEX_TOKEN`.
      — done when: `python plex_refresh.py` prints clear error instead of KeyError.

---

## Phase C — Python Polish

- [ ] **C1 — Write `glossaries/<show>.lastrun.json` from `generate.py`.**
      After `process()` for all episodes in a show, write a summary to
      `os.path.join(GLOSS_DIR, show + ".lastrun.json")`:
      `{show, elapsed_s, episodes_total, episodes_transcribed, cards_written,
      dropped_hallucination, collapsed_runs, flagged, model, model_version,
      glossary_version}`.
      — done when: `lastrun.json` exists after a `--root` run.

- [ ] **C2 — Parallelize `glossary_verify.adjudicate()` with ThreadPoolExecutor.**
      Add `VERIFY_WORKERS` env var (default 4). In `verify()`, replace the
      dict comprehension loop over `terms` with
      `concurrent.futures.ThreadPoolExecutor(max_workers=VERIFY_WORKERS)`.
      — done when: `test_glossary_verify.py` passes; manual test shows 4
      concurrent HTTP calls.

- [ ] **C3 — Cache `mux.partners()` by inode.**
      Add a module-level `_partners_cache: dict[tuple[int, int], list[str]] = {}`.
      `partners()` checks cache first; `os.stat(orig)` → `(st_ino, st_dev)` key.
      Cache persists for process lifetime (which is one mux sweep).
      — done when: second call with same inode returns instantly.

- [ ] **C4 — Fix `ordering.read_start()` default path + warning.**
      Change default `path=None`. Resolve from
      `os.environ.get("SEASON_PRIORITY_FILE")`; if still None, return 0
      with `log("ordering: SEASON_PRIORITY_FILE not set — watch-order disabled")`.
      Non-integer values: `log(f"ordering: non-integer start for {show!r}: {val!r}")`
      instead of silently returning 0.
      — done when: `test_ordering.py` tests updated + pass.

- [ ] **C5 — Cache `identify()` in `mux.py`.**
      Add `_identify_cache: dict[str, dict] = {}` at module level.
      `identify(path)` checks cache first (keyed by path). Pass the
      cached `orig_info` through `process()` → `build_cmd()` so
      `build_cmd` doesn't call `identify(orig)` again.
      — done when: `test_mux.py` passes; manual verify shows one `mkvmerge -J`
      call per file (not two).

- [ ] **C6 — Fix `mux.HL_ROOTS` default logic.**
      ```python
      _val = os.environ.get("HARDLINK_ROOTS")
      HL_ROOTS = _val.split(":") if _val else ROOTS
      ```
      — done when: `test_mux.py` passes.

- [ ] **C7 — Add `--dry-run` flag to `anime_library.sh`.**
      If first arg is `--dry-run`: walk the show list, count episodes that
      `needs_work()` would return True for (check for absence of `.done`
      stamp, `.ass` sidecar, `.fail` marker), print "would generate N, repair
      M, mux K" and exit 0. No containers launched.
      — done when: `anime_library.sh --dry-run` prints counts and exits.

- [ ] **C8 — Extract hardcoded patterns to `data/` files.**
      Create `data/common_proper_noun_deny.txt` from `mine_glossary.COMMON`
      (one word per line). Create `data/hallucination_blocklist.txt` from
      `hallucination.BLOCKLIST` (one regex per line, comments allowed).
      Update `mine_glossary.py` and `hallucination.py` to load from data
      files with inline fallbacks.
      — done when: existing tests pass with data files present AND absent.

- [ ] **C9 — Add prompt-injection guard to `repair.build_prompt()`.**
      Wrap the fansub reference: change `ref_line = f"Official subtitle..."`
      to `ref_line = f"<official_subtitle_reference>{sub}</official_subtitle_reference>\n"`.
      — done when: `test_repair.py:test_build_prompt_*` tests updated and pass.

- [ ] **C10 — Log all `os.chown` failures.**
      Audit every `except OSError: pass` after `os.chown` in the codebase
      (found in `generate.py`, `repair.py`, `dub_signs_merge.py`, `mux.py`).
      Replace `pass` with `log(f"chown failed for {p}: {e}")` for each.
      — done when: grep shows no remaining bare `except OSError: pass` after
      `os.chown`.

- [ ] **C11 — Populate Authorization sections in specs.**
      For each existing spec file (`a1-reflow-timing`, `b1-hallucination-gate`,
      `c1-glossary-precision`, `d1-mux-fonts`, `glossary-wiki-verify`),
      fill in the Authorization section: Who can execute (root in container,
      PLEX_TOKEN for refresh, OLLAMA_URL for repair). Behavior without
      permission (repair skips, generate skips, merge skips).
      — done when: `grep -A3 Authorization specs/*/spec.md` shows content
      in all 5 spec files.

- [ ] **C12 — Fix `_glossary_terms()` string cap boundary.**
      Replace `return ", ".join(out)[:1000]` with a loop that accumulates
      terms until adding the next would exceed 1000 chars, then returns.
      — done when: `test_repair.py` tests `test_glossary_terms_no_truncation_mid_name`.

- [ ] **C13 — Clean up `reflow.wrap_balance()` fallback variable.**
      Add a separate `best_max_len` variable. Replace the tuple fallback
      `(max_len, text)` with two variables `best_max_len` and `fallback_text`.
      — done when: `ruff check reflow.py` clean; `test_reflow.py` passes.

- [ ] **C14 — Remove redundant `os.path.samefile()` from `mux.partners()`.**
      Delete the inner `if os.path.samefile(p, orig)` check. Inode+dev is
      the identity.
      — done when: `ruff check mux.py` clean; `test_mux.py` passes.

- [ ] **C15 — Fix CUDA error gating in `generate.py` (#2).**
      Replace the substring match on `"cuda"` in the exception handler
      (`if any(k in str(e).lower() for k in ("cuda", ...))`) with an
      explicit check on the exception type: `isinstance(e, RuntimeError)`
      (faster-whisper raises `RuntimeError` from ctranslate2 for GPU
      errors, while non-CUDA errors like `ZeroDivisionError` that
      coincidentally mention "cuda" in the stacktrace should NOT poison
      the episode). Non-CUDA errors: log + remove the `.fail` marker so
      the episode retries on next sweep. Persist a JSON retry log
      (`<stem>.dubtitles.crash.json` with `{path, exc_type, msg, time}`).
      — done when: `ruff check generate.py` clean; test with monkeypatched
      exception types shows correct behavior (RuntimeError → exit 3,
      ValueError → remove .fail + continue).

- [ ] **C16 — Remove half-size heuristic from `mux.verify()` (#5).**
      In `mux.py::verify()`, delete the line:
      `if not (os.path.exists(out) and os.path.getsize(out) > os.path.getsize(orig) * 0.5): return "too-small"`
      The existing checks below (track-presence, Dubtitles-track, duration
      tolerance) are sufficient to verify a valid mux. The size heuristic
      false-positively rejects compact muxes where mkvmerge shrinks the
      CUES or a large embedded `.ass` is dropped.
      FIRST verify the duration-tolerance check is on every "ok" return path
      (it is the real truncation canary once the size gate is gone); if a path
      can pass without a duration comparison, fix that in the same commit.
      — done when: `ruff check mux.py` clean; `test_mux.py` passes;
      `grep "too-small" mux.py` returns nothing; a test asserts a truncated
      output (short duration) still fails `verify()`.

---

## Phase D — Signs/Songs Low-Priority

- [ ] **D1 — Add style collision logging to `dub_signs_merge.build()`.**
      In the `for sname, sty in subs.styles.items()` loop, when `sname in
      base.styles`, compare `fontname` and `fontsize`. If either differs:
      `log(f"  style conflict: '{sname}' — font/size differ, using first definition")`.
      — done when: `ruff check dub_signs_merge.py` clean.

- [ ] **D2 — Add font embedding audit to `mux.verify()`.**
      After existing track-presence checks, count font attachments:
      ```python
      src_fonts = [t for t in identify(orig)["tracks"] if t["type"] == "attachments"]
      out_fonts = [t for t in info["tracks"] if t["type"] == "attachments"]
      if len(src_fonts) != len(out_fonts):
          return "font-count-mismatch"
      ```
      Bonus: check MIME type is font-like (not `application/octet-stream`),
      log warning if not.
      — done when: `test_mux.py` updated.

- [ ] **D3 — Log `WrapStyle` values in `build()`.**
      After `base = subs`, check `base.info.get("WrapStyle")`. For each
      subsequent track, compare. If they differ: `log(f"WrapStyle differs:
      base={base_ws} track={track_ws} — using base")`.
      — done when: `ruff check dub_signs_merge.py` clean.

- [ ] **D4 — Force `ScaledBorderAndShadow: yes` in `build()`.**
      After `base = subs`, add: `base.info["ScaledBorderAndShadow"] = "yes"`.
      This ensures consistent rendering across Plex, mpv, VLC.
      — done when: saved `.ass` file has `ScaledBorderAndShadow: yes` in header.

- [ ] **D5 — Add resolution mismatch check to `build()`.**
      After the `for n, idx in enumerate(eng_sub_streams(video))` loop,
      collect `(PlayResX, PlayResY)` from each track. If they differ:
      `log("WARNING: resolution mismatch between subtitle tracks — signs may
      be mispositioned")`. Don't transform coordinates (deferred to V3).
      — done when: `ruff check dub_signs_merge.py` clean.

---

## Closing (the *close* phase of `dev-lifecycle` — always keep last)

- [ ] Full test suite: `pytest -q` passes all existing + new tests;
      `ruff check .` clean on all changed files.
- [ ] Manual integration test: build `Dockerfile.builder`, run one show
      through container_run.sh, verify no regressions.
- [ ] Push the branch to origin — done when: branch published.
- [ ] Draft the PRs (Summary / Notable Decisions / Test Plan) and
      **pause for approval** — done when: user approved.

## Done

<move tasks marked [x] here as you progress, preserving the done criterion>
