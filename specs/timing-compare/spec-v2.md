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

- [ ] A standalone script `tools/timing_compare.py` runs as
      `python tools/timing_compare.py <show_dir> [<show_dir> ...]`, GPU-free, importing nothing that
      requires a GPU (no `faster_whisper` import at module scope).
- [ ] For each episode it locates the sibling `<stem>.dubtitles.conf.json`; episodes without one
      are reported as `no-conf` and skipped (not an error).
- [ ] `conf.json` hardening: `FileNotFoundError`, `PermissionError`, and `json.JSONDecodeError` log a
      `bad-conf` status and skip the episode. Rows with `start >= end` or negative `start` are
      dropped silently; processing continues.
- [ ] Subtitle extraction uses the existing `common.eng_sub_streams` + `common.extract_sub` helpers
      and writes extracted `.ass` files to a `tempfile.TemporaryDirectory()` that is cleaned up
      after each episode.
- [ ] **Dialogue-track selection:** among the English sub streams it picks the dialogue-dense track
      using `common.dialogue_intervals` with per-stream scoring. Episodes whose only English sub
      track is signs/songs-only, or that have no English sub track, are reported as `no-reference`
      and skipped (counted, not errored). Track ties are broken by lower stream index.
- [ ] **Offset:** it estimates a per-episode global offset (median of nearest-onset deltas between
      cards and cues). Only card/cue pairs with `abs(card.start - cue.start) ≤ 5.0` s contribute;
      unpaired cards count toward `kept_in_gap`. Tie-break: earlier cue wins; on further tie, lower
      stream-index cue wins. Offset correction is applied before overlap classification.
- [ ] **Classification:** each kept card is classified `on-cue` or `in-gap` by slack-aware overlap,
      where a card `C = [c_s, c_e]` overlaps a cue `K = [k_s, k_e]` with tolerance `t` iff
      `max(0, min(c_e, k_e + t) - max(c_s, k_s - t)) > 0`. Default `t = 0.30 s`; `--tolerance` is
      clamped to `[0.0, 2.0]`.
- [ ] **Report** (written as JSON + printed human summary) contains, per episode and aggregated
      per show and overall:
  - `schema_version: 1` and the resolved `config` (`tolerance_s`, `min_cues`, `min_plain_share`).
  - `global_offset_s` (null when `matched_pairs_count < 10`), `matched_pairs_count`,
    `offset_low_confidence: bool`, residual `median_s` and `iqr_s` for matched pairs
    (null when `matched_pairs_count < 2`).
  - coverage: `pct_cards_on_cue`, `pct_cues_covered`.
  - `kept_in_gap`: count plus buckets aligned to `hallucination.py` (named after the
    strict-inequality functions they mirror) — `by_nsp` (`clean_le_0.5`,
    `flag_gt_0.5_le_0.95`, `drop_gt_0.95`), `by_lp` (`clean_ge_-0.6`,
    `flag_lt_-0.6_ge_-2.0`, `drop_lt_-2.0`), and `by_flag` (the existing `flag` field values).
  - `flag_validation`: of `maybe_silence`-flagged kept cards, counts in-gap vs on-cue.
  - `reference_track`: stream index, codec, cue count, density score (0–1).
  - counts of `no-conf`, `no-reference`, `bad-conf`, `analyzed` episodes.
  - headline `applicability_ratio = analyzed / (analyzed + no-reference)` in the printed summary
    (per-show and overall), e.g. `Show: <name>  analyzed=N  no-ref=M  applicability=0.XX  on-cue=XX%  in-gap=XX`.
- [ ] Pure functions (offset estimation, overlap/on-cue classification, dialogue-density scoring,
      band bucketing, nearest-onset pairing) have unit tests with synthetic card/cue fixtures — no
      media, no network, no GPU.
- [ ] `ruff check tools/timing_compare.py tests/test_timing_compare.py` clean; all existing tests
      still pass.

## Data contracts

- **Inputs:**
  - One or more show directory paths (walked for video files, same extension set as
    `common.VIDEO_EXTS`).
  - Per episode: the video (for subtitle extraction) + its existing `<stem>.dubtitles.conf.json`
    (rows carry `start, end, avg_logprob, no_speech_prob`, optional `flag`, optional `word_probs`).
  - Optional flags: `--tolerance` (s, default 0.30, clamped to `[0.0, 2.0]`), `--out` (report path,
    default `timing-compare.report.json` in cwd), `--lang` (sub language filter, default the
    pipeline's `SUB_LANGS` env var parsed as comma-separated and lowercased, matching
    `repair.py`/`dub_signs_merge.py`).
