# Review — `specs/timing-compare/spec.md`

> **Reviewer model:** `minimax/minimax-m3` (Buffy / Freebuff)
> **Spec branch:** `feat/timing-compare`
> **Files read for context:** `spec.md`, `common.py`, `repair.py`, `dub_signs_merge.py`,
> `hallucination.py`, `reflow.py`, `pyproject.toml`, `README.md`,
> `specs/b1-hallucination-gate/{spec,plan,tasks}.md`,
> `specs/_template/{spec,plan,tasks}.md`, `tests/test_hallucination.py`,
> `tests/test_dub_signs_merge.py`, `tools/bakeoff.py`.

## Verdict

The spec is well-motivated and on-strategy for DubTitlerr (correctly framed as analysis-only
Phase 0, GPU-free, non-invasive), and the **reuse-first** posture is the right call against
`common.eng_sub_streams` + `extract_sub`. But it has **concrete gaps that would either
silently mis-behave on real data or be reinterpreted differently by two implementers**.

In priority order, the **5–6 changes below must land before implementation starts**; the rest
are quality-of-spec improvements that make review and rollout smoother.

## Top priority (must address before code)

1. **Reuse `repair.dialogue_intervals`, not `dub_signs_merge.keep_event`** — and put it in `common.py`.
   `repair.py:dialogue_intervals()` already returns exactly `(start_s, end_s, text)` per dialogue event
   using the same regex set the spec wants. `dub_signs_merge.keep_event` is the *sign-vs-dialogue*
   predicate (inverted direction). Hoist `dialogue_intervals(video, stream_index)` to `common.py`
   with the parameterization the spec needs (single track, not "merge-all"), so both `repair.py`
   and `timing_compare.py` call the same function.

