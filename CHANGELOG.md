# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). This file starts at
the public beta. `TRANSCRIBE_VERSION`/`TEXT_VERSION` in `common.py` are the pipeline's own
version history (they say what changed in the _output_, and only a stamp bump puts the fix into
already-processed files); the entries below summarize that history alongside everything else
that shipped since.

## [Unreleased]

## 0.2.2 - 2026-10-08

Hardening pass from a whole-repository review of `main`: no failed stage is muxed and stamped as done any
more, no failure path deletes the only copy of an episode, and the nightly `docker stop` no longer kills the
container mid-transcription. 0.2.1 was prepared (its entry is below) but never tagged or published; everything
in it ships in this release. Every change below was written test first and has run in production.

### Fixed

- The container now exits softly on SIGTERM. `container_run.sh` stays as a supervisor instead of handing PID 1 to a bare `sh`, which ignored the signal: on `docker stop` it only raises a stop flag, the generate, merge and review loops start no new episode, the one in flight finishes, and the container exits 0. Before, the container kept starting new episodes for the whole stop grace period and was then killed mid-transcription.
- That nightly kill used to poison episodes: a transcription killed part-way leaves a permanent `.dubtitles.fail` marker and the episode is skipped forever (seven were affected). The stop flag is only ever read between episodes, so no marker is written by a stop. A stop also skips the per-show MINE, ACQUIRE and VERIFY steps that have not started yet, and a merge pass cut short by a stop now says `MERGE PASS STOPPED` instead of `COMPLETE`.
- `mux.py`: a failed stamp write on an `.mkv` episode deleted the only copy of the episode
  (the rollback removed the freshly replaced file, which was also the original). The stamp
  is now written from the temp file before it replaces the episode, so a stamp failure
  leaves the original untouched and the next sweep retries. A stamp is only removed again
  if the rename into place did not complete.
- `mux.py`: when the cross-device copy in `_finalize` fails partway, the complete temp
  output is kept as `<episode>.muxtmp.mkv.recovered` (not deleted, and not touched by later
  sweeps) and mux writes `<episode>.dubtitles.mux-recovery`. It then refuses to re-mux that
  episode (`recovery-pending`; the stage stays `crashed`, so the pass reports INCOMPLETE)
  until a human restores the kept file over the episode and deletes the marker. A plain
  rename failure (for example a permission error) does NOT trigger this: nothing was
  copied, so the stamp and temp output are removed and the next sweep retries.
- `mux.py`: known remaining limitation (tracked separately): the cross-device fallback
  still overwrites the original in place.
- `mux.py`: failures in the post-stamp cleanup (removing the old mp4 link, writing
  `.dubtitles.mux.log`) no longer record the episode as `crashed`. The episode is already
  muxed and stamped, and the next sweep returns `already-muxed` before any stage write, so
  the bogus record was never cleared and `merge_pass.sh` reported MERGE PASS INCOMPLETE
  forever. Cleanup errors now log a warning and the stage records `ok`.
- Changelog: the 0.2.1 entry for `merge_pass.sh` wrongly says the episode stem is passed
  via an environment variable; it is actually passed as argv (`sys.argv[1]`, `sys.argv[2]`).
- `merge_pass.sh` no longer runs mux after a failed repair or a failed signs step. The
  episode is skipped with a `skip mux: ... failed (<outcome>)` line and retried next pass.
  Records from older runs are cleared before repair and before mux, and an episode that
  already has its `.ass` is muxed as before whatever old records say.
- A refused repair (it would have overwritten repairs already shipped with raw ASR) is now
  recorded as `refused`, which counts as a failure, instead of the passing `no-reference`.
- A missing `conf.json` (or `.srt`) is no longer recorded as `no-video`. It is recorded as
  `ok` with detail `no-conf` / `no-srt`; `no-video` now means there is no video.
- A failed signs build no longer leaves an `.ass` behind for `merge_pass.sh` to trust and mux
  to prefer. The build goes to `<episode>.eng.dubtitles.ass.part` and replaces the `.ass`
  only when it succeeds, so a good earlier `.ass` also survives a failed rebuild. If every
  English subtitle stream fails to extract, signs is now `build-error` / `extract-failed`
  instead of "no signs".
