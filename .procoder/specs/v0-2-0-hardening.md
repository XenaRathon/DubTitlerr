# v0-2-0-hardening

Status: complete

## Problem

`main`'s CI has been red since 2026-09-05 (16 days, unaddressed) while this branch
carries two hotfixes (`7e3d106`, `1e8eaaa`) the pushed `main` lacks (the local
`main` also holds an unpushed docs-only commit `2f8ae80` that stays local) —
"launch-readiness is closed" is not true yet. Underneath that,
five separate categories of debt accumulated across the v0.1.0 beta and five
adversarial review passes, all confirmed live in the current tree (2026-09-21
line-by-line check, five parallel verification passes):

1. **Stage completion is not fail-closed.** `write_stamp()`'s `stages` field
   (`common.py:258-290`) has zero readers anywhere in production code;
   `merge_pass.sh` captures no exit codes and has no `set -e`
   (`merge_pass.sh:48-60`); `dub_signs_merge.py`'s failure returns (`"no-video"`,
   `"build-error"`, `dub_signs_merge.py:292,297`) don't raise. A repair, signs, or
   mux failure can still produce a current-looking `.dubtitles.done` stamp.
2. **MP4/M4V conversion deletes the original before the stamp durably records
   success.** `mux.process()` runs `_finalize(out, final)` → `os.remove(orig)` →
   `write_stamp(...)` in that order (`mux.py:463-467`) — if the stamp write then
   fails, the source file is already gone and only the new mkv remains
   unrecorded.
3. **The deployed unanchored-repair policy has drifted from its own review and
   its own docs.** `REPAIR_UNANCHORED=1` has been deployed library-wide since
   2026-09-06 (`common.py:167`), but the 45-line human review that justified
   unanchored repair covered only 3 One Pace episodes, `handoff.md:183-185`
   still says "do not flip the flag on," and `docs/wiki/How-To-Guides.md:44`
   / `Reference.md:106` still say "do not use it" / "unset — closed."
4. **Decoder/transcription provenance is half-recorded.** `words.json` stores
   `model` and `initial_prompt` (`generate.py:378-407`) but `common.read_words()`
   only ever compared `transcribe_version` (`common.py:223-255`); `compute_type`
   and `beam_size` are read from the environment at generation time
   (`generate.py:105,968`) but never persisted anywhere.
5. **The review server's posture has real open gaps and a real doc/behavior
   drift.** `authorised()` returns `True` for every GET/HEAD regardless of path
   (`review_server.py:212-215`), so `/api/episodes`, `/api/episode`, and
   `/api/shared` disclose absolute media paths and repair text to anyone who can
   reach the port; `serve()` (`review_server.py:1255-1263`) has no
   `REQUIRE_TOKEN` belt at all; and the documented Compose install path
   (`compose.yaml`, untracked, `.env.example` ships `REVIEW_TOKEN` blank) silently
   disables auth by the CURRENT `auth_required()` semantics
   (`review_server.py:138-140`: false only when `REVIEW_TOKEN` is present and
   empty) — while the plain `docker run` Quick Start path hits the safe
   auto-generate branch instead. The two documented install paths disagree on
   default security posture.

Alongside these, `compose.yaml`/`.env.example` were never committed
(`git status` `??`, zero history), five files/dirs sit unclassified in the
working tree, a stash entry is stale, and the T12 real-media leg of
timing-compare and a read-only S&S-extraction prototype are the only
measurement work still open from the note's P2 list. This spec is the v0.2.0
release boundary: everything in scope below ships in 0.2.0; everything under
"Out of scope" is explicitly deferred, not silently dropped.

## Users

- **The operator (single, self-hosted).** Needs `main` green so "the beta is
  live" is actually true, needs a Compose install that doesn't silently ship
  with auth off, needs a mux failure to never look like a success, and needs
  one place recording what's actually deployed (unanchored flag, review
  posture, queue/publish state) instead of five stale documents disagreeing
  with each other and with `common.py`.
- **The reviewer** (the operator, wearing the review-server hat). Needs GET
  requests gated the same as writes once posture changes, and needs the page
  itself to keep working across that change (token sent on GET too).
- **The pipeline itself.** `repair.py`, `dub_signs_merge.py`, and `mux.py` need
  a durable, typed record of what each stage actually did, so `merge_pass.sh`
  can refuse to print a clean pass over a failed episode, and so a transient
  signs failure is never silently promoted to "this episode never had signs."
- **The next contributor / CI.** Needs a repo whose tree, stash, and hygiene
  ledger are classified, not left as five kinds of untracked cruft next to a
  green gate that never actually ran on `main`.

## In scope

- [S-1] Get `main`'s CI green again: fix `ruff` I001 (import order) and W292
  (missing final newline) in `tests/test_gen_loop_set_e.py` (both still present
  on this branch — verified: `ruff check tests/test_gen_loop_set_e.py` reports
  exactly these two), confirm the pushed `github/main` is already an ancestor of
  this branch (it is, at `defe151`; the local-only `2f8ae80` is not pulled in),
  push to the `github` remote, and record one green CI run on
  `main`. Re-run `tests/test_review_apply.py` as the regression check for item
  5 (already closed by `80dc87a`; verify only, do not re-implement).
- [S-2] Commit `compose.yaml` and `.env.example`, and stop the Compose install
  path from disabling auth by default: `auth_required()` (`review_server.py:138-140`)
  must treat an EMPTY `REVIEW_TOKEN` as unset (a token is generated), not as
  "disabled" — disabling requires the explicit `REVIEW_AUTH=off`. Update the
  README's review-server section and `SECURITY.md` to describe the new rule so
  the documented posture matches the code.