2. **Hardcode the band cutoffs that match `hallucination.py`.** The acceptance criterion asks for
   `kept_in_gap` bucketed by `nsp` / `logprob` bands but does not name them. Pin them in the spec
   to the existing `hallucination.py` constants so the report and the gate line up — using the
   *strict* inequalities those constants use (`>` for `nsp`, `<` for `lp`), so a card whose raw
   value lands exactly on a cutpoint goes to the right bucket:
   - `nsp` buckets (cutpoints `NSP_FLAG = 0.5`, `NSP_DROP = 0.95`):
     - `clean_le_0.5`      — `\u2264 0.5`     (not flagged by `flag_reason`)
     - `flag_gt_0.5_le_0.95` — `> 0.5 and \u2264 0.95` (`maybe_silence` flag; not yet dropped)
     - `drop_gt_0.95`      — `> 0.95`         (would be dropped by `drop_reason`'s music combo)
   - `lp` buckets (cutpoints `LP_DROP = -2.0`, `LP_FLAG = -0.6`):
     - `clean_ge_-0.6`         — `\u2265 -0.6`     (not flagged)
     - `flag_lt_-0.6_ge_-2.0`  — `\u2265 -2.0 and < -0.6` (`low_conf` flag; not yet dropped)
     - `drop_lt_-2.0`          — `< -2.0`         (would be dropped)
   Naming the buckets after the inequality (not the cutpoint) prevents the off-by-one at exact
   boundaries — `nsp == 0.5` (not flagged) lands in `clean_le_0.5`, `nsp == 0.95` (flagged; not
   dropped unless paired with very low `lp`) lands in `flag_gt_0.5_le_0.95`.

3. **Define the `--tolerance` math, and the "nearest onset" tie-break.** The acceptance criterion
   *"each kept card is classified on-cue or in-gap by overlap (after offset correction) within a
   configurable tolerance (default ±0.30 s / any-overlap)"* is two different rules accidentally fused.
   Specify one. Recommendation:
   - Treat `tolerance` as a **slack applied symmetrically to the cue interval**: a card overlaps
     a cue iff `max(0, min(card.end, cue.end + tol) - max(card.start, cue.start - tol)) > 0`.
   - For nearest-onset-delta pairing (offset estimation), use `abs(card.start - cue.start)`
     **only** (don't fold ends in). Tie-break: the earlier cue wins; on further tie, the lower
     stream-index cue wins. Cap the pairing radius (e.g. ±5.0 s) so a Whisper card with no
     nearby cue does not poison the median with an outlier — pair or skip, don't smear.

4. **Move `timing_compare.py` to `tools/`.** The spec says `"A standalone script timing_compare.py
   exists in the repo root"` and `"ruff check timing_compare.py tests/test_timing_compare.py"` —
   but `tools/` already houses the analytics-style scripts (`bakeoff.py`, the `dump_whisper.py`
   the spec itself references). Put it at `tools/timing_compare.py` and update the ruff line
   accordingly. Keeps the repo root limited to live pipeline stages (`generate`, `repair`,
   `mux`, `merge`, …).

5. **Specify small-N and IQR safety.** Per-episode offset estimation with 3 cards and 3 cues
   is a 3-pair median — statistically meaningless. Add:
   - `matched_pairs_count` field per episode.
   - If `matched_pairs_count < 10`, report `global_offset_s = null` (not 0) and add
     `offset_low_confidence: true` to the per-episode row. Aggregate uses only paired episodes.
   - `residual_iqr_s` is `null` when `matched_pairs_count < 2`; the same for `p95`.

6. **Harden `conf.json` reads.** Add to the Edge-cases table:
   - Mid-write `conf.json` (subgen/generate is still appending): catch `json.JSONDecodeError`,
     report the episode as `bad-conf`, skip, count in a fifth bucket alongside `no-conf` /
     `no-reference` / `analyzed`.
   - Row with `start >= end` or negative `start`: drop the row, continue (don't crash).

## Per-area detailed changes

### 1. Correctness / scope

- **Cite:** *"estimated globally for each episode (median of nearest-onset deltas between cards
  and cues)"* → **Add a max pairing radius.** Without it, a sparse dub track where the nearest
  cue is e.g. 60 s away will pin the offset median to that delta. Specify e.g.
  *"only card/cue pairs with `abs(card.start - cue.start) ≤ 5.0` s contribute to the offset
  median; longer gaps are excluded and counted as `unpaired`."*

- **Cite:** *"Offset correction is applied before overlap classification"* → **Specify the sign
  convention.** Recommendation: `effective_card_start = card.start - global_offset_s`,
  `effective_card_end = card.end - global_offset_s` (offset the dub forward into the sub
  timeline). Make the sign part of the schema (`global_offset_s` is the value to **subtract**
  from card times to align with cues).

- **Cite:** *"Card overlaps two adjacent cues … matched-pair onset-delta uses the nearest cue"*
  → **Tighten the pair selection.** Use `min |card.start - cue.start|` over cues that satisfy
  the absolute-time cap; ties broken per Top-Priority #3 above.

- **Missing criterion:** what happens if `global_offset_s` estimation succeeds but **residual
  spread is huge** (e.g. IQR > 1.5 s)? Add an acceptance criterion: report
  `residual_iqr_s > 1.0` ⇒ add a `look_for_drift: true` flag at the per-episode level so
  Phase-1 can prioritize DTW on those episodes.

### 2. Reuse / DRY

The spec's *"reuse, don't duplicate"* line is good, but the *specific predicate* it points at
is mildly wrong:

- `dub_signs_merge.keep_event(ev)` returns `True` for **signs/songs/credits**, and `False` for
  dialogue and warnings. The tool wants the *inverse* — *"this event is plain dialogue"* — and
  the same regexes (`KARAOKE`, `POSITIONED`, `KEEP_STYLE`, `DROP_STYLE`).
- `repair.dialogue_intervals(video)` already implements the exact selection the spec wants
  (returns `(start_s, end_s, text)` triples for the dialogue subset). It does, however,
  *merge all English streams into one list*, which is not what `timing_compare` wants
  (it needs to score each stream independently to pick the dialogue-dense one).

  **Suggested diff**
  - Hoist `dialogue_intervals(video, stream_indices=None)` into `common.py`:
    - if `stream_indices is None`: same all-stream behavior (preserves `repair.py` callers).
    - if `stream_indices` is an iterable: process only those indices and return their events +
      the list of indices used.
  - Add `dialogue_event_count(video, stream_index) -> int` and
    `dialogue_density_score(video, stream_index) -> float` in `common.py`, both pure
    `pysubs2`-in / numbers-out, both unit-testable.
  - `repair.py`'s `dialogue_intervals(...)` becomes `from common import dialogue_intervals`
    (no behavior change for existing callers).
  - `timing_compare.py` consumes both helpers; no new regexes.

### 3. Acceptance criteria gaps

- **Cite the spec:** *"breakdown by `no_speech_prob` band and `avg_logprob` band"* — bands are
  not named. **Replace with** the four-band bucket list in Top-Priority #2 above, naming
  each bucket after the `hallucination.flag_reason` / `hallucination.drop_reason` tier it
  maps to, so the report is symmetric with the gate.

- **Cite the spec:** *"Start heuristic (e.g. ≥ N cues and ≥ X% plain bottom-position events)"*
  — this is a runtime tuning note masquerading as a criterion. **Replace with a binding
  initial value** and a one-line rationale:
  - *"A track is treated as a dialogue reference iff its filtered dialogue-cue count is
    `≥ 50` AND the share of `plain` (no `\pos` / `\an N` / no `\k`-tag, style ∈ Default/Main)
    events among all dialogue events is `≥ 0.70`. Both thresholds are env-overridable
    (`TIMING_COMPARE_MIN_CUES`, `TIMING_COMPARE_MIN_PLAIN_SHARE`) so Phase 0's first-run
    diagnostics can refine them without a code change."*

- **Cite the spec:** *"Report (written as JSON + printed human summary) contains, per episode
  and aggregated per show and overall: …"* — bullet list a schema but no shape. **Replace
  with** a concrete JSON skeleton, e.g.:

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
            "pct_cards_on_cue": 0.91, "pct_cues_covered": 0.78,
            "kept_in_gap": {
              "total": 14,
              "by_nsp": {"clean_le_0.5": 1, "flag_gt_0.5_le_0.95": 9, "drop_gt_0.95": 4},
              "by_lp":  {"clean_ge_-0.6": 0, "flag_lt_-0.6_ge_-2.0": 11, "drop_lt_-2.0": 3},
              "by_flag": {"maybe_silence": 9, "low_conf": 4, "none": 1}
            },
            "flag_validation": {"maybe_silence_in_gap": 9, "maybe_silence_on_cue": 3},
            "reference_track": {"stream_index": 2, "codec": "ass", "cue_count": 412,
                                "density_score": 0.83}
          }
        },
        "aggregate": { "pct_cards_on_cue": 0.88, "kept_in_gap": 145, ... }
      }
    },
    "aggregate": { "no_conf": 4, "no_reference": 11, "bad_conf": 0, "analyzed": 73, ... }
  }
  ```

- **Cite the spec:** *"`--tolerance` (s, default 0.30)"* — no bounds. Add min/max sanity
  (recommend `--tolerance` clamped to `[0.0, 2.0]`; outside that range, print a warning but
  proceed, since some pathological shows genuinely need >1 s of slack).

### 4. Testability

The spec lists *"offset estimation, overlap/on-cue classification, dialogue-density scoring,
band bucketing"* as pure functions needing unit tests. Pin them with explicit signatures and
fixture shapes so implementation can't drift:

- `estimate_offset(card_starts: list[float], cue_starts: list[float],
  max_pair_radius_s: float = 5.0) -> tuple[float | None, int, list[float]]`
  — returns `(median_offset_or_None, matched_pairs_count, residual_deltas_post_correction)`.
- `classify_overlap(card_start, card_end, cue_start, cue_end, tolerance_s) -> bool`
  — returns `True` iff the slack-aware interval intersection is positive; unit-testable with
  edge cases (touching boundaries, partial overlap, sub-cue inside card, card inside sub-cue).
- `score_dialogue_density(events: list[pysubs2.SSAEvent]) -> tuple[int, float]`
  — returns `(dialogue_cue_count, plain_event_share)`. Should take pre-loaded events (not a
  file path), so tests construct `SSAEvent` fixtures directly.
- `bucket_nsp(nsp: float) -> Literal["clean_le_0.5", "flag_gt_0.5_le_0.95", "drop_gt_0.95"]`
  and the matching `bucket_lp(lp: float) -> Literal["drop_lt_-2.0", "flag_lt_-0.6_ge_-2.0",
  "clean_ge_-0.6"]`. Trivial, but spec it so test count is dictated by the spec and to lock the
  cutpoint-vs-inequality naming decision.
- `nearest_onset_pairs(card_starts, cue_starts, max_radius) -> list[tuple[int, int, float]]`
  — pure assignment function; tested with sorted-card / sorted-cue fixtures, ties, and the
  radius cap.

### 5. Project-convention issues

- **Missing `Authorization` section.** The template (`specs/_template/spec.md`) makes
  *Authorization* a required section, and `b1-hallucination-gate/spec.md` has one even
  though the gate is in-process. **Add an `## Authorization` subsection** that documents:
  - This is a read-only analytics tool with no auth boundary of its own.
  - It writes one file: `timing-compare.report.json` (location chosen by `--out`, default cwd).
  - It runs as the user invoking it (no privilege escalation, no chown, no setuid; unlike
    live stages, ownership is *not* rewritten so it can run as an unprivileged user against
    the same media).