- A broken failed-stage scan at the end of `merge_pass.sh` no longer prints `MERGE PASS
  COMPLETE`. It prints `MERGE PASS INCOMPLETE: failed-stage scan error`. Counts from several
  scan batches are now added up instead of breaking the comparison.
- `common.failed_stage` reads stages in pipeline order (repair, signs, mux) as its docstring
  says, not in file order, and takes an optional `only=` list of stages.
- The `.dubtitles.done` stamp and repair's `.srt`, audit `.csv` and summary `.json` are now
  written through a temp file and renamed into place (`common.atomic_write`, shared with
  `generate.py`). A crash mid-write no longer truncates the previous stamp, which used to
  trigger a re-mux of the episode on every sweep, or the shipped `.srt`.
- A failing ffmpeg no longer produces a truncated transcription: `extract_wav` now checks the
  exit code, deletes the partial wav and reports `extract-failed`, so the episode is retried
  instead of getting subtitles for only part of the audio.
- The publish unit (`deploy/dubtitlerr-publish.service`) no longer puts the GitHub token on
  the docker command line, where `ps`, the journal and `systemctl status` showed it. It now
  passes `-e GITHUB_USER -e GITHUB_PAT` without values. Copying the unit to the host is a
  manual step.
- `merge_pass.sh` no longer runs mux when repair or signs crashed and the crash record could
  not be written either (for example an unwritable stage file): that stem is skipped as
  `<stage> crashed (no record)`. A crash after a stage already recorded `ok` does not block it.
- A stale `<episode>.eng.dubtitles.ass.part` (left if the pipeline was killed while installing
  the signs file) is now removed when the episode is muxed.

### Added

- `deploy/dubtitlerr-window-{open,close}.{service,timer}`: the nightly window units, until now only on the
  host, with `tests/test_deploy_units.py`, which parses them, unescapes the `ExecStart` lines the way systemd
  does and runs the muxtmp sweep against a fake library. The close unit stops the container with
  `docker stop -t 900` (the soft exit needs the grace period to cover the longest single episode or mux),
  logs the container's exit code (0 is a soft exit, 137 is a SIGKILL) and its sweep skips any stem that has a
  `.dubtitles.mux-recovery` marker. Copy the units to `/etc/systemd/system/` and run `systemctl daemon-reload`;
  raise the stop grace only together with this release's image, because an older image ignores SIGTERM and
  would simply keep working for the longer grace.

## 0.2.1 - 2026-09-24

Release-integrity and fail-closed hardening driven by the v0.2.0 adversarial release review
(findings B1–B9; the original review file is missing — a labeled reconstruction plus a
post-review evidence log in `docs/Adversarial Reviews/` document the findings and this
remediation).

### Fixed

- `mux.py`: every failure exit path now writes a real stage record using an outcome from
  `common.STAGE_OUTCOMES`. Mux verification failures record `build-error` with a
  `verify:<reason>` detail, signs-regression refusals are recorded as a visible failure
  instead of a silent return, and unexpected exceptions record a sanitized `crashed`
  detail. Previously these paths wrote no record (or an invalid one), so `failed_stage()`
  could not see the failure and the episode could look current.
- `merge_pass.sh`: the crash-classification fallbacks receive the episode stem via an
  environment variable instead of inline `'$stem'` interpolation — stems containing
  apostrophes (e.g. `JoJo's Bizarre Adventure`) no longer raise `SyntaxError` or write
  bogus crash records.

### Changed

- `release.yml`: image build/push is gated behind a reusable `ci-gate` workflow that
  re-runs the CI matrix for the tagged commit and skips the image job on any red
  conclusion — image push cannot follow failed CI (proven on a disposable failed-tag
  run, see Verification).
- `uv.lock` resynced to the `pyproject.toml` version; the sprint-015 retro carries a
  dated correction (the upstream `azrtydxb/procoder#301` issue now exists); stale
  CHANGELOG sentences and test docstrings fixed.

### Verification

Sanitized evidence recorded 2026-09-24/25 (no secrets; no live mutation accompanied it):

