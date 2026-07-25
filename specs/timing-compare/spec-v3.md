# Spec — Timing Compare: dubtitle-vs-subtitle timing analysis (Phase 0)

> **Supersedes `spec.md` (v1) and `spec-v2.md` (v2).** v2 folded in the minimax-m3 review
> (`REVIEW.md`) — schema, edge-cases, band buckets, offset sign, tempdir extraction, small-N
> null-handling. **v3 folds in the multi-model panel consult (2026-07-24)**, which found
> methodology gaps v2 still had: a constant offset is wrong for PAL/framerate drift; "in a
> subtitle gap" alone can't tell a hallucination from a real dub-only line without an
> independent audio check; the greedy-median estimator is fragile; and "kept-in-gap" is a
> survivorship floor, not the true hallucination rate. Changes from v2 are marked **[v3]**.
>
> A GPU-free measurement tool that compares Whisper-generated dubtitle timing against the
> embedded human-timed subtitle track, to (a) validate how well dub and sub timing align,
> (b) quantify how many silence/music hallucinations leak into the output, and **[v3]** (c)
> distinguish those from real dub-only lines the subs omit — before wiring the subtitle track
> in as a gating signal. This is **analysis only**; the gating feature is Phase 1 (out of scope).

## Context and problem

DubTitlerr's biggest remaining accuracy leak is Whisper inventing text over silence/music.
`hallucination.drop_reason` only drops a card as `"music"` when **both** `no_speech_prob > 0.95`
**and** `avg_logprob < -2.0` — deliberately strict, because a looser gate culls real
music-masked dialogue (e.g. a "Buster Call" line under loud action sits at `nsp ~0.86`). The
consequence: genuine hallucinations that don't clear that bar leak into the final dubtitles.

Anime English dubs are recorded to lip-sync the original animation, so **dub speech onsets land
at ~the same timestamps as the original dialogue** — which the embedded, human-timed subtitle
track already marks. That subtitle track is a partial answer to "was anyone speaking here?".

**[v3] But it is only a *partial* answer, and the panel consult made that precise.** A kept
Whisper card sitting in a subtitle **gap** has two explanations the subtitle track alone cannot
separate: (1) a hallucination over silence/music — what we want to catch — or (2) a **real dub
line the subs simply omit** (ADR/background chatter, narration, dub-only added dialogue). Gating
naively on "in-gap" would silently drop case (2). So Phase 0 must add an **independent acoustic
check** of the dub audio at each in-gap card to split those two cases — that split *is* the
measurement that decides whether a Phase-1 gate is safe.

Before wiring any of this into gating (and before the pending V2 rebuild/deploy), we measure:
timing alignment (including **[v3]** drift, not just a constant offset), library applicability,
how much leaks past B1, and — the key new number — **how often an in-gap card is actually real
dub speech the subs missed** (the false-drop risk a gate would incur).

## Goals

- Quantify dub-vs-sub timing alignment: **[v3]** a linear model `offset(t) = a + b·t` (intercept
  **and** drift slope) + residual spread, per episode/show/aggregate.
- Quantify the leaked-past-B1 hallucination opportunity: of the cards Whisper **kept**, how many
  sit in a subtitle **gap**, cross-tabbed with their confidence signals.
- **[v3]** Split every in-gap card by an **independent VAD** of the dub audio into
  `in_gap_silent` (no voiced speech → confident hallucination) vs `in_gap_speech` (voiced speech
  present → likely a real dub-only line the subs omit). The `in_gap_speech` rate is the
  **false-in-gap** proxy — the real speech a naive sub-gap gate would wrongly drop.
- Measure library applicability: episodes with a usable **dialogue** sub track vs signs-only/none.
- Stay GPU-free and non-invasive: read existing `conf.json` sidecars, reuse the pipeline's
  subtitle-extraction plumbing, add only a lightweight CPU VAD, change nothing in the live pipeline.

## Non-goals (explicit — out of scope)

- **The gating feature itself (Phase 1).** Using the subtitle+VAD signal to actually drop/flag/snap
  cards is a separate spec, informed by this tool's results.
