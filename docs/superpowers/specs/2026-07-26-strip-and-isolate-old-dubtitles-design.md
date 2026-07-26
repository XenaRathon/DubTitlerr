# Strip-at-mux + context isolation for old dubtitle tracks

**Date:** 2026-07-26
**Status:** Design (approved shape; pending spec review)

## Problem

The pipeline embeds its generated dub subtitle as a subtitle track named `Dubtitles`.
When we regenerate an episode with an improved pipeline version, two things go wrong under
the current code:

1. **Duplication / no-op.** `mux.py` refuses to touch a file that already carries a
   `Dubtitles` track (`process()` returns `already-muxed`), and `generate.py` skips it too
   (`SKIP_IF_MUXED` → `has_dubtitles_track`). That is *why* a heavy separate pre-strip pass
   (`mkvmerge` remux to drop the track) was needed before every regeneration. If we simply
   drop the pre-strip, regeneration silently no-ops on every already-dubbed file.

2. **Context contamination.** The embedded `Dubtitles` track is `codec=ass, language=eng`.
   Every stage that reads the *fansub* as context selects English ASS/SSA tracks **by
   language + codec only** — it never checks the track name — so it will happily pick up our
   own old dubtitle as if it were the human fansub:
   - `repair.py` → `common.dialogue_intervals()` uses the fansub as a **semantic reference**
     to fix garbled Whisper lines → would repair the new line against last version's errors.
   - `tools/timing_compare.py` → `select_reference_track()` uses fansub cue **timing** as the
     reference → would align to last version's timing.
   - `dub_signs_merge.py` reads the fansub to lift **signs/songs**.
   - `mine_glossary.py` mines **glossary terms** from subs (its own ffprobe selector) → would
     re-mine and reinforce last version's spelling errors.

We want, going forward: **strip the old dubtitle track as part of muxing the new one in**
(no separate pass), and **never let the old dubtitle influence the new output — only the
genuine subtitle track is used for context.**

## Approach

One shared marker (the track name `Dubtitles`) and one shared version field drive everything.

### 1. Context isolation — exclude the `Dubtitles` track everywhere it could be read as context

The generated track is always named `Dubtitles` (set by `mux.build_cmd`), so the track name
is a reliable, self-authored marker.

- **`common.eng_sub_streams()`** — the single chokepoint for `repair`, `timing_compare`, and
  `dub_signs_merge`. Fetch `stream_tags=title` alongside language, and exclude any stream
  whose `title == TRACK_NAME`. This one change isolates all three consumers.
- **`mine_glossary.py`** — has its own ffprobe subtitle selector; add the same
  `title != TRACK_NAME` exclusion so mined glossary terms never come from our old output.

**No fallback to the dubtitle.** If exclusion leaves zero eligible reference tracks (an
episode whose only English sub is our old dubtitle), the pipeline proceeds **reference-free**:
`repair` already handles an empty interval set (omits the reference from the prompt);
`timing_compare` already has a no-eligible-track path (reports no reference). We never fall
back to reading the dubtitle for context — that is the whole point.

### 2. Strip-at-mux — replace, don't duplicate; retire the separate pre-strip pass

- **`mux.keep_sub()`** — return `False` for any subtitle track named `TRACK_NAME`, so an old
  dubtitle track is always placed in `dropped` and excluded from the remux. The new dubtitle
  is added fresh from the sidecar as before. Result: exactly one `Dubtitles` track, always
  the newest.
- **`mux.process()` skip-guard** — becomes **stamp-only**: skip only when
  `stamp_valid(read_stamp(stamp), orig)` is true. Remove the `or has_dubtitles_track(...)`
  clause. Because `build_cmd` now drops-then-re-adds the dubtitle, re-muxing is idempotent,
  which also makes the old ffprobe crash-recovery backstop unnecessary (a crash between embed
  and stamp is self-healing on the next run). `has_dubtitles_track()` stays — `verify()` still
  uses it to confirm the new track landed.

### 3. Regeneration trigger — pipeline version stamp

A file with a valid current-version stamp is done; a file whose stamp predates the current
pipeline version is stale and must be regenerated **in place**.

- **`common.PIPELINE_VERSION = 1`** — the current output version. Bump it (to 2, …) when a
  verified-better pipeline warrants a global in-place regeneration.
- **`common.GRANDFATHER_VERSION = 1`** — fixed constant; the version assigned to any stamp
  written before this feature (no `version` field). Never changes.
- **`common.write_stamp()`** — record `"version": PIPELINE_VERSION` in `.dubtitles.done`.
- **`common.stamp_valid()`** — in addition to the existing size+mtime+`muxed` checks, require
  `stamp.get("version", GRANDFATHER_VERSION) >= PIPELINE_VERSION`.
- **`generate.py` `SKIP_IF_MUXED` guard** — make version-aware: skip a file with a
  `Dubtitles` track only when its stamp is also current-version
  (`stamp_valid(read_stamp(stem + STAMP_SUFFIX), video)`). A present track with a stale or
  missing-but-grandfathered-below-current stamp is transcribed again.