- [S-3] Classify every untracked/modified path from `git status`:
  `.craftsman-baseline.json` and `.lycheecache` are gitignored (the baseline's
  own entries reference only ignored worktree/venv paths, so ignoring it drops
  nothing meaningful); `docs/agents/`, `docs/beta-feedback/`, `docs/promo/`, and
  the modified `.procoder/github/LESSONS.md` are committed; `stash@{0}` ("luna
  pre-fix export_reviewed") is dropped — its content already shipped as
  `1da6879` (`tools/export_reviewed.py` + `tests/test_export_reviewed.py` exist
  on `main`); `ISSUE-s32e02-timing.md` is committed next to the other
  `ISSUE-*.md` files (owner decision — recommended default, confirm at sprint
  010 open).
- [S-4] Take a read-only production snapshot and write it to the vault: the
  active worker host, checked with `docker ps` on vm102 AND fasc AND 3200g (not
  assumed from the last note); the deployed `REPAIR_UNANCHORED` value; any
  per-show `unanchored_repair` glossary opt-ins found; the review server's
  bind address and whether `REVIEW_TOKEN`/`REVIEW_AUTH` is set; a diff between
  the deployed order file and a fresh `watch_queue.py --dry-run`; the publish
  timer's status; and whether the stopped `dubtitle-builder` container on the
  old 3200g host is classified dead-weight or standby.
- [S-5] This spec IS the v0.2.0 boundary. Open a `## 0.2.0 - Unreleased`
  section in `CHANGELOG.md` (distinct from the existing `## [Unreleased]`
  section) listing every scope id below as included, and naming the "Beyond
  v0.2.0" list as explicitly deferred.
- [S-6] Add a durable per-episode stage-status artifact with typed outcomes:
  `common.STAGES_SUFFIX = ".dubtitles.stages.json"`,
  `common.STAGE_OUTCOMES = ("ok", "no-reference", "llm-empty",
"backend-unreachable", "extract-error", "build-error", "no-video", "timeout",
"crashed", "unwritable")`, `common.write_stage(stem, stage, outcome, detail="")`
  (merges into the per-episode JSON), `common.read_stages(stem) -> dict`
  (empty dict when absent/unreadable), and `common.failed_stage(stem) -> str |
None` (first stage whose outcome is not in `{"ok", "no-reference",
"no-video"}`). `repair.py`, `dub_signs_merge.py`, and `mux.py` each record
  their real outcome on every return path. A transport failure to the LLM
  backend is recorded as `"backend-unreachable"`, never `"llm-empty"` — a prior
  outage dumped roughly 1,300 queue entries under `llm_empty` that were really
  a dead endpoint.
- [S-7] `merge_pass.sh` captures each stage invocation's exit code and prints
  `MERGE PASS COMPLETE` only when no episode has a failed stage (per
  `common.failed_stage`); otherwise it prints `MERGE PASS INCOMPLETE: <n>
episodes with a failed stage`. An `rc != 0` with no stage record for that
  stem is itself recorded as `write_stage(..., "crashed", "rc=<n>")` via
  `python3 -c`.
- [S-8] A transient signs extract/build failure is made distinguishable from a
  genuinely signs-free episode: `mux.py` refuses to mux a dialogue-only
  replacement as though it were the combined track when `common.read_stages`
  says the `signs` stage failed AND the prior `.ass` sidecar had at least one
  sign event — it must not silently fall through `sub_source()`'s
  ASS-then-SRT fallback (`mux.py:403-409`) and stamp the demoted output as
  done.
- [S-9] For an MP4/M4V source, reorder `mux.process()` so the stamp is written
  BEFORE `os.remove(orig)`, not after (today's order is the reverse:
  `mux.py:462-467`). On a `write_stamp` failure, the new `final` mkv is
  removed and `orig` is kept — retryable, no data loss, no duplicate episode.
  README states plainly that the original container is deleted only after a
  verified, stamped remux. New tests cover an unwritable stamp directory and a
  simulated interruption between finalize and stamp.
- [S-10] `words.json` schema 2 adds `compute_type` and `beam_size`;
  `common.WORDS_SCHEMA_VERSION` becomes `2`; `generate.decoder_identity()`
  returns `{"model": MODEL, "initial_prompt": INITIAL_PROMPT, "compute_type":
COMPUTE, "beam_size": int(os.environ.get("WHISPER_BEAM_SIZE", "7"))}`;
  `common.read_words(stem, rec=None, expect: dict | None = None)` compares
  `model`/`initial_prompt`/`compute_type`/`beam_size` against `expect` when
  given: a field that IS recorded and differs counts `words_config_mismatch`
  and returns `None`; a field absent or `""` in the sidecar (schema-1 files,
  including the pre-existing bug where `model` was written from an unset
  `WHISPER_MODEL` env var as `""`, independent of the resolved `MODEL`
  constant) counts `words_config_unknown` and is still returned — the 366 live
  sidecars are not invalidated by this. A future-`transcribe_version` test is
  added for the already-real `words_version_mismatch` behavior. Same-size/
  same-mtime media replacement is documented in `common.py`'s stamp docstring
  as the accepted immutable-media assumption, not upgraded to a content hash
  (owner decision — recommended default, confirm at sprint 010 open).
- [S-11] Reconcile the deployed unanchored-repair policy: the 4 rejected S31
  targets from `REVIEW-2026-08-27-unanchored-repair-45-lines.md` are recorded
  in the One Pace decision store via `decisions.record(...)` under
  `decisions.locked(show, dir)` (followed by `decisions.save`), joining the 41
  already-approved lines; `handoff.md:183-185` is marked superseded in place;
  `docs/wiki/How-To-Guides.md:44` and `Reference.md:106` (both currently say
  "do not use `REPAIR_UNANCHORED`" / "unset — closed") are reconciled with the
  deployed global flag; one vault operator note holds the deployed value, the
  human-review boundary, and the recovery procedure together (owner decision —
  recommended default: keep the global flag, since v10's `TEXT_VERSION` bump
  already paid the regeneration cost; recovery is a `reject` verdict through
  `decisions.record` + `review_apply.py`; confirm at sprint 010 open).
- [S-12] Close the phonetic-name-guard issue as resolved by a different
  design: `ISSUE-phonetic-name-guard.md` gets a status header pointing at
  `repair.invents_name()` (the glossary-membership half) and
  `repair.substitutes_a_vouched_name()` (the Jaro-Winkler half,
  `PHONETIC_MIN` default `0.75`). No fixture or measurement work — the guard
  already matches the issue's proposed fix.
- [S-13] Retire `REPAIR_BACKEND_SECONDARY`: remove `IMPROVEMENTS.md` §5
  ("Architecture: Two-Backend Repair") entirely; update `REVIEW.md:1025-1029`
  and `REVIEW.md:1099` to state it is retired rather than "not yet
  implemented" (owner decision — recommended default: retire; three prior
  reviews already recommend this, and `REPAIR_MODEL_SECONDARY` already covers
  the second-opinion need).
