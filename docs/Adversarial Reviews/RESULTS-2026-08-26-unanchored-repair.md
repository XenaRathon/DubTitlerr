# [S-12]/[S-14] measurement — LLM repair on cards with no fansub anchor

Measured 2026-08-26, One Pace S31E01, replayed from sidecars captured earlier the same day.
No GPU on VM102: transcription is skipped entirely and the saved `conf.json` is the input.
The LLM itself is `nanbeige4.2-3b` on the remote llamacpp backend (192.168.1.209:8090),
p95 latency 1271 ms.

## Result

    arm                                    targets   repaired
    baseline (gate closed, production)         161          0
    [S-12] ungated                             161         21
    [S-12] + [S-14] both guards                161         21   <- identical set

Every one of the 161 targets is refused today at `repair.py:512` for want of a fansub
anchor. Ungating them produced 21 repairs from 25 proposals (`rejected_guard=4` from the
pre-existing length/borrow/fits-card gates).

## The 21, against the owner's acceptance bar

18 acceptable, 3 regressions. The bar is referent and sense, not word-for-word fidelity.

Most are the stage's stated duty -- run-together splits and missing punctuation:

    "your crew disappeared for two years What were you doing all that time?"
    "Your crew disappeared for two years. What were you doing all that time?"

And the one that closes the loop this whole day started from:

    "The heavenly demon, Don Quixote Dothamingo."
    "The heavenly demon, Don Quixote Doflamingo."

`glossary.correct()` structurally cannot make that fix -- difflib 0.800 against a 0.84
cutoff, metaphone T0MNK vs TFLMNK -- and hotwords reached it only while corrupting
phonetic neighbours. Surrounding-card context plus a verification-framed glossary did it in
one pass.

Acceptable-with-a-caveat:

    "First, the world's greatest swordsman, Hawkeye Dracule Mihawk."
    "First, the world's greatest swordsman, Mihawk."
      Shorter than the dub speaks. Owner's call: same referent, same information.

Regressions:

    "We're looking for a factory."   -> "We're looking for a needle."   meaning destroyed
    "Spare Mata-koth for me!"        -> "Sparing Mata-koth for me!"     grammar
    "It's a VIVRA card?"             -> "It's a Vivi card?"             wrong referent

## [S-14] blocked nothing, and that is the honest finding

Both guards -- known->known refusal, and phonetic proximity on the unknown->known path --
were enabled and produced a set BYTE-IDENTICAL to ungated. Zero regressions prevented, zero
fixes lost.

Unit-verified on the known cases, 7 of 7:

    oimo -> zoro                blocked (known -> known, the bake-off failure)
    dothamingo -> doflamingo    accepted (0.893)
    syrahose -> shirahoshi      accepted (0.755)
    zolo -> zoro                accepted (0.867)
    conjured unknown name       blocked
    deccan -> decman            blocked

So the guards are insurance against a documented prior failure that did not recur in this
sample, not an observed improvement. Keep them -- `Oimo -> Zoro` is the reason this gate
was closed and they cost nothing -- but do not let the 7/7 unit result imply they earned
their place on production evidence. They have not yet.

## The phonetic threshold cannot be tightened

    from          to            verdict          jaro_winkler
    dothamingo    doflamingo    GOOD                    0.893
    zolo          zoro          GOOD                    0.867
    vivra         vivi          BAD                     0.848
    syrahose      shirahoshi    GOOD                    0.755
    oimo          zoro          BAD                     0.667

The genuine `syrahose -> shirahoshi` fix scores LOWER than the bad `vivra -> vivi`. No
threshold separates them, and metaphone is False for every pair, so it cannot discriminate
either. 0.75 is chosen to block `oimo -> zoro` while admitting all three genuine fixes;
`vivra -> vivi` is knowingly let through.

## Two of the three regressions are not guard-shaped

`factory -> needle` is ordinary English on both sides, so `proper_cores` never sees it.
`Spare -> Sparing` is grammar. Only `VIVRA -> Vivi` is in the name guard's domain, and it
is really a GLOSSARY COVERAGE gap: "Vivre Card" is a real One Piece term absent from the
92 names, so the model reached for the nearest thing that was present.

That is the concrete job left for [S-2]'s arc-scoped acquisition after [S-10] was cut:
not priming the decoder, but giving the repair LLM the right target to reach for.
"Vivre Card" appeared in the Dressrosa wiki extraction made earlier the same day.

## CORRECTION 2026-08-27 — the coverage explanation above is FALSIFIED

This file blamed `VIVRA -> Vivi` on glossary coverage: `Vivre Card` is a real term absent
from the 92 names, so the model reached for the nearest name present. The round-2 review
called that an excuse as a general defence and named the falsifying test.

The test was run. Adding `Vivre Card` to the glossary and re-running S31E01 on the real
code produced **21 repairs in both arms, an identical set, and the same
`"It's a VIVRA card?" -> "It's a Vivi card?"` repair**. The model did not reach for the
correct term when it was available, so its absence was never the cause.

`VIVRA -> Vivi` is therefore an OPEN regression with no assigned cure, and the routing of
it to [S-2]'s arc coverage in this file and in the spec was wrong. Full result:
`RESULTS-2026-08-27-s16-coverage-falsified.md`.
