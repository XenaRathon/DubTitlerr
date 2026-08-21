# Round 2 — three of your findings land, two do not, and one needs your mechanism replaced

Your review is in and mostly held up. Below: what I accepted, what I checked and reject, and
the one question worth your remaining session time.

---

## Accepted, no argument

1. **The `watched` column.** Confirmed and material. Measured on the live WatchState DB:

       last 30 days, episode rows:   watched=0 -> 804 rows, newest today
                                     watched=1 -> 640 rows

   Filtering `watched=1` removes ~8 shows from the 60-day list and corrects One Pace from 464
   episodes to 267. Same last-watched timestamp, so ordering survives; membership does not.
   The spec was going to ship a queue counting rows that were touched, not watched.

2. **§3.4's invariant is too weak.** Correct — "something reachable" passes when a wrong
   canonical replaced the right term. It must be the *verified term itself*.

3. **Release sequencing is unordered.** Correct. The next scheduled `glossary_verify.py` run
   re-triggers the bug under old code.

---

## Rejected — you verified the right facts and drew the wrong conclusion

**4. The "10 of 12" measurement is not an overclaim.**

You found `Alabasta` and `Straw Hats` are `hard_fixes` values. That is true, and it is exactly
why the spec says **10** of 12. Re-measured against the live glossary:

    Alabasta     hard_fixes value: True   (keys: arabasta, alabaster)
    Straw Hats   hard_fixes value: True   (key:  straw hats)
    Doflamingo, Kaido, Lucci, Hancock, Raftel, Jabra,
    Trafalgar, Rayleigh, Montblanc, Cricket        -> all False

Ten absent, two present. The spec text reads "10 of 12 sampled bare dub forms are absent from
`names`, `phrases` and `hard_fixes` values alike." Nothing was overclaimed.

**5. You checked the wrong field on the stale-claim finding.**

You searched `source_end` in `tools/`. The prompt's claim was about **`flag`**, a different
incident (the `source_end` one was a separate bullet, about a test's default value). Your
conclusion still lands, for a different reason: `flag` reads are gone from
`tools/timing_compare.py` too, refactored into `nsp_bucket_labels()` / `lp_bucket_labels()`
earlier the same day. So the example genuinely does not reproduce. Right verdict, wrong route.

---

## The one that matters: your mechanism does not work, but your conclusion might

You refuted §3.2 ("no deterministic signal separates a correct canonicalisation from a wrong
one") by pointing at `is_expansion` / `source_gate` in `glossary_acquire.py`. Those functions
are real, and your **structural** point is correct and valuable: `glossary_verify.apply_results()`
is an older, blunter path that uses **none** of the guards its sibling module developed for the
identical problem. Two modules, same question, one of them learned something.

But `is_expansion` does not do the job you assigned it. I ran it on all twelve real cases:

    variant     -> canonical              is_expansion   truth
    Doflamingo  -> Donquixote Doflamingo      True       correct
    Hancock     -> Boa Hancock                True       correct
    Lucci       -> Rob Lucci                  True       correct
    Rayleigh    -> Silvers Rayleigh           True       correct
    Cricket     -> Mont Blanc Cricket         True       correct
    Straw Hats  -> Straw Hat Pirates          True       correct
    Montblanc   -> Mont Blanc                False       correct
    Kaido       -> Kaidou                     True       WRONG (wiki-over-dub)
    Trafalgar   -> Trafalgar Lami             True       WRONG (different entity)
    Alabasta    -> Arabasta                  False       WRONG (wiki-over-dub)
    Raftel      -> Ratel                     False       WRONG (different entity)
    Jabra       -> Jabari                    False       WRONG (different entity)

    As a correct-vs-wrong discriminator: 3/12.
    Blocks 6 of 6 correct expansions. Allows 3 of 5 wrong ones.

It fails because it was never a correctness test — it answers "would substituting this grow a
word into a longer name", a substitution-safety rule for a path that replaces. Under
add-alongside semantics, expansion stops being a hazard at all.

**What survives is `source_gate`'s underlying principle — corpus corroboration.** `Ratel`,
`Kaidou`, `Arabasta` and `Jabari` are none of them spoken in the dub, and the pipeline holds
the show's own transcripts plus, for many releases, an embedded fansub track.

### So, concretely:

1. **Design the corroboration guard.** What corpus, queried how, at what threshold? Be
   specific enough to implement: which of `harvest_candidates`, `context_lines`,
   `settled_target`, `anchor_terms` to reuse; whether a raw count, a Wilson lower bound
   (`wilson_lower` exists), or a ratio against the variant's own count; and what the rule does
   when the corpus is empty or the show has no fansub track.

2. **Name its false-positive mode.** A legitimately new canonical that the transcript has
   never contained because Whisper always misheard it is the case this guard would reject.
   `Shirahoshi` and `Van Der Decken` are real examples from this show — unmineable precisely
   because no release ships a fansub track. How does the guard avoid becoming a rule that only
   admits names the pipeline already gets right?

3. **Given 1 and 2, is §3.2's human-escalation rung still needed as a floor, or does the guard
   replace it?**

4. **Should `glossary_verify.apply_results` keep existing at all,** or should verification
   route through `glossary_acquire`'s proposal pipeline so there is one adjudication path
   rather than two? Consider that `apply_results` currently runs on a schedule against
   production glossaries.

Append your answer to your existing review file. Short is fine — I want the mechanism, not an
essay.
