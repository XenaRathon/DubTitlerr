# Tasks — V1 Polish: Accuracy, Signs Preservation & Code Quality

> Persistent memory between sessions. New session: read `spec.md` + this file and
> check out the branch below before anything else.
> Legend: `[ ]` pending · `[~]` in progress · `[x]` done.

**Branch:** `feat/v1-polish` (base: `main`)

Rules: each task ≤ ~1h, dependency-ordered, verifiable done criterion. Before
`[x]`: gates green (ruff · pytest). 1 task = 1 conventional commit.

**Execution order (resolves the phase-number vs. test-first tension):** the
phase *numbers* are a grouping, not the literal commit order. Execute:
Phase 1 (foundation) → **write T14's signs/layer tests before T12/T13** (the
`test_layer_ordering` assertion encodes the correct ASS z-order — higher layer
on top — and is what guards the layer-normalization fix from regressing) →
T12/T13 implementation → Phase 3 accuracy → T18/T19 (additive coverage of
existing untested `needs_work()` / `mine_text()`; order among themselves is
free). In short: for the signs work, test-first; the other Phase-4 tests are
independent coverage that can land anywhere after Phase 1.

---

## Phase 1 — Foundation: `common.py` + deps + CI

- [ ] **T1 — Create `common.py` with stamp helpers + MEDIA_UID/GID/log.**
      Extract `read_stamp`, `write_stamp`, `stamp_valid`, `STAMP_SUFFIX` from
      `mux.py`. Extract `MEDIA_UID`, `MEDIA_GID` resolution pattern (env→int
      with defaults 1000/100). Extract `log(*a)` helper. All pure stdlib.
      — done when: `ruff check common.py` clean; `python -c "import common"` succeeds.

- [ ] **T2 — Add `out_for`, `ts_srt`, `VIDEO_EXTS`, `EXTRA_DIRS` to `common.py`.**
      Extract `out_for` from `generate.py` (the os.makedirs variant — safe superset).
      Extract `ts` from `generate.py` as `ts_srt`. Extract `VIDEO_EXTS` as
      `(".mkv", ".mp4", ".m4v")`. Extract `EXTRA_DIRS` set. All pure stdlib.
      — done when: `ruff check common.py` clean; module imports without error.

- [ ] **T3 — Add `find_video`, `eng_sub_streams`, `extract_sub` to `common.py`.**
      Extract `find_video` from `repair.py` (uses `VIDEO_EXTS`). Extract
      `eng_sub_streams` — unified implementation checking `codec_name in ("ass", "ssa")`
      (correct for both `repair.py` and `dub_signs_merge.py` consumers). Extract
      `extract` as `extract_sub`. Requires `subprocess`, `json`, `tempfile` in
      `common.py`.
      — done when: `ruff check common.py` clean; `python -c "import common"` succeeds.

