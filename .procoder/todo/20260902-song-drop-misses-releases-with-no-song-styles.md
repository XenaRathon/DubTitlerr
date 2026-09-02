# The song-span drop cannot fire on a release whose signs track has no song styles

Status: open
Created: 2026-09-02

## Description

`_song_spans` builds its intervals from events whose STYLE matches `SONG_FAMILY_STYLE`
(`^(?:opening|ending)[\s_-]|^(?:op|ed)\d+[\s_-]`). A release that carries no such style
yields no spans, so nothing is dropped -- and whisper's transcription of the sung OP ships
exactly as it did before the fix.

MEASURED 2026-09-02 on MARRIAGETOXIN S01E02 (production library, read-only). Its three
English tracks use only `Default`, `Italics`, `Flashback`, `Top`: zero karaoke tags, zero
song-family styles, zero spans, zero cards dropped. Fifteen song cards ship in the OP
window (55.2-111.1s), and they are unmistakable:

      55.2-  57.3  lp=-1.343  No mama, lots of time.
      61.3-  64.3  lp=-0.459  Fun, fun, fun, you're so cool, no, blah, blah?
      65.0-  67.0  lp=-1.654  Rage in the end of the day.
      70.9-  74.1  lp=-2.059  Tock of, 抱えたままで.
      80.5-  82.3  lp=-0.867  Toxic, 君のため never.
      95.8- 102.0  lp=-0.280  欲しいの Toxic ずっとここにいるよ不思議なほど

against -0.007 / -0.015 / -0.002 for the ordinary dialogue on either side of them.

CONFIRMED BY THE OWNER, watching S01E02 directly: the signs track is `English (Forced)`
and it IS being pulled into the dubtitle track correctly, and **the release ships no lyric
captions for the OP at all**.

That last point is the one that matters, and it changes what a fix can be. The drop derives
its spans from the fansub's OWN song events. This release has none -- not oddly-named ones,
NONE. So widening `SONG_FAMILY_STYLE`, adding style patterns, or matching more keywords
cannot help here and never will: there is nothing on the signs track to derive a span from.
Any fix has to read the DUB CARDS themselves.

This is NOT a regression -- the behaviour predates the fix and the fix simply cannot reach
it. But the CHANGELOG says whisper's sung OP/ED "is dropped from the dub track", and for a
release shaped like this one that is not true. The signs half of the merge works correctly
here (62 `Default`-styled sign events kept via their `\pos`/`\move` tags, which is the
weak-drop-yields-to-keep-tag rule doing its job); it is only the song half that no-ops.

Done looks like: the drop stops depending on the fansub having captioned the song at all,
or the changelog and wiki say plainly that a release which does not caption its OP lyrics
gets no protection.

## The signal is already on disk

`conf.json` persists `avg_logprob` per card -- it is in the field list today, no new
pipeline stage needed. That is the gate `build()`'s debt: note already names as the
alternative to a blanket span cut.

Note it is not sufficient alone: the pure-Japanese cards above score -0.145 / -0.153 /
-0.280, well inside the ordinary-dialogue range. A CJK-script check is the obvious
companion -- the dub track is English by construction, so a card carrying kana/kanji is
wrong whatever its confidence. Neither test needs a signs track at all, which is the point.

## Acceptance criteria

- [x] A release that captions NO song lyrics at all now has its sung-OP output dropped by a
      rule that needs no signs track: `hallucination.drop_reason` -> `cjk_in_english_dub`.
      A style-pattern change could never have satisfied this, and none was made.
- [x] Measured against SAO S01E02, which the signs-track drop already handles: 58 CJK cards
      across the show, all lyrics, and the existing 25-card song-span drop is untouched.
- [x] Tests fail against the previous implementation.
      `tests/test_hallucination.py::test_japanese_script_in_an_english_dub_is_dropped`
- [~] MARRIAGETOXIN S01E02's fifteen OP cards: **10 of 15 removed, not 15.** The five that
      remain are pure English -- "No mama, lots of time.", "Fun, fun, fun, you're so cool,
      no, blah, blah?", "Rage in the end of the day.", "Let's go!" -- and nothing
      categorical separates them from dialogue. The only remaining lever is an avg_logprob
      threshold, and ADR 0002 is the standing measurement against exactly that: the
      nsp/logprob rules were DELETED rather than tuned because every reachable relaxation
      destroyed more real dialogue than it saved. This criterion is revised rather than
      met, deliberately. The dialogue at 12.8-34.2s and 127.4s+ IS untouched, as required.

## Evidence

Implemented on `feat/review-sorting`, 2026-09-02.

- `hallucination.has_cjk` / `drop_reason` -> `cjk_in_english_dub`. NOT a tuned threshold,
  which is what ADR 0002 forbids: it has no threshold and no precision/recall trade-off.
  The dub track is English by construction, so kana/kanji is whisper falling back to the
  Japanese under a song. A dub says a Japanese name in romaji, never in kana.
- MEASURED over the whole production library: 1,240 of 395,671 cards (0.3134%) across 24
  shows. Sampled every affected show; every hit was an OP/ED lyric and not one resembled
  dialogue. Many carry GOOD avg_logprob (-0.02, -0.04, -0.07, -0.11), which is the direct
  evidence that no confidence gate could have found them.
- `TEXT_VERSION` 8 -> 9. The gate runs inside `generate.text_stages`, the CPU-only tier, so
  unlike the merge-stage song drop this DOES reach episodes already in the library --
  re-derived from words.json, no GPU. common.py's own rule requires the bump and says
  nothing detects it mechanically.
- 3 new tests; full suite green (exit 0).

Known residue, accepted: pure-English song hallucination on a release that captions no
lyrics. Named here rather than left to be rediscovered.
