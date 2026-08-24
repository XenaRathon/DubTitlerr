# v5-two-tier-idempotency — implementation plan

Status: draft
Spec: `.procoder/specs/v5-two-tier-idempotency.md`

## Goal

Split the single `PIPELINE_VERSION` into a transcription tier and a text tier, and
persist enough state that a text-tier change re-runs on CPU instead of the GPU.

## Architecture

`common.py` grows two version constants and a `stale_tiers()` reader; `generate.py`
writes a `words.json` sidecar after punctuation restore and after reflow's word
transforms, so a replay skips both; `tools/reapply_glossary.py`'s per-episode work
becomes a pipeline-called card-text stage keyed on the stored `initial_prompt`
string. Two independent side quests ride along: an orphan-sidecar reclaim tool and
a guard on implausible `source_*` windows. The model bake-off is sequenced last and
depends on none of it.

## Constraints

Copied from the spec; every task inherits these.

- Adoption constants are `TRANSCRIBE_VERSION = 4`, `TEXT_VERSION = 5`. Setting both
  to 5 re-transcribes 576 live episodes and is wrong.
- Sidecar writes go through `common.out_for()`; existence checks use the raw path
  (mergerfs unifies the branch — `common.py:40-43`, `generate.py:304-305`).
  `words.json` follows the same convention on **both** sides.
- Sidecars are group-writable: `common.SIDECAR_MODE` 0o664, umask 002.
- All writes are temp file + `os.replace`. Stale sidecars are parked (`.stale`),
  never deleted.
- Tests: `python3 -m pytest --ignore=tests/test_boxxo_voice_extract.py`. Baseline
  is **1,108 passing**. Record the new count in each commit message.
- No AI-attribution trailers in commit messages — `procoder check` blocks them.
- Any diagnostic `docker run` against the pipeline image passes an explicit
  `--entrypoint`; `container_run.sh` is the entrypoint and ignores a trailing
  command.
- Production `dubtitle-builder` on vm102 is stopped for the duration. Do not start
  it to test; use fixtures.

## Task 1: Two-tier version constants

Files: `common.py` (replace `PIPELINE_VERSION`, add `stale_tiers`),
`tests/test_common.py` (new cases).
Interfaces: produces `common.TRANSCRIBE_VERSION: int`, `common.TEXT_VERSION: int`,
`common.stale_tiers(stamp: dict | None, video: str) -> set[str]` returning a subset
of `{"transcribe", "text"}`. `common.stamp_valid(stamp, video) -> bool` keeps its
signature and returns `not stale_tiers(...)` plus the existing file match.
Consumed by Tasks 2, 3, 4, 7.

- [ ] Read `common.py:95-127` — the per-version bump manual and `PIPELINE_VERSION`
      — and `common.py:188-217` (`stamp_version`, `_stamp_matches_file`,
      `stamp_valid`). Every behaviour below must preserve `_stamp_matches_file`'s
      `size` equality and `abs(mtime) < 1.0` tolerance untouched.
- [ ] Write the failing tests in `tests/test_common.py`:

```python
def test_a_v4_stamp_reports_both_tiers_at_four(tmp_path):
    """All 813 live stamps predate tiers. A stamp with only `version` must read as
    both tiers equal to it, and must not raise."""
    import common
    v = tmp_path / "e.mkv"; v.write_bytes(b"x")
    st = v.stat()
    stamp = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True, "version": 4}
    assert common.stale_tiers(stamp, str(v)) == {"text"}


def test_adoption_constants_do_not_retranscribe_the_library():
    """TRANSCRIBE_VERSION must adopt at 4, not 5: 576 live v4 stamps are
    transcribe-fresh and only text-stale. 5/5 burns ~2 GPU-days for a bookkeeping
    change. This asserts the real constants, so it fails if adoption moves."""
    import common
    assert common.TRANSCRIBE_VERSION == 4
    assert common.TEXT_VERSION == 5


def test_a_v2_stamp_is_stale_in_both_tiers(tmp_path):
    import common
    v = tmp_path / "e.mkv"; v.write_bytes(b"x")
    st = v.stat()
    stamp = {"size": st.st_size, "mtime": st.st_mtime, "muxed": True, "version": 2}
    assert common.stale_tiers(stamp, str(v)) == {"transcribe", "text"}


def test_a_renamed_file_is_stale_regardless_of_tiers(tmp_path):
    """size/mtime mismatch outranks the tier read: the stamp describes another file."""
    import common
    v = tmp_path / "e.mkv"; v.write_bytes(b"xx")
    stamp = {"size": 999, "mtime": 0, "muxed": True,
             "transcribe_version": common.TRANSCRIBE_VERSION,
             "text_version": common.TEXT_VERSION}
    assert not common.stamp_valid(stamp, str(v))
```

