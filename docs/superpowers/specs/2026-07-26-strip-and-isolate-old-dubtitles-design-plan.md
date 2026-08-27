# Plan — Strip-at-mux + context isolation for old dubtitle tracks

> Implementation plan for `2026-07-26-strip-and-isolate-old-dubtitles-design.md`.
> Approve this plan, then execute the matching `tasks.md`.

## Branch and delivery

- **Branch:** `feat/strip-and-isolate-old-dubtitles` (base: `main`).
- **PR slicing:** single PR. The changes are coupled across `common.py`, `mux.py`,
  `generate.py`, and `mine_glossary.py`; they must land together to keep the pipeline
  consistent. No intermediate state is safe.

## Technical approach

Move the canonical `TRACK_NAME` constant to `common.py`, make `eng_sub_streams()` exclude
any stream with that title, and add a pipeline-version field to the `.dubtitles.done` stamp.
`mux.py` drops old `Dubtitles` subtitle tracks during remux and skips only on a current-version
stamp. `generate.py` removes its `SKIP_IF_MUXED` ffprobe backstop and relies solely on the
version-aware stamp check. `mine_glossary.py` gets the same title exclusion, since it bypasses
`eng_sub_streams()`.

A one-time migration pass writes v1 stamps for files that already carry a `Dubtitles` track
but have no `.dubtitles.done` sidecar, so the rollout remains a no-op. Files without a stamp
after the migration window are treated as stale and regenerated.

## Affected files (by layer)

| Layer           | File                                                                                                 | Change                                                                                                                                                                                                                                                    |
| --------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Core            | `common.py`                                                                                          | Add `TRACK_NAME`, `PIPELINE_VERSION`, `GRANDFATHER_VERSION`. Update `eng_sub_streams()` to fetch `stream_tags=title` and exclude `TRACK_NAME`. Update `write_stamp()` to record version. Update `stamp_valid()` to require `version >= PIPELINE_VERSION`. |
| MUX             | `mux.py`                                                                                             | Import `TRACK_NAME` from `common.py` (drop local constant). Update `keep_sub()` to drop tracks whose `track_name == TRACK_NAME`. Make `process()` skip guard stamp-only (remove `has_dubtitles_track()` backstop).                                        |
| Generation      | `generate.py`                                                                                        | Remove the `SKIP_IF_MUXED` guard and the now-dead `has_dubtitles_track()` function. Rely on the existing version-aware `stamp_valid` check at the top of `process()`.                                                                                     |
| Glossary        | `mine_glossary.py`                                                                                   | Update `eng_sub_text()` ffprobe query to fetch `stream_tags=title` and exclude streams with `title == TRACK_NAME`.                                                                                                                                        |
| Migration (new) | `scripts/migrate_write_v1_stamps.py`                                                                 | One-time pass: for files with a `Dubtitles` track but no `.dubtitles.done` stamp, write a v1 stamp.                                                                                                                                                       |
| Tests           | `tests/test_common.py`, `tests/test_mux.py`, `tests/test_generate.py`, `tests/test_mine_glossary.py` | Add/update unit tests for title exclusion, version-aware stamps, stamp-only skip, and migration.                                                                                                                                                          |

## Risks and mitigation

| Risk                                                                   | Mitigation                                                                                                                              |
| ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Mass regeneration of files without stamps                              | Run `scripts/migrate_write_v1_stamps.py` before deploy; deploy only after migration is complete.                                        |
| Old dubtitle still used as context in a missed code path               | Audit: every call site that reads embedded subs is listed in the spec's enumeration audit; verify with grep/code search before merging. |
| Track ordering changes in MKV players                                  | New track is appended last; default track flag is set correctly by `mux.build_cmd`. Test in a player before version bump.               |
| Orphaned sidecars after stamp write but before cleanup                 | Documented, low-impact; sidecar is harmless and will be cleaned up on the next version-bump re-process.                                 |
| `generate.has_dubtitles_track()` removed but another script imports it | Search the codebase before removal; no external callers expected.                                                                       |

## Rollback and reversibility

- Reverting the PR restores the old skip-backstop behavior, but any files that were
  re-muxed with the new track ordering will keep that layout.
- The migration script only writes stamps; it is safe to run idempotently and does not
  modify media files.

## Testing strategy

- **Unit (`pytest`):**
  - `test_common`: `eng_sub_streams` excludes `title == "Dubtitles"`; `write_stamp` stores
    `version`; `stamp_valid` rejects old versions, accepts grandfathered/missing version when
    `PIPELINE_VERSION == GRANDFATHER_VERSION`.
  - `test_mux`: `keep_sub` drops `Dubtitles` track; `process` skips only on current-version
    stamp; dropped list contains the old `Dubtitles` track id.
  - `test_generate`: `process` no longer returns `"already-muxed"` solely from a Dubtitles
    track; returns it only when the stamp is current-version; existing backstop test is
    removed or retargeted.
  - `test_mine_glossary`: `eng_sub_text` excludes a `Dubtitles` stream.
- **Integration (manual / server):**
  - Pick a show already muxed with v1 stamps; run `mux.py --apply` and confirm no-op and no
    duplicate tracks.
  - Pick a file with a Dubtitles track but no stamp; run migration, confirm stamp written,
    then confirm `generate.py`/`mux.py` skip it.
  - Bump `PIPELINE_VERSION` locally, confirm stale file is regenerated and re-muxed in place.

## Observability

- `mux.py` already logs the count of dropped tracks; verify the old `Dubtitles` track
  appears in `dropped`.
- `generate.py` summary log will no longer report `"already-muxed"` from the ffprobe backstop;
  confirm it still reports it from the stamp check during rollout.
