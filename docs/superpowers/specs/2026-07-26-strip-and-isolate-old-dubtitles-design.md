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

---

## Spec Review

**Reviewed by:** `minimax/minimax-m3` (mimo-v2.5-pro)
**Date:** 2026-07-26
**Scope:** Full technical review against the current codebase (`common.py`, `mux.py`, `generate.py`, `mine_glossary.py`, `dub_signs_merge.py`, `repair.py`, `tools/timing_compare.py`, `recreate_srt.py`) and existing test suites (`test_mux.py`, `test_generate.py`, `test_common.py`, `test_timing_compare.py`, `test_dub_signs_merge.py`).

### Verdict

Sound design, well-scoped. The single-chokepoint approach (`eng_sub_streams` title exclusion) is the right architecture, the stamp-based versioning with grandfather constant is a clean rollout, and the robustness analysis is thorough. **Six issues found — one high, three medium, two low.** All are spec-level clarifications; no architectural changes needed.

---

### Issues

#### 1 · HIGH — `generate.py` `SKIP_IF_MUXED` guard change is underspecified

**Cite:** Affected files table row: `generate.py | Version-aware SKIP_IF_MUXED guard`; §3 bullet: "skip a file with a `Dubtitles` track only when its stamp is also current-version."

**Problem:** The current code in `generate.py` `process()` is:
```python
if os.environ.get("SKIP_IF_MUXED", "1") == "1" and has_dubtitles_track(video):
    return "already-muxed"
```
The spec says to make this "version-aware" but does not specify the concrete change. An implementer needs to know:
- Does the guard become `has_dubtitles_track(video) and stamp_valid(read_stamp(stem + STAMP_SUFFIX), video)` — keeping the ffprobe check but gating it on a current-version stamp?
- Or is the entire `SKIP_IF_MUXED` check removed from `process()`, relying solely on the stamp check at the top of the function (`if stamp_valid(read_stamp(stem + STAMP_SUFFIX), video): return "already-muxed"`)?
- Does the `SKIP_IF_MUXED` env var stay (as a disable switch) or go away?

**Suggested spec addition:** Add a concrete diff to §3 or the Affected files section:
```python
# BEFORE (process()):
if os.environ.get("SKIP_IF_MUXED", "1") == "1" and has_dubtitles_track(video):
    return "already-muxed"

# AFTER: remove this block entirely. The stamp check at the top of process()
# (now version-aware via stamp_valid) is the sole muxed-skip guard.
# SKIP_IF_MUXED env var is retired.
```
This also makes `generate.has_dubtitles_track()` dead code (no remaining callers in `generate.py`); the spec should say whether to remove it or keep it (harmless but unused).

---

#### 2 · MEDIUM — `generate.has_dubtitles_track()` vs `mux.has_dubtitles_track()` ambiguity

**Cite:** §2: "`has_dubtitles_track()` stays — `verify()` still uses it to confirm the new track landed."

