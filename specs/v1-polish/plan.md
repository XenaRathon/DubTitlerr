# Plan — V1 Polish: Accuracy, Signs Preservation & Code Quality

> Only write this after `spec.md` is approved.
> An approved plan triggers the **kickoff** phase of the `dev-lifecycle` skill (branch creation).

## Branch and delivery

- **Branch:** `feat/v1-polish` (base: `main`)
- **PR slicing:** Single PR. All four phases are interdependent (Phase 1's
  `common.py` extraction is a prerequisite for clean diffs in Phases 2–4;
  Phase 4's tests validate Phases 2–3). Splitting would create churn in the
  PR review cycle.

## Technical approach

Execute in strict phase order: **Foundation → Signs Bugs → Accuracy → Tests**.

Phase 1 creates `common.py` by extracting the 8 duplicated helpers from their
current homes, then updates all 6 consumer modules to import from `common`
instead of redefining. The stamp helpers (`read_stamp`, `write_stamp`,
`stamp_valid`, `STAMP_SUFFIX`) are owned by `common`, not `mux` — `generate.py`
needs them but should never import all of `mux` (which drags in argparse,
subprocess, mkvmerge). `VIDEO_EXTS` is harmonized to `(".mkv", ".mp4", ".m4v")`
everywhere. `out_for()` is the `generate.py` variant (creates intermediate dirs,
which is a safe superset). Phase 1 also adds the `[project]` section to
`pyproject.toml` and the CI workflow.

Phase 2 adds two module-level regexes (`HAS_DRAWING`, `ANIMATED`) to
`dub_signs_merge.py` and checks them in `keep_event()` after the existing
`KARAOKE` check. Then adds a 6-line layer-normalization pass at the end of
`build()`, after all events are appended. This is backward-compatible: existing
signs with layer 0 are unchanged, signs with higher layers are moved to 0
(above dialogue), and Dubtitles dialogue moves to layer 1.

Phase 3 makes `beam_size` in `generate.py` read from `WHISPER_BEAM_SIZE` env
var (default 7). In `repair.py`, `build_prompt()` gains `prev_text=""` and
`next_text=""` parameters; when non-empty, they're included as context lines
in the prompt. `process()` passes `conf[i-1]["text"]` and `conf[i+1]["text"]`
when those indices exist. The `>=` → `>` fencepost fix in `is_target()` is a
one-character change.

Phase 4 writes three new test files using the project's existing test patterns
(`tmp_path` for file I/O, `monkeypatch` for env vars, plain dicts for event
fixtures). Each test file targets one load-bearing untested function.

## Affected files (by layer)

| Layer           | File                            | Change                                                                                                                                                                                                                                 |
| --------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| New module      | `common.py`                     | Create: `out_for`, `ts_srt`, `find_video`, `eng_sub_streams`, `extract_sub`, `VIDEO_EXTS`, `EXTRA_DIRS`, `read_stamp`, `write_stamp`, `stamp_valid`, `STAMP_SUFFIX`, `MEDIA_UID`, `MEDIA_GID`, `log`                                   |
| Transcription   | `generate.py`                   | Remove `out_for`, `ts`, `EXTRA_DIRS` definitions; remove `import mux`; import from `common`; `beam_size` → `WHISPER_BEAM_SIZE` env var                                                                                                 |
| Mux             | `mux.py`                        | Remove stamp helpers, `MEDIA_UID`, `MEDIA_GID`, `log`; import from `common`; keep `IDENTIFY` caching (out of scope but opportunistic)                                                                                                  |
| Repair          | `repair.py`                     | Remove `out_for`, `ts`, `find_video`, `eng_sub_streams`, `extract`, `VIDEO_EXTS`, `MEDIA_UID`, `MEDIA_GID`; import from `common`; `build_prompt()` + prev/next params; `is_target()` fencepost; `process()` passes surrounding lines   |
| Signs merge     | `dub_signs_merge.py`            | Remove `find_video`, `eng_sub_streams`, `extract`, `VIDEO_EXTS`, `MEDIA_UID`, `MEDIA_GID`, `out_for`, `log`; import from `common`; add `HAS_DRAWING` + `ANIMATED` regexes; update `keep_event()`; add layer normalization in `build()` |
| Glossary mining | `mine_glossary.py`              | Remove `EXTRA_DIRS`; import from `common`                                                                                                                                                                                              |
| SRT rebuild     | `recreate_srt.py`               | Remove `ts`; import from `common`                                                                                                                                                                                                      |
| Config          | `pyproject.toml`                | Add `[project]` section with `dependencies` and `[project.optional-dependencies]`                                                                                                                                                      |
| CI              | `.github/workflows/test.yml`    | Create: checkout → setup-python → pip install pysubs2 pytest → pytest -q                                                                                                                                                               |
| Tests (new)     | `tests/test_dub_signs_merge.py` | `test_keep_event_matrix`, `test_layer_ordering`                                                                                                                                                                                        |
| Tests (new)     | `tests/test_generate.py`        | `test_needs_work_matrix` (7 cases)                                                                                                                                                                                                     |
| Tests (new)     | `tests/test_mine_glossary.py`   | `test_mine_text` (capitalization, mid-sentence, filtering)                                                                                                                                                                             |
| Tests (update)  | `tests/test_repair.py`          | Update `test_build_prompt_*` for new signature; add `test_build_prompt_includes_context`; add `test_is_target_fencepost`                                                                                                               |
| Tests (update)  | `tests/test_mux.py`             | Update imports to use `common` instead of `mux` for stamp helpers                                                                                                                                                                      |

## Risks and mitigation

| Risk                                                                                          | Mitigation                                                                                                                                                                                                                                    |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `common.py` extraction breaks an import edge case (circular import, module-level side effect) | `common.py` is pure stdlib with zero imports from other project modules — no circular import possible. Phase 1 is purely moving code, no logic changes.                                                                                       |
| `eng_sub_streams()` unified implementation misses a codec_name edge case                      | `repair.py` needs ASS/SSA only; `dub_signs_merge.py` also needs ASS/SSA (the "subrip" branch is for `mine_glossary.py`, which doesn't use `eng_sub_streams`). Single implementation checks for `("ass", "ssa")` — correct for both consumers. |
| `keep_event()` drawing-check false positive on `\p0` (disable drawing)                        | Dialogue never uses `\p`. The false-positive rate is effectively zero. If it ever occurs, the event is kept (rendered normally, no visual corruption) — strictly better than dropping a real sign.                                            |
| Beam size 7 OOMs the GTX 1060 6GB                                                             | `WHISPER_BEAM_SIZE` env var means no code change needed to revert to 5. Test on a single short episode first.                                                                                                                                 |
| CI fails because `pysubs2` or test deps aren't available                                      | GitHub Actions `ubuntu-latest` has pip; `pysubs2` is pure Python on PyPI. The workflow YAML explicitly installs it.                                                                                                                           |

## Rollback and reversibility

- Reverting the PR is sufficient for all changes. No data migration, no schema
  change, no irreversible side effects.
- The `common.py` extraction is purely a code reorganization — the runtime
  behavior of all functions is preserved (verified by existing tests).
- New test files are additive and don't affect production behavior.

## Testing strategy

- **Unit:** All new Phase 4 test files target pure functions (no network, no
  GPU, no subprocess). `test_keep_event_matrix` uses plain `pysubs2.SSAEvent()`
  objects. `test_needs_work_matrix` uses `tmp_path` fixtures. `test_mine_text`
  is pure string processing.
- **Integration:** None new. The existing test suite (88 tests across 7 files)
  serves as the regression gate for the `common.py` extraction.
- **Target coverage:** All new public functions in `common.py` exercised by
  existing tests (no new coverage gaps). Phase 4 test files target previously
  uncovered code paths in `dub_signs_merge.py`, `generate.py`, and
  `mine_glossary.py`.

## Observability / performance

- No new LLM calls. `common.py` extraction has zero runtime overhead (same
  functions, different import path).
- Beam size 5→7 adds ~15% to Whisper inference time per episode. On the
  existing `large-v3` model at int8, this is ~40→46 seconds per 24-minute
  episode. Acceptable trade for the accuracy gain; tunable via env var.
