# `--dry-run` reports, for all 46 size-matched orphans, whether each is content-identical, and changes nothing. `--apply` re-keys only content-confirmed matches, refuses while the pipeline is live, and leaves ambiguous matches (both directions) untouched. The re-key set is enumerated explicitly and excludes `.fail`, `.stale` and `.muxtmp.mkv`.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 5 of `.procoder/plans/v5-two-tier-idempotency.md`.

67 stamps describe videos that no longer exist under that name; 46 match a library video by size and 31 also by mtime. The 15 in between are most likely copies that lost their timestamp, but that is a guess until a content hash says so. Done means --dry-run reports the verdict for all 46 and changes nothing, --apply re-keys only content-confirmed unambiguous matches, and it refuses to run while the pipeline is live, since generate and mux write the very files it renames.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `--dry-run` grades every orphan and changes nothing. A size+mtime match is `reclaimable`; a size-only match is `probable` and is NOT re-keyed without `--include-probable`; more than one claimant in either direction is `ambiguous` and moves nothing. `--apply` refuses while a pipeline process is running, never deletes, and re-keys an explicitly enumerated suffix set that excludes `.dubtitles.fail`, `.stale` and `.muxtmp.mkv`.

## Evidence

- **Run against the LIVE library** (read-only, production stopped), via the pipeline
  image with an explicit `--entrypoint`:

      DRY RUN - 67 orphaned stamp(s)
        reclaimable    : 31   (size + mtime agree)
        probable       : 15   (size only -- needs --include-probable)
        ambiguous      : 0    (left untouched on purpose)
        unrecoverable  : 21   (reported, never deleted)

  Exactly the 31/15 split measured independently this morning, from a different script.

- The spec's original criterion — "confirm by content hash before re-keying" — was
  **not implementable** and was corrected rather than faked: a stamp records `size` and
  `mtime` and no digest, so a hash has nothing to compare against and proves only that
  the candidate is readable. Verdicts are graded by the evidence that exists, and the 15
  size-only matches are reported rather than acted on.
- `test_a_size_only_match_is_probable_not_reclaimable` proves a probable match does not
  move by default; `test_include_probable_opts_into_the_size_only_matches` proves the
  operator can take that risk deliberately.
- `test_apply_never_moves_the_markers` (`.fail`, `.stale`),
  `test_apply_never_deletes_anything`, `test_apply_refuses_while_the_pipeline_is_live`,
  and both ambiguity directions are pinned.
- Suite: `1180 passed`. `procoder check`: 0 blocking. Commit `b8339f0`.
