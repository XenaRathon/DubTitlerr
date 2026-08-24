# v5-two-tier-idempotency

Status: complete

## Problem

`PIPELINE_VERSION` (`common.py:127`, currently 4) is a single global number, and
`stamp_valid()` (`common.py:208-217`) rejects any stamp below it. So a change that
alters only what a caption *says* invalidates every stamped episode exactly as
hard as a change to the decoder, forcing full re-transcription. The 2026-08-21
review ranked this the largest recurring cost in the system.

Underneath the single version are **three** distinct costs, which the codebase
already separates in practice but never records:

1. **Card text** — glossary corrections. `tools/reapply_glossary.py` already does
   this with "no GPU, no LLM, no re-transcription": it reads
   `<stem>.dubtitles.conf.json`, runs `glossary.correct()` per card, rewrites the
   conf and srt, and drops the stamp so `merge_pass` re-muxes. It works. It is
   also **manual, unversioned and not watch-gated**, and nothing in the stamp
   records which glossary an episode's text was corrected against.
2. **Word reflow** — punctuation and card splitting. `punctuation.restore()`
   mutates `word["text"]` in place (`punctuation.py:240`) at `generate.py:732`,
   before `reflow.reflow()` at `:737`. The word list is never persisted
   (`generate.py:679` requests `word_timestamps=True`; the words die after
   reflow), so this genuinely cannot be re-run without the GPU.
3. **Transcription** — the decoder. The glossary reaches it by exactly one route:
   `INITIAL_PROMPT = GLOSS["initial_prompt"]` (`generate.py:112`), passed at
   `:684`. Nothing else glossary-derived touches audio→words.

Separately, sidecar lookup is by filename stem (`mux.py:325-326`) while
validation is by content (`common.py:205`), so an external transcoder's rename
orphans a sidecar whose stamp still describes its video perfectly. Measured on the
live library 2026-08-24: 3,889 video files, 813 stamps (576 at v4, 236 at v2, 1 at
v3), 67 orphaned stamps — 46 match a library video by size, 31 by size and mtime
together. The review brief's "285 of 861" was an estimate taken before any
library-wide scan existed; this measurement supersedes it.

## Users

- **The operator (single, self-hosted).** Needs a glossary fix to cost CPU-minutes
  rather than GPU-hours, needs to know which episodes are running on a stale
  prompt or a stale glossary, and needs the library to **converge ahead of the
  viewer** — the honest invariant, since `watch_queue.py` deliberately never
  queues unwatched shows. The 236 episodes sitting at v2 for weeks are that design
  working, not failing; what is missing is visibility into the residual.
- **The pipeline itself.** `generate.py`, `repair.py` and `mux.py` need to decide,
  per episode, which stages must re-run — from recorded state, not from a flag
  someone remembered to set.

## In scope

- [S-1] Replace the global `PIPELINE_VERSION` with `TRANSCRIBE_VERSION` and
  `TEXT_VERSION`. `stamp_valid()` keeps its meaning; a new `stale_tiers()` returns
  which of `{"transcribe", "text"}` are behind. Old stamps carrying only `version`
  read as both tiers equal to it. **Adoption is `TRANSCRIBE_VERSION = 4`,
  `TEXT_VERSION = 5`**: the 576 live v4 stamps are text-stale but
  transcribe-fresh, so they migrate at watch-gated pace instead of burning the
  library at once. The per-version bump manual currently in `common.py:95-127`
  is ported into both constants' docstrings, stating explicitly that any
  decoder-affecting configuration change (model, beam size, compute type, whisper
  thresholds, `initial_prompt`) requires a `TRANSCRIBE_VERSION` bump — that
  alignment has no mechanical signal and documentation is the load-bearing
  register.
- [S-2] Persist the word list as `<stem>.dubtitles.words.json`, written after
  `punctuation.restore()` and after reflow's `normalize`/`_clamp_to_segments`/
  `_dejitter` transforms, so the cached path replays from byte-identical inputs
  and **skips those transforms entirely**. Because per-segment `no_speech_prob`
  and the clamp bounds exist only on segment dicts (`reflow.py:398-405`,
  `:423-437`) and are unrecoverable from words, the sidecar also carries one
  record per segment plus the episode's `audio_duration` (an independent scalar
  from `media_duration(wav)`, `generate.py:666`, needed for the tail clamp at
  `reflow.py:376-377` and for `CascadeInfeasible`).
