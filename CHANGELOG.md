# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). Nothing has been
tagged yet — this file starts at the public beta. `TRANSCRIBE_VERSION`/`TEXT_VERSION` in
`common.py` are the pipeline's own version history (they say what changed in the _output_,
and only a stamp bump puts the fix into already-processed files); the entries below summarize
that history alongside everything else that shipped since.

## [Unreleased]

### Fixed

- `export_subtitles`: the public repository publishes `Show - SxxExx - Episode Title`, not
  the media filename. The encode's provenance (`[WEBDL-1080p][8bit][AAC 2.0][x264]-VARYG`,
  and the unbracketed `1080p 6ch x265` shape) is meaningful in a library and is noise on a
  subtitle download. Measured against the production library: 386 of 845 completed episodes
  are renamed, 459 already matched and are untouched — including all 48 episodes already
  published, so nothing in the repository moves for this.
- `export_subtitles`: a show that publishes nothing no longer has a manifest file created
  for it. The file's existence is the claim "this show is published", and the publish script
  runs the exporter over every directory in the library -- 95 of them on 2026-09-04, all
  with nothing to ship. An existing manifest is still rewritten, so a set that shrinks to
  zero is recorded rather than left stale.
- `publish_subtitles.sh`: the subtitle checkout is declared a safe directory before it is
  read. It is a bind mount into a container running as root, so git refused the host-owned
  repository as "dubious ownership" -- verified on the real deployment, where every
  scheduled run would have died at `git status`. The missing-git check also moved to the
  top of the script: the library walk takes minutes, and a run that discovers its missing
  tool at the end has already spent them.
- `publish_subtitles.sh`: an environment without `git` is refused (exit 3) instead of
  reading as "nothing changed - no commit". Observed 2026-09-04 on vm102: the container
  image carried no git, so a full library sweep reported success and published nothing.
  `git` is now installed in `Dockerfile.builder`, which is where the publish path runs.
- `export_subtitles`: two encodes of one episode (they differ only by a release tag, e.g. a
  `[JA+EN]` re-release — 19 titles across 38 files in the library) now publish once and are
  counted as `duplicate-encode`. Previously the second silently overwrote the first's files
  and the manifest carried two entries under one key, which republished the pair on every
  sweep as the winner alternated.

## 0.1.0 - 2026-09-04

The first public beta. Everything below shipped before the first tag; the pipeline's own
output versions (v2-v8) are listed at the end, since they are what decides whether an
episode already in your library is stale.

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
- `tools/asr_bakeoff.py` — the ASR bakeoff harness: runs faster-whisper, NeMo (Parakeet,
  Canary) and Qwen3-ASR entrants over the same episodes on one card, and scores them against
  a real reference transcript rather than against each other. Measured results for a 6GB
  GTX 1060 and an 8GB RTX 2070 Super are in `docs/asr-bakeoff/`, and the reasoning behind the
  `WHISPER_MODEL`/`COMPUTE_TYPE` defaults is now written down in the wiki's
  _Choosing an ASR model_ rather than assumed.

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
  is no longer missing. Only releases whose signs track carries song-family styles are
  affected; a track without them is untouched. Measured 2026-09-02 against the production
  library: SAO, JUJUTSU KAISEN, SPY x FAMILY and Reborn as a Vending Machine as expected,
  and also One Pace seasons 17 and 27 (25-26 dropped cards per S27 episode), which earlier
  notes in this repository wrongly described as having no OP/ED at all. Most other One Pace
  seasons do produce no spans.
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
- Docs: the `COMPUTE_TYPE` reference row claimed `float16` was the quality setting. The
  bakeoff disproved it — on Pascal cards `float16` does not load at all, and where both load
  the transcripts are equivalent. Precision is a compatibility knob here, not a quality one.

### Pipeline output-version history (see `common.py` for the authoritative log)

- **v9** (2026-09-02) — the hallucination gate drops a card carrying Japanese script: in an
  English dub that is whisper falling back to the Japanese it heard under a song, not a
  low-confidence English line. 1,240 of 395,671 cards across 24 shows, every sampled one an
  OP/ED lyric. Unlike the signs-track song drop, this reaches releases that caption no song
  lyrics at all — and unlike that fix, a `TEXT_VERSION` bump DOES carry it into episodes
  already in your library, on CPU, without re-transcribing.
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

[Unreleased]: https://github.com/XenaRathon/DubTitlerr/compare/v0.1.0...HEAD