- [ ] Run `python3 -m pytest tests/test_common.py -k "tier or adoption" -v`.
      Expected: FAIL — `common.stale_tiers` does not exist.
- [ ] Implement. Replace `PIPELINE_VERSION = 4` with the two constants, each
      carrying the ported bump manual. The `TRANSCRIBE_VERSION` docstring must
      list the decoder-affecting settings by name — model, `WHISPER_BEAM_SIZE`,
      compute type, whisper thresholds, `initial_prompt` — and state that changing
      any of them requires a bump, because nothing detects it mechanically.
      `write_stamp` writes both keys; `stamp_version` keeps reading legacy
      `version` and both tiers fall back to it.
- [ ] Run the full suite. Expected: PASS. Update any test pinning
      `PIPELINE_VERSION`; there is one at `tests/test_common.py` and callers in
      `generate.py`, `mux.py`.
- [ ] Commit: `feat(common): split PIPELINE_VERSION into transcribe and text tiers`.

## Task 2: Persist the word list

Files: `generate.py` (write the sidecar, replay path, `SIDECAR_SUFFIXES`),
`common.py` (suffix constant), `tests/test_generate.py`.
Interfaces: consumes `common.TRANSCRIBE_VERSION` from Task 1. Produces
`<stem>.dubtitles.words.json` in the shape given in the spec's Data section, and
qc counters `words_reused`, `words_missing`, `words_version_mismatch`. Consumed by
Task 3 (`initial_prompt`) and Task 7.

- [ ] Read `generate.py:660-760` end to end — `media_duration` at `:666`,
      transcription at `:679-684`, `punctuation.restore` at `:732`,
      `reflow.reflow` at `:737`. Read `reflow.py:398-405` (`card_confidence`) and
      `reflow.py:423-437` (`_clamp_to_segments`) to confirm what segment data is
      load-bearing before choosing what to store.
- [ ] Write the failing test. It must compare a cached run against the **original
      production run**, not against a second cache-shaped run — the review found
      this is the one criterion that can pass while the feature is broken:

```python
def test_a_cached_replay_reproduces_the_original_cards_exactly(tmp_path):
    """The cached path must match the run that wrote the sidecar, on an episode
    where the transforms actually did something: at least one word moved by
    _clamp_to_segments, and at least one segment carrying a non-zero
    no_speech_prob (which lives ONLY on segment dicts and is unrecoverable from
    words -- reflow.py:398-405)."""
    import reflow
    words, segments = _fixture_words_needing_clamp_and_nsp()
    audio_duration = 30.0
    fresh = reflow.reflow(words, segments, audio_duration=audio_duration)
    sidecar = _write_words_json(tmp_path, words, segments, audio_duration)
    cached = _replay_from_words_json(sidecar)
    assert [(c["start"], c["end"], c["text"]) for c in cached] == \
           [(c["start"], c["end"], c["text"]) for c in fresh]
    assert [c["no_speech_prob"] for c in cached] == [c["no_speech_prob"] for c in fresh]
    assert any(c["no_speech_prob"] > 0 for c in fresh), "fixture proves nothing"


def test_a_sidecar_from_an_older_transcribe_version_is_treated_as_absent(tmp_path):
    """A crash between transcription and stamping leaves exactly this."""
    ...
    assert rec.counters["words_version_mismatch"] == 1


def test_words_json_is_written_through_out_for_and_found_again(monkeypatch, tmp_path):
    """Writes redirect onto OUTPUT_ROOT; reads must follow the same convention or
    the cache misses silently and every episode re-transcribes forever."""
```

