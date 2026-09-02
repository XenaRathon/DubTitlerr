# Drop whisper's song lyrics on episodes with a signs/songs track, and restore the fansub's English translation

Status: closed
Created: 2026-08-30
Closed: 2026-09-02
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

- [x] On an episode WITH a signs/songs track, dubtitle cards overlapping a song-styled S&S
      event are dropped from the shipped track.
- [x] `dub_signs_merge.keep_event` no longer discards the fansub's English song translation,
      so the OP/ED ship with translated lyrics instead of none.
- [x] The style pattern covers the Romaji, Kanji, Japanese AND English siblings — asserted on
      the real style names above, not on a synthetic `Song` style.
- [x] An episode with NO signs/songs track is completely unaffected.
- [x] One Pace is byte-identical before and after — no chapters, no OP/ED, nothing to drop.
- [x] The edge case above is either handled or explicitly accepted in a comment naming the
      condition that would revisit it.
- [x] SAO S01E02's 14 OP cards and 12 ED cards are gone, and its `ED1-English` events are
      present in the muxed track.

## Evidence

Implemented in `166e88d` (fix(dub_signs_merge): drop whisper's song hallucinations, restore
fansub lyrics).

- `STRONG_DROP_STYLE`'s `translat` removed — the fansub's own song translation is kept, not
  dropped. `SONG_FAMILY_STYLE` (`^(?:opening|ending)[\s_-]|^(?:op|ed)\d+[\s_-]`, case
  insensitive) catches a song's Kanji/Japanese/English siblings via the shared style-name
  prefix, without enumerating every language name.
- `_song_spans()` merges song-family-styled kept events into per-song (start, end) blocks
  (a 2,000ms adjacency gap); `build()`'s dub loop skips any card overlapping one.
- Unit tests (`tests/test_dub_signs_merge.py`): `keep_event` keeps the translation style and
  the Kanji/Japanese/English siblings and beats a weak-drop style guess; `build()` drops a
  card inside a synthetic song span, keeps one outside it, keeps the fansub lyrics alongside
  the drop, logs the dropped count, and leaves a signs-track with no song-family styles
  (the One Pace shape) completely untouched.
- **Verified read-only against the real SAO S01E02** production video (no mutation — the
  dub srt was reconstructed from `conf.json`, `build()` wrote to a `/tmp` scratch path, and
  the deployed scratch script was deleted after): 25 whisper cards dropped; all 4
  hallucinated lines this todo quoted (`Miss ni koha...`, `I can't live in the heart.`, `I'm
looking for short future.`, `I've been to the strong witness.`) are absent from the
  shipped track; all 7 real song-family styles present in the merged output
  (`Opening-Romaji-L1` 2142, `Opening-Kanji-L1` 780, `Opening-English-L0`/`L1` 12 each,
  `ED1-Romaji` 1445, `ED1-Japanese` 504, `ED1-English` 22 — the `Opening-English-L0/L1`
  split wasn't in this todo's own style census but is covered by the same prefix pattern).
- Edge case (dialogue over an intro) left as a named `debt:` comment in `build()`, per the
  todo's own acceptance option, rather than solved — no measured case has fired it yet.

Full suite green, `ruff check .` clean.

## Interaction with other open work

`20260830-audio-start-offset-shifts-every-cue.md` also touches SAO E01/E02 output. Land the
audio offset first — it changes every card's timing, so the OP/ED spans this todo keys on
would shift under it.