- **Outputs:**
  - `timing-compare.report.json` — the structured report (schema per Acceptance criteria).
  - A printed human-readable summary (per-show + aggregate headline numbers, including
    `applicability_ratio`), e.g.
    `Show: <name>  analyzed=N  no-ref=M  applicability=0.XX  on-cue=XX%  in-gap=XX`.
  - No mutation of any media, sidecar, or pipeline state. Read-only except writing the report file.
- **Reused interfaces:**
  - `common.eng_sub_streams`, `common.extract_sub`, `common.VIDEO_EXTS`, and the new
    `common.dialogue_intervals(video, stream_indices=None)` (hoisted from `repair.py`).
  - `common.dialogue_event_count(video: str, stream_index: int) -> int`
  - `common.dialogue_density_score(events: list[pysubs2.SSAEvent]) -> tuple[int, float]`
    (returns `(dialogue_cue_count, plain_event_share)`).

## Authorization

- **Who can execute:** any user with read access to the show directory and write access to the
  `--out` path. This is a read-only analytical tool — no auth boundary, no chown, no privilege
  escalation.
- **Behavior without permission:** if the show directory is unreadable or `--out` is not writable,
  the tool exits non-zero with one log line per failed path. No partial state is left behind — the
  only write is the final report file, written atomically.

## Edge cases and failure modes

| Case                                                   | Expected behavior                                                                                                       |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| Episode has no `.dubtitles.conf.json`                  | Report `no-conf`, skip (not an error)                                                                                   |
| `conf.json` is mid-write or malformed JSON             | Catch `json.JSONDecodeError`, report `bad-conf`, skip, count                                                            |
| `conf.json` row has `start >= end` or negative `start` | Drop the row, continue with the rest                                                                                    |
| No embedded English sub track (e.g. dub-only mp4)      | Report `no-reference`, skip                                                                                             |
| Only sub track is signs/songs-only                     | Dialogue-density scorer rejects it → `no-reference`, skip                                                               |
| Multiple English sub tracks                            | Pick the highest dialogue-density one; record which was used; ties → lower index                                        |
| All episodes in a show are `no-reference`              | Per-show aggregate coverage/offset fields are `null`; status counts are still reported                                  |
| `conf.json` present but empty (no kept cards)          | Report `analyzed` with 0 cards; coverage undefined → report `null`, not a crash                                         |
| Large constant offset (dub lead/lag or framerate)      | Captured as `global_offset_s`; residual spread still measured after correction — the offset is a finding, not a failure |
| Sub cues include non-dialogue events mixed in          | Dialogue selection filters to plain dialogue events before building cue intervals                                       |
| Card overlaps two adjacent cues                        | `on-cue` if it overlaps any; matched-pair onset-delta uses the nearest cue                                              |

## Components / changes

| Layer             | File                           | Change                                                                                                                            |
| ----------------- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| Analytics (new)   | `tools/timing_compare.py`      | CLI, report builder, human summary.                                                                                               |
| Tests (new)       | `tests/test_timing_compare.py` | Unit tests for pure functions.                                                                                                    |
| Common (refactor) | `common.py`                    | Hoist `dialogue_intervals(video, stream_indices=None)` from `repair.py`; add `dialogue_event_count` and `dialogue_density_score`. |
| Repair (refactor) | `repair.py`                    | Replace local `dialogue_intervals` with `from common import dialogue_intervals` (no behavior change).                             |

## Decisions taken

| Decision                                                                                | Rejected alternative                              | Why                                                                                                                                                                                      |
| --------------------------------------------------------------------------------------- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Offset-corrected overlap (estimate + report a per-episode global offset, then classify) | Raw overlap with no offset correction             | A constant dub-vs-sub offset would smear alignment and coverage into noise. The offset itself is an actionable finding.                                                                  |
| Single global offset per episode                                                        | DTW / drift-aware alignment                       | Phase-0 wants a cheap, interpretable first signal. Drift handling is a later refinement if residual spread shows real drift.                                                             |
| conf.json-only (kept cards)                                                             | Also raw-dump every episode for false-drops       | GPU-free, seconds over a couple shows, uses existing sidecars. The leaked-hallucination direction is the primary silence failure users see; false-drops need raw dumps and are deferred. |
| Auto-detect the dialogue reference track by density/style                               | Require the user to name the track                | Track layout varies per release. Auto-detect effectively measures the `applicability_ratio`.                                                                                             |
| Standalone script in `tools/`                                                           | A mode inside `generate.py` / the container loops | Analysis is offline and non-invasive; keeping it out of the live pipeline matches the `dump_whisper.py`/`bakeoff.py` tooling pattern.                                                    |
| Reuse `common.dialogue_intervals` / style classification                                | Reimplement extraction in `timing_compare.py`     | Same plumbing `repair.py` already uses; single source of truth, no drift.                                                                                                                |
| Extract `.ass` files to a temp directory                                                | Extract next to source media                      | Preserves the read-only, non-invasive constraint on the live media tree.                                                                                                                 |