**Problem:** There are **two** `has_dubtitles_track()` functions:
- `mux.has_dubtitles_track(info)` — takes an `mkvmerge -J` dict; called by `verify()` and (currently) `process()`. Stays.
- `generate.has_dubtitles_track(video)` — runs its own ffprobe; called only by the `SKIP_IF_MUXED` guard in `generate.process()`. If that guard is removed (issue #1), this function has zero callers.

The §2 statement correctly describes `mux.has_dubtitles_track` but could be misread as covering both. **Suggested fix:** Add "(`mux.has_dubtitles_track` — `generate.has_dubtitles_track` becomes unused if its `SKIP_IF_MUXED` guard is removed, see §3)."

---

#### 3 · MEDIUM — `eng_sub_streams` ffprobe change not spelled out

**Cite:** §1: "Fetch `stream_tags=title` alongside language, and exclude any stream whose `title == TRACK_NAME`."

**Problem:** The current ffprobe call in `eng_sub_streams` queries `stream_tags=language` only:
```python
"-show_entries", "stream=index,codec_name:stream_tags=language"
```
To filter by title, the query must also fetch `stream_tags=title` (or `stream_tags=language,title`), and the filter loop must check `(st.get("tags") or {}).get("title", "") != TRACK_NAME`. The spec should include this concrete diff to prevent an implementer from adding the filter without updating the ffprobe query (which would silently pass all streams through).

**Suggested spec addition in §1:**
```python
# BEFORE:
"-show_entries", "stream=index,codec_name:stream_tags=language"

# AFTER:
"-show_entries", "stream=index,codec_name:stream_tags=language,title"

# AND in the filter loop, add:
if ((st.get("tags") or {}).get("title", "") or "").strip() == TRACK_NAME:
    continue
```

---

#### 4 · MEDIUM — Existing `test_generate.py::test_ffprobe_muxed_backstop_in_process` will break

**Cite:** Testing section lists new tests but does not mention updating existing ones.

**Problem:** `test_generate.py` has `test_ffprobe_muxed_backstop_in_process` which monkeypatches `has_dubtitles_track` to return `True` and asserts `process()` returns `"already-muxed"`. If the `SKIP_IF_MUXED` guard is removed (per issue #1), this test fails. The spec should list it under "tests to update" alongside the new tests.

**Suggested addition to Testing section:**
- `test_generate`: update `test_ffprobe_muxed_backstop_in_process` — remove or retarget (the backstop no longer exists; the stamp-only guard is tested by the new version-aware stamp tests).

---

#### 5 · LOW — `mine_glossary.py` ffprobe fix should specify the query change

**Cite:** §1: "`mine_glossary.py` — has its own ffprobe subtitle selector; add the same `title != TRACK_NAME` exclusion."

**Problem:** `mine_glossary.eng_sub_text()` queries `stream_tags=language` but not `title`. Same as issue #3: the ffprobe query itself needs updating, not just a filter added after. The spec should note this.

---

#### 6 · LOW — Enumeration audit omits `recreate_srt.py`

**Cite:** Robustness section: "Every subtitle-enumeration call site was checked: `eng_sub_streams()` (repair, timing-compare, signs-merge) and `mine_glossary.py`'s selector are the only two that read subs as context."

**Problem:** `recreate_srt.py` is listed in `common.py`'s docstring as a pipeline stage. It reads `conf.json` (not embedded subs), so it is correctly excluded from the audit — but the audit does not explicitly mention it. A reader verifying completeness has to read `recreate_srt.py` to confirm. **Suggested fix:** Add a one-liner: "`recreate_srt.py` reads `conf.json` only (not embedded subs) — no exclusion needed."

---

### Strengths (things the spec gets right)

1. **Single chokepoint.** Putting the title exclusion in `eng_sub_streams()` means `repair`, `timing_compare`, and `dub_signs_merge` all inherit it with zero code changes. Future consumers that call `eng_sub_streams()` are automatically isolated.
2. **`mine_glossary.py` correctly identified as a separate path.** It has its own ffprobe selector and would have been missed by a chokepoint-only approach.
3. **No-fallback policy.** "Reference-free when zero eligible tracks" is the correct default — falling back to the old dubtitle would defeat the entire purpose.
4. **Strip-at-mux idempotency.** Drop-then-add in one mkvmerge pass means re-runs are safe and crash-recovery is self-healing.
5. **Grandfather constant.** `PIPELINE_VERSION == GRANDFATHER_VERSION == 1` at introduction means zero files regenerate on deploy — clean rollout.
6. **Robustness analysis.** The race-condition, zero-track, replace-good-with-bad, enumeration-audit, and lost-stamp sections are thorough and well-reasoned.

---

## Second Spec Review

**Reviewed by:** `gemini-2.5-pro` (complementary second pass)
**Date:** 2026-07-26
**Scope:** Same spec; focuses on angles the first review did not cover.

### Verdict

Complementary to the first review. One **HIGH** issue: the rollout assumption that every muxed file already has a `.dubtitles.done` stamp is optimistic and could cause unintended mass regeneration. Two **MEDIUM** issues about crash-orphaned sidecars and track ordering. Two **LOW** clarifications.

---

### Issues

#### 1 · HIGH — Rollout is only a no-op if every muxed file already has a stamp

**Cite:** §3: "**Rollout is a no-op.** At introduction `PIPELINE_VERSION == GRANDFATHER_VERSION == 1`, so every existing stamp — including the freshly regenerated One Pace episodes — grandfathers to v1 and reads as current."

**Problem:** The spec correctly describes the behavior for files *with* a `.dubtitles.done` stamp, but it is silent on files that were muxed **before stamps existed** or whose stamp was lost. Under the old code, `generate.py` and `mux.py` both had a `has_dubtitles_track()` backstop that skipped such files. After this change, that backstop is removed. A file with a `Dubtitles` track but **no stamp** will now read as stale and be fully regenerated + re-muxed.

If the library has a meaningful number of files without stamps, this is not a no-op rollout — it is a mass regeneration. The spec either needs to:
- Accept this as deliberate and document it as a one-time migration cost, or
- Preserve a grandfathering backstop for the first deploy: e.g. "if no stamp exists but a `Dubtitles` track is present, write a v1 stamp and skip" (a single migration pass in `mux.py`).

**Suggested fix:** Add a "Migration / rollout edge" subsection that explicitly addresses no-stamp files. For example:
> "Files muxed before the `.dubtitles.done` stamp existed (no sidecar stamp, but a `Dubtitles` track present) are treated as stale under the new stamp-only guard. Operators must run a one-time `write_stamp` migration for such files, or accept that the first sweep will regenerate them."

---

#### 2 · MEDIUM — Crash between stamp write and sidecar cleanup can orphan sidecars

**Cite:** Robustness section: "`mux` writes the stamp **before** removing the sidecar."

**Problem:** The robustness analysis covers the window *before* the stamp is written (sidecar still present, so `generate` skips). It does not cover the window *after* the stamp is written but *before* the sidecar is deleted. If `mux` crashes or is killed at that point:
- `generate` sees the sidecar and skips (`SKIP_IF_SRT`).
- `mux` sees the valid stamp and skips.
- The `.srt`/`.ass` sidecar is never cleaned up and remains orphaned on disk.

This is not incorrect output, but it is a disk/operational leak. The spec could note this and suggest a periodic cleanup sweep or that the next version-bump will re-process the file and delete the sidecar.

---

#### 3 · MEDIUM — New Dubtitles track is appended at the end, which may shift default-track order

**Cite:** §2: "The new dubtitle is added fresh from the sidecar as before." `mux.build_cmd` appends the new track after existing tracks.

**Problem:** `mkvmerge` places the new track at the end of the track list. If the old `Dubtitles` track was not the last subtitle track (e.g. a signs/songs track came after it), removing the old one and appending the new one changes the relative order of subtitle tracks. Most players pick the default track by the `default-track-flag`, but some clients or scripts that enumerate tracks by index may be surprised. The spec should document that the new track is always appended last, and that ordering of non-Dubtitles tracks is otherwise preserved.

---

#### 4 · LOW — Duplicate `Dubtitles` tracks are self-healing; worth calling out

**Cite:** §2: "Result: exactly one `Dubtitles` track, always the newest."

**Problem:** The spec assumes one old `Dubtitles` track, but a buggy past run could have produced multiple tracks with the same name. The design naturally handles this because `keep_sub` drops *any* track named `Dubtitles` and `build_cmd` appends exactly one new one. This is a nice self-healing property; explicitly mentioning it makes the spec more robust.

---

#### 5 · LOW — Fate of `strip_op.py` should be explicit

**Cite:** Non-goals: "The existing bulk `strip_op.py` remains usable for one-off manual strips but is no longer part of the regeneration workflow."

**Problem:** Leaving a now-unnecessary script in the repo without a deprecation note risks future developers using it by habit. The spec should clarify whether `strip_op.py` is kept indefinitely, marked deprecated, or scheduled for removal. If the workflow no longer needs stripping, the cleaner choice is to deprecate and remove it after this change proves stable.

---

### Strengths (additional angles)

1. **Track-name as self-marker is robust.** Unlike relying on language tags or codec, the `Dubtitles` track name is set only by our own pipeline, so false positives are negligible.
2. **No-reference fallback is correctly scoped.** `repair.py`, `timing_compare.py`, and `dub_signs_merge.py` all degrade gracefully when `eng_sub_streams()` returns nothing, so excluding the old dubtitle cannot crash the pipeline.
3. **Stamp-only idempotency is the right long-term model.** Removing the ffprobe backstop removes a class of false-positive skips and makes the pipeline easier to reason about once migration is complete.

---

## Third Spec Review

**Reviewed by:** `kimi-k2.7-code` (Freebuff / Buffy)
**Date:** 2026-07-26
**Scope:** Same spec; focused on implementation-level hazards and cross-file consistency not fully covered by prior reviews.

### Verdict

Agrees with both prior reviews. The design is sound, and the first two reviews have already identified the main spec-level gaps. **Three additional low/medium issues and one procedural note.**

---

### Issues

#### 1 · MEDIUM — `mux.keep_sub()` ordering must drop `Dubtitles` before signs/songs logic

**Cite:** §2: "`mux.keep_sub()` — return `False` for any subtitle track named `TRACK_NAME`"

**Problem:** The current `keep_sub()` first checks language/mul/signs-songs, then returns. If a track is named `Dubtitles` but also happens to have a signs/songs name or `mul` language, the current logic might keep it. The exclusion by track name should be the *first* check, overriding everything else.

**Suggested fix:** Make the first check in `keep_sub()`:
```python
if (track.get("properties") or {}).get("track_name") == TRACK_NAME:
    return False
```

---

#### 2 · LOW — Title-tag whitespace/None handling

**Cite:** §1 and §5: title comparison against `TRACK_NAME`.

**Problem:** ffprobe may return `title` with leading/trailing whitespace, or the `tags` dict may be missing/None. The filter comparisons should normalize: `((tags.get("title") or "").strip() == TRACK_NAME)`.

**Suggested fix:** Add a small helper in `common.py`:
```python
def _track_title(st):
    return ((st.get("tags") or {}).get("title", "") or "").strip()
```
Use it in both `eng_sub_streams()` and `mine_glossary.py`.

---

#### 3 · LOW — Future `PIPELINE_VERSION` bump semantics

**Cite:** §3: "A file with a valid current-version stamp is done; a file whose stamp predates the current pipeline version is stale."

**Problem:** The spec states the version check but does not explicitly document what happens when `PIPELINE_VERSION` is bumped from 1 to 2. Existing v1 stamps will fail `stamp_valid` (1 < 2), triggering regeneration. This is the intended behavior, but the "Rollout is a no-op" section only covers the initial deploy; it should also state that a future bump is the deliberate operator-controlled regeneration trigger.

**Suggested fix:** Add a sentence: "Bumping `PIPELINE_VERSION` to 2 is the operator's signal for a global in-place regeneration; all v1 stamps become stale and will be re-processed."

---

### Procedural note

A plan file already exists at `DubTitlerr/docs/superpowers/specs/2026-07-26-strip-and-isolate-old-dubtitles-design-plan.md`. The revised spec and a new tasks file should be created alongside it; their file paths should be appended to this document.

---

### Strengths (agreement with prior reviews)

1. **Single chokepoint is correct.** `eng_sub_streams()` is the right place for the exclusion.
2. **Migration path is necessary.** The second review correctly identifies that files without stamps must be addressed.
3. **Stamp-only idempotency is the right long-term model.** Removing the ffprobe backstop removes a class of false-positive skips and makes the pipeline easier to reason about once migration is complete.

---

## Revised Spec — Strip-at-mux + context isolation for old dubtitle tracks

**Date:** 2026-07-26
**Status:** Design reviewed; ready for implementation

This section incorporates all review findings from the three spec reviews above.

### 1. Problem

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

### 2. Approach

One shared marker (the track name `Dubtitles`) and one shared version field drive everything.

#### 2.1 Context isolation — exclude the `Dubtitles` track everywhere it could be read as context

The generated track is always named `Dubtitles` (set by `mux.build_cmd`), so the track name
is a reliable, self-authored marker.

- **`common.eng_sub_streams()`** — the single chokepoint for `repair`, `timing_compare`, and
  `dub_signs_merge`. Fetch `stream_tags=title` alongside language, and exclude any stream
  whose normalized title == `TRACK_NAME`. This one change isolates all three consumers.
  - Concrete change to the ffprobe query:
    ```python
    # BEFORE:
    "-show_entries", "stream=index,codec_name:stream_tags=language"
    # AFTER:
    "-show_entries", "stream=index,codec_name:stream_tags=language,title"
    ```
  - Concrete change to the filter loop:
    ```python
    if _track_title(st) == TRACK_NAME:
        continue
    ```
  - Add a helper in `common.py`:
    ```python
    def _track_title(st: dict) -> str:
        return ((st.get("tags") or {}).get("title", "") or "").strip()
    ```
- **`mine_glossary.py`** — has its own ffprobe subtitle selector; add the same
  `title != TRACK_NAME` exclusion (including the ffprobe `stream_tags=title` query update)
  so mined glossary terms never come from our old output.
- **`recreate_srt.py`** — reads `conf.json` only (not embedded subs), so no exclusion is needed.
  This is explicitly noted for completeness.

**No fallback to the dubtitle.** If exclusion leaves zero eligible reference tracks (an
episode whose only English sub is our old dubtitle), the pipeline proceeds **reference-free**:
`repair` already handles an empty interval set (omits the reference from the prompt);
`timing_compare` already has a no-eligible-track path (reports no reference). We never fall
back to reading the dubtitle for context — that is the whole point.

#### 2.2 Strip-at-mux — replace, don't duplicate; retire the separate pre-strip pass

- **`common.TRACK_NAME`** — move the canonical constant `"Dubtitles"` from `mux.py` to
  `common.py` so every consumer uses the same marker.
- **`mux.keep_sub()`** — return `False` for any subtitle track named `TRACK_NAME`, regardless
  of its language or signs/songs name. The name check must be the **first** guard in the
  function:
  ```python
  if (track.get("properties") or {}).get("track_name") == TRACK_NAME:
      return False
  ```
  The old `Dubtitles` track is therefore always placed in `dropped` and excluded from the
  remux. The new dubtitle is added fresh from the sidecar as before. Result: exactly one
  `Dubtitles` track, always the newest. If a buggy past run produced multiple `Dubtitles`
  tracks, all are dropped and replaced by one new track (self-healing).
- **`mux.process()` skip-guard** — becomes **stamp-only**: skip only when
  `stamp_valid(read_stamp(stamp), orig)` is true. Remove the `or has_dubtitles_track(...)`
  clause. Because `build_cmd` now drops-then-re-adds the dubtitle, re-muxing is idempotent,
  which also makes the old ffprobe crash-recovery backstop unnecessary (a crash between embed
  and stamp is self-healing on the next run). `mux.has_dubtitles_track()` stays — `verify()`
  still uses it to confirm the new track landed.

#### 2.3 Regeneration trigger — pipeline version stamp

A file with a valid current-version stamp is done; a file whose stamp predates the current
pipeline version is stale and must be regenerated **in place**.

- **`common.PIPELINE_VERSION = 1`** — the current output version. Bump it (to 2, …) when a
  verified-better pipeline warrants a global in-place regeneration.
- **`common.GRANDFATHER_VERSION = 1`** — fixed constant; the version assigned to any stamp
  written before this feature (no `version` field). Never changes.
- **`common.write_stamp()`** — record `"version": PIPELINE_VERSION` in `.dubtitles.done`.
- **`common.stamp_valid()`** — in addition to the existing size+mtime+`muxed` checks, require
  `stamp.get("version", GRANDFATHER_VERSION) >= PIPELINE_VERSION`.
- **`generate.py` `SKIP_IF_MUXED` guard** — remove the block entirely. The version-aware
  `stamp_valid` check at the top of `process()` is the sole muxed-skip guard. Retire the
  `SKIP_IF_MUXED` environment variable.
  ```python
  # BEFORE:
  if os.environ.get("SKIP_IF_MUXED", "1") == "1" and has_dubtitles_track(video):
      return "already-muxed"

  # AFTER: removed. The stamp check at the top of process() handles skipping.
  ```
- **`generate.has_dubtitles_track()`** — becomes unused once the `SKIP_IF_MUXED` guard is
  removed. Delete it. `mux.has_dubtitles_track(info)` remains, called only by `mux.verify()`.
- **Future version bumps:** Bumping `PIPELINE_VERSION` to 2 is the operator's signal for a
  global in-place regeneration; all v1 stamps become stale and will be re-processed.

#### 2.4 Migration / rollout edge

**Rollout is a no-op for stamped files.** At introduction
`PIPELINE_VERSION == GRANDFATHER_VERSION == 1`, so every existing stamp — including the
freshly regenerated One Pace episodes — grandfathers to v1 and reads as current. Nothing
regenerates on deploy. Control stays with the operator: a deliberate `PIPELINE_VERSION` bump
is the only thing that marks prior-version output stale.

**No-stamp files must be migrated.** Files muxed before the `.dubtitles.done` stamp existed
(no sidecar stamp, but a `Dubtitles` track present) are treated as stale under the new
stamp-only guard. Run a one-time migration that writes v1 stamps for such files before
deploy, or accept that the first sweep will regenerate them.

### 3. Affected files

| File | Change |
|------|--------|
| `common.py` | Add `TRACK_NAME`, `PIPELINE_VERSION`, `GRANDFATHER_VERSION`; `_track_title()` helper; `eng_sub_streams` title exclusion; `write_stamp`/`stamp_valid` version field |
| `mux.py` | Import `TRACK_NAME` from common (drop local); `keep_sub` excludes named track first; `process` stamp-only skip |
| `generate.py` | Remove `SKIP_IF_MUXED` guard and `generate.has_dubtitles_track()`; rely on version-aware `stamp_valid` |
| `mine_glossary.py` | Add `stream_tags=title` query and `title != TRACK_NAME` exclusion |
| `tools/timing_compare.py` | No code change — inherits the `eng_sub_streams` fix; verify no other path reads the dubtitle |
| `dub_signs_merge.py` | No code change — inherits the `eng_sub_streams` fix; verify |
| `recreate_srt.py` | No change needed — reads `conf.json` only |

### 4. Testing

All stream-copy; no re-encode; existing suites extended:

- `test_common`: `eng_sub_streams` drops a `title=="Dubtitles"` stream; `write_stamp` records
  version; `stamp_valid` false when stamp version < `PIPELINE_VERSION`, true when
  grandfathered-equal, true when missing-and-equal.
- `test_mux`: `keep_sub`/`build_cmd` drops an old `Dubtitles` track (and it lands in
  `dropped`); `process` skips only on a current-version stamp, re-muxes a stale-version file.
- `test_generate`: remove or retarget `test_ffprobe_muxed_backstop_in_process`; add
  version-aware skip tests — a `Dubtitles` track + current stamp skips; + stale
  stamp does not.
- `test_timing_compare`, `test_dub_signs_merge`: reference selection excludes the dubtitle
  track.
- New `mine_glossary` coverage: excludes the dubtitle track from mining.

### 5. Robustness & failure analysis

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
`title != TRACK_NAME` exclusion. `recreate_srt.py` reads `conf.json` only (not embedded subs)
— no exclusion needed. `generate.has_dubtitles_track()` enumerates subs *to detect*
the dubtitle (removed with the `SKIP_IF_MUXED` guard); `generate`'s other selector reads
**audio**; `timing_compare._sub_codec_map()` only labels the already-chosen track's codec.
The exclusion lives in the lowest-level enumeration routine, so a future consumer that calls
`eng_sub_streams()` inherits it automatically.

**Lost sidecar stamp is safe.** Removing the ffprobe "already-muxed" backstop means a file
with a current dubtitle track but a *missing* stamp reads as stale and is regenerated. That is
extra work, not incorrect: re-mux is idempotent (drop old + add fresh). Embedding the version
in the track itself is a possible future hardening (see non-goals).

**Crash between stamp write and sidecar cleanup can orphan sidecars.** `mux` writes the
stamp **before** removing the sidecar. If `mux` crashes after the stamp write but before the
sidecar delete, `generate` sees the sidecar and skips, and `mux` sees the valid stamp and
skips, so the `.srt`/`.ass` sidecar is never cleaned up.

**CORRECTED (implementation review):** the original claim that "the next version-bump
re-process will remove it" was wrong, and the error was not cosmetic. On a version bump such
a file has a *stale* stamp **and** a leftover sidecar; the sidecar-existence skips in
`generate.process()` are not version-aware, so `generate` returns `already-ass` forever while
`mux` re-embeds that **old** subtitle and stamps it **current** — a bump that silently no-ops
on exactly the files it was meant to fix, leaving v1 content labelled v2. Fixed by
`common.stale_version_stamp()`: when the stamp matches the file exactly but records an older
version, the file *is* our superseded output, so its sidecars are that same run's leftovers.
`generate.process()` discards them (`discard_stale_sidecars`) and `needs_work()` returns True
for that state so `process()` is actually reached.

**Leftover vs fresh is decided by mtime, not by the stale stamp alone.** An earlier draft of
this fix argued the discard was safe because "generate is itself blocked by the stale
sidecar, so nothing fresh can exist beside it" — that reasoning is circular and wrong:
unblocking generate is the whole point of the fix, and the stamp does not advance until
`mux` succeeds, so a freshly transcribed sidecar sits beside a still-stale stamp for at
least one `MERGE_INTERVAL` (and indefinitely if the mux keeps failing on `skip-no-room` /
`verify-*`). Discarding *that* would re-run Whisper on every `gen_loop.sh` resume pass and,
because the loop's stall detector counts `.srt` files, the deletions would read as "no
progress" and abandon the show mid-regeneration. The implemented predicate is therefore:
**a sidecar is a leftover only if it predates the stamp** (the run that stamped wrote its
sidecars first and deleted them just after), and anything newer is this run's own work and
is kept. A poison-marked (`.dubtitles.fail`) episode is exempt from the discard entirely —
it is never transcribed, so removing its sidecars would be pure destruction. Residual
(accepted): if `mux`/`merge_pass` is mid-assemble on a genuine leftover at the moment
generate deletes it, the open fd survives and that old content can still be embedded and
stamped current — one episode, only in the already-rare crashed-mux state, and a further
bump clears it.

**Track ordering may shift.** `mkvmerge` places the new track at the end of the track list.
If the old `Dubtitles` track was not the last subtitle track, removing the old one and
appending the new one changes the relative order of subtitle tracks. Most players pick the
default track by `default-track-flag`, but clients/scripts that enumerate tracks by index
may be surprised. Document this behavior in operator notes.

### 6. Non-goals

- No re-encode; no change to what the dub content is, only which tracks are read/kept.
- No automatic version bumping — the operator bumps `PIPELINE_VERSION` deliberately.
- ~~The existing bulk `strip_op.py` remains usable for one-off manual strips~~ —
  **CORRECTED:** `strip_op.py` does not exist in this repo and never has
  (`git log --all -- strip_op.py` is empty). The pre-strip pass was run ad hoc, not as a
  committed script, so there is nothing to deprecate; strip-at-mux replaces it outright.
- Embedding the pipeline version *inside* the MKV (e.g. in the track name) instead of the
  sidecar stamp — possible future hardening against a lost stamp; out of scope here.

---

## Implementation Artifacts

The following documents support this spec:

- **Plan:** `DubTitlerr/docs/superpowers/specs/2026-07-26-strip-and-isolate-old-dubtitles-design-plan.md`
- **Tasks:** `DubTitlerr/docs/superpowers/specs/2026-07-26-strip-and-isolate-old-dubtitles-tasks.md`


---

## Implementation Amendments

Found during implementation + code review; each is now covered by a test.

1. **`-s` is a whitelist; mkvmerge's default is copy-every-subtitle-track.** The original
   `build_cmd` omitted `-s` when the keep list was empty, which would have copied back the
   very track `dropped` reported as removed — so a file whose only subtitle is our old
   dubtitle (every mp4-origin episode, and the "only English sub is ours" case §5 promised
   would end with exactly one track) would have ended up with **two** `Dubtitles` tracks.
   `verify()` is presence-only, so it would have passed and been stamped. An empty keep list
   now emits an explicit `-S`.
2. **One shared "is this ours?" predicate.** `common.is_our_track(name)` covers both shapes
   (ffprobe `tags.title` via `stream_title()`, mkvmerge `properties.track_name`), so the
   exclude-from-context test and the drop-at-mux test cannot drift. A drift is silent:
   exclude-but-keep yields a duplicate, keep-but-drop loses the fansub. This also replaced
   the cross-module import of a private `_track_title`.
3. **Version-aware sidecar staleness** — see the corrected orphaned-sidecar paragraph
   above, including the mtime leftover-vs-fresh predicate and the `.dubtitles.fail` exemption
   (a second review pass caught that the first cut of this fix deleted freshly transcribed
   sidecars, which would have broken crash-resume during exactly the version-bump rollout
   the feature exists to enable).
4. **A failed stamp write is now its own status** (`stamp-write-failed`, sidecars kept).
   With the ffprobe backstop retired the stamp is the only "done" record, so a silent
   failure meant re-running the whole multi-GB remux every sweep, forever.
5. **`stamp_valid()` tolerates a non-int `version`** (`"1"` coerces; garbage reads as
   invalid rather than raising). The check runs outside `mux.process()`'s `try`, so one
   corrupt sidecar would otherwise abort a whole sweep.
6. **`properties: None` hardening** across `mux.py`'s mkvmerge-track accessors, and a
   present-but-null `language` tag no longer raises in `mine_glossary.eng_sub_text()`.