- **`Components / changes` section missing.** The B1 spec has a "Components / changes"
  section listing new vs modified files. **Add one**, so reviewers can immediately see the
  diff blast-radius. Concrete shape:
  - **New:** `tools/timing_compare.py`, `tests/test_timing_compare.py`.
  - **Modified:** `common.py` — add `dialogue_intervals(video, stream_indices=None)` and
    `score_dialogue_density(events)`.
  - **Modified:** `repair.py` — change local `dialogue_intervals` to call the new
    `common.dialogue_intervals` (char-for-char unchanged behavior).
  - Not modified: `generate.py`, `mux.py`, `dub_signs_merge.py`, `hallucination.py`,
    `Dockerfile.builder`, `pyproject.toml`.

- **Acceptance criterion language:** *"ruff check timing_compare.py tests/test_timing_compare.py
  clean; all existing tests still pass."* → **Update path** to
  `tools/timing_compare.py tests/test_timing_compare.py` after the file move.

### 6. Missing risks

- **Concurrent write to `conf.json`.** If a stage (generate, repair) is mid-write when
  `timing_compare.py` reads, the JSON will be half-parsed. **Add:** catch `JSONDecodeError`
  → report status `bad-conf`, count in a new bucket, log the path.
- **Tie on density score.** Two English sub tracks with identical dialogue cue counts and
  identical plain-share score → undefined choice. **Specify deterministic tie-break:**
  lower stream-index wins.
