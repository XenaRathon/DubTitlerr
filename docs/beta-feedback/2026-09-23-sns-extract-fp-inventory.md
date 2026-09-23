# S&S extract-only prototype — false-positive inventory (2026-09-23)

Run against 3 real extracted subtitle-stream .ass tracks (one per show class from
Task 18's discovery: a fansub dialogue track, a signs-only track, One Pace) via:

```sh
python3 tools/sns_extract.py track1.ass track2.ass track3.ass --out /tmp/sns-out
```

## FP classes observed

- **position_only, alignment-only (\an8/\an7/... with no \pos):** count and 2-3
  example lines. This is the class `test_classify_event_an8_top_alignment_counted_
  position_only` names explicitly as "known" -- record whether it's actually noisy
  on real tracks or mostly correct in practice.
- **position_only, genuine sign but style already matched by dub_signs_merge.keep_
  event:** count -- these are harmless double-counts, not a real FP class, but worth
  separating from the above so the alignment-only class isn't overcounted.
- **drop, should have been kept (false negative):** any sign/credit/karaoke line
  that fell through both classifiers -- count and example lines; this is the class
  that would need a THIRD heuristic if the feature moves forward.
- **keep, should have been dropped (false positive from dub_signs_merge itself):**
  any plain dialogue kept only because of a style-name guess (KEEP_STYLE/WEAK_DROP_
  STYLE) -- not new to this prototype, but worth noting if it shows up disproportion-
  ately in the tracks sampled here.

## Decision

<standalone script vs. future pipeline stage -- per the weekly plan, do not wire
this into merge_pass.sh regardless of the answer here; that requires fixtures beyond
this prototype's programmatic ones, i.e. a follow-up task, not this one.>