- **"False drops" (real dialogue wrongly dropped as music).** `conf.json` stores only KEPT cards, so
  dropped cards can't be seen here; that direction needs a raw pre-drop GPU dump (deferred).
  **[v3] Note the survivorship consequence explicitly:** because B1 already removed the most obvious
  music hallucinations, `kept_in_gap` is a **lower bound / floor** on the true hallucination rate,
  not the rate itself. The report and the Phase-1 trigger must be read as "leaked *past B1*."
- **Timing refinement / snapping** card boundaries to cue boundaries.
- **[v3] Full DTW / piecewise-nonlinear alignment.** The linear (offset+drift) model is the Phase-0
  upgrade over a constant offset. If post-fit residual IQR stays large, the report flags the episode
  (`look_for_drift`) for a possible piecewise/DTW Phase-1 refinement; Phase 0 does not implement it.
- **Re-transcription.** No GPU, no Whisper invocation.

## Acceptance criteria (verifiable)

- [ ] A standalone script `tools/timing_compare.py` runs as
      `python tools/timing_compare.py <show_dir> [<show_dir> ...]`, GPU-free, importing nothing that
      requires a GPU (no `faster_whisper` import at module scope).
- [ ] For each episode it locates the sibling `<stem>.dubtitles.conf.json`; missing → `no-conf`,
      skip (not an error).
- [ ] `conf.json` hardening: `FileNotFoundError`, `PermissionError`, `json.JSONDecodeError` → `bad-conf`
      status, skip. Rows with `start >= end` or negative `start` are dropped silently; continue.
- [ ] Subtitle extraction uses `common.eng_sub_streams` + `common.extract_sub`, writing `.ass` files
      to a `tempfile.TemporaryDirectory()` cleaned up after each episode (no sidecar left on media).
- [ ] **Dialogue-track selection:** among the English sub streams, pick the dialogue-dense track via
      `common.dialogue_intervals` + `common.dialogue_density_score` (threshold `min_cues=50`,
      `min_plain_share=0.70`, env-overridable). Signs-only / no-track → `no-reference`, skip, count.
      Track ties → lower stream index.
- [ ] **[v3] Timing model:** fit `offset(t) = a + b·t` over paired `(card.start, cue.start)` points,
      **robustly** (RANSAC: seed with nearest-onset pairs within `±5.0 s`, fit a line, keep inliers
      within `±0.30 s` of the line, refit by least-squares on inliers). Report `offset_a_s` (intercept
      at t=0), `drift_b` (slope, s per s), `matched_pairs_count`, `inlier_count`, and the
      **post-fit** residual `median_s` / `iqr_s`. `offset_a_s`/`drift_b` are `null` when
      `inlier_count < 10`; residual stats `null` when `inlier_count < 2`. Report `look_for_drift: true`
      when post-fit residual `iqr_s > 1.0` **or** `abs(drift_b) > 0.002` (≈ >0.12 s over a 60 s span).
- [ ] **Classification:** each kept card is placed on the cue timeline via the fitted model
      (`aligned_start = card.start - (offset_a_s + drift_b * card.start)`, same for end), then
      classified `on-cue` or `in-gap` by slack-aware overlap: card `[a_s,a_e]` overlaps cue `[k_s,k_e]`
      with tolerance `t` iff `max(0, min(a_e, k_e + t) - max(a_s, k_s - t)) > 0`. Default `t = 0.30 s`,
      `--tolerance` clamped to `[0.0, 2.0]`.
- [ ] **[v3] VAD probe of in-gap cards:** for every kept card classified `in-gap`, extract the DUB
      audio window at the card's **original** (un-aligned) `[start, end]` — Whisper's timebase, since
      the audio is what Whisper heard — as 16 kHz mono via ffmpeg into the temp dir, and run a
      lightweight CPU VAD (`webrtcvad`, aggressiveness configurable) over it. Classify the card:
      - `in_gap_silent` — VAD reports no voiced speech in the window (confident hallucination).
      - `in_gap_speech` — VAD reports voiced speech (likely a real dub-only line the subs omit).
      On VAD/extraction failure (no audio stream, ffmpeg error) → `in_gap_vad_error`, counted
      separately, never silently merged into either verdict. VAD backend selectable via `--vad`
      (`webrtcvad` default; `ffmpeg-silencedetect` dep-free fallback, cruder — energy-based, cannot
      separate speech from loud music). The known limitation (speech under loud music may read as
      silent/ambiguous) is documented, not hidden — the `by_nsp`/`by_lp` cross-tab is the second view.