- **`repair.dialogue_intervals`'s all-streams merge.** Reusing it naïvely in
  `timing_compare.py` would defeat the purpose of measuring *track selection*. **Make the
  refactor explicit** (see §2 above): add a per-track variant before any reuse.
- **Inverted selection with `dub_signs_merge`'s "Translation" tier.** `keep_event`
  *drops* `style=Translation` as a song-translation; but for `timing_compare` you may
  *want* to count `Translation` as dialogue if the release uses a translation-only track
  with no `Default` style. **Add a rule** to the track-selection step: count an event as
  `plain dialogue` if `style ∈ {Default, Main, …}` **or** `style ∈ {Translation}` (with
  `Translation`-tier events weighted at e.g. `0.5` of an event, since the wording differs).
  Failing this rule risks dismissing fansub-only tracks even when their cue density is much
  higher than whatever the dialogue-style split happens to be in that release.

### 7. Ambiguity / weak wording

- **Cite:** *"is very likely a hallucination / is very likely real"* — **Replace** the
  qualitative *"very likely"* with a falsifiable hypothesis the report can test, e.g.
  *"We expect ≥ 80% of `no_speech_prob` > 0.5 cards outside dialogue cues to be clear
  hallucinations (blocklist / repetition / Whisper music framing); the report's
  `kept_in_gap.by_flag` row tells us if the in-gap set is concentrated in `maybe_silence`,
  which is the actionable signal for Phase 1."*