## Constraints

- **GPU-free, non-invasive:** no Whisper, no changes to `generate.py`/`repair.py`/`mux.py` behavior;
  the only write is the report file.
- **Read-only on media:** extracted subtitle files are written to a `tempfile.TemporaryDirectory()`
  and removed after each episode; no `.ass` sidecar is left next to source media.
- **Reuse, don't duplicate** the subtitle-extraction and dialogue-vs-sign logic (extract a shared
  predicate to `common.py` only if the existing one isn't cleanly importable).
- **Deterministic + testable:** pure functions for offset, classification, density, bucketing;
  the only untested seam is ffmpeg subtitle extraction (exercised manually on the real shows).
- **Runs on the server** (OMV .209) or wherever the media + conf.json sidecars live; the laptop does
  not have the videos. RTK note: run tests via `rtk proxy python -m pytest`.

## Open questions (risks / tuning knobs)

- [ ] **Initial values (binding for Phase 0).** - Dialogue-track threshold: `min_cues=50`, `min_plain_share=0.70` (env-overridable by
      `TIMING_COMPARE_MIN_CUES` and `TIMING_COMPARE_MIN_PLAIN_SHARE`). - Offset pairing radius: `5.0 s` (env-overridable by `TIMING_COMPARE_PAIR_RADIUS_S`). - `--tolerance` default `0.30 s`, range `[0.0, 2.0]`. - Phase-1 trigger: at least **3 shows** with `pct_cards_on_cue ≥ 0.80` and
      `no-reference` rate ≤ 30% before any gating spec is opened.
- [ ] **Runtime knobs (not decisions).** Show selection for the first run is the user's call — the
      tool accepts any show dirs. Names are decoded from `os.walk`; the tool does not case-fold.
- [ ] **Translation-style handling.** If a release uses a fansub-`Translation`-style track as its
      only reference, the first-run diagnostics (`reference_track.density_score`) will reveal it.
      Threshold tuning may follow.

## Report schema (reference)

```jsonc
{
  "schema_version": 1,
  "config": {"tolerance_s": 0.30, "min_cues": 50, "min_plain_share": 0.70},
  "shows": {
    "Show A": {
      "episodes": {
        "ShowA - 01.mkv": {
          "status": "analyzed",
          "global_offset_s": 0.42,                // null if matched_pairs_count < 10
          "offset_low_confidence": false,
          "matched_pairs_count": 137,
          "residual_iqr_s": 0.18,                 // null if matched_pairs_count < 2
          "pct_cards_on_cue": 0.91,
          "pct_cues_covered": 0.78,
          "kept_in_gap": {
            "total": 14,
            "by_nsp": {"clean_le_0.5": 1, "flag_gt_0.5_le_0.95": 9, "drop_gt_0.95": 4},
            "by_lp":  {"clean_ge_-0.6": 0, "flag_lt_-0.6_ge_-2.0": 11, "drop_lt_-2.0": 3},
            "by_flag": {"maybe_silence": 9, "low_conf": 4, "none": 1}  // none = no flag field
          },
          "flag_validation": {"maybe_silence_in_gap": 9, "maybe_silence_on_cue": 3},
          "reference_track": {"stream_index": 2, "codec": "ass", "cue_count": 412,
                              "density_score": 0.83}
        }
      },
      "aggregate": { "pct_cards_on_cue": 0.88, "kept_in_gap": 145,
                      "applicability_ratio": 0.88 }
    }
  },
  "aggregate": { "no_conf": 4, "no_reference": 11, "bad_conf": 0, "analyzed": 73,
                 "applicability_ratio": 0.87 }
}
```

When a show has zero analyzed episodes, its per-show aggregate coverage/offset fields are
`null` while the status-count fields remain numeric.
