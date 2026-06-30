# Plan — D1: Mux dubtitles + fonts into the MKV

> After spec approval. Approving triggers kickoff (branch).

## Branch and delivery

- **Branch:** `feat/d1-mux-fonts` (base: `main`).
- **PR slicing:** single, direct-merge to main (build flow).

## Technical approach

Enhance the existing `mux.py` and wire it per-episode into the merge loop. Keep the heavy
mkvmerge/os.replace work where it is, but **extract pure helpers** so the policy logic is
unit-testable without mkvtoolnix: stamp read/write/validate, `is_muxed` (stamp + ffprobe),
free-space gate, subtitle-keep decision (incl. signs/songs survival), and the existing
`build_cmd` (operates on an `mkvmerge -J` dict — testable with a fake identify). `generate.py`
gains a stat-only `.dubtitles.done` skip. Test-first for the helpers; the real remux is
validated by the multi-show end-to-end on the server.

## Affected files (by layer)

| Layer | File | Change |
|---|---|---|
| Core | `mux.py` | `DELETE_BROKEN_HARDLINKS=0` default; `.dubtitles.done` stamp (write after verify+replace, before sidecar rm; record size+mtime); `MIN_FREE_GB` free-space gate (`has_room`); **mp4→mkv** path (embed `.srt`, remove old `.mp4` link only); broaden `keep_sub` (mul / signs-songs name); EXDEV-safe finalize; assert fonts kept. |
| Orchestration | `merge_pass.sh` | After assemble (mkv `.ass`) or for a terminal mp4 `.srt`, run the per-episode mux (root); skip if stamped/muxed. |
| Orchestration | `generate.py` | `needs_work()` + `process()` skip on a valid `.dubtitles.done` stamp (stat-only). |
| Image | `Dockerfile.builder` | `apt-get install mkvtoolnix`. |
| Tests (new) | `tests/test_mux.py` | stamp, is_muxed/skip, has_room, keep_sub (signs/songs), build_cmd flags (fake identify), mp4 detection. |

## Risks and mitigation

| Risk | Mitigation |
|---|---|
| Atomic finalize EXDEV (temp on another mergerfs branch) | Detect EXDEV; retry with a temp colocated on the target's branch; never leave a partial library file (verify-then-replace). Validated on server. |
| Filling the near-full pool | `has_room` pre-check skips+logs; self-throttles; reaper frees old inodes. |
| Breaking a seeding torrent | Never delete partner hardlinks; only the library's own old file. |
| mp4→mkv rename confuses Sonarr/Radarr | Accepted (user chose uniform mkv); call out in the rollout notes; arrs re-import the renamed file. |
| Re-transcription loop after sidecar deletion | `.dubtitles.done` stat-gate + ffprobe backstop; explicit test. |
| Losing weird signs/songs tracks | `keep_sub` keeps `mul`/signs-songs-named tracks; tested. |

## Rollback and reversibility

- Code revert + image rebuild restores sidecar behavior. **Muxing itself mutates media files**
  (container/track changes, mp4→mkv) — not auto-reversible per file, but originals survive as the
  seeding hardlink partners until the reaper runs. Roll out gradually (start with a few shows).

## Testing strategy

- **Unit (pytest):** the extracted pure helpers — stamp round-trip + staleness, `has_room`
  boundary, `keep_sub` (eng/orig kept, fre dropped, `mul`/signs-songs kept), `build_cmd` sets
  eng-audio-default + Dubtitles-default + drops foreign + keeps attachments (fake identify dict),
  mp4-vs-mkv branch selection.
- **Integration — FULL A1→D1 end-to-end on the server (the user's requirement):** pick a random
  episode from each of **One Pace, Reborn as a Vending Machine, JoJo's Bizarre Adventure (2012),
  Fullmetal Alchemist Brotherhood, + 1–2 more random shows**; run generate→repair→assemble→mux;
  verify each: clean reflowed timing (A1), correct names (C1, where a glossary exists),
  no hallucinations/loops (B1), and an embedded default Dubtitles track **with fonts** rendering
  signs/karaoke (D1) — especially JoJo's `mul`-tagged signs/songs. Eyeball in Plex / via ffprobe.
- Coverage ≥90% on `mux.py`'s pure helpers.

## Observability

- mux logs per episode: muxed / skipped-no-room / verify-fail / dropped-tracks; the merge loop
  reports muxed count per pass.
