# Spec — Timing Compare: dubtitle-vs-subtitle timing analysis (Phase 0)

> A GPU-free measurement tool that compares Whisper-generated dubtitle timing against the
> embedded human-timed subtitle track, to (a) validate how well dub and sub timing align and
> (b) quantify how many silence/music hallucinations leak into the output — before wiring the
> subtitle track in as a gating signal. This is **analysis only**; the gating feature is Phase 1
> (out of scope here).

## Context and problem

DubTitlerr's biggest remaining accuracy leak is Whisper inventing text over silence/music.
`hallucination.drop_reason` only drops a card as `"music"` when **both** `no_speech_prob > 0.95`
**and** `avg_logprob < -2.0` — deliberately strict, because a looser gate culls real
music-masked dialogue (e.g. a "Buster Call" line under loud action sits at `nsp ~0.86`). The
consequence: genuine hallucinations that don't clear that bar leak into the final dubtitles.

Anime English dubs are recorded to lip-sync the original animation, so **dub speech onsets land
at essentially the same timestamps as the original dialogue** — which the embedded, human-timed
subtitle track already marks precisely. That subtitle track is an **independent** answer to "was
anyone actually speaking here?" that Whisper does not have: a Whisper card sitting in a gap with
no dialogue cue is very likely a hallucination; a card overlapping a cue is very likely real.

Before wiring that signal into gating (and before the pending V2 rebuild/deploy), we need to
**measure**: how well does dub timing actually align with sub timing, is any misalignment a fixable
constant offset vs genuine noise, how much of the library even carries a usable dialogue sub track,
and how big is the leaked-hallucination opportunity. This tool produces that evidence.

## Goals

- Quantify dub-vs-sub timing alignment (global offset + residual spread) per episode/show/aggregate.
- Quantify the silence-detection opportunity: of the cards Whisper **kept**, how many sit in a
  subtitle **gap** (candidate leaked hallucinations), cross-tabbed with their confidence signals.
- Measure library applicability: how many episodes carry a usable **dialogue** sub track vs
  signs/songs-only or none.
- Stay GPU-free and non-invasive: read existing `conf.json` sidecars, reuse the pipeline's existing
  subtitle-extraction plumbing, change nothing in the live pipeline.

## Non-goals (explicit — out of scope)

- **The gating feature itself (Phase 1).** Using the subtitle signal to actually drop/flag/snap
  cards is a separate spec, informed by this tool's results.
- **"False drops" (real dialogue wrongly dropped as music).** `conf.json` stores only KEPT cards, so
  dropped cards can't be seen here. Measuring that direction needs the raw pre-drop cards
  (a `dump_whisper.py` GPU pass) and is deferred to a later mode.
- **Timing refinement / snapping** card boundaries to cue boundaries.
- **DTW / drift-aware sequence alignment.** A single global offset is the Phase-0 model; drift
  handling is a possible later refinement.
- **Re-transcription.** No GPU, no Whisper invocation.

## Acceptance criteria (verifiable)

- [ ] A standalone script `timing_compare.py` exists in the repo root, runnable as
      `python timing_compare.py <show_dir> [<show_dir> ...]`, GPU-free, importing nothing that
      requires a GPU (no `faster_whisper` import at module scope).
- [ ] For each episode it locates the sibling `<stem>.dubtitles.conf.json`; episodes without one
      are reported as `no-conf` and skipped (not an error).
- [ ] It extracts the embedded English subtitle stream(s) via the existing
      `common.eng_sub_streams` + `extract_sub` helpers (no new extraction path).
- [ ] **Dialogue-track selection:** among the English sub streams it picks the dialogue-dense track
      (by cue density and share of plain, non-positioned dialogue events, reusing the merge stage's
      style classification). Episodes whose only English sub track is signs/songs-only, or that have
      no English sub track, are reported as `no-reference` and skipped (counted, not errored).
- [ ] **Offset:** it estimates a per-episode global offset (median of nearest-onset deltas between
      cards and cues) and reports it. Offset correction is applied before overlap classification.
- [ ] **Classification:** each kept card is classified `on-cue` or `in-gap` by overlap (after offset
      correction) within a configurable tolerance (default ±0.30 s / any-overlap).
- [ ] **Report** (written as JSON + printed human summary) contains, per episode and aggregated
      per show and overall:
  - `global_offset_s`, and the residual onset-delta median + IQR for matched pairs
  - coverage: `pct_cards_on_cue`, `pct_cues_covered`
  - `kept_in_gap`: count + a breakdown by `no_speech_prob` band and `avg_logprob` band and existing
    `flag` value (validates whether in-gap cards look like hallucinations)
  - `flag_validation`: of `maybe_silence`-flagged kept cards, counts in-gap (confirmed) vs on-cue
    (false alarm)
  - `reference_track`: which stream index/codec was used, its cue count, and its density score
  - counts of `no-conf`, `no-reference`, `analyzed` episodes
- [ ] Pure functions (offset estimation, overlap/on-cue classification, dialogue-density scoring,
      band bucketing) have unit tests with synthetic card/cue fixtures — no media, no network, no GPU.
