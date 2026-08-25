# 0002 — The nsp-gated rules are deleted, not tuned

Status: accepted
Date: 2026-08-24

## Context

`hallucination.drop_reason` had three rules and `flag_reason` had two. Two of the five
were gated on `no_speech_prob`:

- `music` — `nsp > 0.95 AND avg_logprob < -2.0` → drop the card
- `maybe_silence` — `nsp > 0.5` → keep but mark suspect

`music` caught **zero cards across 859 episodes / 353,879 cards**. On 2026-08-21 that was
read as a bug and the threshold was loosened to 0.90 — then reverted the same day once a
labelled set existed to judge it against. The measurement that forced the revert, recorded
here because the source comment carrying it is deleted by this decision:

    labels: 207 certain hallucinations (blocklist-matching) vs 57,572 real cards, 136 episodes
    nsp separates them (0.796 vs 0.330, |AUC-0.5|+0.5 = 0.929); avg_logprob too (0.913)

    nsp>0.70 lp<-0.3 -> recall 82.6%, precision 18.5%, 5.54 false drops per episode
    nsp>0.80 lp<-0.3 -> recall 54.6%, precision 19.8%, 3.37
    nsp>0.90 lp<-2.0 -> recall  2.9%, precision 19.4%, 0.18   <- the loosened setting
    nsp>0.95 lp<-2.0 -> recall  0.0%, precision  0.0%, 0.00   <- as shipped

Precision peaks near 20%: four of every five drops would be real dialogue. Per `0ee667e`,
"a caption that never covers its line is lost content. That is the worse failure." So an
inert rule was judged strictly better than any reachable setting, and the rule was kept
deliberately unreachable with a comment forbidding a "fix".

Two further facts were established on 2026-08-24, and they are what changed the decision.

First, `large-v3-turbo` — the model in production — returns `no_speech_prob` of **exactly
0.0**, median and max, across 263 segments; and 0 of 267 segments carried a live value in
the production path. Not ~1e-10 as previously believed. Neither nsp rule can evaluate to
true on any input the pipeline actually sees.

Second, and decisively: `large-v3` **does not fix this**. Measured on the same episode,
same beam, card to itself, it produces a live nsp distribution (median 0.397, max 0.963,
6 segments over 0.95) — and `music_rule_would_fire` is still **0**, at beams 3, 4 and 7.
None of the segments clearing `nsp > 0.95` also has `avg_logprob < -2.0`; large-v3's worst
5% of segments sit at -0.445 and the rule wants -2.0. The two conditions do not co-occur
on this content.

## Decision

Delete both nsp-gated rules rather than tune them.

The rule is not dead because the decoder collapsed a signal, which a model change could
repair. It is dead because the conjunction it asks for does not occur in this material,
and because every reachable relaxation of it destroys more real dialogue than it saves.
Those are permanent properties of the content and the measurement, not of the model.

Rejected alternatives:

- **Keep them inert, as before.** This was the right call while "the model collapsed nsp"
  was the explanation, because a better model would have revived them. That explanation is
  now falsified: a model with a perfectly live nsp still never fires the rule. What remains
  is a rule that cannot fire, evaluated on every card, forever.
- **Switch to `large-v3` to revive them.** It buys nothing for the gate — the conjunction
  stays unmet — and costs roughly 4x throughput at matched beam (1.64 vs 6.32 min/episode)
  with confidence a wash (logprob median -0.222 vs -0.225).
- **Loosen the thresholds.** Refused on the same evidence as 2026-08-21, which this ADR
  preserves above. Nothing measured since has improved that precision ceiling.

`low_conf` (`avg_logprob < -0.6`), `blocklist` and `repetition` are KEPT: all three fire on
real content — 10, and 1 respectively in a single validation episode.

## Consequences

Easier: five gated rules become three, and every remaining one demonstrably fires. The
liveness counters added on 2026-08-22 stop reporting two rules that evaluate on every card
and can never activate, which is noise in exactly the instrument built to detect dead rules.
`drop_reason` no longer reads `no_speech_prob` at all, so the gate's behaviour no longer
depends on a field the production decoder does not populate.

Harder, and accepted: the pipeline has no music/silence drop defence. In practice it never
had one — the rule caught zero cards in its entire life — so nothing is lost that was ever
gained. `BLOCKLIST` and `is_repetition` remain the live defences, as they already were.

If a future decoder produces a nsp/logprob pair that DOES co-occur, this decision must be
revisited from the measurement above rather than by re-adding the rule from memory: the
precision ceiling near 20% is the thing to beat, not the threshold.

Historical `conf.json` sidecars still carry `flag: "maybe_silence"` from past runs, so
`tools/timing_compare.py` keeps its bucket for that key. Deleting the rule does not
retroactively clean the data it produced.
