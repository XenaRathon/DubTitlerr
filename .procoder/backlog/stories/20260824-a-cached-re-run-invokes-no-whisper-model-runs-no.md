# A cached re-run invokes no Whisper model, runs no punctuation LLM call, and increments `words_reused`. With the sidecar absent, truncated, or carrying an older `transcribe_version`, it increments `words_missing` or `words_version_mismatch` and does not crash.

Status: open
Created: 2026-08-24
Epic: v5-two-tier-idempotency
Sprint: 001-v5-foundation-two-tier-versions-word-list-persistence-and

## Description

Implements plan Task 2 of `.procoder/plans/v5-two-tier-idempotency.md`.

The whole point of the text tier is that it costs CPU-minutes. Done means a replay runs no Whisper model and no punctuation LLM call, and that every way the sidecar can be unusable — absent, truncated, or written by an older transcribe version after a crash between transcription and stamping — is counted and falls back to full transcription without raising.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A cached re-run invokes no Whisper model, runs no punctuation LLM call, and increments `words_reused`. With the sidecar absent, truncated, or carrying an older `transcribe_version`, it increments `words_missing` or `words_version_mismatch` and does not crash.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->

