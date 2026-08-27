# [S-16] — the coverage defence for `VIVRA -> Vivi` is falsified

Measured 2026-08-27, One Pace S31E01, replayed from sidecars on the REAL code
(`5616ca7`), not a throwaway patch. `REPAIR_UNANCHORED=1`, both [S-14] and [S-15] guards
active, nanbeige4.2-3b on the remote backend.

## The test the round-2 review demanded

The results file for the unanchored measurement blamed one regression on glossary coverage:
`VIVRA -> Vivi` happened, it said, because `Vivre Card` -- a real One Piece term -- was
absent from the 92 names, so the model reached for the nearest name that was present. The
review accepted that for this case but called it "an excuse as a general defence" and named
the falsifying test: add `Vivre Card`, re-run, see if the repair disappears.

## Result: it does not

    arm                       repairs   the VIVRA line
    glossary as-is (92)            21   "It's a VIVRA card?" -> "It's a Vivi card?"
    + `Vivre Card` (93)            21   "It's a VIVRA card?" -> "It's a Vivi card?"

    differing repairs between the two arms: NONE

Adding the correct term changed nothing. The model did not reach for `Vivre Card` when it
was available, so its absence was not the cause. **The coverage explanation is wrong**, and
it was recorded as fact in `RESULTS-2026-08-26-unanchored-repair.md` before this test
existed.

## What that means

- **[S-15]'s known false negative is a real gap, not a downstream problem.** The spec
  routed it to [S-2] on the coverage story; that routing is now invalid. `vivra -> vivi`
  scores 0.848 jaro-winkler, above the 0.75 threshold, and no threshold can exclude it
  because the genuine `syrahose -> shirahoshi` fix scores 0.755. The gate admits it and
  coverage does not save it.
- **[S-2]/[S-11] keep their value for a different reason.** Measured the same night, arc
  tagging across 7 arcs moves the Dressrosa prompt from 110 terms to 94, recovering
  `Nico Robin`, `Rob Lucci`, `Trafalgar D. Water Law` and `Silvers Rayleigh` from the
  1000-char cap and demoting the Enies Lobby cast. That is a real effect and it stands.
  What does not stand is presenting arc coverage as the cure for this regression class.
- **The guards are confirmed inert on real code.** The base arm reproduces the
  throwaway-patch run exactly -- 21 repairs, same set -- so [S-14] and [S-15] blocked
  nothing here. That satisfies the review's F2 demand that the "identical set" claim be
  about what ships, and it means their justification remains the documented `Oimo -> Zoro`
  failure, not observed benefit.

## What is still unexplained

Why the model prefers `Vivi` over `Vivre Card` when both are in the reference list. Three
candidates, none tested:

- `Vivi` is a frequent character name in this show and `Vivre Card` an item, so a
  frequency prior may dominate the list.
- The prompt frames the list as "reference spellings", which may bias toward person-names.
- `VIVRA` may be closer to `Vivi` than to `Vivre Card` in whatever the model uses
  internally, in which case no list membership fixes it.

Until one of these is measured, `VIVRA -> Vivi` is an OPEN regression with no assigned cure,
and the spec should say that rather than pointing at [S-2].
