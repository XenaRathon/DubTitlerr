## Problem

S32E02 dubtitles have noticeably bad timing — dub lines do not line up with the corresponding Japanese audio.

Observed 2026-09-08. Not yet measured: haven't logged against the video to characterize whether this is a constant offset, a drift, or desync concentrated in one section. That determines which fix applies (start-offset correction in `extract_wav`, a re-anchor pass, or a whole-episode rebuild).

## Why this matters

One Pace is the only fully-supported config for the current beta release, so a visibly-broken episode is exactly the kind of first impression we don't want to ship with.

## Open questions

- What's the actual offset — constant, or does it grow across the episode?
- Does the audio start offset (`generate.extract_wav`) threshold need to be widened, or is this an anchoring failure on a re-edit?
- Is the source file for S32E02 re-edited (OP/ED stripped like the rest of the show), or is it a different kind of copy that's feeding the pipeline an unexpected start?

## Related

- Track 0 #1 in the beta plan (audio start offset threshold) — same class of bug, different episode.
- Glossary config: `One Pace.json` under `dubtitle-config/decisions/`.