- **CI gate proof (release integrity):** a disposable failed-tag run (temporary branch
  and annotated tag, both deleted afterwards) went red on the Python 3.11/3.13 tests
  while lint and osv-scan passed, and the image job was **skipped** as designed. No
  image build/push or release publication followed the red CI conclusion. The public
  `v0.2.0` tag was not moved.
- **Deployment host, read-only audit:** the worker container runs
  `dubtitle-builder:0.1.3` while the deployed publish service pins `0.1.0` — a pin
  mismatch is observed, its causal effect unproven, and alignment is tracked separately.
  Representative media (One Pace S33, sampled 5 of 39 episodes) all carry nonempty
  `.done` stamps and mux logs with no fail stamps, exactly one default SubRip
  `Dubtitles` stream each, no external subtitle sidecars, and the sampled episodes
  decoded cleanly with hundreds of positive subtitle packets and none empty. A full
  39-file sweep is not proven; conclusions are limited to the sample.
- **Known open item:** the owner-reported playback symptom (One Pace S33 dubtitle tracks
  render nothing) is **not root-caused**. Ranked hypotheses and the smallest safe next
  diagnostic (a bounded read-only probe on the actual player/server host) are recorded
  in the homelab documentation vault; no causation is claimed.

## 0.2.0 - 2026-09-23

Scope boundary for the v0.2.0 hardening pass, set 2026-09-21. The scope ids S-1 through
S-22 are defined in `.procoder/specs/v0-2-0-hardening.md`; the tasks that deliver them are
in `.procoder/plans/v0-2-0-hardening.md` (sprints 010-015).

### Included

- S-1 through S-5 (sprint 010, Ground truth): get main's CI green again (ruff check . was
  failing on tests/test_gen_loop_set_e.py since 2026-09-05); commit compose.yaml and
  .env.example for the first time and fix the review server's auth default so an empty
  REVIEW_TOKEN no longer silently disables auth; clear the untracked/modified hygiene
  ledger; take a read-only production snapshot; this scope declaration.
- S-6 through S-9 (sprint 011, Fail closed): a durable per-episode stage-status artifact
  with typed outcomes so a failed repair/signs/mux stage can never produce a
  current-looking .done stamp; merge_pass.sh captures and classifies exit codes; a
  transient signs-extraction failure is distinguished from a genuinely signs-free episode;
  the MP4-to-MKV conversion's stamp-before-remove ordering gets crash/failure tests and a
  documented recovery policy.
- S-10 through S-13 (sprint 012, Provenance and policy): words.json schema v2 persists
  compute_type and beam_size and read_words() compares model/initial_prompt/compute_type/
  beam_size against the current config, counting mismatches instead of only checking
  transcribe_version (S-10); the unanchored-repair rollout is reconciled against the
  3-episode human review that justified it, including the 4 outstanding S31 verdicts
  recorded through the actual decision store (S-11); the phonetic-name-guard issue is
  closed as resolved by a different design (S-12); the REPAIR_BACKEND_SECONDARY
  recommendation is retired from IMPROVEMENTS.md and REVIEW.md (S-13).
- S-14 through S-16 (sprint 013, Posture and liveness): every data surface of the review
  server — the /api/ routes and the rendered pages — is gated behind the same token as
  writes, and REQUIRE_TOKEN=1 hard-fails startup if auth ends up disabled anyway (S-14);
  a real-socket HTTP integration test covers auth, slow reads and the concurrency bound
  (S-15); a heartbeat file, a GET /healthz route and a Docker HEALTHCHECK let liveness be
  checked without inferring it from an idle-looking container (S-16).
- S-17 through S-20 (sprint 014, Measurement): tools/timing_compare.py's real-media
  validation (T12) runs on 3 representative shows with a written go/no-go report, and
  specs/timing-compare/tasks.md's stale checklist is reconciled with what already shipped
  on main (S-17); the queue/publish operational checklist (timers, order-file drift,
  manifest policy) is verified live (S-18); the storage/host checklist is closed and
  FFMPEG_TIMEOUT's default is raised from 600 s to 1800 s, measured too short against a
  556 MB episode on the production NFS mount (S-19); the signs/songs-extraction prototype
  (tools/sns_extract.py) is built read-only with a false-positive inventory (S-20).