- [S-3] Absorb `tools/reapply_glossary.py` into the pipeline as a versioned,
  watch-gated **card-text** stage, and record in the stamp which glossary the
  episode's text was corrected against. Classify by comparing the **stored
  `initial_prompt` string** against the one the current glossary produces — not by
  hashing the glossary file. A glossary edit that leaves the prompt byte-identical
  (every `mine_glossary.py` `hard_fixes` append, which runs per sweep from
  `gen_loop.sh`) is card-text work only; an edit that changes the prompt marks the
  episode transcription-stale.
- [S-4] A staleness queue reporting, per tier, how many episodes are behind —
  **with a reader before it ships**: folded into `lastrun.json`, which
  `generate.py` already writes per show. Drains in `watch_queue.py` order.
- [S-5] Orphan reclaim (`tools/reclaim_orphans.py`): find stamps whose stem has no
  video, match candidates by size, then **confirm by content hash** before
  re-keying — head and tail reads, not the whole file. `--dry-run` (default)
  prints the verdict for all 46 size-matched candidates, including whether the 15
  that fail the mtime check are byte-identical. `--apply` re-keys and refuses to
  run while either loop in `container_run.sh` is live. Never deletes.
- [S-6] Guard the implausible `source_*` window (VAD design §6): on a card of
  ≤2 words where `source_end - source_start > MAX_DUR`, `repair.overlap_ref()`
  returns **no reference** and `generate._card_word_probs()` returns **empty** —
  both counted. Neither falls back to the display window: on 99% of gated cards
  `end == source_end` exactly, so a display-window fallback reproduces the very
  window the guard just declared invalid. Both call sites currently apply a
  `.get()` default (`generate.py:266`, `repair.py:410`); the guard must fire
  before the default. Treat [S-6] as observability, not recovery.
- [S-7] A bake-off measuring `large-v3-turbo` against `large-v3` on the labelled
  set (207 certain hallucinations, 57,572 real cards), reporting catch rate at
  matched precision, wall-clock minutes per episode, and peak VRAM. Models load
  sequentially with a full offload between them. VRAM and throughput are
  re-derived on VM102 — the card moved hosts on 2026-08-23 and the old figures
  do not transfer. Sequenced **after** [S-1]–[S-6]; nothing in them depends on it.
- [S-8] Tick the stale checkboxes in
  `docs/superpowers/plans/2026-08-22-1050ti-to-r520-swap.md`, which still reads
  "planned, not started" for a move completed and verified 2026-08-23.
- [S-9] Split `generate.main()`'s model-load gate so a text-only stale population
  does not load `WhisperModel` (`generate.py:886-888` loads it whenever `todo` is
  non-empty). Otherwise the cheap tier still pays the model load on every sweep.

## Out of scope

- The VAD design's §5 hang trim (`end > source_end`, ~1% of gated cards). It
  changes displayed timing and touches "a caption may be late, never early".
- Repair on episodes with no fansub anchor (`repair.py:355-360`). Becomes a
  card-text change once [S-3] lands.
- Per-stage versioning beyond the two tiers. Rejected: a dependency graph whose
  wrong edge silently skips a stage is the bug class this work removes.
- Migrating the historical design docs out of `docs/superpowers/specs/` or the
  feature directories under `specs/`.
- The 63-variable configuration surface (review §6.2). Cross-host locking (§6.5)
  is also out of scope **as general work**, but [S-5] is a new writer into the
  sidecar namespace and carries its own "the pipeline is not live" precondition.

## Constraints

- **GPU: GTX 1050 Ti, 4 GB, on VM102** (`192.168.1.232`), shared with
  `llama-embed` (714 MiB measured 2026-08-24). `large-v3-turbo` int8 peaks ~1.4 GB;
  `large-v3` int8 does not reliably fit alongside a co-tenant in the measured
  2,396 MiB free. `llama-embed` is evicted for the duration of [S-7] and the sweep,
  and restored afterwards.
- **Repair LLM is remote**: nanbeige4.2-3b on fasc `.209` GTX 1060 via
  `REPAIR_LLAMACPP_URL`; unaffected by that eviction.
- **Sidecar path convention.** Writes go through `common.out_for()`, which
  redirects onto `OUTPUT_ROOT`; existence checks use the raw path, because
  mergerfs unifies the branch back into the same pool view
  (`common.py:40-43`, `generate.py:304-305`). `words.json` follows the same
  convention on both sides. Getting this half-right makes the cache miss
  silently — `words_missing` forever — which is precisely the budget [S-2] exists
  to protect.