**Rollout is a no-op.** At introduction `PIPELINE_VERSION == GRANDFATHER_VERSION == 1`, so
every existing stamp — including the freshly regenerated One Pace episodes — grandfathers to
v1 and reads as current. Nothing regenerates on deploy. Control stays with the operator: a
deliberate `PIPELINE_VERSION` bump is the only thing that marks prior-version output stale.

## Affected files

| File | Change |
|------|--------|
| `common.py` | Add `TRACK_NAME`, `PIPELINE_VERSION`, `GRANDFATHER_VERSION`; `eng_sub_streams` title exclusion; `write_stamp`/`stamp_valid` version field |
| `mux.py` | Import `TRACK_NAME` from common (drop local); `keep_sub` excludes named track; `process` stamp-only skip |
| `generate.py` | Version-aware `SKIP_IF_MUXED` guard |
| `mine_glossary.py` | `title != TRACK_NAME` exclusion in its ffprobe selector |
| `tools/timing_compare.py` | No code change — inherits the `eng_sub_streams` fix; verify no other path reads the dubtitle |
| `dub_signs_merge.py` | No code change — inherits the `eng_sub_streams` fix; verify |

## Testing

All stream-copy; no re-encode; existing suites extended:

- `test_common`: `eng_sub_streams` drops a `title=="Dubtitles"` stream; `write_stamp` records
  version; `stamp_valid` false when stamp version < `PIPELINE_VERSION`, true when
  grandfathered-equal, true when missing-and-equal.
- `test_mux`: `keep_sub`/`build_cmd` drops an old `Dubtitles` track (and it lands in
  `dropped`); `process` skips only on a current-version stamp, re-muxes a stale-version file.
- `test_generate`: version-aware skip — a `Dubtitles` track + current stamp skips; + stale
  stamp does not.
- `test_timing_compare`, `test_dub_signs_merge`: reference selection excludes the dubtitle
  track.
- New `mine_glossary` coverage: excludes the dubtitle track from mining.

## Robustness & failure analysis

*(Reviewed against a multi-model panel; these are the answers to the hazards it raised.)*

**No new write race between the generate and mux sweeps.** They already run continuously in
one container today. `generate` only writes **sidecars** (`.srt`/`.conf`); it never writes the
MKV (it reads the audio stream). `mux` reads sidecars and rewrites the MKV. The two are
serialized by sidecar existence: `mux` no-ops (`no-sub`) until a sidecar exists, and `generate`
skips a file once its `.srt`/`.ass` sidecar exists (`SKIP_IF_SRT`). This change adds no new
shared-write path, so it introduces no new race. The one transient window — after `mux`
finalizes the new MKV but before it writes the stamp — is covered because `mux` writes the
stamp **before** removing the sidecar, and the still-present sidecar makes `generate` skip the
file during that window.

**A file cannot lose its dubtitle or end up with zero subtitle tracks.** `mux` only acts when
a sidecar exists, and `build_cmd` *always* appends that sidecar as the new track — the old
track is dropped **in the same pass that adds the new one**, never independently. `verify()`
then requires `has_dubtitles_track(out)` **and** video+audio present **before** the atomic
replace; on any failure the temp is deleted and the **original is left untouched**. So the
worst case is "old dubtitle retained," never "no dubtitle." A file whose only English sub was
the old dubtitle ends with exactly the new one (≥1 sub track).

**Replace-good-with-bad tradeoff (accepted).** In-place regen means a failed *new* generation
could, in principle, replace a good old dubtitle. This is bounded: a transcription failure
writes `.fail`/`.crash` and produces **no sidecar**, so `mux` never runs and the old track is
kept; and the version bump is a **deliberate operator action taken only after verifying test
output**. Acceptable given those guards; `mux` `verify()` remains presence-only by design (no
quality gate).

**Enumeration audit — no other path reads subtitles as context.** Every subtitle-enumeration
call site was checked: `eng_sub_streams()` (repair, timing-compare, signs-merge) and
`mine_glossary.py`'s selector are the only two that read subs *as context* — both get the
`title != TRACK_NAME` exclusion. `generate.has_dubtitles_track()` enumerates subs *to detect*
the dubtitle (correct as-is); `generate`'s other selector reads **audio**; `timing_compare.
_sub_codec_map()` only labels the already-chosen track's codec. The exclusion lives in the
lowest-level enumeration routine, so a future consumer that calls `eng_sub_streams()` inherits
it automatically.

**Lost sidecar stamp is safe.** Removing the ffprobe "already-muxed" backstop means a file
with a current dubtitle track but a *missing* stamp reads as stale and is regenerated. That is
extra work, not incorrect: re-mux is idempotent (drop old + add fresh). Embedding the version
in the track itself is a possible future hardening (see non-goals).

## Non-goals

- No re-encode; no change to what the dub content is, only which tracks are read/kept.
- No automatic version bumping — the operator bumps `PIPELINE_VERSION` deliberately.
- The existing bulk `strip_op.py` remains usable for one-off manual strips but is no longer
  part of the regeneration workflow.
- Embedding the pipeline version *inside* the MKV (e.g. in the track name) instead of the
  sidecar stamp — possible future hardening against a lost stamp; out of scope here.

---
*Built with help of Claude (Anthropic).*