- [ ] **T4 — Update `mux.py` imports.**
      Replace local stamp helpers, `MEDIA_UID`, `MEDIA_GID`, `log` with
      `from common import ...`. Keep `IDENTIFY` caching (opportunistic: wrap
      `identify()` with a dict cache keyed by path to eliminate the double-call
      noted in #32).
      — done when: existing `tests/test_mux.py` passes with updated imports.

- [ ] **T5 — Update `generate.py` imports + beam_size env var.**
      Replace `import mux` and local `out_for`, `ts`, `EXTRA_DIRS` with
      `from common import ...`. Change hardcoded `beam_size=5` to
      `int(os.environ.get("WHISPER_BEAM_SIZE", "7"))`. Add `best_of=beam_size`.
      — done when: `ruff check generate.py` clean; `python -c "import ast; ast.parse(open('generate.py').read())"` ok.

- [ ] **T6 — Update `repair.py` imports.**
      Replace local `out_for`, `ts`, `find_video`, `eng_sub_streams`, `extract`,
      `VIDEO_EXTS`, `MEDIA_UID`, `MEDIA_GID` with `from common import ...`.
      — done when: `ruff check repair.py` clean; existing `tests/test_repair.py` passes.

- [ ] **T7 — Update `dub_signs_merge.py` imports.**
      Replace local `find_video`, `eng_sub_streams`, `extract`, `VIDEO_EXTS`,
      `MEDIA_UID`, `MEDIA_GID`, `out_for`, `log` with `from common import ...`.
      — done when: `ruff check dub_signs_merge.py` clean; `python -c "import ast; ast.parse(open('dub_signs_merge.py').read())"` ok.

- [ ] **T8 — Update `mine_glossary.py` and `recreate_srt.py` imports.**
      `mine_glossary.py`: replace local `EXTRA_DIRS` with `from common import EXTRA_DIRS`.
      `recreate_srt.py`: replace local `ts` with `from common import ts_srt`.
      — done when: `ruff check` clean on both files; `python -c "import ast; ast.parse(...)"` ok for both.

- [ ] **T9 — Add `[project]` section to `pyproject.toml`.**
      ```toml
      [project]
      name = "dubtitlerr"
      requires-python = ">=3.11"
      dependencies = ["pysubs2>=1.7", "faster-whisper>=1.2"]
      [project.optional-dependencies]
      dev = ["pytest", "ruff"]
      ```
      — done when: `ruff check pyproject.toml` clean; existing `pip install -e ".[dev]"` succeeds.

- [ ] **T10 — Create `.github/workflows/test.yml`.**
      ```yaml
      name: tests
      on: [push, pull_request]
      jobs:
        test:
          runs-on: ubuntu-latest
          steps:
            - uses: actions/checkout@v4
            - uses: actions/setup-python@v5
              with: { python-version: '3.13' }
            - run: pip install pysubs2 pytest
            - run: pytest -q
      ```
      — done when: YAML is valid; CI triggers on push (verifiable on GitHub after PR).

- [ ] **T11 — Full test suite gate.**
      Run `pytest -q` and `ruff check .` — all 88 existing tests must pass,
      ruff clean on all changed files. Fix any import-related breakage.
      — done when: `pytest -q` exit 0; `ruff check .` exit 0.

---

## Phase 2 — Signs/songs visual bug fixes

- [ ] **T12 — Add `HAS_DRAWING` + `ANIMATED` regexes and update `keep_event()`.**
      In `dub_signs_merge.py`, add module-level:
      ```python
      HAS_DRAWING = re.compile(r"\\p\d|\\clip|\\iclip")
      ANIMATED = re.compile(r"\\t\(|\\fade?\(|\\move\(")
      ```
      In `keep_event()`, after the `KARAOKE` check and before `POSITIONED`,
      add checks for `HAS_DRAWING` and `ANIMATED`. (Merge `ANIMATED` into
      the existing `POSITIONED` check — `\\move` is already there.)
      — done when: `ruff check dub_signs_merge.py` clean.

- [ ] **T13 — Add layer normalization in `build()`.**
      After the `for ev in dub:` loop in `build()`, add. NOTE: in ASS a
      **higher** layer renders ON TOP (libass ASS File Format Guide) — dialogue
      must be on the *lowest* layer. Shift signs up by one rather than zeroing
      them so intentional inter-sign layering is preserved:
      ```python
      # Dubtitles dialogue on the floor (layer 0); every sign/song event bumped
      # one layer up so it renders on top. Shift (not zero) keeps the relative
      # z-order among multi-layer sign compositions.
      for ev in base.events:
          if ev.style == "Dubtitles":
              ev.layer = 0
          else:
              ev.layer = ev.layer + 1
      ```
      — done when: `ruff check dub_signs_merge.py` clean.

- [ ] **T14 — Write `tests/test_dub_signs_merge.py` (keeper + layer tests).**
      Using the Phase 4 test-first pattern, write:
      - `test_keep_event_drops_plain_dialogue`
      - `test_keep_event_keeps_karaoke`
      - `test_keep_event_keeps_positioned`
      - `test_keep_event_keeps_drawing_p1`
      - `test_keep_event_keeps_drawing_clip`
      - `test_keep_event_keeps_animated_transform`
      - `test_keep_event_keeps_animated_fade`
      - `test_keep_event_drops_translation_style_despite_karaoke`
      - `test_layer_ordering_dub_below_signs` (dialogue → layer 0; a sign
        originally on layer 0 → layer 1; two signs on layers 0 and 1 stay in
        that relative order — dialogue strictly below every sign)
      — done when: all new tests pass; `ruff check tests/test_dub_signs_merge.py` clean.

---

## Phase 3 — Accuracy improvements

- [ ] **T15 — Add prev/next context to `repair.build_prompt()`.**
      Add `prev_text: str = ""` and `next_text: str = ""` parameters.
      When non-empty, include in prompt:
      ```
      Previous line (for context): "{prev_text}"
      ...
      Next line (for context): "{next_text}"
      ```
      Update existing tests in `test_repair.py` for the new signature (existing
      callers pass no prev/next → produces same prompt as before).
      — done when: existing `test_repair.py` passes; new test
      `test_build_prompt_includes_context` passes.

- [ ] **T16 — Pass surrounding lines from `repair.process()`.**
      In `process()`, for each target at index `i` in the `conf` list:
      - `prev = conf[i-1]["text"] if i > 0 else ""`
      - `next = conf[i+1]["text"] if i+1 < len(conf) else ""`
      - Pass both to `build_prompt(c["text"], ref, gloss, prev, next)`
      — done when: `ruff check repair.py` clean; `python -c "import ast; ast.parse(open('repair.py').read())"` ok.

- [ ] **T17 — Fix `is_target()` fencepost (`>=` → `>`).**
      Change `c.get("no_speech_prob", 1.0) >= NSP_MAX` to `> NSP_MAX`.
      Add `test_is_target_fencepost` to `test_repair.py` verifying a card
      at exactly 0.5 nsp is now treated as a target (speech).
      — done when: existing repair tests + new fencepost test pass.

---

## Phase 4 — Test coverage for load-bearing gaps

> Ordering: T14 (signs/layer classifier tests) is written **before** its
> implementation in T12/T13 — see the execution-order note at the top. T18/T19
> below are additive coverage of already-existing untested functions and can
> land any time after Phase 1.

- [ ] **T18 — Write `tests/test_generate.py::test_needs_work_matrix`.**
      Using `tmp_path` fixtures:
      1. muxed stamp present → `needs_work()` returns False
      2. `.ass` sidecar present → False
      3. `.srt` sidecar + `SKIP_IF_SRT=1` → False
      4. `.fail` marker present → False (poison)
      5. No sidecar/marker → True (needs work)
      6. Stamp with stale size (file replaced) → True (needs re-mux)
      7. ffprobe says Dubtitles track present but no stamp → False (backstop)
      — done when: all 7 cases pass; `ruff check tests/test_generate.py` clean.

- [ ] **T19 — Write `tests/test_mine_glossary.py::test_mine_text`.**
      Test the `mine_text()` function:
      - Capitalized word mid-sentence → counted + added to `midsentence`
      - Capitalized word at sentence start → counted, NOT added to `midsentence`
      - Lowercase word → ignored
      - Word in COMMON set → ignored
      - Word shorter than 3 chars → ignored
      — done when: all cases pass; `ruff check tests/test_mine_glossary.py` clean.

- [ ] **T20 — Write `tests/test_dub_signs_merge.py` (already done as T14 above).**
      Reference — this task is T14, included here for phase completeness.

---

## Closing (the *close* phase of `dev-lifecycle` — always keep last)

- [ ] Evolve tests/CI: confirm `pytest -q` passes all 88 existing + new tests;
      `ruff check .` clean on all files. CI workflow triggers on push.
      — done when: pipeline green.
- [ ] Push the branch to origin — done when: branch published.
- [ ] Draft the PR (Summary / Notable Decisions / Test Plan, in English) and
      **pause for approval** — done when: user approved title + description.

## Done

<move tasks marked [x] here as you progress, preserving the done criterion>