- S-21 and S-22 (sprint 015, Release): the osv-scanner/pyproject extractor gap is
  tracked and the uv.lock scanning decision recorded (S-21); the 0.2.0 release itself
  (S-22).

### Deferred

Carried forward from the 2026-09-21 weekly plan's "Beyond v0.2.0 / visible backlog" — not
silently promoted into this release:

- Web UI dashboard expansion, glossary editor, community glossary auto-fetch/push.
- Full decoder/config fingerprint migration if not taken as S-10 through S-13 this release.
- Full cross-host locking/claim mechanism beyond the current "never run two workers"
  operational rule.
- Full ASS coordinate transformation for mismatched PlayResX/PlayResY; the current
  timing/signs work only warns.
- Card splitting as a broader automatic feature; card_split.py stays deliberately limited
  to human corrections.
- Automatic subtitle-repository reopen sweep; the beta design explicitly chose manual
  reopen.
- Full CI/workflow consolidation if the current GitHub beta workflows are green; do not
  relitigate launch mechanics unless a concrete failure is found.
- V1/V2 polish backlog items: style-collision logs, WrapStyle audit, font MIME warnings,
  mux.partners() optimization, extra data-file extraction, and broad observability
  polish, unless promoted by evidence from post-beta checks.
- Phase-1 timing gating (using the timing-compare signal to drop/flag/snap cards): a
  separate spec, written only if S-17's go/no-go says GO.

### Fixed

- `gen_loop.sh`: a verify pass that ran past `VERIFY_TIMEOUT` (1200s) took the container
  down with exit code 124. The wrapper `timeout ...; rc=$?` was a _standalone_ command under
  "verify TIMED OUT … (continuing)" message that was already written to handle exactly this
  case — the message's `[ $rc -eq 124 ] && echo …` never got a chance to run because the
  shell had already exited. Same `&& rc=0 || rc=$?` pattern `generate.py` (line 96) already
  uses to keep crash-resume alive: the compound's last subcommand is always 0, so `set -e`
  cannot trip on the `timeout`'s 124, and the real rc is captured for the message. Measured
  on vm102 across the 14h ending 2026-09-05 14:00 EDT: every container restart in the
  window exited with code 124 (journal-confirmed via `journalctl -u docker … exitCode=124`),
  and `VERIFY_TIMEOUT` firing on One Pace (the WATCH_QUEUE_PIN show, run first) lands
  within 2s of every measured exit. After the fix, a timed-out verify logs the existing
  "verify TIMED OUT … (continuing; terms stay unverified)" line and the sweep continues.
- `gen_loop.sh`: the ACQUIRE `timeout` (line 64) was already guarded with `|| echo …`, so
  it was never the trigger — kept the existing wording and added a one-line cross-reference
  comment so the next reader does not "fix" the asymmetry by removing the ACQUIRE guard.

- `export_subtitles`: the public repository publishes `Show - SxxExx - Episode Title`, not
  the media filename. The encode's provenance (`[WEBDL-1080p][8bit][AAC 2.0][x264]-VARYG`,
  and the unbracketed `1080p 6ch x265` shape) is meaningful in a library and is noise on a
  subtitle download. Measured against the production library: 386 of 845 completed episodes
  are renamed, 459 already matched and are untouched — including all 48 episodes already
  published, so nothing in the repository moves for this.
- `export_subtitles`: an episode this run could not export is not thereby unpublished. The
  manifest was rebuilt from what a single run managed to export, so a library gone stale
  against a `TEXT_VERSION` bump qualified nothing and emptied a manifest describing 48
  episodes whose 96 files were sitting untouched beside it -- reached the public repository
  on 2026-09-04 and was reverted. An entry is now carried forward while its files are still
  in the repository, and dropped only once they are gone.
- `export_subtitles`: a show that publishes nothing no longer has a manifest file created
  for it. The file's existence is the claim "this show is published", and the publish script
  runs the exporter over every directory in the library -- 95 of them on 2026-09-04, all
  with nothing to ship. An existing manifest is still rewritten, so a set that shrinks to
  zero is recorded rather than left stale.
