# Per-tier stale counts appear in `lastrun.json` and are non-zero after a `TEXT_VERSION` bump on a pinned show; a subsequent sweep of that show shows `words_reused > 0`. Live observation, not only a fixture.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: -
Carried: 001-v5-foundation-two-tier-versions-word-list-persistence-and — Its second half requires a LIVE sweep: bump TEXT_VERSION on a pinned show, sweep, observe words_reused > 0. Production is deliberately stopped and stays stopped until every change from this week is committed (owner decision 2026-08-24), so the observation cannot be made. The fixture half is implemented and green; carrying rather than closing on fixtures alone, because 'a fixture proves ordering but never proves anything drains' is exactly what this story exists to guard.

## Description

Implements plan Task 4 of `.procoder/plans/v5-two-tier-idempotency.md`.

A number with no reader sits unread: `flag` was decorative for four days and 236 stamps sat at v2 for weeks with nothing reporting it. Done means the per-tier counts land in `lastrun.json`, which already has a consumer, and that a live bump-sweep-observe cycle on a pinned show is recorded — a fixture proves ordering but never proves anything drains.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] Per-tier stale counts appear in `lastrun.json` and are non-zero after a `TEXT_VERSION` bump on a pinned show; a subsequent sweep of that show shows `words_reused > 0`. Live observation, not only a fixture.

## Evidence

Both halves now satisfied. The live half was obtained on a single COPIED episode in an
isolated tree (`/home/claude/validation`), not by sweeping the library — production
remains stopped.

- **Per-tier counts, live** in the real `lastrun.json`:

      {'show': 'One Pace', 'episodes_total': 1, 'episodes_transcribed': 0,
       'transcribe_stale': 0, 'text_stale': 1, 'model': 'large-v3-turbo'}

  Transcribed 0 while text_stale 1 — the episode was served entirely by the text tier.

- **`words_reused > 0`**, read from the qc sidecar the replay wrote: `words_reused: 1`.
- The stamp was aged to `text_version=4` (the state of all 576 live v4 episodes) rather
  than patching `TEXT_VERSION` in the tree, so the observation is of the real condition.
- generate's own log for the replay: `transcribe=0 text=1 transcribe_stale=0 text_stale=1`
  followed by `text-tier work only — skipping the model load`, then `ok` with 323 cards
  and 18 name fixes. No whisper model was constructed.
- The same run confirms two of the gate's rules are inert on turbo, from production data
  rather than a fixture: `rule_music_evaluated 323 / activated 0` and
  `rule_maybe_silence_evaluated 313 / activated 0`, with `0 of 267` segments carrying a
  live no_speech_prob.
- The S-6 guard is live and honest here too: `rule_source_window_evaluated 323 /
activated 0` — evaluated on every card, fired on none, which is correct for an episode
  with no implausible windows.