- **Cite:** *"e.g. ≥ N cues and ≥ X% plain"* → **Replace with concrete numbers** (see §3).
- **Cite:** *"Start heuristic … tune on the first run's `reference_track` diagnostics"* — split
  into spec-time initial numbers and an Open Question about tuning based on the run.
- **Cite:** *"... one or more show directory paths (walked for video files, same extension
  set as `common.VIDEO_EXTS`)."* — **Add:** pruning for `EXTRA_DIRS` and walk behavior
  (recursive, symlink-following, hidden-dir). Recommend matching `repair.py`'s behavior
  (`os.walk(root)` with no symlink argument → does not follow by default).

### 8. Tiny wins the implementer would otherwise miss

- **Empty `conf.json` with valid rows but no overlap with any cue** → `pct_cards_on_cue = 0.0`,
  `pct_cues_covered = 0.0`, `kept_in_gap.total = N`. Already legal under existing spec, but
  call out that `null` is reserved for *structural* impossibility (no cues at all → can't
  compute), not for *zero* results.
- **`--out` writes into a path that lives on a different filesystem than the media.**
  Forbidden by the *"read-only"* rule, but explicitly say the report write is the **only**
  write and never touches `OUTPUT_ROOT` (this is analytics, not part of the media pipeline,
  so `output_for()` redirection doesn't apply).
- **Show dir argument case.** Linux paths — `os.walk` is case-sensitive; mention that the
  tool **does not** case-fold show names. (Affects aggregate display; can be confusing if
  the user types `./AEON/` vs `./Aeon/`.)
- **`tools/bakeoff.py` is a useful adjacent pattern** — it uses `argparse`, a `--limit`,
  prints a clean comparison block. Mention `timing_compare.py` should have the same
  `argparse` shape and a `--summary-only` flag (no per-episode JSON dump, just the human
  headline) for quick first-run sanity checking.
- **A "Phase 0 vs Phase 1" boundary** is implied but not stated; add a one-line note that
  Phase 1 (gating) **cannot begin** until this spec's report has been reviewed on ≥ 3 shows
  with usable dialogue tracks. That makes the Phase-0 → Phase-1 hand-off explicit.

## Suggested diffs to `spec.md` (regional edits)

Here are the smallest-edit diffs to apply directly. Each opens with the **from** text and
shows the **to** text.

### Diff A — Top-of-doc model heading + Authorization section

```diff
 # Spec — Timing Compare: dubtitle-vs-subtitle timing analysis (Phase 0)

 > A GPU-free measurement tool …
+
+## Authorization
+
+- **Who can execute:** any user with read access to the show directory and write access to
+  the `--out` path. This is a read-only analytical tool — no auth boundary, no chown, no
+  privilege escalation.
+- **Behavior without permission:** if the show directory is unreadable or `--out` is not
+  writable, the tool exits non-zero with one log line per failed path. No partial state is
+  left behind — the only write is the final report file, written atomically.

 ## Context and problem
```

### Diff B — Acceptance criterion tightening

```diff
-- [ ] A standalone script `timing_compare.py` exists in the repo root, runnable as
-      `python timing_compare.py <show_dir> [<show_dir> ...]`, GPU-free, importing nothing that
-      requires a GPU (no `faster_whisper` import at module scope).
+- [ ] A standalone script `tools/timing_compare.py` runs as
+      `python tools/timing_compare.py <show_dir> [<show_dir> ...]`, GPU-free, importing
+      nothing that requires a GPU (no `faster_whisper` import at module scope).
@@
-- [ ] **Classification:** each kept card is classified `on-cue` or `in-gap` by overlap (after offset
-      correction) within a configurable tolerance (default ±0.30 s / any-overlap).
+- [ ] **Classification:** each kept card is classified `on-cue` or `in-gap` by slack-aware
+      overlap with the references' dialogue cues (after offset correction), where a card
+      `C = [c_s, c_e]` overlaps a cue `K = [k_s, k_e]` with tolerance `t` iff
+      `max(0, min(c_e, k_e + t) - max(c_s, k_s - t)) > 0`. Default `t = 0.30 s`.
+      `--tolerance` is clamped to `[0.0, 2.0]`; values outside the range print a warning
+      and proceed.
@@
-- [ ] **Report** (written as JSON + printed human summary) contains, per episode and aggregated
-      per show and overall:
-  - `global_offset_s`, and the residual onset-delta median + IQR for matched pairs
-  - coverage: `pct_cards_on_cue`, `pct_cues_covered`
-  - `kept_in_gap`: count + a breakdown by `no_speech_prob` band and `avg_logprob` band and existing
-    `flag` value (validates whether in-gap cards look like hallucinations)
-  - `flag_validation`: of `maybe_silence`-flagged kept cards, counts in-gap (confirmed) vs on-cue
-    (false alarm)
-  - `reference_track`: which stream index/codec was used, its cue count, and its density score
-  - counts of `no-conf`, `no-reference`, `analyzed` episodes
+- [ ] **Report** (written as JSON + printed human summary) contains, per episode and
+      aggregated per show and overall:
+  - `schema_version: 1` and the resolved `config` (`tolerance_s`, `min_cues`,
+    `min_plain_share`) so re-runs are comparable.
+  - `global_offset_s` (null when `matched_pairs_count < 10`), `matched_pairs_count`,
+    `offset_low_confidence: bool`, residual `median_s` and `iqr_s` for matched pairs
+    (both null when `matched_pairs_count < 2`).
+  - coverage: `pct_cards_on_cue`, `pct_cues_covered`.
+  - `kept_in_gap`: count plus buckets aligned to `hallucination.py` (named after the
+    strict-inequality function they mirror) — `by_nsp` (`clean_le_0.5` /
+    `flag_gt_0.5_le_0.95` / `drop_gt_0.95`), `by_lp` (`clean_ge_-0.6` /
+    `flag_lt_-0.6_ge_-2.0` / `drop_lt_-2.0`), and `by_flag` (the existing `flag` field values).
+  - `flag_validation`: of `maybe_silence`-flagged kept cards, counts in-gap vs on-cue.
+  - `reference_track`: stream index, codec, cue count, density score (0–1).
+  - counts of `no-conf`, `no-reference`, `bad-conf`, `analyzed` episodes (one each in
+    `aggregate.<bucket>` and `shows[<SHOW>].aggregate.<bucket>`).
+- [ ] **Pairing radius:** only card/cue pairs with `abs(card.start - cue.start) ≤ 5.0 s`
+      contribute to offset estimation; unpaired cards count as `kept_in_gap`. Tie-break
+      for equidistant cues: earlier cue wins; on further tie, lower stream index.
+- [ ] **Hardened read:** `FileNotFoundError`, `PermissionError`, and `json.JSONDecodeError`
+      on `conf.json` → status `bad-conf`; row with `start >= end` or negative `start` →
+      row dropped silently, completion continues.
```

### Diff C — Edge cases additions

```diff
 | Case | Expected behavior |
 |---|---|
 | Episode has no `.dubtitles.conf.json` | Report `no-conf`, skip (not an error) |
+| `conf.json` is mid-write or malformed JSON | Catch `json.JSONDecodeError`, report `bad-conf`, skip, count |
+| `conf.json` row has `start >= end` or negative `start` | Drop the row, continue with the rest |
 | No embedded English sub track (e.g. dub-only mp4) | Report `no-reference`, skip |
 | Only sub track is signs/songs-only | Dialogue-density scorer rejects it → `no-reference`, skip |
 | Multiple English sub tracks | Pick the highest dialogue-density one; record which was used; ties → lower index |
 | `conf.json` present but empty (no kept cards) | Report `analyzed` with 0 cards; coverage undefined → report `null`, not a crash |
```

### Diff D — Edge-cases sign convention

```diff
 | Large constant offset (dub lead/lag or framerate) | Captured as `global_offset_s`; residual spread still measured after correction — the offset is a finding, not a failure. Sign convention: `global_offset_s` is the value to **subtract** from card times to align with cues (`effective_card_start = card.start - global_offset_s`). |
```

### Diff E — Open questions → initial values + remaining knobs

```diff
 ## Open questions (to confirm at spec review / runtime)

-- [ ] **Which 2–3 shows** for the first run? …
-- [ ] **Tolerance / on-cue definition** — start at ±0.30 s / any-overlap; revisit if coverage looks
-      implausibly low/high on the first run.
-- [ ] **Dialogue-density threshold** — how dense/plain a track must be to count as a dialogue
-      reference (vs signs-only). Start heuristic (e.g. ≥ N cues and ≥ X% plain bottom-position
-      events), tune on the first run's `reference_track` diagnostics.
+- [ ] **Initial values (binding for Phase 0).**
+      - Dialogue-track threshold: `min_cues=50`, `min_plain_share=0.70`. Env-overridable by
+        `TIMING_COMPARE_MIN_CUES` and `TIMING_COMPARE_MIN_PLAIN_SHARE`.
+      - Offset pairing radius: `5.0 s`. Env-overridable by `TIMING_COMPARE_PAIR_RADIUS_S`.
+      - `--tolerance` default `0.30 s`, range `[0.0, 2.0]`.
+      - Phase-1 trigger: at least **3 shows** with `pct_cards_on_cue ≥ 0.80` and
+        `no-reference` rate ≤ 30% before any gating spec is opened.
+- [ ] **Runtime knobs (not decisions).** Show selection for the first run is the user's
+      call — the tool accepts any show dirs. Names are decoded from `os.walk`; the tool
+      does not case-fold.
+- [ ] **Translation-style handling.** If a release uses a fansub-`Translation`-style track
+      as its only reference, the first-run diagnostics (`reference_track.density_score`)
+      will reveal it. Threshold tuning may follow.
```

## Out-of-scope clarifications (no behavior change, just sharper wording)

The current **Non-goals** section is solid. Two micro-tightenings:

- **Re: "DTW / drift-aware sequence alignment"** — add a forward-pointing note: *"Phase 1 may
  revisit per-episode global offset if any episode has `residual_iqr_s > 1.0`; treat that as
  drift evidence, not as a spec violation."* Phase 0 then needs to *report* that flag (see
  Acceptance criteria above).