- [S-14] Harden the review server's auth posture in code: `GET`/`HEAD` on any
  path starting with `/api/` requires the token like writes do (401
  `{"error": "a token is required"}`); the rendered pages `/`, `/index.html`
  and `/shared` are gated the same way through a `dubtitlerr_token` cookie the
  token box sets alongside localStorage — without a valid header or cookie
  they render only the token box, never a stem or repair text; `/healthz`
  stays open. `REQUIRE_TOKEN=1` makes `serve()` hard-exit with status 2,
  logging `"review server: REQUIRE_TOKEN=1 but auth is disabled
(REVIEW_AUTH=off)"`, before binding. `SECURITY.md` is updated to match the code (owner decision — keep
  the `0.0.0.0` bind: loopback inside a container would make the published
  port unreachable, so the token is the actual boundary; confirm at sprint 010
  open).
- [S-15] Add a real-socket HTTP test: the server started on port 0 in a
  thread, not the handler called directly. Covers: 401 on `GET /api/episodes`
  without a token, 200 with one; a slow/partial body read that times out at
  `Handler.timeout`; and `MAX_CONCURRENT + 1` simultaneous connections, where
  the extra connection is closed rather than queued indefinitely.
- [S-16] Add a heartbeat file, `GET /healthz`, and a Dockerfile HEALTHCHECK:
  `common.HEARTBEAT_PATH`, `common.heartbeat(**fields)` (atomic merge-write),
  `common.read_heartbeat()`. `/healthz` returns 503 when the mount is stale, the
  order file is missing, or no sweep has completed within `3 ×
RESCAN_INTERVAL`. Whether an autoheal actuator exists in the real deployment
  is a live-host check only (the label lives in an out-of-repo compose file),
  not something this repo can verify or fix.
- [S-17] Run the T12 real-media leg of timing-compare on 3 selected shows (one
  fansub dialogue track, one signs-only, one One Pace episode), producing a
  report and a go/no-go note under `docs/timing-compare/`. VAD errors are
  reported as their own field, separate from offset/drift numbers. No Phase-1
  gate is wired as a result. `specs/timing-compare/tasks.md` is reconciled:
  T1–T11 ticked (already shipped), the stale `feat/timing-compare` branch
  reference corrected.
- [S-18] Write a queue/publish operations verification note: `systemd-analyze
verify` output, the publish timer's status, the last publish result, a
  drift check between the deployed order file and `watch_queue.py --dry-run`,
  and confirmation the public manifest/title policy (release-group stripping,
  duplicate-encode handling) remains intentional.
- [S-19] Write a storage/host checklist note: the single active worker
  confirmed (not assumed), mergerfs `pfrd` persistence through the
  OMV-managed config, the unexplained continuous writer on `sdc1`, and
  `llama-embed` confirmed back on the 1050 Ti after any heavy run. Raise
  `generate.py`'s `FFMPEG_TIMEOUT` default from `600` to `1800`, with a
  README/Reference note explaining the slow-NFS-mount rationale already
  documented at `generate.py:32-33`.
- [S-20] Build a read-only S&S (signs & songs) extract-only prototype,
  `tools/sns_extract.py`: standalone, imports `dub_signs_merge.keep_event` and
  adds a numeric heuristic `off_default_position(ev, play_res_y)`.
  Programmatic fixtures via `pysubs2.SSAEvent` (no `.ass` files on disk) cover
  dialogue/karaoke/credits false positives. A false-positive inventory is
  written under `docs/beta-feedback/`. Not wired into the merge path.
- [S-21] Close the osv-scanner/`pyproject.toml` extractor gap as a tracked,
  documented workaround: file/track the procoder issue, record the decision on
  whether the gate should scan `uv.lock` directly, and document the
  machine-local `~/.local/bin/osv-scanner` shim in `AGENTS.md` as host-local
  only, never a repo-portable fix.
- [S-22] Release 0.2.0: bump `pyproject.toml`'s version, finalize the
  `CHANGELOG.md` `0.2.0` section with a date, run `procoder release 0.2.0`
  clean, and print (never execute) the tag command. Verified on representative
  media selected for this purpose, not on the already-completed beta rollout
  as evidence.

## Out of scope

Verbatim from the reviewed weekly-cycle note's "Beyond v0.2.0 / visible
backlog — not this week's commitment":

- Web UI dashboard expansion, glossary editor, community glossary
  auto-fetch/push.
- Full decoder/config fingerprint migration if not taken as item 4 this week.
- Full cross-host locking/claim mechanism beyond the current "never run two
  workers" operational rule.
