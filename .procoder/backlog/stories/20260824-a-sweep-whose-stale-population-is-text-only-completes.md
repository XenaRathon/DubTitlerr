# A sweep whose stale population is text-only completes without loading `WhisperModel` — asserted by the absence of the load, not by timing.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 7 of `.procoder/plans/v5-two-tier-idempotency.md`.

`main()` loads WhisperModel whenever there is anything to do, so a text-only sweep pays a ~40 second GPU model load to perform zero transcription — the cheap tier quietly is not cheap. Done means the todo list is partitioned and the model is constructed only when there is transcription work, asserted by making the constructor raise rather than by measuring elapsed time.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A sweep whose stale population is text-only completes without loading `WhisperModel` — asserted by the absence of the load, not by timing.

## Evidence

- `partition_todo()` splits outstanding work by tier, and `main()` constructs
  `WhisperModel` only when the transcribe queue is non-empty; otherwise it logs
  "text-tier work only — skipping the model load".
- `test_a_text_stale_episode_with_words_goes_to_the_text_queue` — the 576 v4 episodes
  land in the text queue, not the GPU one. Without this a TEXT_VERSION bump costs
  roughly two GPU-days.
- `test_a_transcribe_stale_episode_is_never_sent_to_the_text_queue` — a v2 episode's
  words came from an older decoder and must not be replayed.
- `test_a_text_stale_episode_without_words_must_be_retranscribed` — no sidecar means it
  transcribes once and gains one, rather than being skipped forever for want of a cache.
- `test_a_poison_marked_episode_is_in_neither_queue` and
  `test_a_current_episode_is_in_neither_queue` pin the skips.
- Suite: `1180 passed`. `procoder check`: 0 blocking. Commit `bbf5ebf`.

