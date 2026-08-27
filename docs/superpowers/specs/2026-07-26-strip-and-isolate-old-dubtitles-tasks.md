# Tasks — Strip-at-mux + context isolation for old dubtitle tracks

> Actionable task breakdown for `2026-07-26-strip-and-isolate-old-dubtitles-design.md`.
> See the companion plan (`-design-plan.md`) for the high-level approach.

## T1 — Move `TRACK_NAME` to `common.py`

**File:** `DubTitlerr/common.py`

- [x] Add `TRACK_NAME = "Dubtitles"`.
- [x] Add `PIPELINE_VERSION = 1` and `GRANDFATHER_VERSION = 1`.
- [x] Add `_track_title(st: dict) -> str` helper.

## T2 — Version-aware stamp helpers

**File:** `DubTitlerr/common.py`

- [x] Update `write_stamp(path, video)` to write `"version": PIPELINE_VERSION`.
- [x] Update `stamp_valid(stamp, video)` to require `stamp.get("version", GRANDFATHER_VERSION) >= PIPELINE_VERSION`.
- [x] Add unit tests in `tests/test_common.py` for version recording, old-version rejection, grandfather equality, and missing-version fallback.

## T3 — Exclude `Dubtitles` from `eng_sub_streams()`

**File:** `DubTitlerr/common.py`

- [x] Update ffprobe query to include `stream_tags=title`.
- [x] Use `_track_title()` to skip any stream whose title == `TRACK_NAME`.
- [x] Add unit tests in `tests/test_common.py` for title exclusion (with/without whitespace, missing tags, multiple tracks).

## T4 — Update `mux.py` strip-at-mux logic

**File:** `DubTitlerr/mux.py`

- [x] Import `TRACK_NAME` from `common` and remove the local constant.
- [x] Update `keep_sub()` to drop any subtitle track named `TRACK_NAME` as the first check.
- [x] Update `process()` skip guard to be stamp-only (remove `or has_dubtitles_track(...)`).
- [x] Add/update unit tests in `tests/test_mux.py` for `keep_sub` dropping the Dubtitles track and `process` skipping only on current-version stamps.

## T5 — Remove `generate.py` `SKIP_IF_MUXED` backstop

**File:** `DubTitlerr/generate.py`

- [x] Remove the `SKIP_IF_MUXED` guard block in `process()`.
- [x] Remove the now-unused `has_dubtitles_track()` function.
- [x] Verified `needs_work()` never used `SKIP_IF_MUXED` (stat-only pre-filter) — no change needed.
- [x] Update/remove `test_ffprobe_muxed_backstop_in_process` in `tests/test_generate.py`.
- [x] Add unit tests for version-aware skip behavior (current stamp skips, stale stamp does not).

## T6 — Exclude `Dubtitles` in `mine_glossary.py`

**File:** `DubTitlerr/mine_glossary.py`

- [x] Update ffprobe query to fetch `stream_tags=title`.
- [x] Filter out streams whose title == `common.TRACK_NAME`.
- [x] Import `TRACK_NAME` from `common` if not already available.
- [x] Add unit tests in `tests/test_mine_glossary.py` for the exclusion.

## T7 — Verify inherited consumers

**Files:** `DubTitlerr/repair.py`, `DubTitlerr/dub_signs_merge.py`, `DubTitlerr/tools/timing_compare.py`, `DubTitlerr/recreate_srt.py`

- [x] Confirm `repair.py`, `dub_signs_merge.py`, and `timing_compare.py` use `eng_sub_streams()` and inherit the fix without code changes.
- [x] Confirmed `recreate_srt.py` reads `conf.json` only — no embedded-sub access, no change.
- [x] Update tests for `timing_compare` and `dub_signs_merge` to assert reference selection excludes the Dubtitles track.

## T8 — Migration script (one-time)

**File:** `DubTitlerr/scripts/migrate_write_v1_stamps.py` (new)

- [x] Create a script that finds files with a `Dubtitles` track but no `.dubtitles.done` stamp and writes a v1 stamp for each.
- [x] Make the script idempotent and dry-run by default; require `--apply` to write stamps.
- [x] Document the migration step in operator notes (README "Notes & gotchas").

## T9 — Integration / manual validation

- [x] Run unit tests: full suite green (`pytest -q`, 377 passed) + `ruff check` clean.
- [ ] **PENDING (server, needs real media):** dry-run `mux.py` on a small test show and verify old `Dubtitles` tracks appear in `drop-tracks=` and new ones are appended.
- [ ] **PENDING (server):** bump `PIPELINE_VERSION` and confirm a stale file is regenerated and re-muxed in place.
- [ ] **PENDING (server):** verify no duplicate `Dubtitles` tracks after re-mux (`mkvmerge -J`).

## T10 — Deprecate `strip_op.py` — **N/A**

`strip_op.py` does not exist in this repo and never has (`git log --all -- strip_op.py` is
empty). The pre-strip pass the spec refers to was run ad hoc, not as a committed script, so
there is nothing to deprecate. Strip-at-mux replaces it outright.