- Full ASS coordinate transformation for mismatched `PlayResX`/`PlayResY`; the
  current timing/signs work only warns.
- Card splitting as a broader automatic feature; current `card_split.py` is
  deliberately limited to human corrections.
- Automatic subtitle-repository reopen sweep; beta design explicitly chose
  manual reopen.
- Full CI/workflow consolidation if current GitHub beta workflows are green;
  do not relitigate launch mechanics unless a concrete failure is found.
- V1/V2 polish backlog items such as style-collision logs, WrapStyle audit,
  font MIME warnings, `mux.partners()` optimization, extra data-file
  extraction, and broad observability polish unless promoted by evidence from
  this week's post-beta checks.
- Timing-compare draft PR/push bookkeeping remains a branch-specific close
  task, not implementation work. Correction: neither `a1-reflow-timing` nor
  `timing-compare` exists as a branch name (`git branch -a` confirmed) — the
  actual unmerged commits (T1–T11) live on branch `dubtitlerr`. Verify against
  that branch, not the names above, before carrying this forward.

## Constraints

- Tests: `python3 -m pytest` (pyproject sets `-q` and testpaths). CI installs
  only `pytest pysubs2 jellyfish`; `faster_whisper` is stubbed in
  `tests/test_generate.py`, `webrtcvad` monkeypatched in `tests/test_vad.py`.
  New tests must not need anything else.
- `ruff check .` must be clean (config in pyproject). `procoder check` gate
  blocks on lint, a red suite, AI-attribution trailers, and unanswered
  `.procoder/ask/QA.md` questions.
- Sidecar writes: temp file + `os.replace`, mode `common.SIDECAR_MODE`, path
  through `common.out_for()`; existence checks on the raw path. Stale
  sidecars are parked (`.stale`), never deleted.
- `TRANSCRIBE_VERSION = 4` and `TEXT_VERSION = 11` stay unless a task says
  otherwise; a TRANSCRIBE bump re-transcribes the library on GPU and is wrong
  here.
- Never start the production worker to test; use fixtures. Any diagnostic
  `docker run` against the pipeline image passes `--entrypoint`
  (`container_run.sh` ignores a trailing cmd).
- No library-wide sweep until sprint 011 and 012 have shipped.
- Commit subjects: conventional `type(scope): subject`, present tense, ≤ 72
  chars.

## Interfaces

Stage status (sprint 011 produces; 012/013 consume):

- `common.STAGES_SUFFIX = ".dubtitles.stages.json"`
- `common.STAGE_OUTCOMES = ("ok", "no-reference", "llm-empty",
"backend-unreachable", "extract-error", "build-error", "no-video", "timeout",
"crashed", "unwritable")`
- `common.write_stage(stem: str, stage: str, outcome: str, detail: str = "") ->
None` where `stage ∈ {"repair", "signs", "mux"}`; merges into the
  per-episode JSON `{"<stage>": {"outcome": ..., "detail": ..., "at": <unix
float>}}`.
- `common.read_stages(stem: str) -> dict` (empty dict when absent/unreadable).
- `common.failed_stage(stem: str) -> str | None` — first stage whose outcome
  is not in `{"ok", "no-reference", "no-video"}`.
- `merge_pass.sh` captures `rc=$?` after each stage invocation; `rc != 0` with
  no stage record → `write_stage(..., "crashed", "rc=<n>")` via `python3 -c`;
  prints `MERGE PASS COMPLETE` only when no episode has a failed stage, else
  `MERGE PASS INCOMPLETE: <n> episodes with a failed stage`.
- `mux.py` MP4 path order becomes: verify → `_finalize` → `write_stamp(final)`
  → `os.remove(orig)`. If `write_stamp` raises: remove `final`, keep `orig`,
  `write_stage("mux", "unwritable")`, return without stamping.

Decoder identity (sprint 012):

- `common.WORDS_SCHEMA_VERSION` → `2`.
- `words.json` gains `"compute_type": <str>` and `"beam_size": <int>`.
- `generate.decoder_identity() -> dict` returns `{"model": MODEL,
"initial_prompt": INITIAL_PROMPT, "compute_type": COMPUTE, "beam_size":
int(os.environ.get("WHISPER_BEAM_SIZE", "7"))}`.
- `common.read_words(stem, rec=None, expect: dict | None = None)`: a field
  recorded AND differing → `words_config_mismatch`, returns `None`; a field
  absent or `""` → `words_config_unknown`, still returned. A
  `transcribe_version` greater than current → `words_version_mismatch`.

Review server (sprint 010 task changes `auth_required`; sprint 013 the rest):

- `auth_required()`: an EMPTY `REVIEW_TOKEN` is unset (token generated); auth
  disabled only by `REVIEW_AUTH=off`. `REQUIRE_TOKEN=1` makes `serve()` exit
  status 2 before binding.
- `authorised(method, presented)`: GET/HEAD on `/api/*` require the token
  (401 `{"error": "a token is required"}`); `presented` is the
  `X-Review-Token` header or, failing that, the `dubtitlerr_token` cookie
  (`_cookie_token(headers)`). `/`, `/index.html`, `/shared` render
  `render_locked(page_kind)` (token box only) when `authorised` is False;
  `/healthz` is never gated.
- `GET /healthz` → 200 `{"ok": true, ...}` or 503 `{"ok": false, "reasons":
[...]}` from `common.read_heartbeat()`; never includes filesystem paths.
- `common.HEARTBEAT_PATH = os.environ.get("HEARTBEAT_PATH",
"/config/heartbeat.json")`, `common.heartbeat(**fields) -> None` (atomic
  merge-write), `common.read_heartbeat() -> dict`. Fields:
  `last_sweep_start`, `last_sweep_end`, `last_success_stem_name` (basename
  only), `considered`, `changed`, `failed`, `held`, `last_error`,
  `roots_readable: bool`, `order_file_present: bool`.
