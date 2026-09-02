# A reject verdict reopens the episode and forces a full remux for no text change

Status: open
Created: 2026-09-02

## Description

`review_apply.apply_episode` increments `changed` for ANY hit from `decisions.for_orig`
(review_apply.py:120). That includes `reject`, whose entire meaning is that the ASR text
stands. The episode is nevertheless reopened: a fresh srt is written, the `.ass` is
dropped, the stamp is removed, and merge_pass puts a multi-gigabyte file back through
mkvmerge to emit byte-identical text. Repeating the review sweep repeats the cost, because
the rejection stays in the store.

Deferred deliberately on 2026-09-02 (beta-readiness triage): the defect is bounded to I/O
and latency and cannot alter a shipped subtitle, so it does not block the public beta.

Done looks like: a verdict is classified by whether it CAN change the emitted text before
it counts toward `changed`. `reject` cannot, and must not reopen.

The tempting general fix -- comparing the verdict's `at` against the stamp mtime to skip
"already shipped" verdicts -- is NOT in scope here and must not be smuggled in. The
2026-08-29 measurement (11 of 20 One Pace corrections absent from the shipped track) is
the standing evidence that mtime is not proof a previous mux contains the approved text.
Narrow this to no-op verdicts only.

## Acceptance criteria

- [ ] A store holding ONLY `reject` entries for an episode's originals leaves the stamp
      in place and writes no sidecar (`changed == 0`).
- [ ] A store mixing a `reject` and a `correct` still reopens, and ships the correction.
- [ ] Both cases have a test that fails against the current `changed += 1`.

## Evidence

<!-- filled at close -->
