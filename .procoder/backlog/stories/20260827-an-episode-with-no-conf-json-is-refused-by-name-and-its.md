# An episode with no `conf.json` is refused by name, and its stamp is untouched.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 005-task-5-review-apply-py-rebuild-an-episode-s-srt-from-conf

## Description

Task 5. `conf.json` is the source the srt is rebuilt from; without it there is nothing to apply verdicts
to. Done means the episode is refused BY NAME and its stamp is left alone -- a half-applied episode,
stamp cleared but text unchanged, is the state to avoid.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] An episode with no `conf.json` is refused by name, and its stamp is untouched.

## Evidence

- `test_a_missing_conf_json_is_refused_by_name_and_leaves_the_stamp` passes: the result
  carries `error: "no conf.json"` AND the stem, and the stamp is untouched.
- Refused BEFORE any write -- a half-applied episode is the failure to avoid. For a muxed
  episode `conf.json` is the only surviving source, so without it there is nothing to
  rebuild from; `tools/recover_dub_srt.py` is the tool for that case and it reads the muxed
  track instead.
- Mutation: replacing the refusal with an empty row list fails it.
