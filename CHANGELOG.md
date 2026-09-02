# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). Nothing has been
tagged yet — this file starts at the public beta. `TRANSCRIBE_VERSION`/`TEXT_VERSION` in
`common.py` are the pipeline's own version history (they say what changed in the _output_,
and only a stamp bump puts the fix into already-processed files); the entries below summarize
that history alongside everything else that shipped since.

## [Unreleased]

### Added

- Per-show glossary acquisition, arc/episode-scoped: wiki-mined proper nouns admitted per
  episode rather than per franchise, with per-token provenance and a repair-weighting pass
  by episode/arc tags.
- Review page: user-selectable sort order (chronological, queue order, longest-first,
  alongside the measured risk-first default) on both the episode and shared-lines pages.
- `tools/export_reviewed.py` / `tools/export_subtitles.py` — publish dubtitles to a public
  subtitle repository, gated on full human review or (separately) on pipeline completion.
- `docs/wiki/` — the wiki content lives in this repository now and mirrors to both GitHub
  and the self-hosted Forgejo wiki via `tools/sync_wiki.sh`.
- [XenaRathon/DubTitlerr-glossaries](https://github.com/XenaRathon/DubTitlerr-glossaries) —
  the community glossary repository.
- `decisions.locked()` — a cross-process file lock around a show's decision-store
  load-modify-save, closing a race between the review server and the `unresolved.py` CLI.

### Fixed

- `dub_signs_merge`: a style-name guess (e.g. a style named like a dialogue track) now
  yields to an unambiguous keep-tag (positioned, karaoke, drawing, animated) — previously
  such signs/song events were silently dropped from the merged track.
- `dub_signs_merge`: whisper's transcription of a sung OP/ED is dropped from the dub track
  and the fansub's own song translation is kept instead. Whisper does not transcribe
  Japanese singing, it hallucinates over it (`avg_logprob` -1.7 to -4.1 against -0.3/-0.7
  for ordinary dialogue), and the fansub translation it displaced was being discarded. A
  song's Kanji/Japanese/English sibling styles are now recognised by their shared
  `Opening-`/`ED<N>-` prefix rather than by keyword, so half of each song's on-screen text
  is no longer missing. Only releases with a conventional OP/ED are affected; a track with
  no song-family styles is untouched.
  **Forward-only, with a targeted re-open.** This changes the merge stage, not the words or
  the text, so `TEXT_VERSION` does not cover it and an already-muxed episode has no sidecar
  left for the merge to rebuild — it keeps its hallucinated song cards. To correct an
  existing library, point `tools/reopen_for_signs.py` at the shows that have an OP/ED
  (dry run first) and let the next `merge_pass.sh` sweep re-merge and re-mux them. A
  `TEXT_VERSION` bump would also work and would re-mux every episode in the library,
  including the many with no song styles at all.
- `generate.py`: a delayed audio stream's start offset is now carried onto the video
  timeline (measured up to +1745ms on one show), instead of shipping every cue early by
  that delay. **Forward-only.** The offset is applied to the word timestamps before they
  are persisted, so an episode transcribed before this fix has the uncorrected times baked
  into its `words.json` and no text-tier rebuild can recover them — only a re-transcribe
  can, which is why `TRANSCRIBE_VERSION` was deliberately NOT bumped (it would put the
  whole library back through the GPU). Episodes already in your library keep the old
  timing; new ones get the fix.
- `repair.py`: a card the repair stage skips (no fansub anchor, or an unreachable LLM
  backend) no longer discards a human's stored `correct`/`force` verdict for that line —
  it ships the human's text instead of reverting to raw ASR.
- `repair.py`: a merge pass that would strip every repair from an already-repaired episode
  (e.g. a misconfigured backend) now aborts that episode instead of silently reverting it.
- `review_apply`: saving a verdict against an already-muxed episode now re-opens it so the
  correction actually reaches the video, instead of only updating the decision store.
- `export_subtitles`: no manifest entry is written for an episode whose `.ass` extraction
  failed.

### Pipeline output-version history (see `common.py` for the authoritative log)

- **v8** (2026-08-29) — two reflow character-welding fixes (thousands separators, decimal
  points wrongly joined to the previous word).
- **v7** (2026-08-26) — the phonetic name guard widens from substitutions to any gained
  (fabricated) name.
- **v6** (2026-08-26) — repair gains the phonetic name guard: rejects an LLM repair that
  substitutes a proper noun found in neither the glossary nor the original.
- **v5** (2026-08-24) — the single version splits into `TRANSCRIBE_VERSION`/`TEXT_VERSION`,
  so a text-only fix no longer forces a full re-transcribe.
- **v4** (2026-08-21) — hyphenated words no longer ship with a stray space
  ("Gas -Gas" → "Gas-Gas"); 9 One Pace glossary hard-fixes added.
- **v3** (2026-08-20) — sub-`MIN_DUR` cards repaired, multi-line cue wrapping restored,
  sentence punctuation restored before card splitting.
- **v2** (2026-07-27) — fixed a signs-merge bug that rendered captions as solid black
  and duplicated signs across tracks.

[Unreleased]: https://github.com/XenaRathon/DubTitlerr/commits/main