- **Re: "fake drops / raw-dump every episode"** — note explicitly that this requires
  `dump_whisper.py` to write *only* the post-A1+pre-drop card candidates, NOT the survivors;
  otherwise the dump will reproduce post-B1 data and a future `dump_whisper.py`-driven mode
  will not be able to measure false-drops. This is a constraint on a *future*, not-present
  tool, but pinning it now prevents silent breakage later.

---

**Reviewed by:** `minimax/minimax-m3`
**Date:** 2026-07-24 (matches this session's date)
**Status:** *Review complete — recommendations above are concrete diffs; await author response
on Top-Priority items 1–6 before implementation starts.*

---

# Second review — `specs/timing-compare/spec.md`

> **Reviewer model:** `minimax/minimax-m3` (Buffy / Freebuff)
> **Review type:** Complementary / implementation-rollout focused
> **Files read for context:** `spec.md`, `REVIEW.md` (first pass), `common.py`,
> `hallucination.py`, `specs/_template/spec.md`.

## Verdict

The first review already covers the core correctness, DRY, and acceptance-criteria gaps. This second pass focuses on **rollout safety, implementation sequencing, and how the report will be consumed** — areas the spec treats implicitly. The spec is structurally sound, but three of the points below need explicit wording before implementation starts so Phase 0 does not accidentally destabilize the live pipeline or leave ambiguous operational behavior.

## Complementary findings

1. **Praise: the analysis-only Phase-0 scoping is the right derisk.**
   The spec explicitly walls off gating, snapping, and re-transcription. That is the correct way to introduce a new signal: measure first, gate later. Keep that framing prominent.

2. **Subtitle extraction artifacts violate the read-only promise unless cleaned up.**
   **Cite:** *"It extracts the embedded English subtitle stream(s) via the existing
   `common.eng_sub_streams` + `extract_sub` helpers"* and *"No mutation of any media, sidecar,
   or pipeline state."*
   `common.extract_sub(video, idx, out)` writes an `.ass` file to the path given. If the
   implementation points `out` at the media directory, it creates sidecar clutter on a
   read-only filesystem. **Add a constraint:** extracted subtitle files must be written inside
   `tempfile.TemporaryDirectory()` and deleted when the episode is processed.

3. **The `common.py`/`repair.py` refactor is a prerequisite with live-pipeline blast radius.**
   The first review recommends hoisting `dialogue_intervals` to `common.py`. That is a live
   pipeline change even though the consumer (`timing_compare.py`) is offline. Sequence it:
   - Merge the `common.py`/`repair.py` refactor **first**.
   - Add unit tests that pin the fallback `stream_indices=None` behavior to exactly the
     current `repair.py` output.
   - Only then merge `tools/timing_compare.py`.
   This prevents a situation where the offline analytics PR breaks the repair stage.

4. **CLI `--lang` default must mirror the live pipeline's env convention.**
   **Cite:** *"`--lang` (sub language filter, default the pipeline's `SUB_LANGS`)."*
   `common.py` does not export a unified `SUB_LANGS`; live modules load it locally as
   `os.environ.get("SUB_LANGS", "eng,en,und").split(",")`. To keep parity, `timing_compare.py`
   should use the exact same env default and the same parsing (comma-split, lowercased). Add
   this explicitly to the Data Contracts / Inputs section.

5. **The printed summary should headline the "applicability ratio."**
   The report JSON carries `no-reference` and `analyzed` counts, but the human summary is
   undefined. Add: the printed summary must show, per show and overall,
   `applicability_ratio = analyzed / (analyzed + no-reference)` rounded to two decimals.
   This is the single most important headline for deciding whether Phase 1 gating is even
   worthwhile — if only 20% of episodes have a usable dialogue sub track, the signal is not
   broadly deployable.

6. **Clarify what happens when all episodes in a show are `no-reference`.**
   The spec says aggregate per show and overall. If a show has zero `analyzed` episodes, the
   aggregate `pct_cards_on_cue` is undefined. Specify that the per-show aggregate should
   report `null` (not `0` or `1`) for coverage/offset fields, while still reporting the
   episode-status counts. This avoids confusing `0.0` with "0% covered" when there was no
   usable reference.

## Suggested spec additions (small edits)

- **Constraints / extraction:** *"Extracted subtitle files are written to a temporary directory
  and removed after the episode is processed; no `.ass` sidecar is left next to the source
  media."*
- **Inputs / `--lang`:** *"Default is `SUB_LANGS` env var, parsed as a comma-separated list and
  lowercased, matching `repair.py` / `dub_signs_merge.py` conventions."*
- **Outputs / printed summary:** *"The human-readable summary prints per-show and overall
  `applicability_ratio`, defined as `analyzed / (analyzed + no-reference)`, plus the
  top-line `pct_cards_on_cue` and `kept_in_gap` totals."*
- **Edge cases:** Add a row *"All episodes in a show are `no-reference`"* → *"Per-show
  aggregate coverage/offset fields are `null`; status counts are still reported."*

**Reviewed by:** `minimax/minimax-m3`
**Date:** 2026-07-24
**Status:** *Supplementary review complete — items 2 and 5 should be added to the spec; item 3 should be captured in the implementation plan (plan.md / tasks.md).*

