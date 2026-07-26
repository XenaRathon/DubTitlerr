# Tasks — Strip-at-mux + context isolation for old dubtitle tracks

> Actionable task breakdown for `2026-07-26-strip-and-isolate-old-dubtitles-design.md`.
> See the companion plan (`-design-plan.md`) for the high-level approach.

## T1 — Move `TRACK_NAME` to `common.py`

**File:** `DubTitlerr/common.py`

- [ ] Add `TRACK_NAME = "Dubtitles"`.
- [ ] Add `PIPELINE_VERSION = 1` and `GRANDFATHER_VERSION = 1`.
- [ ] Add `_track_title(st: dict) -> str` helper.

## T2 — Version-aware stamp helpers

**File:** `DubTitlerr/common.py`

- [ ] Update `write_stamp(path, video)` to write `"version": PIPELINE_VERSION`.
- [ ] Update `stamp_valid(stamp, video)` to require `stamp.get("version", GRANDFATHER_VERSION) >= PIPELINE_VERSION`.
- [ ] Add unit tests in `tests/test_common.py` for version recording, old-version rejection, grandfather equality, and missing-version fallback.

## T3 — Exclude `Dubtitles` from `eng_sub_streams()`

**File:** `DubTitlerr/common.py`

- [ ] Update ffprobe query to include `stream_tags=title`.
- [ ] Use `_track_title()` to skip any stream whose title == `TRACK_NAME`.
- [ ] Add unit tests in `tests/test_common.py` for title exclusion (with/without whitespace, missing tags, multiple tracks).

## T4 — Update `mux.py` strip-at-mux logic

**File:** `DubTitlerr/mux.py`

- [ ] Import `TRACK_NAME` from `common` and remove the local constant.
- [ ] Update `keep_sub()` to drop any subtitle track named `TRACK_NAME` as the first check.
- [ ] Update `process()` skip guard to be stamp-only (remove `or has_dubtitles_track(...)`).
- [ ] Add/update unit tests in `tests/test_mux.py` for `keep_sub` dropping the Dubtitles track and `process` skipping only on current-version stamps.

## T5 — Remove `generate.py` `SKIP_IF_MUXED` backstop

**File:** `DubTitlerr/generate.py`

- [ ] Remove the `SKIP_IF_MUXED` guard block in `process()`.
- [ ] Remove the now-unused `has_dubtitles_track()` function.
- [ ] Update `needs_work()` pre-filter if it relied on `SKIP_IF_MUXED` (it does not, but verify).
- [ ] Update/remove `test_ffprobe_muxed_backstop_in_process` in `tests/test_generate.py`.
- [ ] Add unit tests for version-aware skip behavior (current stamp skips, stale stamp does not).

## T6 — Exclude `Dubtitles` in `mine_glossary.py`

**File:** `DubTitlerr/mine_glossary.py`

- [ ] Update ffprobe query to fetch `stream_tags=title`.
- [ ] Filter out streams whose title == `common.TRACK_NAME`.
- [ ] Import `TRACK_NAME` from `common` if not already available.
- [ ] Add unit tests in `tests/test_mine_glossary.py` for the exclusion.

## T7 — Verify inherited consumers

**Files:** `DubTitlerr/repair.py`, `DubTitlerr/dub_signs_merge.py`, `DubTitlerr/tools/timing_compare.py`, `DubTitlerr/recreate_srt.py`

- [ ] Confirm `repair.py`, `dub_signs_merge.py`, and `timing_compare.py` use `eng_sub_streams()` and inherit the fix without code changes.
- [ ] Confirm `recreate_srt.py` reads `conf.json` only and needs no changes.
- [ ] Update tests for `timing_compare` and `dub_signs_merge` to assert reference selection excludes the Dubtitles track.

## T8 — Migration script (one-time)

**File:** `DubTitlerr/scripts/migrate_write_v1_stamps.py` (new)

- [ ] Create a script that finds files with a `Dubtitles` track but no `.dubtitles.done` stamp and writes a v1 stamp for each.
- [ ] Make the script idempotent and dry-run by default; require `--apply` to write stamps.
- [ ] Document the migration step in operator notes.

## T9 — Integration / manual validation

- [ ] Run unit tests: `pytest tests/test_common.py tests/test_mux.py tests/test_generate.py tests/test_mine_glossary.py tests/test_timing_compare.py tests/test_dub_signs_merge.py`.
- [ ] Run a dry-run `mux.py --apply` on a small test show and verify old `Dubtitles` tracks are dropped and new ones appended.
- [ ] Bump `PIPELINE_VERSION` locally and confirm a stale file is regenerated and re-muxed in place.
- [ ] Verify no duplicate `Dubtitles` tracks after re-mux.

## T10 — Deprecate `strip_op.py`

**File:** `DubTitlerr/strip_op.py` (if present)

- [ ] Add a deprecation warning/note at the top of the file explaining it is no longer needed.
- [ ] Optionally schedule removal in a future cleanup PR.
