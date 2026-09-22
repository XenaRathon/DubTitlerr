# Provenance and policy: decoder identity in words.json, unanchored-repair reconciliation, phonetic guard and secondary backend closed

Status: active
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
