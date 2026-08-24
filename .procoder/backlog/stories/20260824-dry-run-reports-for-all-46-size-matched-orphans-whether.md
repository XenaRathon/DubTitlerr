# `--dry-run` reports, for all 46 size-matched orphans, whether each is content-identical, and changes nothing. `--apply` re-keys only content-confirmed matches, refuses while the pipeline is live, and leaves ambiguous matches (both directions) untouched. The re-key set is enumerated explicitly and excludes `.fail`, `.stale` and `.muxtmp.mkv`.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 5 of `.procoder/plans/v5-two-tier-idempotency.md`.

67 stamps describe videos that no longer exist under that name; 46 match a library video by size and 31 also by mtime. The 15 in between are most likely copies that lost their timestamp, but that is a guess until a content hash says so. Done means --dry-run reports the verdict for all 46 and changes nothing, --apply re-keys only content-confirmed unambiguous matches, and it refuses to run while the pipeline is live, since generate and mux write the very files it renames.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] `--dry-run` reports, for all 46 size-matched orphans, whether each is content-identical, and changes nothing. `--apply` re-keys only content-confirmed matches, refuses while the pipeline is live, and leaves ambiguous matches (both directions) untouched. The re-key set is enumerated explicitly and excludes `.fail`, `.stale` and `.muxtmp.mkv`.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