- Stale rule for `/healthz`: 503 when `now - last_sweep_end > 3 *
RESCAN_INTERVAL` (env, default 21600) or `roots_readable` is false or
  `order_file_present` is false.
- `Dockerfile.builder`: `HEALTHCHECK --interval=5m --timeout=10s
--start-period=10m --retries=3 CMD python3 -c
"import urllib.request,sys; sys.exit(0 if
urllib.request.urlopen('http://127.0.0.1:8842/healthz',
timeout=5).status==200 else 1)"`.

Timing compare (sprint 014): report path
`docs/timing-compare/<YYYY-MM-DD>-phase0-report.json` plus
`docs/timing-compare/<YYYY-MM-DD>-phase0-go-no-go.md`. T1–T11 are already on
`main` and this branch; only T12 is open.

S&S prototype (sprint 014): `tools/sns_extract.py` read-only, imports
`dub_signs_merge.keep_event` and adds `off_default_position(ev, play_res_y)`;
fixtures built programmatically with `pysubs2.SSAEvent`.

## Data

`<stem>.dubtitles.stages.json` (S-6), one file per episode, merge-written:

    {
      "repair": {"outcome": "ok", "detail": "", "at": 1758470400.12},
      "signs":  {"outcome": "build-error", "detail": "mkvextract rc=1", "at": 1758470401.02},
      "mux":    {"outcome": "unwritable", "detail": "OSError: ...", "at": 1758470402.55}
    }