- [ ] Run them. Expected: FAIL — no sidecar writer exists.
- [ ] Implement the writer. Write **after** `punctuation.restore()` (so the stored
      words are post-punctuation and a replay does not repeat the LLM call) and
      before reflow. Store the words UNTRANSFORMED, exactly as generate holds them:
      reflow's three word transforms are pure and cost microseconds, and
      `_card_word_probs()` joins against this same list, so post-transform storage
      would make the replay diverge for no gain. Persist `segments` as
      `{start, end, no_speech_prob}` per index, plus `audio_duration` from
      `media_duration(wav)` at `generate.py:666`. Temp file + `os.replace`, mode
      `common.SIDECAR_MODE`, path via `out_for()`.
- [ ] Implement the replay path: load, verify `transcribe_version`, and hand
      `(words, segments, audio_duration)` straight to `reflow.reflow`. A missing, truncated or version-behind
      sidecar counts and falls through to full transcription — never raises.
- [ ] Add the suffix to `generate.py:273` `SIDECAR_SUFFIXES` so
      `park_stale_sidecars` parks it; otherwise a parked old sidecar is read by
      the cached path.
- [ ] Run the full suite. Expected: PASS. Record the new count.
- [ ] Commit: `feat(generate): persist the word list so text changes skip the GPU`.

## Task 3: Card-text stage from reapply_glossary

Files: `generate.py` (call the stage, classify by prompt), `tools/reapply_glossary.py`
(extract the per-episode function), `tests/test_reapply_glossary.py` (new).
Interfaces: consumes `words.json`'s `initial_prompt` (Task 2) and
`common.TEXT_VERSION` (Task 1). Produces the `glossary_text_reapplied` counter and
a stamp field recording the glossary the text was corrected against.

- [ ] Read `tools/reapply_glossary.py` in full — particularly `process()` and its
      docstring, which already states the boundary this task formalises: "Anything
      that changes how text is DIVIDED needs a full regenerate; this tool only
      changes what the text SAYS." Read `generate.py:112-118` and `:684` for how
      `initial_prompt` is derived and used, and `generate.py:746-749` for the
      per-line `glossary.correct()` call.
- [ ] Write the failing test — the count matters, not just the flag:

```python
def test_a_hard_fixes_only_edit_marks_nothing_transcription_stale(tmp_path):
    """mine_glossary appends hard_fixes on every sweep of a watched show. Those
    never reach initial_prompt, so they must not re-queue the show for the GPU --
    hashing the glossary FILE would flag every episode."""
    before = _glossary(initial_prompt="Luffy, Zoro", hard_fixes={"hockey": "Haki"})
    after  = _glossary(initial_prompt="Luffy, Zoro", hard_fixes={"hockey": "Haki",
                                                                 "buster": "Buster"})
    assert _newly_transcription_stale(before, after) == 0
    assert _text_reapplied(before, after) == 1


def test_a_prompt_changing_edit_marks_the_episode_transcription_stale():
    before = _glossary(initial_prompt="Luffy, Zoro")
    after  = _glossary(initial_prompt="Luffy, Zoro, Nami")
    assert _newly_transcription_stale(before, after) == 1
```

- [ ] Run them. Expected: FAIL.
- [ ] Extract `process()`'s per-episode body into a function the pipeline can call,
      leaving the CLI intact. Call it from the text tier when the stored
      `initial_prompt` matches but the correction maps differ.
- [ ] Classify: stored `initial_prompt` != current → transcription-stale. Equal but
      correction maps differ → card-text work only.
- [ ] Run the full suite. Expected: PASS.
- [ ] Commit: `feat(glossary): re-apply corrections as a versioned pipeline stage`.

## Task 4: Per-tier staleness counts with a reader

