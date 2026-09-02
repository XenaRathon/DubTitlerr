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

- [ ] A release that captions NO song lyrics at all still drops whisper's sung-OP output,
      or the docs state the limitation explicitly and name what a user should expect.
      A style-pattern change alone cannot satisfy this and does not count.
- [ ] MARRIAGETOXIN S01E02's fifteen OP cards are the fixture: whatever is built must
      remove them and must leave the dialogue at 12.8-34.2s and 127.4s+ untouched.
- [ ] Whatever gate is chosen is measured against a release the CURRENT drop already
      handles (SAO S01E02, 25 cards) to prove it does not regress that.
- [ ] A test that fails against today's style-only implementation.

## Evidence

<!-- filled at close -->
