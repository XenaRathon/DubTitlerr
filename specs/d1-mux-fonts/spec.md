# Spec — D1: Mux dubtitles + fonts into the MKV

> Final step of the DubTitlerr quality build (A1/C1/B1 done). Grilled on the brainstorm +
> the idempotency design from the opening conversation. This is the fix for the original
> complaint: signs/songs rendering flat-black / misaligned because a sidecar `.ass` can't
> carry the embedded fonts.

## Context and problem

A sidecar `.ass` can't carry the MKV's embedded fonts, so Plex/libass substitutes a default
font and the karaoke/sign effects (authored for the original font on a 1440×1080 canvas)
render misaligned and muddy. The fix is to **mux** the merged `.ass` **plus the MKV's font
attachments** into the video as a default "Dubtitles" track. `mux.py` already does the mkv
case (mkvmerge remux, fonts kept, default flags, language filter, verify, atomic replace,
`has_dubtitles_track` idempotency) but is standalone and deletes seeding hardlinks. D1 wires
it into the pipeline safely, adds mp4→mkv handling, and adds a durable idempotency stamp so a
muxed file (whose sidecar is gone) is never re-transcribed.

## Acceptance criteria (verifiable)

- [ ] **mkv + `.ass`:** mkvmerge remux embeds the `.ass` as a track named **"Dubtitles"**, set
      **default**; **all font attachments kept** → signs/karaoke render in the correct typeface.
- [ ] **mp4 + `.srt` (no signs):** remux to **mkv** embedding the `.srt` as the default
      "Dubtitles" track; the old `.mp4` library file removed; download hardlink partner untouched.
- [ ] **Audio:** English audio set default; original-language (jpn) audio kept, not default;
      keep `eng/nld/und/`+original audio, drop other-language dubs.
- [ ] **Subtitles:** keep `eng/nld/und/`+original subs **and any likely signs/songs track**
      (lang `mul`, or track name/handler matches signs/songs) so weird JoJo tracks survive;
      Dubtitles default ON (not forced); other subs' default flags cleared.
- [ ] **Per-episode in the merge loop:** after a `.ass` (mkv) or terminal `.srt` (mp4) is ready,
      it's muxed in the same pass; runs as root.