- `publish_subtitles.sh`: `GITHUB_PAT`/`GITHUB_USER`, when the deployment supplies them,
  authenticate the push through a credential helper that reads them from the environment.
  The token is never written into the checkout's remote URL and never passed as an
  argument, so it cannot leak through `.git/config` or `ps`. Unset, the push uses whatever
  credentials the environment already carries.
- `publish_subtitles.sh`: the subtitle checkout is declared a safe directory before it is
  read. It is a bind mount into a container running as root, so git refused the host-owned
  repository as "dubious ownership" -- verified on the real deployment, where every
  scheduled run would have died at `git status`. The missing-git check also moved to the
  top of the script: the library walk takes minutes, and a run that discovers its missing
  tool at the end has already spent them.
- `publish_subtitles.sh`: an environment without `git` is refused (exit 3) instead of
  reading as "nothing changed - no commit". Observed 2026-09-04 on vm102: the container
  image carried no git, so a full library sweep reported success and published nothing.
  `git` is now installed in `Dockerfile.builder`, which is where the publish path runs.
- `export_subtitles`: two encodes of one episode (they differ only by a release tag, e.g. a
  `[JA+EN]` re-release — 19 titles across 38 files in the library) now publish once and are
  counted as `duplicate-encode`. Previously the second silently overwrote the first's files
  and the manifest carried two entries under one key, which republished the pair on every
  sweep as the winner alternated.

## 0.1.0 - 2026-09-04

The first public beta. Everything below shipped before the first tag; the pipeline's own
output versions (v2-v8) are listed at the end, since they are what decides whether an
episode already in your library is stale.

### Added

- Per-show glossary acquisition, arc/episode-scoped: wiki-mined proper nouns admitted per
  episode rather than per franchise, with per-token provenance and a repair-weighting pass
  by episode/arc tags.
- Review page: user-selectable sort order (chronological, queue order, longest-first,
  alongside the measured risk-first default) on both the episode and shared-lines pages.
- `tools/export_reviewed.py` / `tools/export_subtitles.py` — publish dubtitles to a public
  subtitle repository, gated on full human review or (separately) on pipeline completion.
- `docs/wiki/` — the wiki content lives in this repository now and mirrors to both GitHub
  and the self-hosted Forgejo wiki via `tools/sync_wiki.sh`.
