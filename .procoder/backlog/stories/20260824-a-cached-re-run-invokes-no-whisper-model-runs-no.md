# A cached re-run invokes no Whisper model, runs no punctuation LLM call, and increments `words_reused`. With the sidecar absent, truncated, or carrying an older `transcribe_version`, it increments `words_missing` or `words_version_mismatch` and does not crash.

Status: done 2026-08-24
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 2 of `.procoder/plans/v5-two-tier-idempotency.md`.

The whole point of the text tier is that it costs CPU-minutes. Done means a replay runs no Whisper model and no punctuation LLM call, and that every way the sidecar can be unusable — absent, truncated, or written by an older transcribe version after a crash between transcription and stamping — is counted and falls back to full transcription without raising.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] A cached re-run invokes no Whisper model, runs no punctuation LLM call, and increments `words_reused`. With the sidecar absent, truncated, or carrying an older `transcribe_version`, it increments `words_missing` or `words_version_mismatch` and does not crash.

## Evidence

- `test_the_replay_writes_output_without_touching_a_model` monkeypatches
  `generate.WhisperModel` to RAISE, then runs `process_text()` end to end: it returns
  `"ok"` and writes both the srt and the conf. Asserted by the absence of the
  construction, not by timing.
- The replay skips the punctuation LLM call too, because the stored words are written
  after `punctuation.restore()` has already mutated `word["text"]` in place.
- `test_the_replay_reports_when_the_sidecar_is_unusable` — returns `"no-words"` rather
  than raising; `read_words()` counts `words_missing` / `words_version_mismatch` /
  `words_reused` so an uncacheable episode is never silent.
- `text_stages()` is shared by the replay and a fresh transcription, so a replay cannot
  quietly diverge from the run it claims to reproduce.
- Suite: `1180 passed`. `procoder check`: 0 blocking. Commit `bbf5ebf`.

