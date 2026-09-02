# A `force` verdict loses to the phonetic name guard

Status: open
Created: 2026-09-02

## Description

`force` is the strongest verdict a reviewer can give: it exists to ship a repair the
automated checks would otherwise refuse. On MARRIAGETOXIN S01E10 it did not.

MEASURED 2026-09-02 against the production library. The reviewer forced:

    orig: Hammy Rat Network is online!
    want: Hammy-Rat Network is online!

`repair` recorded `rejected_name_invented` and shipped the original. The guard saw
`Hammy-Rat` as a proper noun gained against `Hammy Rat` and refused it.

The guard is wrong here, and the episode itself proves it: the SAME episode's signs track
carries the fansub's own rendering at 0:21:44 --

    Modified Bloodline++ Hammy-Rat Network

so the hyphenated spelling is literally on screen while the dub track ships the unhyphenated
one the human corrected. The reviewer had the video in front of them; the guard had a
string-similarity heuristic.

The guard is valuable and must stay -- it is what stops the LLM conjuring names (v7,
`jester` -> `Dester`). The defect is precedence: it is applied to a HUMAN's forced verdict,
where there is no model to distrust. `accept` should arguably keep the guard (the human is
approving the MODEL's wording, and the guard is a second opinion on the model), but `force`
means the human took responsibility and the guard has nothing left to protect against.

Done looks like: `force` reaches the track, or the reviewer is told at review time that
their forced text will be refused -- what must not happen is a forced verdict silently
losing to a guard.

## Acceptance criteria

- [ ] A `force` verdict whose text trips the phonetic name guard still ships.
- [ ] The guard still refuses the same substitution when it arrives as a MODEL proposal
      with no human verdict behind it (the v7 behaviour does not regress).
- [ ] `accept` behaviour is decided explicitly rather than by omission, and the choice is
      written down here.
- [ ] A test with `Hammy Rat` -> `Hammy-Rat` as the fixture that fails today.

## Evidence

<!-- filled at close -->
