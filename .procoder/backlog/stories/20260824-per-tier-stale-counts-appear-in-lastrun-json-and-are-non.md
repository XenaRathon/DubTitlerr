# Per-tier stale counts appear in `lastrun.json` and are non-zero after a `TEXT_VERSION` bump on a pinned show; a subsequent sweep of that show shows `words_reused > 0`. Live observation, not only a fixture.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 4 of `.procoder/plans/v5-two-tier-idempotency.md`.

A number with no reader sits unread: `flag` was decorative for four days and 236 stamps sat at v2 for weeks with nothing reporting it. Done means the per-tier counts land in `lastrun.json`, which already has a consumer, and that a live bump-sweep-observe cycle on a pinned show is recorded — a fixture proves ordering but never proves anything drains.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] Per-tier stale counts appear in `lastrun.json` and are non-zero after a `TEXT_VERSION` bump on a pinned show; a subsequent sweep of that show shows `words_reused > 0`. Live observation, not only a fixture.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