- [ ] **Report** (JSON + printed human summary), per episode / per show / overall:
  - `schema_version: 2` and resolved `config` (`tolerance_s`, `min_cues`, `min_plain_share`,
    `pair_radius_s`, `vad_backend`, `vad_aggressiveness`).
  - **[v3]** timing model: `offset_a_s`, `drift_b`, `matched_pairs_count`, `inlier_count`,
    residual `median_s`/`iqr_s`, `look_for_drift`.
  - coverage: `pct_cards_on_cue`, `pct_cues_covered`.
  - `kept_in_gap`: `total`, **[v3]** `in_gap_silent`, `in_gap_speech`, `in_gap_vad_error`, plus buckets
    aligned to `hallucination.py` — `by_nsp` (`clean_le_0.5`/`flag_gt_0.5_le_0.95`/`drop_gt_0.95`),
    `by_lp` (`clean_ge_-0.6`/`flag_lt_-0.6_ge_-2.0`/`drop_lt_-2.0`), `by_flag`.
  - **[v3]** `false_in_gap_rate = in_gap_speech / max(1, total kept cards)` — the real-speech-in-gap
    proxy; the headline number for Phase-1 gate safety.
  - `flag_validation`: of `maybe_silence`-flagged kept cards, counts in-gap vs on-cue.
  - `reference_track`: stream index, codec, cue count, density score.
  - status counts: `no-conf`, `no-reference`, `bad-conf`, `analyzed`.
  - printed headline per show + overall: `applicability_ratio = analyzed / (analyzed + no-reference)`,
    `pct_cards_on_cue`, `kept_in_gap.total`, **[v3]** `in_gap_speech` and `false_in_gap_rate`.
- [ ] Pure functions (RANSAC/line fit, overlap classification, dialogue-density scoring, band
      bucketing, nearest-onset pairing, VAD-window frame decision) have unit tests with synthetic
      fixtures — no media, no network, no GPU. The ffmpeg-extract + VAD-on-real-audio seam is the only
      integration-tested-manually part.
- [ ] `ruff check tools/timing_compare.py tests/test_timing_compare.py` clean; all existing tests pass.

## Data contracts

- **Inputs:** show dir(s) (walked for `common.VIDEO_EXTS`, pruning `EXTRA_DIRS`, non-symlink-following
  like `repair.py`); per episode the video + `<stem>.dubtitles.conf.json`. Flags: `--tolerance`
  (0.30, `[0.0,2.0]`), `--out` (`timing-compare.report.json`), `--lang` (default `SUB_LANGS` env,
  comma-split + lowercased), **[v3]** `--vad` (`webrtcvad`|`ffmpeg-silencedetect`, default `webrtcvad`),
  `--vad-aggressiveness` (0–3, default 2), `--summary-only`.
- **Outputs:** `timing-compare.report.json` (schema below) + printed summary. No mutation of media,
  sidecars, or pipeline state; the only write is the report file (never via `OUTPUT_ROOT`).
