# A `force` verdict loses to the phonetic name guard

Status: closed 2026-09-02
Created: 2026-09-02

## Description

CORRECTED 2026-09-02, after tracing the mechanism instead of trusting the log line this
task was opened on. The original premise -- "the phonetic name guard overrides a forced
verdict" -- is WRONG, and the fix is elsewhere.

`APPLYING = ("accept", "correct", "force")` and the admission is
`admitted = ruling in APPLYING or accept_repair(...)`, which short-circuits. A `force` that
REACHES the verdict path already bypasses the guard, and `decisions.lookup` was verified to
return that verdict for the exact MARRIAGETOXIN pair. The `rejected_name_invented` record
that prompted this task came from the 14:11 run under the six-day-stale deployed code;
`unresolved.jsonl` is append-only and carries no timestamp, so two runs' records sit
side by side and read as one.

THE REAL DEFECT. `repair.apply_human_text` rescues a card the repair loop SKIPS -- no
fansub anchor, or the LLM returned "" -- and it asked only `decisions.corrected_text`,
which is `correct`-only by design. So a `force` on a skipped card was lost, and the card
shipped raw ASR while the store said the line was settled. Measured on MARRIAGETOXIN
S01E10: the reviewer forced `Hammy Rat` -> `Hammy-Rat` and the shipped track carries the
unhyphenated original, two seconds before the episode's own signs track renders
"Modified Bloodline++ Hammy-Rat Network" on screen.

A second defect fell out of fixing the first: `record` folds both key sides through
`key()`, so a `force` stored only the CASE-FOLDED `proposed`. Shipping that would have
lowercased the line into the subtitle. `record` now copies the verbatim wording into
`text`, the way `correct` always has.

`accept` is deliberately NOT rescued: it endorses the model's wording for a proposal the
skipped card no longer has. It stays owed and stays visible.

## Acceptance criteria

- [x] A `force` verdict on a card the repair stage skips reaches the shipped srt.
      `tests/test_repair.py::test_a_forced_verdict_on_a_skipped_card_still_ships`
- [x] It arrives VERBATIM, not as the folded match key. Same test asserts the casing.
- [x] `accept` on a skipped card stays owed rather than being guessed at.
      `tests/test_repair.py::test_an_accept_verdict_on_a_skipped_card_is_owed_not_guessed`
- [x] A `force` entry written before verbatim storage refuses rather than shipping the
      folded key. `tests/test_decisions.py::test_a_force_entry_written_before_verbatim_storage_is_owed_not_mangled`
- [x] The name guard still refuses the same substitution as a MODEL proposal with no human
      verdict behind it -- untouched: the guard was never the defect.
- [x] Tests fail against the previous code (mutation-checked both ways: dropping the
      forced_text fallback, and reading `proposed` instead of `text`).

## Evidence

Implemented on `feat/review-sorting`, 2026-09-02.

- `decisions.forced_text(store, orig)` -- the `force` sibling of `corrected_text`, same
  newest-by-`at` tie-break, refusing rather than guessing when two undated forced wordings
  disagree. Reads `text`, never the folded `proposed`.
- `decisions.record` copies the verbatim proposal into `text` for a `force` with no text of
  its own, so the wording is shippable at all.
- `repair.apply_human_text` falls back to `forced_text` after `corrected_text`.
- 7 new tests. Mutation-checked: removing the fallback fails the repair test; reading
  `proposed` instead of `text` fails on casing in three tests.
- Full suite green, `ruff check .` clean.

NOT closed by this: the two MARRIAGETOXIN forced verdicts already in the store predate
verbatim storage, so they have no recoverable wording and correctly report as owed. They
need re-forcing through the review page to become shippable.
