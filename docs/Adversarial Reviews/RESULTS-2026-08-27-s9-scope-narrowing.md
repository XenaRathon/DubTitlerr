# [S-9] — scope narrowing does NOT admit the three false negatives

Measured 2026-08-27 against 459 `conf.json` sidecars across One Pace, and against the
admission gates in `glossary_acquire.py`.

## The hypothesis under test

The spec recorded that the three confirmed false negatives were refused on frequency
grounds, and that [S-4]'s narrowing of acquisition scope to a single season "changes those
frequency denominators, so [S-4] may resolve them as a side effect". [S-9] existed to
verify that before any threshold was touched.

## The denominators do move

All three mishears occur in Season 30.

    mishear -> canonical      show-wide     within its season
    Samji   -> Sanji             1/811                  1/34
    Shadron -> Shandora           1/46                   1/0
    Uggh    -> Buggy             1/206                   1/1

## But the gates that refused them are not ratio gates

- **`Samji` was refused `below-floor`, and that gate is
  `variant_count < NEAR_MISS_MIN_COUNT` (2)** -- `glossary_acquire.py:479-481`. It tests the
  MISHEAR's own recurrence, not its share against the canonical. `Samji` appears exactly
  ONCE, show-wide and season-scoped alike. Narrowing the scope cannot change a count of one,
  so it cannot admit this term.
- **`Shadron` and `Uggh` were refused `sentence-initial-only`** -- `glossary_acquire.py:520`.
  That is a POSITIONAL test: the variant was only ever seen at the start of a sentence,
  where capitalisation carries no evidence. Scope has no bearing on where in a sentence a
  token appeared.

The other `below-floor` gate (`glossary_acquire.py:517`) is
`variant_count + canonical_count < 3`, which all three pass in both scopes and which
therefore never fired.

## Result

**Narrowing scope admits 0 of 3.** The hypothesis is false, and it was false for a reason
worth stating: it assumed the refusals were about the RATIO between mishear and canonical,
when two are positional and the third is about the mishear's own recurrence. The
show-wide-vs-season framing was the wrong axis entirely.

## Consequences

- [S-4] loses this as a justification. Narrowing acquisition to the queued season is still
  defensible on COST -- acquire's dominant cost is documented as 8202 tokens x 8109 titles,
  and it re-walks 461 episodes to learn about the 48 queued -- but it should no longer be
  presented as also fixing admission.
- Admitting these three requires touching the gates themselves, which the spec forbids
  until this measurement existed. It now exists, and it says: `NEAR_MISS_MIN_COUNT` is what
  stands between `Samji -> Sanji` and admission, and the sentence-initial rule is what
  stands between the other two.
- Whether to relax either is NOT decided here. Both gates exist because the module's
  docstring records that "every one of 8109 wiki titles finds SOME obscure article within
  MIN_SIM of any correctly-spelled name", and a single sighting is exactly the evidence
  class that produces. Three known-good terms is not enough to justify weakening a gate
  that protects against that; the next step is measuring how many BAD terms each gate
  currently refuses, so the trade is visible before it is made.