- [ ] `ruff check timing_compare.py tests/test_timing_compare.py` clean; all existing tests still pass.

## Data contracts

- **Inputs:**
  - One or more show directory paths (walked for video files, same extension set as
    `common.VIDEO_EXTS`).
  - Per episode: the video (for subtitle extraction) + its existing `<stem>.dubtitles.conf.json`
    (rows carry `start, end, avg_logprob, no_speech_prob`, optional `flag`, optional `word_probs`).
  - Optional flags: `--tolerance` (s, default 0.30), `--out` (report path, default
    `timing-compare.report.json` in cwd), `--lang` (sub language filter, default the pipeline's
    `SUB_LANGS`).
- **Outputs:**
  - `timing-compare.report.json` — the structured report (schema per Acceptance criteria).
  - A printed human-readable summary (per-show + aggregate headline numbers).
  - No mutation of any media, sidecar, or pipeline state. Read-only except writing the report file.
- **Reused interfaces:** `common.eng_sub_streams`, `common.extract_sub`, `common.VIDEO_EXTS`;
  the merge stage's event-style classification (whatever `dub_signs_merge` exposes for
  dialogue-vs-sign) — reuse, do not duplicate; if it isn't importable cleanly, extract the minimal
  shared predicate into `common.py`.

## Edge cases and failure modes

| Case | Expected behavior |
|---|---|
| Episode has no `.dubtitles.conf.json` | Report `no-conf`, skip (not an error) |
| No embedded English sub track (e.g. dub-only mp4) | Report `no-reference`, skip |
| Only sub track is signs/songs-only | Dialogue-density scorer rejects it → `no-reference`, skip |
| Multiple English sub tracks | Pick the highest dialogue-density one; record which was used |
| `conf.json` present but empty (no kept cards) | Report `analyzed` with 0 cards; coverage undefined → report `null`, not a crash |
| Large constant offset (dub lead/lag or framerate) | Captured as `global_offset_s`; residual spread still measured after correction — the offset is a finding, not a failure |
| Sub cues include non-dialogue events mixed in | Dialogue selection filters to plain dialogue events before building cue intervals |
| Card overlaps two adjacent cues | `on-cue` if it overlaps any; matched-pair onset-delta uses the nearest cue |

## Decisions taken

| Decision | Rejected alternative | Why |
|---|---|---|
| Offset-corrected overlap (estimate + report a per-episode global offset, then classify) | Raw overlap with no offset correction | A constant dub-vs-sub offset (common; also framerate/version) would smear alignment and coverage into noise. The offset is itself an actionable finding. |
| Single global offset per episode | DTW / drift-aware alignment | Phase-0 wants a cheap, interpretable first signal. DTW is a later refinement if residual spread shows real drift. |
| conf.json-only (kept cards) | Also raw-dump every episode for false-drops | GPU-free, seconds over a couple shows, uses existing sidecars. The leaked-hallucination direction (kept cards in gaps) is the primary silence failure users see; false-drops need raw dumps and are deferred. |
| Auto-detect the dialogue reference track by density/style | Require the user to name the track | Track layout varies per release; auto-detect also *measures* library applicability (the `no-reference` count) as a side effect. |
| Standalone script, runs on the server against show dirs | A mode inside generate.py / the container loops | Analysis is offline and non-invasive; keeping it out of the live pipeline matches the `dump_whisper.py`/`bakeoff.py` tooling pattern. |
| Reuse `eng_sub_streams`/`extract_sub`/style classification | Reimplement extraction | Same plumbing `repair.dialogue_intervals` already uses; single source of truth, no drift. |

## Constraints

- **GPU-free, non-invasive:** no Whisper, no changes to `generate.py`/`repair.py`/`mux.py` behavior;
  the only write is the report file.
- **Reuse, don't duplicate** the subtitle-extraction and dialogue-vs-sign logic (extract a shared
  predicate to `common.py` only if the existing one isn't cleanly importable).
- **Deterministic + testable:** pure functions for offset, classification, density, bucketing;
  the only untested seam is ffmpeg subtitle extraction (exercised manually on the real shows).
- **Runs on the server** (OMV .209) or wherever the media + conf.json sidecars live; the laptop does
  not have the videos. RTK note: run tests via `rtk proxy python -m pytest`.

## Open questions (to confirm at spec review / runtime)

- [ ] **Which 2–3 shows** for the first run? Needs shows that are dual-audio with a full English
      **dialogue** sub track (not signs/songs-only). Candidate suggestions welcome; the tool takes
      show dirs as args so this is a runtime choice, but confirming availability up front avoids an
      all-`no-reference` run.
- [ ] **Tolerance / on-cue definition** — start at ±0.30 s / any-overlap; revisit if coverage looks
      implausibly low/high on the first run.
- [ ] **Dialogue-density threshold** — how dense/plain a track must be to count as a dialogue
      reference (vs signs-only). Start heuristic (e.g. ≥ N cues and ≥ X% plain bottom-position
      events), tune on the first run's `reference_track` diagnostics.
