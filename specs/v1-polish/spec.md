# Spec — V1 Polish: Accuracy, Signs Preservation & Code Quality

> Comprehensive implementation spec distilling 56 review recommendations from two
> independent code reviews (Claude Opus 4.8 + DeepSeek v4 Pro, 2026-07-24) and a
> targeted accuracy/signs-formatting deep-dive. See `REVIEW.md` for full rationale.

## Context and problem

DubTitlerr works — it reliably transcribes, repairs, assembles, and muxes
dubtitles for 65+ anime shows. But two independent reviews surfaced a common
pattern: the **seams between stages** are where quality leaks. Duplicated helpers
drift out of sync. The signs/songs merge silently drops vector-drawn signs and
renders dialogue on top of positioned signs. The LLM repair sends single lines
with zero dialogue context. The Whisper beam size and model choice haven't been
revisited since initial setup. And there are zero tests for the gate that
determines whether a 12-hour library sweep is fast or wasteful (`needs_work()`).

This spec packages the highest-leverage fixes into a single cohesive push:
eliminate the helper duplication to make all subsequent changes safe, fix the
two visual-corruption bugs in the signs merge, add dialogue context to the LLM
repair prompt, bump Whisper accuracy, and add the tests that make regressions
visible.

## Acceptance criteria (verifiable)

### Phase 1 — Foundation (common.py + deps + CI)

- [ ] `common.py` exists and is imported by `generate.py`, `mux.py`, `repair.py`,
      `dub_signs_merge.py`, `recreate_srt.py`, `mine_glossary.py`.
- [ ] All 8 duplicated helpers (`out_for`, `ts_srt`, `find_video`,
      `eng_sub_streams`, `extract`, `VIDEO_EXTS`, `EXTRA_DIRS`, stamp helpers)
      have exactly ONE definition in `common.py`.
- [ ] `VIDEO_EXTS` is consistent across all consumers: `(".mkv", ".mp4", ".m4v")`.
- [ ] `pyproject.toml` has a `[project]` section with dependencies declared
      (`pysubs2>=1.7`, `faster-whisper>=1.2`) and dev extras (`pytest`, `ruff`).
- [ ] `.github/workflows/test.yml` exists and runs `pytest -q` on push/PR.
- [ ] All existing tests pass with imports updated to use `common.py`.
- [ ] `ruff check` clean on all changed files.

### Phase 2 — Signs/songs visual bug fixes (items #49, #50, #51)

- [ ] `keep_event()` returns True for events containing `\p\d`, `\clip`, or
      `\iclip` (ASS drawing commands) — vector-drawn signs are no longer dropped.
- [ ] `keep_event()` returns True for events containing `\t(`, `\fade(`, or
      `\fad(` (ASS animation tags) — animated sign overlays preserved.
- [ ] After merging events in `build()`, all Dubtitles events have layer 0 and
      every sign/song event is shifted to `old_layer + 1` — positioned signs
      always render on top of dialogue. (In ASS, **higher** layer = on top;
      shifting rather than zeroing preserves relative inter-sign z-order.)
- [ ] `tests/test_dub_signs_merge.py` exists with at minimum:
  - A `test_keep_event_matrix` covering: plain dialogue → drop, `\k` karaoke →
    keep, `\pos` sign → keep, `\p1` drawing → keep, `\clip` → keep, `\t(` anim
    → keep, `\fade` → keep, `Translation` style → drop even with karaoke tags.
  - A `test_layer_ordering` verifying Dubtitles events get layer 0 and every
    sign event ends up on a strictly higher layer than the dialogue after
    `build()` (and that two signs originally on layers 0 and 1 remain in that
    relative order).

### Phase 3 — Accuracy improvements (items #42, #43, #27)

- [ ] `WHISPER_BEAM_SIZE` env var controls `beam_size` in `generate.py:transcribe()`,
      default 7 (was hardcoded 5). `best_of` set to the same value.