- **Never delete known-good output before its replacement exists.** Stale
  sidecars are parked (`.stale`), never removed; `generate.py:273`'s
  `SIDECAR_SUFFIXES` must learn `words.json` or a parked old-version sidecar gets
  read by the cached path. All writes are temp file + `os.replace`.
- **Sidecars are group-writable** (`common.SIDECAR_MODE` 0o664, umask 002).
- **Tests run locally** — `python3 -m pytest --ignore=tests/test_boxxo_voice_extract.py`;
  `pysubs2` 1.9.0 is present (verified 2026-08-24: 1,108 passed in 21 s). The
  container form remains the check of record for anything touching the image:
  `docker run --rm -v "$PWD":/src -w /src --entrypoint sh dubtitle-builder:latest
  -c "pip install -q pytest; python3 -m pytest --ignore=tests/test_boxxo_voice_extract.py"`.
- **No AI-attribution trailers** in commits or PRs; `procoder check` blocks them.
- Any diagnostic `docker run` against the pipeline image passes an explicit
  `--entrypoint`: `container_run.sh` is the entrypoint and ignores a trailing
  command, which previously started a second `gen_loop` unnoticed.

## Interfaces

- `common.TRANSCRIBE_VERSION`, `common.TEXT_VERSION` replace
  `common.PIPELINE_VERSION`; `common.stale_tiers(stamp, video)` is new.
- `<stem>.dubtitles.words.json` — new sidecar, shape below.
- `tools/reclaim_orphans.py` — `--dry-run` (default) reports size matches, mtime
  agreement and content-hash verdicts; `--apply` re-keys. Never deletes.
- `tools/model_bakeoff.py` — writes a JSON report; runs no sweep itself.
- `tools/reapply_glossary.py` — retained as a CLI, but its per-episode work is
  called by the pipeline under [S-3] rather than only by hand.
- `qc` counters: `words_reused`, `words_missing`, `words_version_mismatch`,
  `text_stale`, `transcribe_stale`, `glossary_text_reapplied`,
  `rule_source_window_evaluated` / `_activated`.

## Data

`<stem>.dubtitles.words.json`, written after punctuation restore and after
reflow's word transforms, before card splitting:

    {
      "schema_version": 1,
      "transcribe_version": 4,
      "model": "large-v3-turbo",
      "initial_prompt": "<the exact string passed to whisper>",
      "audio_duration": 1421.32,
      "transforms_applied": ["punctuation", "normalize", "clamp", "dejitter"],
      "segments": [{"start": 0.0, "end": 4.2, "no_speech_prob": 0.01}, ...],
      "words": [{"word": "...", "start": 0.0, "end": 0.0,
                 "probability": 0.0, "seg": 0}, ...]
    }

`initial_prompt` is stored rather than a glossary hash, so [S-3]'s classification
is a string comparison against the current glossary's prompt — no hash needed, and
`generate._glossary_version()` (`generate.py:151-161`) remains what it is today,
a `lastrun.json` label. `segments` carries only the three fields the cached path
needs; `transforms_applied` records which passes the stored words have already
been through, so the replay path knows exactly what to skip. Estimated 200–300 KB
per episode plus ~5–10 KB of segment records — to be confirmed against the first
written sidecar, not assumed.

## Edge cases

- A stamp with `version` but no tier keys (all 813 existing): both tiers equal to
  `version`. Must not raise.
- A v4 stamp with no `words.json` on disk (all 576 of them at adoption): the text
  tier cannot run, so the episode is transcription-stale and transcribes once,
  writing the sidecar. A migration, not a bump.
- `words.json` present but `transcribe_version` behind: treat as absent and count
  it. A crash between transcription and stamping leaves exactly that.
- `words.json` truncated or unparseable: treat as absent, count, do not crash.
- Two orphan stamps matching one video, or one orphan matching two videos:
  ambiguous in both directions; report and re-key neither.
- An orphan whose video was re-encoded: no content-hash match; report as
  unrecoverable rather than guessing by name similarity.
- A card of ≤2 words with no `source_*` keys at all: [S-6] must not fabricate a
  window from a `.get()` default — the VAD design records two of its own
  measurements invalidated by exactly that mistake.
- A `MAX_DUR`-length window on a card of 3+ words: outside [S-6] by definition;
  the guard must not widen silently.
- A glossary edit for a show the viewer is not currently watching: [S-3] applies
  at watch-gated pace, not immediately. The promise is "converges ahead of the
  viewer", and the queue depth says how far behind the rest is.

## Failure modes