- **Reused / new interfaces:** `common.eng_sub_streams`, `common.extract_sub`, `common.VIDEO_EXTS`;
  new `common.dialogue_intervals(video, stream_indices=None)` (hoisted from `repair.py`),
  `common.dialogue_event_count`, `common.dialogue_density_score`. **[v3]** a small VAD helper module
  (in `tools/`, not `common.py`, since it's analysis-only): `vad_probe(wav_path, aggressiveness) -> bool`.
- **[v3] New dependency:** `webrtcvad` (CPU, ~C-extension) added to `pyproject.toml` optional/analysis
  extras and to `Dockerfile.builder`. The `ffmpeg-silencedetect` backend is dep-free (ffmpeg already
  present) for environments where webrtcvad can't build.

## Authorization

- Read-only analytics tool; no auth boundary, no chown, no privilege escalation. Runs as the invoking
  user. Only write is `--out` (default cwd), written atomically. Extracted `.ass`/`.wav` live in a
  temp dir and are deleted. Unreadable show dir or unwritable `--out` → non-zero exit, one log line
  per failed path, no partial state.

## Edge cases and failure modes

| Case | Expected behavior |
|---|---|
| No `.dubtitles.conf.json` | `no-conf`, skip |
| `conf.json` mid-write / malformed | `json.JSONDecodeError` → `bad-conf`, skip, count |
| `conf.json` row `start >= end` or negative `start` | drop the row, continue |
| No English sub track (dub-only mp4) | `no-reference`, skip |
| Only sub track is signs/songs | density scorer rejects → `no-reference`, skip |
| Multiple English sub tracks | pick highest density; ties → lower index; record which |
| All episodes in a show are `no-reference` | per-show aggregate coverage/offset/false-in-gap = `null`; status counts still numeric |
| `conf.json` empty (0 kept cards) | `analyzed`, 0 cards; coverage `null`, not a crash |
| **[v3]** PAL/framerate drift | captured as `drift_b`; residual measured **after** the linear fit; `look_for_drift` set when residual still large or slope steep |
| **[v3]** Video has no decodable audio stream / ffmpeg fails on a window | that card → `in_gap_vad_error`, counted; never merged into silent/speech |
| **[v3]** `webrtcvad` unavailable/unbuildable | fall back to `--vad ffmpeg-silencedetect` with a warning; if that also fails, in-gap cards get `in_gap_vad_error` and `false_in_gap_rate` is reported `null` |
| Card overlaps two cues | `on-cue` if it overlaps any; pairing uses nearest cue-start |

## Components / changes

| Layer | File | Change |
|---|---|---|
| Analytics (new) | `tools/timing_compare.py` | CLI, RANSAC line fit, overlap + VAD classification, report builder, summary. |
| Analytics (new) | `tools/vad.py` **[v3]** | `vad_probe()` — webrtcvad + ffmpeg-silencedetect backends over a 16 kHz mono window. |
| Tests (new) | `tests/test_timing_compare.py` | Unit tests for the pure functions (incl. RANSAC + VAD frame-decision). |
| Common (refactor) | `common.py` | Hoist `dialogue_intervals(video, stream_indices=None)`; add `dialogue_event_count`, `dialogue_density_score`. |
| Repair (refactor) | `repair.py` | `from common import dialogue_intervals` (no behavior change). |
| Deps **[v3]** | `pyproject.toml`, `Dockerfile.builder` | add `webrtcvad`. |

## Decisions taken

| Decision | Rejected alternative | Why |
|---|---|---|
| **[v3]** Linear offset+drift fit (RANSAC) | Single constant global offset (v2) | PAL 25↔23.976 is ~4% *progressive* drift; a constant median fits the middle and mis-classifies episode ends. A line is O(N), GPU-free, and captures the dominant effect; RANSAC resists clustered-cue / mis-pair bias the greedy median suffers. |
| **[v3]** Independent VAD probe of in-gap cards | Subtitle gaps alone = "hallucination" | The sub track is not exhaustive; a gap card can be a real dub-only/ADR/narration line. Only an independent acoustic check separates "hallucination over silence" from "real speech the subs omit" — which is exactly the Phase-1 gate's safety question. |
| **[v3]** webrtcvad primary, ffmpeg-silencedetect fallback | RMS energy only | Energy can't tell voiced speech from loud music/SFX — and music is the confounder. webrtcvad targets voiced speech; ffmpeg fallback keeps the tool runnable with zero new deps. |
| **[v3]** Report `kept_in_gap` as a leaked-*past-B1* floor | Present it as the hallucination rate | Survivorship: B1 already removed the worst music hallucinations before `conf.json`. Framing prevents the go/no-go from reading an optimistic floor as the truth. |
| conf.json-only (kept cards) | Raw-dump every episode for false-drops | GPU-free, seconds over a couple shows. False-drops need raw dumps; deferred. |
| Auto-detect dialogue track | Name it manually | Layout varies; auto-detect also yields `applicability_ratio`. |
| Standalone `tools/` scripts | A mode inside the live pipeline | Offline, non-invasive; matches `bakeoff.py`/`dump_whisper.py`. |
| Reuse `common.dialogue_intervals` | Reimplement extraction | Single source of truth with `repair.py`; no drift. |
| Temp-dir extraction | Sidecar next to media | Preserves read-only on the media tree. |

## Constraints

- **GPU-free, non-invasive:** no Whisper; no behavior change to `generate.py`/`repair.py`/`mux.py`
  (the `dialogue_intervals` hoist is a pure re-export, pinned by existing repair tests). Only write is
  the report file. **[v3]** VAD is CPU-only.
- **Read-only on media:** extracted `.ass`/`.wav` go to a `TemporaryDirectory()` and are removed.
- **Sequencing (from the panel + minimax review):** land the `common.py`/`repair.py` refactor **first**
  (with a regression test pinning `stream_indices=None` to current `repair.py` output), then the tool —
  so an offline-analytics change can never break the live repair stage.
- **Deterministic + testable:** pure functions for fit/classification/density/bucketing/VAD-frame-decision.
- **Runs on the server** (media + conf.json live there). RTK: run tests via `rtk proxy python -m pytest`.

## Open questions (risks / tuning knobs)

- [ ] **[v3] Recalibrated Phase-1 trigger.** The v2 "≥80% on-cue / ≤30% no-reference" conflated
      *timing aligns* with *gate is safe*. Replace with a gate-safety-first rule: **open the Phase-1
      gating spec only if, across ≥3 shows with a usable dialogue track, `false_in_gap_rate` (real dub
      speech in gaps, per the VAD) is ≤ ~2% AND `in_gap_silent` is a material share of `kept_in_gap`
      (there's actually something to gain).** `pct_cards_on_cue` and `applicability_ratio` remain
      reported context, not the trigger. Exact `false_in_gap_rate` bound to be set after the first run
      calibrates what "safe" looks like on real data.
- [ ] **Which 2–3 shows** for the first run — needs dual-audio titles with a full English **dialogue**
      sub track. Runtime arg; confirm availability up front to avoid an all-`no-reference` run.
- [ ] **VAD aggressiveness + music-masked speech.** webrtcvad aggressiveness (0–3) and the
      speech-under-loud-music limitation want calibration against the `by_nsp` cross-tab on the first run.
- [ ] **`on-cue` validates timing, not wording.** A card can overlap a cue and still be a garbled
      transcription (right time, wrong words). Phase 0 does not check content correctness; note it so
      `pct_cards_on_cue` is never read as an accuracy score.

## Report schema (reference, schema_version 2)

```jsonc
{
  "schema_version": 2,
  "config": {"tolerance_s": 0.30, "min_cues": 50, "min_plain_share": 0.70,
             "pair_radius_s": 5.0, "vad_backend": "webrtcvad", "vad_aggressiveness": 2},
  "shows": {
    "Show A": {
      "episodes": {
        "ShowA - 01.mkv": {
          "status": "analyzed",
          "offset_a_s": 0.42, "drift_b": 0.0003,          // null if inlier_count < 10
          "matched_pairs_count": 152, "inlier_count": 141,
          "residual_median_s": 0.05, "residual_iqr_s": 0.14,  // null if inlier_count < 2
          "look_for_drift": false,
          "pct_cards_on_cue": 0.91, "pct_cues_covered": 0.78,
          "kept_in_gap": {
            "total": 14, "in_gap_silent": 9, "in_gap_speech": 4, "in_gap_vad_error": 1,
            "by_nsp": {"clean_le_0.5": 1, "flag_gt_0.5_le_0.95": 9, "drop_gt_0.95": 4},
            "by_lp":  {"clean_ge_-0.6": 0, "flag_lt_-0.6_ge_-2.0": 11, "drop_lt_-2.0": 3},
            "by_flag": {"maybe_silence": 9, "low_conf": 4, "none": 1}
          },
          "false_in_gap_rate": 0.012,                     // in_gap_speech / kept cards
          "flag_validation": {"maybe_silence_in_gap": 9, "maybe_silence_on_cue": 3},
          "reference_track": {"stream_index": 2, "codec": "ass", "cue_count": 412, "density_score": 0.83}
        }
      },
      "aggregate": {"pct_cards_on_cue": 0.88, "kept_in_gap": 145, "in_gap_speech": 21,
                    "false_in_gap_rate": 0.014, "applicability_ratio": 0.88}
    }
  },
  "aggregate": {"no_conf": 4, "no_reference": 11, "bad_conf": 0, "analyzed": 73,
                "applicability_ratio": 0.87, "false_in_gap_rate": 0.013}
}
```

When a show has zero analyzed episodes, its per-show aggregate coverage/offset/false-in-gap fields are
`null` while status counts remain numeric.