Files: `generate.py` (`lastrun.json` payload), `tests/test_generate.py`.
Interfaces: consumes `common.stale_tiers` (Task 1). Produces `text_stale` and
`transcribe_stale` counts inside the existing `lastrun.json`.

- [ ] Read `generate.py:120-127` and `:934` — the existing `lastrun.json` write.
      This task adds fields to a file that already has a reader; it does not
      create a new artifact. The review's standing lesson is that a number with no
      consumer sits unread (`flag` was decorative for four days; 236 stamps sat at
      v2 for weeks).
- [ ] Write the failing test asserting both counts appear in `lastrun.json` after a
      sweep over a fixture library containing one v2 stamp, one v4 stamp and one
      current stamp. Expected counts: `transcribe_stale == 1`, `text_stale == 2`.
- [ ] Run it. Expected: FAIL.
- [ ] Implement, then verify live: bump `TEXT_VERSION` on a pinned show, sweep,
      and confirm `words_reused > 0` on the following sweep. Record the observed
      numbers in the commit message — a fixture alone does not show a drain.
- [ ] Commit: `feat(qc): per-tier staleness counts in lastrun.json`.

## Task 5: Orphan sidecar reclaim

Files: `tools/reclaim_orphans.py` (new), `tests/test_reclaim_orphans.py` (new).
Interfaces: consumes nothing from other tasks — start here if unblocking work in
parallel. Produces a CLI only.

- [ ] Read `common.py:194-217` (`stamp_version`, `_stamp_matches_file`,
      `stamp_valid`) and `mux.py:325-326` (stem-derived lookup). The tool reuses
      `_stamp_matches_file`'s comparison rather than inventing one.
- [ ] Write the failing tests:

```python
def test_a_renamed_identical_video_is_reclaimed(tmp_path):
    """The 31 orphans matching on size AND mtime."""

def test_a_copied_video_is_reclaimed_only_after_a_content_check(tmp_path):
    """The 15 matching on size but not mtime -- a cp without -p. Size alone is
    numerically safe against coincidence but not against a re-encode that happens
    to land on the same byte count, so --apply requires a content hash."""

def test_a_reencoded_video_is_reported_unrecoverable(tmp_path):

def test_two_orphans_matching_one_video_rekeys_neither(tmp_path):

def test_one_orphan_matching_two_videos_rekeys_neither(tmp_path):

def test_apply_refuses_while_the_pipeline_is_live(tmp_path):
    """generate and mux write and delete exactly the files this renames."""
```

- [ ] Run them. Expected: FAIL — module does not exist.
- [ ] Implement. `--dry-run` is the default and prints, for every size-matched
      candidate, whether mtime agrees and whether a head+tail content hash
      confirms it. `--apply` re-keys only content-confirmed, unambiguous matches.
      The re-key set is exactly: `.dubtitles.done`, `.dubtitles.conf.json`,
      `.dubtitles.qc.json`, `.dubtitles.words.json`, `.eng.dubtitles.srt`,
      `.eng.dubtitles.ass`, `.dubtitles.repair-summary.json`,
      `.dubtitles.unresolved.jsonl`. It must **not** move `.fail`, `.stale` or
      `.muxtmp.mkv`.
- [ ] Run the full suite, then run `--dry-run` against the live library from vm102
      and record the verdict for all 46 size-matched candidates in the commit
      message.
- [ ] Commit: `feat(tools): reclaim sidecars orphaned by external renames`.

## Task 6: Guard the implausible source_* window

Files: `generate.py:266-267` (`_card_word_probs`), `repair.py:410` (`overlap_ref`
call site), `hallucination.py` (reuse `_tick`), `tests/test_repair.py`,
`tests/test_generate.py`.
Interfaces: independent of Tasks 1-5. Produces counters
`rule_source_window_evaluated` / `_activated`.

- [ ] Read the VAD design's §6 (`docs/superpowers/specs/2026-08-21-vad-hang-trim-design.md`)
      and both call sites. Both currently apply `.get("source_start", ...)`
      defaults; the guard must fire **before** the default, or it recreates the
      bug it exists to catch.
