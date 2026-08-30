# Drop whisper's song lyrics on episodes with a signs/songs track, and restore the fansub's English translation

Status: open
Created: 2026-08-30
Owner decision: option 1 of 2 — drop the transcription AND bring back the fansub's English
song translation, so the viewer gets translated lyrics rather than invented ones.

## Description

On an episode carrying a signs/songs track, the OP/ED lyrics whisper transcribes are dropped
from the dubtitle track, and `dub_signs_merge.keep_event` stops discarding the fansub's
English song translation.

This REVERSES a deliberate decision, and the reversal is the point. `dub_signs_merge.py:44`
currently reads:

    # KEEP the Japanese romaji karaoke (top) + signs/credits. DROP the fansub English song
    # TRANSLATION -- it's replaced by whisper's transcribed English-dub lyrics (bottom Dubtitles).

That premise holds only if the dub re-sings the opening in English. SAO's opening is sung in
Japanese, so nothing replaces the translation that was thrown away — and what lands in its
place is hallucination.

## Measured, 2026-08-30 — SAO S01E02, inside the `OP` chapter (40.04–130.005 s)

     59.32  lp=-1.85   Miss ni koha Cait ta u,
     64.46  lp=-0.47   shiro no shibu kagejit wo ima ni.
     71.08  lp=-1.68   Utsus isu isu no
     85.00  lp=-2.71   I can't live in the heart.
     95.78  lp=-4.08   I'm looking for short future.
    104.78  lp=-2.86   I'm gonna be able to pray.
    108.52  lp=-3.60   I've been to the strong witness.

14 cards in the OP, 12 in the ED, all of it worthless: whisper mangles the Japanese into
pseudo-romaji and then invents English outright. `avg_logprob` runs -1.7 to -4.1 against
-0.3/-0.7 for ordinary dialogue in the same episode — the confidence signal already knows,
nothing acts on it.

## Scope

Only conventional releases are affected: SAO, JUJUTSU KAISEN, SPY x FAMILY, Vending Machine.

**One Pace is unaffected and must stay untouched** — it has no chapters and no OP/ED at all
(the re-edits strip them), which is why this never surfaced across 461 One Pace episodes.
Any change here should be a no-op on that library.

## Detection: style name, NOT `\k`

SAO E02's signs/songs track carries **no `\k` karaoke tags at all** — it times syllables as
2,142 separate events per song. `dub_signs_merge.KARAOKE` (`\\[kK][fo]?\d`) therefore finds
nothing on this track and cannot be the primitive.

The style names are explicit and are the way in:

    Opening-Romaji-L1  2142    ED1-Romaji    1445
    Opening-Kanji-L1    780    ED1-Japanese   504
    title                89    ED1-English     22
    Signs                70    prev            20

Note `common.DIALOGUE_EXCLUDE_STYLE` matches `romaji` but NOT `Opening-Kanji`,
`ED1-Japanese` or `ED1-English`. Whatever pattern is chosen must cover the Kanji/Japanese/
English siblings, or half of each song's events stay unclassified.

Chapters are a viable alternative and are clean on this release (`Intro` / `OP` / `Part A` /
`Part B` / `ED` / `Next Time`), but they are absent on other releases, whereas the condition
the owner actually stated is "episodes with a S&S track". Prefer the S&S song-style spans;
chapters are at most a cross-check.

## Known edge case, unsolved

Dialogue spoken OVER an opening would be dropped along with the lyrics, because the song
events run continuously across the whole OP. SAO E02 has none (its first card is at 59.32
against an OP starting at 40.04, so the instrumental intro is empty), but a show with
narration over the opening would lose it. Decide whether that is acceptable or whether the
drop needs a confidence or language check to distinguish sung lyrics from spoken dialogue —
`avg_logprob` separates them cleanly in the measured sample (-1.7/-4.1 vs -0.3/-0.7) and is
already on every card.

## Acceptance criteria

- [ ] On an episode WITH a signs/songs track, dubtitle cards overlapping a song-styled S&S
      event are dropped from the shipped track.
- [ ] `dub_signs_merge.keep_event` no longer discards the fansub's English song translation,
      so the OP/ED ship with translated lyrics instead of none.
- [ ] The style pattern covers the Romaji, Kanji, Japanese AND English siblings — asserted on
      the real style names above, not on a synthetic `Song` style.
- [ ] An episode with NO signs/songs track is completely unaffected.
- [ ] One Pace is byte-identical before and after — no chapters, no OP/ED, nothing to drop.
- [ ] The edge case above is either handled or explicitly accepted in a comment naming the
      condition that would revisit it.
- [ ] SAO S01E02's 14 OP cards and 12 ED cards are gone, and its `ED1-English` events are
      present in the muxed track.

## Evidence

Pending.

Measurements to re-derive: chapter spans via `ffprobe -show_chapters`; the OP/ED cards by
filtering `<stem>.dubtitles.conf.json` to those spans and printing `avg_logprob`; the style
census by loading the S&S stream with `pysubs2` and counting `event.style`.

## Interaction with other open work

`20260830-audio-start-offset-shifts-every-cue.md` also touches SAO E01/E02 output. Land the
audio offset first — it changes every card's timing, so the OP/ED spans this todo keys on
would shift under it.
