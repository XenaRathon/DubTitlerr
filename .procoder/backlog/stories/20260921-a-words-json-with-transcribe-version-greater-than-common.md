# A `words.json` with `transcribe_version` greater than `common.TRANSCRIBE_VERSION` increments `words_version_mismatch` and returns `None` (new test for already-existing behavior).

Status: open
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: -

## Description

Scope S-10 of `.procoder/specs/v0-2-0-hardening.md`: `words.json` schema 2 adds `compute_type` and `beam_size`; `common.WORDS_SCHEMA_VERSION` becomes `2`; `generate.decoder_identity()` returns `{"model": MODEL, "initial_prompt": INITIAL_PROMPT, "compute_type": COMPUTE, "beam_size": int(os.environ.get("WHISPER_BEAM_SIZE", "7"))}`; `common.read_words(stem, rec=None, expect: dict | None = None)` compares `model`/`initial_prompt`/`compute_type`/`beam_size` against `expect` when given: a field that IS recorded and differs counts `words_config_mismatch` and returns `None`; a field absent or `""` in the sidecar (schema-1 files, including the pre-existing bug where `model` was written from an unset `WHISPER_MODEL` env var as `""`, independent of the resolved `MODEL` constant) counts `words_config_unknown` and is still returned — the 366 live sidecars are not invalidated by this.

Delivered by Task 10 and 11 of `.procoder/plans/v0-2-0-hardening.md` (sprint 012); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] A `words.json` with `transcribe_version` greater than `common.TRANSCRIBE_VERSION` increments `words_version_mismatch` and returns `None` (new test for already-existing behavior).

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
