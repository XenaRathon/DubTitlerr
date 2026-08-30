# Transcription ignores a delayed audio stream, shifting every cue by that delay

Status: open
Created: 2026-08-30
Found by: owner, watching SAO S01E01 — "approximately 1600ms too early"

## Description

`generate.extract_wav` (`generate.py:245`) extracts the audio whisper transcribes:

    ffmpeg -nostdin -y -v error -i <video> -map 0:<idx> -ac 1 -ar 16000 -c:a pcm_s16le <wav>

There is no `-copyts`, no `-ss`, and no compensation for the audio stream's `start_time`.
ffmpeg normalises the extracted wav to begin at its first sample, so whisper's timestamps
are relative to a zero that may sit some distance into the VIDEO timeline. The cards are
then written against the video timeline with the offset never added back, so every cue in
the episode is early by exactly the audio delay.

## Measured, 2026-08-30

    SAO S01E01           audio stream starts  +1745 ms   <- video and all 4 sub tracks at 0
    SAO S01E02-E24       audio starts            -7 ms   (Opus pre-skip, negligible)
    One Pace S31 (48)    audio starts             0 ms

`+1745 ms` matches the owner's observed "~1600 ms early" on the one episode that has it.

Only E01 of the 73 episodes measured carries a material offset, so this is a property of
that release rather than a systemic misalignment. The defect is the ABSENT GUARD, not the
prevalence. Any release with a delayed audio stream ships subtitles shifted by that delay,
and nothing detects it — not qc, not the review queue. A human watching the episode is
currently the only detector.

### Proven, not inferred: the offset really is dropped

Running the pipeline's own extraction command on E01 (same `-map`, `-ac`, `-ar`, `-af`):

    video duration : 1422.588 s
    wav   duration : 1418.295 s

The wav matches the AUDIO STREAM's own length, so the 1.745 s leading offset is discarded
rather than padded with silence — `AUDIO_FILTER` is `highpass`+`compand`, neither of which
pads, and there is no `aresample=async`. Whisper therefore times every word against a zero
that sits 1.745 s into the video. (The remaining 2.5 s of the 4.3 s total difference is the
audio stream ending before the video does, which is unrelated and harmless.)

Note the owner confirmed audio and video themselves are in sync on playback. That is
expected and is not a counter-argument: the player honours the stream's `start_time`, so A/V
is correct while the subtitles — built from a wav that discarded it — are not.

### Corroborated independently by the signs/songs track

The owner also reported the signs/songs in the muxed Dubtitles track looking LATE, and
guessed the signs had not been offset the way the dialogue was. That is exactly right, and
it is a second symptom of the same single cause:

- `dub_signs_merge.build()` copies signs events VERBATIM (`base.events.append(ev)`), with no
  timing transform — so the signs are correctly aligned to the video.
- The dialogue comes from the whisper-derived srt and is 1.745 s early.
- Offsetting the whole track in the player to fix the dialogue therefore pushes the
  already-correct signs late by the same amount.

The signs are NOT broken and need no fix. Two observations, one cause. Once the dialogue is
corrected at the source, both align with no player-side retiming — which is also an
acceptance test a human can run without any tooling.

## This blocks the E01 re-run

The 2026-08-29 handoff records that SAO E01 needs a second pass (a `.dubtitles.fail` marker
from an operator SIGTERM was parked after `generate.py` had computed `todo=24`) and says to
re-run the same command. Do NOT, until this is fixed — the re-run regenerates the same
1.745 s-early track. E01 currently has no `.dubtitles.conf.json`, `.dubtitles.words.json` or
`.dubtitles.done`, so there is nothing to salvage; it transcribes from scratch either way.

## Open question for the owner

Should a non-zero audio start be SILENTLY CORRECTED, or REFUSED AND LOGGED? Correcting is
friendlier and is almost certainly right. Refusing is more conservative and surfaces an
unusual release for a human to look at. A third option is correct-and-log, which fixes the
output while leaving evidence that the release was unusual — probably the answer, but it is
the owner's call, not a detail to infer.

## Acceptance criteria

- [ ] A video whose audio stream starts at a non-zero offset produces cards aligned to the
      VIDEO timeline, not the audio's own zero.
- [ ] Asserted on a synthetic delayed-audio fixture — no natural one is in the suite, and
      SAO E01 is not reachable from it.
- [ ] A zero-offset video produces byte-identical output to today (One Pace, all 48 episodes
      measured at 0, must not move).
- [ ] The `-7 ms` Opus pre-skip case does not trigger whatever guard is added — sub-frame
      offsets are noise, not delay. Pick and justify the threshold.
- [ ] Whatever the owner decides on correct-vs-refuse is what the code does, and the log line
      says which happened.
- [ ] SAO S01E01 is re-run afterwards and BOTH its dialogue and its signs line up with no
      Plex-side retiming — the signs are the control, since they are already correct.

## Evidence

Pending.

Measurement to re-derive: `ffprobe -v error -select_streams a:0 -show_entries
stream=start_time -of json <video>` over a season, compared against the video and subtitle
streams' `start_time` from the same probe; then the extraction command above, comparing the
wav's duration to the video's.
