# A card repair skips never reaches the decision store, so the human's text is discarded

Status: open
Created: 2026-08-30

## Description

`repair.process()` consults the decision store at `repair.py:722`, inside the per-card loop
and AFTER a proposal exists:

    verdict = decisions.lookup(store, c["text"], new) if DECISIONS_APPLY else None

Two earlier branches `continue` before ever reaching it:

- `skips_unanchored(ref)` at `:683-697` — no fansub anchor and the gate closed;
- `if not new:` at `:706-714` — `llm()` returned "" on any transport failure or timeout.

`repair.process()` then REBUILDS the whole srt from `conf.json`. So for any card that took
either branch, the shipped text becomes raw ASR — including cards whose text a human had
just corrected through `review_apply`, which writes the human's wording into the sidecar and
drops the stamp precisely so the episode gets re-processed.

`review_apply`'s module docstring states the contract this breaks:

    That is also why rebuilding from conf.json does not lose the LLM repairs: repair.py
    re-runs immediately afterwards and re-derives them, applying the stored verdicts as it
    goes.

It re-derives them only for cards that reach the consult. A skipped card silently loses both
the repair and the verdict.

## Why it matters beyond the misconfiguration that exposed it

Found while chasing the `REPAIR_UNANCHORED` problem
(`20260830-repair-unanchored-is-load-bearing-and-set-nowhere.md`), where every card skipped
and a whole episode reverted to raw ASR. That case is a configuration bug and is tracked
separately.

The durable hazard is `llm_empty`, which needs no misconfiguration at all: the repair backend
being briefly unreachable during a merge pass is an ordinary operational event. Today it
means every targeted card in that episode is rebuilt from `conf.json`, human corrections
included, while the summary records only `llm_empty` — a number that reads as "the model had
nothing to say", not "a reviewer's decisions were dropped". The 2026-08-21 GLM review flagged
the same silent-failure class for `llm_chat()`.

`decisions.lookup` needs BOTH sides of the pair and there is no proposal on a skipped card,
so the fix is not simply hoisting the consult. `decisions.for_orig()` already answers "has a
human ruled on this line at all" on the orig alone — it is what `review_apply` uses to decide
eligibility — and a `correct` verdict carries the human's text, which needs no proposal to
apply. That is the shape of the fix, but the placement is a real design question: `for_orig`
is documented as deciding eligibility and "never what text to write", and this would be the
first caller to write from it.

## Acceptance criteria

- [ ] A card that repair skips as `llm_empty`, but which carries a stored `correct` verdict,
      ships the human's text rather than raw ASR.
- [ ] Same for a card skipped as `skipped_no_ref`.
- [ ] `fits_card` is still never bypassed — C1 holds for this path exactly as it does at
      `:739`; an unrenderable human line is still refused and recorded.
- [ ] A card with no stored verdict is unaffected, byte for byte.
- [ ] The summary distinguishes "skipped and nothing was owed" from "skipped while a verdict
      existed" — the second is the case that must never be silent again.
- [ ] `for_orig`'s docstring is updated if it gains a write caller, or the fix uses another
      route and says why.

## Evidence

Pending.
