# Provenance and policy: decoder identity in words.json, unanchored-repair reconciliation, phonetic guard and secondary backend closed

Status: closed 2026-09-23
Created: 2026-09-22

## Goal

Persist full decoder identity (model, initial_prompt, compute_type, beam_size) in
`words.json` (schema 2) so `common.read_words()` can detect a config change instead of
only a version bump; reconcile the deployed `REPAIR_UNANCHORED` unanchored-repair policy
against the One Pace S31 decision store and stale docs; close the phonetic-name-guard
issue with its shipped resolution; and remove the "not yet implemented"
`REPAIR_BACKEND_SECONDARY` architecture section now that it is retired. Delivers S-10
through S-13 of `.procoder/specs/v0-2-0-hardening.md`.

## Result

committed: 0
done: 0
carried: 0

## Retro

<!-- What slowed us down this sprint. -->

<!-- What we change next sprint because of it. -->

<!-- One adaptation from this sprint worth keeping. -->

## Result

committed: 10
done: 10 (20260921-a-words-json-with-transcribe-version-greater-than-common, 20260921-common-py-s-stamp-docstring-documents-same-size-same-mtime, 20260921-common-read-words-stem-expect-generate-decoder-identity, 20260921-common-words-schema-version-2-a-freshly-written-words-json, 20260921-decisions-load-for-the-relevant-one-pace-show-shows-all-45, 20260921-docs-wiki-how-to-guides-md-44-and-reference-md-106-no, 20260921-generate-decoder-identity-returns-model-model-initial, 20260921-handoff-md-183-185-is-marked-superseded-in-place-dated, 20260921-improvements-md-5-architecture-two-backend-repair-is-absent, 20260921-issue-phonetic-name-guard-md-has-a-status-header-naming)
carried: 0