- [ ] Write the failing tests:

```python
def test_a_two_word_card_with_an_implausible_window_gets_no_reference():
    """VAD design S6: a 7s window on a one-word card selects whatever fansub line
    falls in it. The correct answer is no reference at all -- NOT the display
    window, because on 99% of gated cards end == source_end exactly, so a display
    fallback reproduces the window just declared invalid."""
    assert repair.overlap_ref_guarded(ivals, card) == ""

def test_a_two_word_card_with_an_implausible_window_gets_no_probabilities():
    assert generate._card_word_probs(card, words) == []

def test_a_three_word_card_with_the_same_window_is_unchanged():

def test_a_card_with_no_source_keys_takes_neither_branch():
    """No fabricated window from a .get() default: the VAD design records two of
    its own measurements invalidated by exactly that."""
    assert rec.counters.get("rule_source_window_activated", 0) == 0
```

- [ ] Run them. Expected: FAIL.
- [ ] Implement, reusing `hallucination._tick` so the counters follow the existing
      liveness pattern.
- [ ] Run the full suite. Expected: PASS.
- [ ] Commit: `fix(repair): stop trusting a word timestamp proven implausible`.

## Task 7: Split the model-load gate

Files: `generate.py:886-888`, `tests/test_generate.py`.
Interfaces: consumes `common.stale_tiers` (Task 1) and the replay path (Task 2).

- [ ] Read `generate.py:880-895`. `WhisperModel` loads whenever `todo` is
      non-empty, which costs ~40 s and, for a text-only population, loads the model
      to do zero transcription — the cheap tier quietly is not cheap.
- [ ] Write the failing test: a stale population containing only text-tier episodes
      completes without constructing `WhisperModel`. Assert on the absence of the
      construction (monkeypatch it to raise), not on elapsed time.
- [ ] Run it. Expected: FAIL.
- [ ] Implement: partition `todo` into text-todo and transcribe-todo; load the
      model only if transcribe-todo is non-empty.
- [ ] Run the full suite. Expected: PASS.
- [ ] Commit: `perf(generate): do not load whisper for a text-only sweep`.

## Task 8: Model bake-off

Files: `tools/model_bakeoff.py` (new), `tests/test_model_bakeoff.py` (new).
Interfaces: depends on Tasks 1-7 being merged; produces a JSON report only. Runs no
sweep and changes no pipeline behaviour.

- [ ] Evict `llama-embed` from the 1050 Ti so `large-v3` has the full 4 GB, and
      record `nvidia-smi` before and after. The card moved to VM102 on 2026-08-23;
      the E5-2450 is 2.1 GHz against the 3200G's 3.6 GHz, so prior
      minutes-per-episode figures do not transfer and must be re-measured here.
- [ ] Write the test for the report shape: each entrant yields catch rate at
      matched precision, minutes per episode, and peak VRAM; an OOM is recorded as
      that entrant's result rather than retried at a smaller beam.
- [ ] Run it. Expected: FAIL.
- [ ] Implement and run against the labelled set (207 certain hallucinations,
      57,572 real cards). Load the two models sequentially with a full offload
      between them.
- [ ] Restore `llama-embed` to the card and record `nvidia-smi` as evidence.
- [ ] Commit: `feat(tools): bake off large-v3 against turbo on the labelled set`.

## Task 9: Correct the swap plan document

Files: `docs/superpowers/plans/2026-08-22-1050ti-to-r520-swap.md`.
Interfaces: none. Independent of every other task.

- [ ] Read the document's status line and checklist. It reads "planned, not
      started" for a move completed and verified 2026-08-23 (commit `4f0b827`,
      "retarget the GPU move to VM 102, resized and verified").
- [ ] Change the status to completed-and-verified with the date, and tick the
      checkboxes whose steps were actually performed. Do not tick a step you have
      not confirmed; leave it and say so in the document.
- [ ] Commit: `docs: the 1050 Ti move to VM 102 is done, not planned`.