- [ ] `repair.build_prompt()` accepts optional `prev_text` and `next_text`
      parameters and includes them in the prompt as context lines when present.
- [ ] `repair.process()` passes the surrounding 1–2 cards' text to
      `build_prompt()` for each target line (using the target's index in the
      `conf` list).
- [ ] `repair.is_target()` uses `>` not `>=` for the NSP_MAX comparison
      (fencepost fix: a card at exactly 0.5 nsp is now treated as speech).
- [ ] Existing repair tests (`test_repair.py`) updated for the new
      `build_prompt()` signature; new test verifying prev/next lines appear in
      the prompt.

### Phase 4 — Test coverage for load-bearing gaps (items #9, #33)

- [ ] `tests/test_generate.py` exists with `test_needs_work_matrix` covering:
      muxed stamp → skip, `.ass` present → skip, `.srt`+`SKIP_IF_SRT` → skip,
      `.fail` → skip, no marker → needs_work, stale stamp → needs_work,
      ffprobe Dubtitles track present → skip.
- [ ] `tests/test_dub_signs_merge.py` exists (see Phase 2 criteria).
- [ ] `tests/test_mine_glossary.py` exists with `test_mine_text` covering:
      basic capitalized word counting, midsentence-only tracking, COMMON word
      filtering, sentence-initial capitalization exclusion.

## Out of scope (explicit)