- [ ] **Idempotency:** mux writes `<stem>.dubtitles.done` (recording the muxed file's size+mtime)
      **before** deleting the `.ass`/`.srt`; `generate.py` `needs_work()` skips (stat-only, no model
      load, no re-transcribe) when the stamp matches; `has_dubtitles_track()` ffprobe is the
      authoritative backstop; a replaced file (mtime changed) is correctly re-processed.
- [ ] **No re-transcription of a muxed file** across sweeps (the loop the user flagged).
- [ ] **Disk-safe:** a free-space pre-check skips+logs an episode when the pool lacks room for a
      full-size temp; **never** ENOSPC-crashes.
- [ ] **Hardlinks:** the seeding download partner is **never deleted** (orphan-reaper owns that);
      only the library's own old file is replaced/removed.
- [ ] **Verify-before-replace:** output has video+audio + a Dubtitles track + duration within
      tolerance before the original is touched; ownership preserved.

## Out of scope (explicit)

- The restyle/extract-fonts alternatives (rejected in brainstorm).
- The full library **rollout** (rebuild image, mux all existing episodes, sync glossaries) — a
  separate post-merge operation; D1 delivers the capability + per-episode automation.

## Data contracts

- **Inputs per episode:** the video (`.mkv`/`.mp4`) + its sibling `.eng.dubtitles.ass` (mkv) or
  terminal `.eng.dubtitles.srt` (mp4, no signs).
- **Outputs:** an `.mkv` with the embedded default "Dubtitles" track + fonts; `<stem>.dubtitles.done`
  stamp (`{"size": int, "mtime": float, "muxed": true}`); the `.ass`/`.srt` removed; a
  `.dubtitles.mux.log` audit (dropped tracks).
- **Env:** `MUX_ROOTS`, `KEEP_LANGS`, `DUR_TOL`, `MEDIA_UID/GID`, `MIN_FREE_GB` (skip threshold),
  `DELETE_BROKEN_HARDLINKS=0` (default off now).

## Components / changes

1. **`mux.py`:** add `DELETE_BROKEN_HARDLINKS=0` default (don't touch partners); add the
   `.dubtitles.done` stamp (written after verify+replace, before sidecar removal); add the
   free-space pre-check (`MIN_FREE_GB`); **mp4 path** — remux mp4→mkv embedding the `.srt`,
   remove the old `.mp4` (its own link only), stamp; broaden the subtitle keep to retain
   signs/songs tracks (`mul` / name match); confirm fonts kept (mkvmerge keeps attachments by
   default — assert, don't `--no-attachments`). Handle the cross-branch finalize (EXDEV) safely.
2. **`merge_pass.sh`:** after `dub_signs_merge.py` (and for terminal mp4 `.srt`), invoke the
   mux step per episode (root); skip if already muxed/stamped.
3. **`generate.py`:** `needs_work()` + `process()` also skip when a valid `.dubtitles.done`
   stamp is present (stat-only), in addition to the existing `has_dubtitles_track` gate.
4. **`Dockerfile.builder`:** `apt-get install mkvtoolnix`.
5. **Tests:** `tests/test_mux.py` — stamp write/validate, `is_muxed`/skip logic, free-space
   gate, subtitle-keep (signs/songs survive), build-cmd track/default flags, mp4 detection.
   (mkvmerge calls themselves are integration, validated on the server.)

## Edge cases and failure modes

| Case | Expected |
|---|---|
| mkv has no fonts (plain) | Still muxes the `.ass`; nothing to carry — fine. |
| mp4 with an `.ass` (had signs somehow) | Treat like mkv embed into the new mkv. |
| File replaced after stamp (new download) | mtime mismatch → stamp stale → re-process. |
| Pool too full for temp | Skip + log; retry next pass / after reaper. |
| mkvmerge fails / verify fails | Leave original untouched; remove temp; log; retry later. |
| EXDEV on finalize (temp on another branch) | Fall back to same-branch temp / safe move; never leave a half-written library file. |
| Still-seeding partner | Never deleted (DELETE_BROKEN_HARDLINKS=0). |
| arrs see mp4→mkv rename | Accepted (user chose uniform mkv); note in rollout. |

## Decisions taken

| Decision | Rejected | Why |
|---|---|---|
| Mux (.ass + fonts) | Restyle to safe fonts; extract fonts beside | Only muxing carries fonts → correct signs/karaoke. |
| Per-episode in merge loop | Separate loop; manual | Immediate per-episode availability, simplest. |
| Don't delete partner hardlinks | Delete always; delete-outside-torrent | Seed-until-orphan policy; reaper owns deletion. |
| mp4 → remux to mkv + embed | Keep .srt sidecar; mov_text | User wants a uniform, sidecar-free mkv library. |
| Free-space pre-check, skip+log | Pin temp branch; just-run | No ENOSPC crashes; self-throttles on the near-full pool. |
| `.dubtitles.done` stamp (size+mtime) + ffprobe backstop | ffprobe-only; ledger | Stat-only fast skip that survives sidecar deletion; handles replaced files. |
| Eng audio default; keep eng+nld+und+orig; drop other dubs | JP default; keep all; eng-only | Dub-subtitle intent; small files; keep the original for choice. |
| Keep signs/songs subs (mul/name) | Strict language drop | Don't lose weird JoJo signs/songs tracks. |

## Constraints

- mux runs as **root** (mergerfs atomic replace + ownership); needs **mkvtoolnix** + ffprobe.
- Idempotent + restart-safe; never crash a sweep on one bad file.
- Must not regress A1/C1/B1 (mux is the final stage, after the `.ass` exists).

## Open questions (risks)

- [ ] mergerfs EXDEV behavior on the atomic finalize — validated on the server during D1 verify.
- [ ] `MIN_FREE_GB` value tuned to typical episode size at rollout.