`<stem>.dubtitles.words.json` schema 2 (S-10), additive to the existing shape
(`transcribe_version`, `model`, `initial_prompt`, `audio_duration`,
`segments`, `words`, per `v5-two-tier-idempotency`'s spec):

    {
      "schema_version": 2,
      "transcribe_version": 4,
      "model": "large-v3-turbo",
      "initial_prompt": "<the exact string passed to whisper>",
      "compute_type": "int8",
      "beam_size": 7,
      "audio_duration": 1421.32,
      "segments": [...],
      "words": [...]
    }

`HEARTBEAT_PATH` (default `/config/heartbeat.json`), single JSON object,
merge-written atomically (S-16):

    {
      "last_sweep_start": 1758470000.0,
      "last_sweep_end": 1758470400.0,
      "last_success_stem_name": "S01E01",
      "considered": 42,
      "changed": 3,
      "failed": 0,
      "held": 1,
      "last_error": "",
      "roots_readable": true,
      "order_file_present": true
    }

`docs/timing-compare/<date>-phase0-report.json` and the paired
`-go-no-go.md` (S-17): per-show offset/drift/`in_gap_vad_error` numbers plus a
written go/no-go decision — shape is whatever `tools/timing_compare.py`
already emits; this spec does not change that shape, only runs it on 3 real
shows.

## Edge cases

- A `.dubtitles.done` stamp written by current code carries an OPTIONAL
  `stages` field that nothing reads (`common.write_stamp`, `common.py:258-290`,
  `"stages": doc["stages"] = stages` only if truthy). S-6's new
  `.dubtitles.stages.json` sidecar is a SEPARATE artifact from this stamp
  field — `read_stages`/`failed_stage` must not confuse the two, and the old
  stamp field is left alone (still additive/optional, still ignored by
  `stamp_valid`) so no existing stamp reads as stale.
- `merge_pass.sh`'s per-stem work runs inside `... | while IFS= read -r stem;
do ... done` (`merge_pass.sh:48-60`) — a pipe into `while` runs the loop
  body in a SUBSHELL under `/bin/sh`. A counter incremented inside the loop
  (e.g. "how many stems failed") does not survive past `done`. S-7's
  `MERGE PASS COMPLETE`/`INCOMPLETE` decision must therefore be computed by a
  fresh scan for failed stages AFTER the loop exits, never from a shell
  variable set inside it.
- `dub_signs_merge.py`'s `"no-video"` (`dub_signs_merge.py:292`) and
  `"build-error"` (`:297`) returns are plain strings with no `raise` — the
  caller (`merge_pass.sh`) currently does nothing with them at all, so a
  build-error today reads identically to success. `mux.py`'s `sub_source()`
  (`mux.py:403-409`) then falls back from `.ass` to `.srt` with no way to tell
  "no signs ever existed" from "the signs build just failed" — the exact case
  S-8 closes.
- `generate.write_words()` (`generate.py:378-407`) writes `"model":
os.environ.get("WHISPER_MODEL", "")` directly from the environment,
  independent of the already-resolved `MODEL` constant
  (`generate.py:104`, default `"large-v3-turbo"`). A sidecar written while
  `WHISPER_MODEL` was unset in the environment therefore records `model=""`
  even though transcription actually ran on the default model — S-10's
  `read_words(expect=...)` must treat this as `words_config_unknown`, not
  `words_config_mismatch`, or all 366 live sidecars would suddenly fail
  validation against a field that was never wrong, only unrecorded.
- `common.read_words()` (`common.py:223-255`) already treats a truncated or
  unparseable `words.json` as absent (`except (OSError, ValueError):` at
  line 235, counted `words_missing`) — S-10 must preserve that path exactly
  and add the `expect=` comparison only on a document that DID parse.
- `mux.py process()` (`mux.py:431-494`) currently removes `orig`
  (`:465`) BEFORE `write_stamp` (`:467`); the existing `except OSError`
  around the stamp write (`:469-479`) already returns `"stamp-write-failed"`,
  but by then `orig` is already gone — today's "retryable" state is not
  actually retryable for an MP4/M4V source once the stamp write fails. S-9
  must close this window by reordering, not by adding a bigger except clause.
- `review_server.authorised()` (`review_server.py:212-215`) currently returns
  `True` unconditionally for GET/HEAD before even checking `auth_required()`.
  S-14's path-prefix check must apply BEFORE that early return, or the new
  gate is dead code exactly like the old `stages` stamp field.
- `review_server.auth_required()` (`review_server.py:138-140`) currently
  returns `False` only when `"REVIEW_TOKEN" in os.environ and
os.environ["REVIEW_TOKEN"] == ""` — the exact shape `compose.yaml`'s
  `REVIEW_TOKEN: ${REVIEW_TOKEN:-}` produces when an operator follows the
  documented `cp .env.example .env` without setting the variable. S-2's fix
  must change this predicate itself, not just the Compose file, or a future
  install path can reproduce the same silent-disable.
- `review_server.serve()` (`review_server.py:1255-1263`) has no
  `REQUIRE_TOKEN` check at all today — it resolves/announces the token and
  binds unconditionally. S-14's hard-exit must run BEFORE
  `BoundedHTTPServer(...)` is constructed, or a caller relying on
  `REQUIRE_TOKEN=1` to guarantee auth would still get a running, unauthenticated
  server for the fraction of a second (or indefinitely, if binding never
  raises) between construction and the check.

## Failure modes

- **`write_stage` write fails** (unwritable `.dubtitles.stages.json`, e.g. a
  read-only mount). The stage's own outcome (repair/signs/mux) has already
  happened; losing the record must not abort that stage's own work, but
  `failed_stage()` reading a missing/corrupt sidecar must treat it as "cannot
  confirm success" (fail closed toward `MERGE PASS INCOMPLETE`), never as "ok"
  by omission.
- **Transport failure to the LLM backend during repair**
  (`repair.py`'s `LLM_UNREACHABLE` path, `repair.py:853-867`, and the
  all-unreachable episode refusal at `:1060-1067`). Already partly guarded
  (the episode-level refusal exists), but nothing today writes a stage record
  distinguishing this from a real empty LLM reply — S-6 requires
  `write_stage(stem, "repair", "backend-unreachable")` on this path so a
  future outage is visible as "backend down" in the stage artifact, not
  mixed into `llm_empty` counts the way the prior ~1,300-entry outage was.
- **`mux.py` write-stamp fails after the reorder (S-9).** The mkv (`final`)
  already exists and passed `verify()`, but nothing durable records it as
  done. The new order removes `final` and keeps `orig`, so the NEXT sweep
  sees an untouched original and simply retries the whole mux — costly
  (re-runs mkvmerge) but lossless, which is the tradeoff this spec accepts
  over the current lossy failure.
- **`merge_pass.sh` itself crashes mid-loop** (container OOM-killed, host
  reboot). Because the loop is a subshell reading from a pipe
  (`merge_pass.sh:48-60`), a killed process leaves no in-memory counters to
  lose — the next run's fresh filesystem scan for failed stages (S-7) is
  unaffected by exactly how the previous run died.
- **`common.heartbeat()` write fails** (unwritable `/config`). `/healthz`
  must report 503 via the stale-heartbeat rule rather than raise inside the
  handler — a broken heartbeat write is itself a liveness failure worth
  surfacing, not a crash to hide from the healthcheck.
- **`osv-scanner` silently zero-scans `pyproject.toml`.** Already true today
  (no extractor for it in 2.5.1) — a security review that treats "osv-scanner
  ran" as "dependencies were checked" is currently wrong. S-21's ledger entry
  exists precisely because this failure mode produces a clean-looking report
  with zero actual coverage.
- **`decisions.locked()` is advisory, not mandatory** (`decisions.py:266-283`
  docstring). A one-off script writing the 4 S31 verdicts (S-11) without
  going through `decisions.locked()` + `decisions.save()` could race
  `review_server.py`'s own writer and silently lose a verdict — the scope
  item requires the locked path specifically, not a direct file write.
- **API gating ships without page gating (S-14 sequencing).** The pages
  build their data in-process from the same handlers, so gating `/api/*`
  alone leaves every stem and repair text readable at `/` — the cookie
  gating of the rendered pages and the API gating must land in the same
  release, and S-15's real-socket test is what catches a partial rollout.

## Acceptance criteria

- [ ] [S-1] `ruff check tests/test_gen_loop_set_e.py` prints "All checks
      passed!" (today it reports I001 at line 21 and W292 at line 144).
- [ ] [S-1] `git merge-base --is-ancestor github/main HEAD` succeeds and
      `git log --oneline` on the branch contains `7e3d106` and `1e8eaaa`; the
      branch is pushed to the `github` remote and `gh run list --repo
XenaRathon/DubTitlerr --branch fix/published-episode-titles --limit 1`
      shows conclusion `success`; after the owner merges the PR, the same
      command with `--branch main` shows `success`.
- [ ] [S-1] `python3 -m pytest tests/test_review_apply.py -q` passes,
      including `test_a_rejection_reopens_because_it_reverts_a_repair_that_already_shipped`.
- [ ] [S-2] `git ls-files compose.yaml .env.example` lists both (currently
      untracked).
- [ ] [S-2] With `REVIEW_TOKEN=""` set (the Compose-default shape),
      `review_server.auth_required()` returns `True` (auth still required);
      only `REVIEW_AUTH=off` in the environment makes it return `False` —
      asserted directly against the function, not just the compose file.
- [ ] [S-2] `README.md`'s review-server section and `SECURITY.md` both contain
      the string `REVIEW_AUTH=off` describing it as the only way to disable
      auth.
- [ ] [S-3] `git status --porcelain` shows no untracked entry for
      `.craftsman-baseline.json` or `.lycheecache`; `docs/agents/`,
      `docs/beta-feedback/`, `docs/promo/`, `.procoder/github/LESSONS.md`, and
      `ISSUE-s32e02-timing.md` are tracked; `git stash list` is empty.
- [ ] [S-4] A vault note exists (`Homelab/Projects/DubTitlerr/<date> Production
Snapshot.md`) recording `docker ps` output from vm102, fasc, and 3200g;
      the deployed `REPAIR_UNANCHORED` value; per-show `unanchored_repair`
      opt-ins found (if any); the review bind/token/`REVIEW_AUTH` posture; a
      diff between the live order file and `watch_queue.py --dry-run`; the
      publish timer's status; and the stopped 3200g `dubtitle-builder`
      container's classification.
- [ ] [S-5] `CHANGELOG.md` contains a `## 0.2.0 - Unreleased` heading
      listing every S-id in this spec as included and the "Beyond v0.2.0"
      items as explicitly deferred.
- [ ] [S-6] `common.write_stage(stem, "repair", "ok")` then
      `common.read_stages(stem)` returns `{"repair": {"outcome": "ok",
"detail": "", "at": <float>}}`; a second `write_stage` call for a
      different stage merges rather than overwrites the first.
- [ ] [S-6] `common.failed_stage(stem)` returns `None` when every recorded
      outcome is in `{"ok", "no-reference", "no-video"}`, and returns the
      first offending stage name otherwise.
- [ ] [S-6] Fixture runs of `repair.py`, `dub_signs_merge.py`, and `mux.py`
      that force `extract-error`/`build-error`/`crashed`/`timeout`/
      `unwritable` each leave a matching entry in
      `<stem>.dubtitles.stages.json` — checked by reading the sidecar, not
      just the function's return string.
- [ ] [S-6] A forced `LLM_UNREACHABLE` path in `repair.py` (`repair.py:853`)
      results in `write_stage(stem, "repair", "backend-unreachable")`, never
      `"llm-empty"` — a test asserts the two outcomes are never produced by
      the same code path.
- [ ] [S-7] `merge_pass.sh` captures `rc=$?` immediately after each of the
      three `python3` invocations (repair.py, dub_signs_merge.py, mux.py) and
      writes a `"crashed"` stage record via `python3 -c` when `rc != 0` and no
      stage record exists for that stem.
- [ ] [S-7] With two fixture episodes, one forced to a failed stage, the
      script prints `MERGE PASS INCOMPLETE: 1 episodes with a failed stage`;
      the incomplete count is computed by scanning `.dubtitles.stages.json`
      files after the loop exits, not from a variable set inside the
      pipe-subshell loop (`merge_pass.sh:48-60`).
- [ ] [S-7] With zero failed stages, the script prints exactly `MERGE PASS
COMPLETE`.
- [ ] [S-8] Given a prior `.ass` sidecar containing at least one non-dialogue
      (signs) event, a forced `dub_signs_merge.py` failure (`"build-error"` or
      `"no-video"`) makes `mux.process()` refuse to mux the dialogue-only
      `.srt` and return a distinct non-muxing status instead of stamping the
      demoted output as done.
- [ ] [S-8] A genuinely signs-free episode (no prior `.ass`,
      `dub_signs_merge.py` returns `"no-signs"`) mux proceeds normally under
      the identical forced-failure test harness — the two fixtures produce
      different mux outcomes.
- [ ] [S-9] For an MP4/M4V source with a monkeypatched `write_stamp` that
      raises `OSError`, `final` (the new mkv) is removed and `orig` still
      exists on disk afterward; the return value signals a retryable state
      distinct from today's `"stamp-write-failed"`-with-`orig`-already-gone.
- [ ] [S-9] An MKV source (`orig == final`) never calls `os.remove` on the
      original, asserted by a fixture where `orig` and `final` are the same
      path.
- [ ] [S-9] `README.md` states the original MP4/M4V container is deleted only
      after a verified, stamped remux.
- [ ] [S-9] Two new tests pass: one with an unwritable stamp path, one
      simulating an interruption between `_finalize` and `write_stamp` —
      both assert either `orig` or a validly stamped `final` survives, never
      neither.
- [ ] [S-10] `common.WORDS_SCHEMA_VERSION == 2`; a freshly written
      `words.json` contains `compute_type` and `beam_size` alongside the
      existing schema-1 fields.
- [ ] [S-10] `generate.decoder_identity()` returns `{"model": MODEL,
"initial_prompt": INITIAL_PROMPT, "compute_type": COMPUTE,
"beam_size": int(os.environ.get("WHISPER_BEAM_SIZE", "7"))}`, asserted
      field-by-field against the module's live globals.
- [ ] [S-10] `common.read_words(stem, expect=generate.decoder_identity())`
      returns `None` and increments `words_config_mismatch` when a recorded
      field differs; returns the doc and increments `words_config_unknown`
      when a field is absent or `""` (including the `model=""` schema-1 case);
      neither path raises.
- [ ] [S-10] A `words.json` with `transcribe_version` greater than
      `common.TRANSCRIBE_VERSION` increments `words_version_mismatch` and
      returns `None` (new test for already-existing behavior).
- [ ] [S-10] `common.py`'s stamp docstring documents same-size/same-mtime
      replacement as the accepted immutable-media assumption (owner decision
      — recommended default, confirm at sprint 010 open).
- [ ] [S-11] `decisions.load()` for the relevant One Pace show shows all 45
      S31 lines with a recorded verdict (currently 41 of 45); the 4 new
      entries were written under `decisions.locked(show, dir)` +
      `decisions.save(...)` returning `True`.
- [ ] [S-11] `handoff.md:183-185` is marked superseded in place, dated.
- [ ] [S-11] `docs/wiki/How-To-Guides.md:44` and `Reference.md:106` no longer
      contradict `common.py:167`'s confirmed deployed state; both point at
      the single vault operator note (owner decision — recommended default:
      keep the global flag; confirm at sprint 010 open).
- [ ] [S-12] `ISSUE-phonetic-name-guard.md` has a status header naming
      `repair.invents_name()` and `repair.substitutes_a_vouched_name()`
      (`PHONETIC_MIN=0.75`) as the shipped resolution; no new fixture file is
      added for this item.
- [ ] [S-13] `IMPROVEMENTS.md` §5 ("Architecture: Two-Backend Repair") is
      absent from the file; `REVIEW.md:1025-1029` and `:1099` state
      `REPAIR_BACKEND_SECONDARY` is retired, not "not yet implemented" (owner
      decision — recommended default: retire; confirm at sprint 010 open).
- [ ] [S-14] `review_server.authorised("GET", None)` returns `False` for a
      path starting with `/api/` and `True` for `/`, `/index.html`,
      `/shared`, `/healthz`.
- [ ] [S-14] With `REQUIRE_TOKEN=1` and `REVIEW_AUTH=off` both set,
      `review_server.serve()` exits with status 2 and logs the exact message
      before `BoundedHTTPServer(...)` is ever constructed (asserted by
      mocking the constructor and confirming it is never called).
- [ ] [S-14] The token box JS sets a `dubtitlerr_token` cookie next to the
      localStorage write; `GET /` and `GET /shared` with no header and no
      cookie return 200 with `needs-token` in the body and no stem from a
      monkeypatched `known_stems`; with the cookie they render the full page.
- [ ] [S-14] `SECURITY.md`'s review-server section matches the new GET-gating
      behavior and states the `0.0.0.0` bind is a deliberate choice (owner
      decision, confirm at sprint 010 open).
- [ ] [S-15] A test starts `review_server` on port 0 in a background thread
      (real socket): `GET /api/episodes` with no token → 401; with the
      correct token → 200.
- [ ] [S-15] A client that stalls its body write is disconnected at
      `Handler.timeout`, asserted by wall-clock bound in the test.
- [ ] [S-15] Opening `MAX_CONCURRENT + 1` simultaneous connections results in
      the extra connection being closed by the server rather than queued
      indefinitely.
- [ ] [S-16] `common.heartbeat(...)` writes `common.HEARTBEAT_PATH`
      atomically; `common.read_heartbeat()` returns the same fields back.
- [ ] [S-16] `GET /healthz` returns 503 independently for each of: a stale
      `last_sweep_end` (> `3 * RESCAN_INTERVAL`), `roots_readable=False`, and
      `order_file_present=False`; returns 200 otherwise; the response body
      never contains a filesystem path.
- [ ] [S-16] `Dockerfile.builder` contains the exact `HEALTHCHECK` instruction
      targeting `127.0.0.1:8842/healthz`.
- [ ] [S-16] The autoheal-actuator question is recorded as a live-host-only
      finding in the S-4 vault note, with no repo change attempted for it.
- [ ] [S-17] `tools/timing_compare.py` produces
      `docs/timing-compare/<date>-phase0-report.json` and
      `docs/timing-compare/<date>-phase0-go-no-go.md` for 3 named shows (one
      fansub dialogue, one signs-only, one One Pace); `in_gap_vad_error` is a
      separate field from offset/drift; no gate is wired into any script as a
      result.
- [ ] [S-17] `specs/timing-compare/tasks.md` shows T1–T11 checked and no
      longer references the nonexistent `feat/timing-compare` branch.
- [ ] [S-18] A vault note records `systemd-analyze verify` output, the
      publish timer's live status, a diff between the deployed order file and
      `watch_queue.py --dry-run`, and confirmation of the manifest/title
      policy.
- [ ] [S-19] A vault note records the confirmed single active worker host,
      mergerfs `pfrd` persistence status, the `sdc1` writer finding, and
      `llama-embed`'s confirmed presence on the 1050 Ti via `nvidia-smi`
      output.
- [ ] [S-19] `python3 -c "import generate; assert generate.FFMPEG_TIMEOUT ==
1800"` passes with `FFMPEG_TIMEOUT` unset in the environment; the
      README/Reference table and `generate.py:32-33`'s comment both state the
      new default.
- [ ] [S-20] `tools/sns_extract.py` exists, imports only
      `dub_signs_merge.keep_event` from the pipeline, and implements
      `off_default_position(ev, play_res_y)`.
- [ ] [S-20] Programmatic `pysubs2.SSAEvent` fixtures covering a genuine
      off-position sign, a karaoke event, a credits event, and a plain
      dialogue event produce the expected true/false-positive classification
      in a test.
- [ ] [S-20] A false-positive inventory file exists under
      `docs/beta-feedback/`; `grep -rn sns_extract merge_pass.sh mux.py
dub_signs_merge.py` returns no matches (not wired into the merge path).
- [ ] [S-21] A tracked issue (GitHub issue or `.procoder/backlog` entry)
      records the osv-scanner/`pyproject.toml` extractor gap, with a recorded
      decision on scanning `uv.lock` directly.
- [ ] [S-21] `AGENTS.md` documents the `~/.local/bin/osv-scanner` shim as
      host-local only.
- [ ] [S-22] `pyproject.toml`'s `version` field reads `"0.2.0"`.
- [ ] [S-22] `CHANGELOG.md`'s `0.2.0` section carries a release date and the
      full included-item list.
- [ ] [S-22] `procoder release 0.2.0` completes clean (version sync,
      changelog, clean tree, gate, suite all pass) and prints the tag command
      without executing it.
- [ ] [S-22] The release note records verification against representative
      media selected for this purpose (cross-referenced to S-17's 3 shows),
      not the beta rollout, as evidence.
- [ ] `procoder check` is clean and the full suite passes on the synced,
      committed tree at release time.

## Open questions