- [XenaRathon/DubTitlerr-glossaries](https://github.com/XenaRathon/DubTitlerr-glossaries) —
  the community glossary repository.
- `decisions.locked()` — a cross-process file lock around a show's decision-store
  load-modify-save, closing a race between the review server and the `unresolved.py` CLI.
- `tools/asr_bakeoff.py` — the ASR bakeoff harness: runs faster-whisper, NeMo (Parakeet,
  Canary) and Qwen3-ASR entrants over the same episodes on one card, and scores them against
  a real reference transcript rather than against each other. Measured results for a 6GB
  GTX 1060 and an 8GB RTX 2070 Super are in `docs/asr-bakeoff/`, and the reasoning behind the
  `WHISPER_MODEL`/`COMPUTE_TYPE` defaults is now written down in the wiki's
  _Choosing an ASR model_ rather than assumed.

### Fixed

- `dub_signs_merge`: a style-name guess (e.g. a style named like a dialogue track) now
  yields to an unambiguous keep-tag (positioned, karaoke, drawing, animated) — previously
  such signs/song events were silently dropped from the merged track.
- `dub_signs_merge`: whisper's transcription of a sung OP/ED is dropped from the dub track
  and the fansub's own song translation is kept instead. Whisper does not transcribe
  Japanese singing, it hallucinates over it (`avg_logprob` -1.7 to -4.1 against -0.3/-0.7
  for ordinary dialogue), and the fansub translation it displaced was being discarded. A
  song's Kanji/Japanese/English sibling styles are now recognised by their shared
  `Opening-`/`ED<N>-` prefix rather than by keyword, so half of each song's on-screen text
  is no longer missing. Only releases whose signs track carries song-family styles are
  affected; a track without them is untouched. Measured 2026-09-02 against the production
  library: SAO, JUJUTSU KAISEN, SPY x FAMILY and Reborn as a Vending Machine as expected,
  and also One Pace seasons 17 and 27 (25-26 dropped cards per S27 episode), which earlier
  notes in this repository wrongly described as having no OP/ED at all. Most other One Pace
  seasons do produce no spans.
  **Forward-only, with a targeted re-open.** This changes the merge stage, not the words or
  the text, so `TEXT_VERSION` does not cover it and an already-muxed episode has no sidecar
  left for the merge to rebuild — it keeps its hallucinated song cards. To correct an
  existing library, point `tools/reopen_for_signs.py` at the shows that have an OP/ED
  (dry run first) and let the next `merge_pass.sh` sweep re-merge and re-mux them. A
  `TEXT_VERSION` bump would also work and would re-mux every episode in the library,
  including the many with no song styles at all.
- `generate.py`: a delayed audio stream's start offset is now carried onto the video
  timeline (measured up to +1745ms on one show), instead of shipping every cue early by
  that delay. **Forward-only.** The offset is applied to the word timestamps before they
  are persisted, so an episode transcribed before this fix has the uncorrected times baked
  into its `words.json` and no text-tier rebuild can recover them — only a re-transcribe
  can, which is why `TRANSCRIBE_VERSION` was deliberately NOT bumped (it would put the
  whole library back through the GPU). Episodes already in your library keep the old
  timing; new ones get the fix.
- `repair.py`: a card the repair stage skips (no fansub anchor, or an unreachable LLM
  backend) no longer discards a human's stored `correct`/`force` verdict for that line —
  it ships the human's text instead of reverting to raw ASR.
- `repair.py`: a merge pass that would strip every repair from an already-repaired episode
  (e.g. a misconfigured backend) now aborts that episode instead of silently reverting it.
- `review_apply`: saving a verdict against an already-muxed episode now re-opens it so the
  correction actually reaches the video, instead of only updating the decision store.
- `export_subtitles`: no manifest entry is written for an episode whose `.ass` extraction
  failed.
- Docs: the `COMPUTE_TYPE` reference row claimed `float16` was the quality setting. The
  bakeoff disproved it — on Pascal cards `float16` does not load at all, and where both load
  the transcripts are equivalent. Precision is a compatibility knob here, not a quality one.

### Pipeline output-version history (see `common.py` for the authoritative log)

- **v9** (2026-09-02) — the hallucination gate drops a card carrying Japanese script: in an
  English dub that is whisper falling back to the Japanese it heard under a song, not a
  low-confidence English line. 1,240 of 395,671 cards across 24 shows, every sampled one an
  OP/ED lyric. Unlike the signs-track song drop, this reaches releases that caption no song
  lyrics at all — and unlike that fix, a `TEXT_VERSION` bump DOES carry it into episodes
  already in your library, on CPU, without re-transcribing.
- **v8** (2026-08-29) — two reflow character-welding fixes (thousands separators, decimal
  points wrongly joined to the previous word).
- **v7** (2026-08-26) — the phonetic name guard widens from substitutions to any gained
  (fabricated) name.
- **v6** (2026-08-26) — repair gains the phonetic name guard: rejects an LLM repair that
  substitutes a proper noun found in neither the glossary nor the original.
- **v5** (2026-08-24) — the single version splits into `TRANSCRIBE_VERSION`/`TEXT_VERSION`,
  so a text-only fix no longer forces a full re-transcribe.
- **v4** (2026-08-21) — hyphenated words no longer ship with a stray space
  ("Gas -Gas" → "Gas-Gas"); 9 One Pace glossary hard-fixes added.
- **v3** (2026-08-20) — sub-`MIN_DUR` cards repaired, multi-line cue wrapping restored,
  sentence punctuation restored before card splitting.
- **v2** (2026-07-27) — fixed a signs-merge bug that rendered captions as solid black
  and duplicated signs across tracks.

[0.2.1]: https://github.com/XenaRathon/DubTitlerr/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/XenaRathon/DubTitlerr/compare/v0.1.0...v0.2.0
[Unreleased]: https://github.com/XenaRathon/DubTitlerr/compare/v0.2.1...HEAD