- **Model bake-off or model change** — trying `large-v3-turbo` (#41), the 35B
  MoE repair model (#44), two-pass repair (#47), and phonetic matching (#45)
  are all deferred to a follow-up spec. They need hardware testing and/or new
  API adapters that shouldn't block the code-quality and bug-fix push.
- **Shell script changes** — deprecating `anime_library.sh`/`all_seasons.sh`
  (#20), fixing `merge_watcher.sh` (#21), the Dockerfile rename (#22), `set -e`
  in `gen_loop.sh` (#23), shell dependency self-healing (#24), and EXTRA_DIRS
  consolidation (#25) are deferred to a separate ops-focused spec.
- **Structured logging / state.json** (#6) — deferred to the Web UI data-layer
  spec.
- **Remaining low-priority items** — #7 (parallel glossary verify), #8 (partners
  caching), #10 (ordering fallback), #12-#19, #28-#30, #32, #34, #36-#40,
  #46, #48, #52-#56 are deferred to future specs or picked up opportunistically.
- **`common.py` beyond the 8 duplicated symbols** — this spec creates the module
  and migrates the duplicated helpers. Further refactoring (e.g., extracting
  ASS regexes from `repair.py`/`dub_signs_merge.py`, building a shared `llm()`
  function) is deferred.

## Data contracts

- **Inputs:** Existing Python source files, test files, `pyproject.toml`.
  No new runtime data formats or env vars beyond `WHISPER_BEAM_SIZE`.
- **Outputs:**
  - `common.py` — new module exporting: `out_for`, `ts_srt`, `find_video`,
    `eng_sub_streams`, `extract_sub`, `VIDEO_EXTS`, `EXTRA_DIRS`,
    `read_stamp`, `write_stamp`, `stamp_valid`, `STAMP_SUFFIX`,
    `MEDIA_UID`, `MEDIA_GID`, `log`.
  - Updated imports in 6 consumer modules.
  - `tests/test_dub_signs_merge.py` — new test file.
  - `tests/test_generate.py` — new test file.
  - `tests/test_mine_glossary.py` — new test file.
  - `.github/workflows/test.yml` — new CI workflow.
- **Schemas affected:** `pyproject.toml` gains `[project]` section.
  `dubtitles.conf.json` format unchanged. `.dubtitles.done` stamp format unchanged.
- **External dependencies:** None new. `common.py` is stdlib-only.
  `pysubs2` and `faster-whisper` already in use; only declared now.

## Edge cases and failure modes

| Case                                                          | Expected behavior                                                                                                   |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Consumer imports `common.MEDIA_UID` before env is set         | Module reads env at import time (existing pattern); test with `monkeypatch.setenv`                                  |
| `build_prompt()` called without prev/next (existing callers)  | Backward-compatible: `prev_text=""` and `next_text=""` defaults produce the same prompt as today                    |
| `keep_event()` receives event with `\p0` (disable drawing)    | `\p\d` matches `\p0` — treated as drawing-capable event, kept. Acceptable false positive (dialogue never uses `\p`) |
| `WHISPER_BEAM_SIZE` unset or non-integer                      | Default to 7; `ValueError` on non-integer → log warning and fall back to 7                                          |
| `needs_work()` test with tmp_path file missing                | Test creates its own temp files via `tmp_path`; no live media dependency                                            |
| CI runner has no `pysubs2`                                    | Declared in `pip install pysubs2 pytest` in the workflow YAML                                                       |
| Stamp helpers moved to `common` but `mux.py` still needs them | `mux.py` imports from `common`; `common` owns the single definition                                                 |

## Decisions taken

| Decision                                                       | Rejected alternative                       | Why                                                                                                                                                           |
| -------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `common.py` owns stamp helpers, not `mux.py`                   | Keep stamps in `mux.py`, import from there | `generate.py` needs stamp helpers but shouldn't import all of `mux` (drags in argparse, subprocess, mkvmerge). Single source of truth wins.                   |
| `WHISPER_BEAM_SIZE` defaults to 7                              | Keep 5, make it env-configurable later     | The turbo model (#41, deferred) buys back speed; 7 is a net quality win on `large-v3` at ~15% slower. Configurable so it can be tuned per-GPU.                |
| `keep_event()` adds new regexes as module-level constants      | Inline regex in the function               | Consistent with existing `KARAOKE`/`POSITIONED`/`KEEP_STYLE`/`DROP_STYLE` pattern. Testable independently.                                                    |
| Layer normalization happens AFTER all events are appended      | Set layer on append                        | Events are appended from multiple tracks; the final pass guarantees correctness regardless of append order.                                                   |
| Phase gating: foundation first, then signs bugs, then accuracy | All at once                                | The `common.py` extraction touches 6 files; doing it first makes all subsequent changes cleaner. Bug fixes before enhancements.                               |
| Defer model/LLM changes to follow-up spec                      | Bundle everything                          | Model changes need hardware bake-off (#44) or new library dependencies (#45, needs `jellyfish`). Code-quality fixes shouldn't be blocked on bake-off results. |

## Constraints

- **No regression:** All 88 existing tests must pass. `ruff check` must stay clean
  (line-length 130, target py39, select E/F/I/W/UP/B, ignore E701/E702).
- **Backward-compatible:** `build_prompt(ASR, sub, gloss)` still works without
  prev/next args. All env var defaults unchanged. `.dubtitles.done` stamp format
  unchanged.
- **Deterministic:** `common.py` helpers are pure functions or idempotent stat
  readers. No new randomness or network calls.
- **No new runtime dependencies:** `common.py` and test files use stdlib only
  (plus `pysubs2` in tests, already required).

## Open questions (risks)

- [ ] **Whisper beam_size=7 on the GTX 1060 6GB** — confirmed to fit at int8?
      Low risk (beam search uses the same model; only the decoder runs more
      candidates). If it OOMs, the env var makes it trivially tunable to 5.
- [ ] **`eng_sub_streams()` / `extract()` dedup** — `repair.py` and
      `dub_signs_merge.py` use identical copies. Extracting to `common.py` is
      straightforward, but `repair.py`'s variant additionally checks for
      `codec_name in ("ass", "ssa")` while the merge variant also allows SRT
      (`"subrip"`). Verify the single implementation handles both cases correctly.
- [ ] **`out_for()` subtle drift** — `generate.py`'s version creates intermediate
      directories (`os.makedirs`); `repair.py`'s version does NOT. The common
      version must create dirs (safe superset), and repair's callers must not
      rely on the old non-creating behavior (they don't — they write to existing
      dirs).
