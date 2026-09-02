# A reject verdict reopens the episode and forces a full remux for no text change

Status: closed (won't fix -- premise falsified)
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

## Outcome: WON'T FIX. The premise is false.

Investigated 2026-09-02. A rejection is NOT a no-op, and the remux it triggers is the
whole point of it.

`repair.py` never rewrites `conf.json` -- it writes only its `.repair-summary.json`
sidecar. So conf.json holds RAW ASR, while the shipped track holds repair's output, which
routinely includes repairs `accept_repair` admitted automatically with no human involved.
When a reviewer rejects one of those, "the ASR text stands" is a CHANGE to the video:
review_apply rebuilds the srt from conf.json, repair.py's next pass consults the store,
sees the rejection and declines to re-apply, and the episode re-muxes carrying the ASR
text. Skipping the reopen would leave the rejected repair on screen forever while the
store claimed the reviewer had settled it -- the same class of failure as the 11-of-20
measurement, arrived at from the other direction.

The codebase said so before the analysis did: narrowing `changed` to exclude `reject`
broke TEN existing tests in `tests/test_review_apply.py`, which use a rejection as their
standard vehicle for "an episode with a verdict". That was not tests needing an update; it
was the suite refusing a wrong change.

No safe narrowing exists. Telling a wasteful rejection (the line shipped as ASR anyway)
from a load-bearing one (the line shipped as an auto-admitted repair) requires knowing what
is actually in the muxed track, and the 2026-08-29 measurement is the standing evidence
that mtime cannot answer that.

Kept: `tests/test_review_apply.py::test_a_rejection_reopens_because_it_reverts_a_repair_that_already_shipped`
pins the behaviour and records why, so this is not "optimised" again.

## Original acceptance criteria (not implemented -- see above)

- [ ] A store holding ONLY `reject` entries for an episode's originals leaves the stamp
      in place and writes no sidecar (`changed == 0`).
- [ ] A store mixing a `reject` and a `correct` still reopens, and ships the correction.
- [ ] Both cases have a test that fails against the current `changed += 1`.

## Evidence

<!-- filled at close -->