- **`words.json` write fails.** Transcription output is already committed; the
  episode is text-tier-uncacheable, counted `words_missing`, and behaves exactly
  as today. Never fails the run.
- **`OUTPUT_ROOT` not in the same mergerfs pool.** Writes land where reads never
  look, so every episode reports `words_missing` and re-transcribes forever. The
  counter is what makes this visible within one sweep instead of one month.
- **NFS mount disappears mid-sweep.** Existing crash-resume and the `.fail` poison
  marker apply unchanged; no new failure path.
- **`large-v3` OOMs during [S-7].** Recorded as that entrant's result rather than
  retried at a smaller beam — a model that does not fit is a finding.
- **Glossary file unreadable when deriving the prompt.** The episode is treated as
  transcription-stale rather than current: unknown provenance is not evidence of
  freshness.
- **`[S-5] --apply` races a live mux.** Refused by precondition; generate and mux
  write and delete exactly the files reclaim renames.
- **`llama-embed` not restored after the sweep.** Its own acceptance criterion,
  because it is exactly the ops step that silently does not happen.

## Acceptance criteria

- [ ] [S-1] A v4 stamp (`{"version": 4, ...}`) parses, reports both tiers as 4,
      and raises nothing. With `TRANSCRIBE_VERSION = 4` / `TEXT_VERSION = 5`, it
      reports text-stale and transcribe-fresh — asserted on the real constants,
      so the assertion fails if adoption is ever set to 5/5.
- [ ] [S-1] Bumping `TEXT_VERSION` alone leaves `stale_tiers()` free of
      `"transcribe"`; bumping `TRANSCRIBE_VERSION` marks both. Both constants'
      docstrings name the decoder-affecting settings that require a transcribe bump.
- [ ] [S-2] On an episode where `_clamp_to_segments` actually moved at least one
      word and at least one segment carries a non-zero `no_speech_prob`, a cached
      re-run from `words.json` produces cards **identical to the original run's**,
      including each card's `no_speech_prob` — asserted against the original
      production run, not against a second cache-shaped run.
- [ ] [S-2] A cached re-run invokes no Whisper model, runs no punctuation LLM call,
      and increments `words_reused`. With the sidecar absent, truncated, or
      carrying an older `transcribe_version`, it increments `words_missing` or
      `words_version_mismatch` and does not crash.
- [ ] [S-2] `words.json` is written through `out_for()` and found by the read path
      when `OUTPUT_ROOT` is set to a different directory; `SIDECAR_SUFFIXES`
      parks it.
- [ ] [S-3] A glossary edit that changes only `hard_fixes` leaves `initial_prompt`
      byte-identical, marks **zero** episodes transcription-stale, and re-applies
      the correction to conf and srt through the card-text path. An edit that
      changes `initial_prompt` marks the episode transcription-stale. The count of
      newly-flagged episodes is asserted, not just the flag.
- [ ] [S-4] Per-tier stale counts appear in `lastrun.json` and are non-zero after
      a `TEXT_VERSION` bump on a pinned show; a subsequent sweep of that show
      shows `words_reused > 0`. Live observation, not only a fixture.
- [ ] [S-5] `--dry-run` reports, for all 46 size-matched orphans, whether each is
      content-identical, and changes nothing. `--apply` re-keys only
      content-confirmed matches, refuses while the pipeline is live, and leaves
      ambiguous matches (both directions) untouched. The re-key set is enumerated
      explicitly and excludes `.fail`, `.stale` and `.muxtmp.mkv`.
- [ ] [S-6] On a 2-word card with `source_end - source_start > MAX_DUR`,
      `overlap_ref()` returns no reference and `_card_word_probs()` returns empty;
      both counters move. Unchanged on a 3-word card with the same window, and no
      activation recorded on a card with no `source_*` keys.
- [ ] [S-7] The bake-off emits catch rate at matched precision, minutes per
      episode, and peak VRAM per model, measured on VM102; an OOM is recorded as
      that model's result.
- [ ] [S-8] The swap plan states the move as completed and verified 2026-08-23,
      checkboxes ticked.
- [ ] [S-9] A sweep whose stale population is text-only completes without loading
      `WhisperModel` — asserted by the absence of the load, not by timing.
- [ ] `llama-embed` is confirmed back on the 1050 Ti after the sweep, by recorded
      `nvidia-smi` output.
- [ ] `procoder check` is clean and the suite passes; the new count is recorded
      (baseline 1,108 passing before this work, boxxo excluded).

## Open questions

