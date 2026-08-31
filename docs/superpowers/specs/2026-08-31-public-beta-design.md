# Public beta — design

Written 2026-08-31. Supersedes nothing; this is the first release-scoped spec.

## TL;DR

Ship a public beta of DubTitlerr this week, plus a companion repository of finished One Pace
subtitle files, aimed at the r/onepace readers who asked about dubtitle availability. The
tool is published to the existing GitHub repository with tagged GHCR images; the subtitles
and the per-show glossaries each get their own repository. Four defects that ship wrong
output or lose human work are fixed first. Card splitting, a glossary CI gate and the
automatic re-open sweep are explicitly out.

The audience asked about **availability**, not about a pipeline. The subtitle drop is what
answers them; the tool release serves the smaller group who want to run it themselves.

---

## Audience and claim

- **Code is general**; One Pace is the showcase **and the only fully supported configuration
  for this version**. Other shows are "try it, file an issue".
- Beta users are self-hosters with a CUDA card, Docker and a Plex/Jellyfin library. That is a
  narrow slice of the target subreddit, which is why the subtitle files ship alongside.

---

## Settled decisions

| #   | Decision                          | Answer                                                                 |
| --- | --------------------------------- | ---------------------------------------------------------------------- |
| 1   | Tool or output                    | **Both, same week**                                                    |
| 2   | Where the subtitle files live     | **Their own repository**                                               |
| 3   | Public git history                | **Publish in full, after a secret scan**                               |
| 4   | Card splitting in beta            | **No.** Queue sorting yes                                              |
| 5   | VRAM target                       | **Measure both**: 6GB on fasc, 8GB on xenapc                           |
| 6   | Glossary submission path          | **Read-only + PR template, no CI gate**                                |
| 7   | What users pin to                 | **Tagged releases**; `:edge` later. Feature branches → PR → main       |
| 8   | Version-stamp promise             | **Stated in README**: stamps may be invalidated during beta            |
| 9   | Unvalidated configurations        | **Loud non-fatal warnings**, pasteable into an issue                   |
| 10  | Subtitle drop scope               | **Only episodes with a human review pass**, restriction stated plainly |
| 11  | Definition of "reviewed"          | **Every queued line in the episode has a verdict**                     |
| 12  | Subtitle file format              | **Both** `.srt` and the merged `.ass`                                  |
| 13  | Source of the shipped files       | **Fresh `review_apply` pass**, then export                             |
| 14  | Automatic re-open sweep           | **No.** Manual button plus a warning on the page                       |
| 15  | Internal hosts in the public repo | **Scrub the current tree only**; history keeps them                    |

### Why 11 is worded that way

`decisions.py:10` — _"Keyed on the normalised `(orig, proposed)` TEXT PAIR, never on episode
or card index."_ Nothing records that a human read an episode's queue, and it cannot be
reconstructed for past work. "Every queued line has a verdict" is derivable today from the
queue and the store, and it is true when written down. Shared-line verdicts count correctly:
a human did judge that line, even if they were reading a different episode at the time.

The repositories must therefore say, in plain language, that **only the lines the pipeline
was unsure about were read by a human — not the whole episode.**

---

## Workstream A — correctness fixes

All four are release blockers. Each follows `procoder:tdd`: a failing test first, the
failing-then-passing output recorded as the todo's evidence.

### A1 — Audio start offset

Todo: `.procoder/todo/20260830-audio-start-offset-shifts-every-cue.md`

`generate.extract_wav` (`generate.py:245`) discards the audio stream's `start_time`, so every
cue is early by that delay. Measured: SAO S01E01 `+1745 ms`; SAO S01E02–E24 `-7 ms` (Opus
pre-skip); One Pace S31 `0 ms` across 48 episodes.

**Behaviour: correct and log.** The offset is added back and a log line records that the
release carried a delayed audio stream.

**Threshold: 50 ms.** Justification: the two measured populations are 7 ms (codec pre-skip,
sub-frame noise) and 1745 ms (real delay). 50 ms sits an order of magnitude above the noise
and an order of magnitude below the signal, and is roughly one frame at 24 fps — below the
point at which a subtitle offset is perceptible. Recorded here so it is a decision, not an
accident; override by editing this line and the constant together.

Acceptance:

- A synthetic delayed-audio fixture produces cards aligned to the video timeline.
- A zero-offset video produces byte-identical output to today; One Pace S31 must not move.
- A `-7 ms` offset does not trigger the correction and does not log.
- The log line says which branch was taken.

### A2 — Unanchored repair, per show

Todo: `.procoder/todo/20260830-repair-unanchored-is-load-bearing-and-set-nowhere.md`

`repair.skips_unanchored()` (`repair.py:194`) refuses any card with no fansub reference unless
`REPAIR_UNANCHORED` is set (`repair.py:285`). One Pace has no reference track, so with the gate
closed every card is skipped — and `repair.py` rebuilds the srt from `conf.json` regardless,
so a merge pass run from the committed scripts **reverts an already-repaired episode to raw
ASR**. Reproduced on S31E24: `targets=144 repaired=0 skipped_no_ref=144`, restored with
`review_apply.apply_episode`; re-run with the flag: `targets=144 repaired=13 skipped_no_ref=0`.

**This is not a One Pace edge case.** Many users hold dub-only copies of shows the maintainer
holds in dual audio, so the unanchored path is a mainstream configuration. The docstring's
caution — glossary-only repair hallucinates names, and the gate-open evidence is one episode
of one show on one model — therefore applies to the mainstream path and must be surfaced to
the user rather than buried in a default.

**Design:**

1. The setting moves into the show's glossary file, which already carries per-show config.
2. It is populated from a setup question phrased in the user's terms: _does your copy of this
   show have English subtitles for the Japanese audio?_ No → unanchored repair is enabled for
   that show, with the trade stated.
3. The global `REPAIR_UNANCHORED` default stays closed and `skips_unanchored`'s docstring
   remains the authority on why.
4. **Guard (c), independent of the above:** a run that would skip _every_ target on an episode
   that already has repairs aborts that episode and logs it, instead of rebuilding raw ASR
   over it.

Acceptance:

- A merge pass from the committed scripts, with no hand-set environment, does not reduce the
  repair count of any already-repaired episode.
- Fixture: an episode with prior repairs, no reference track, gate closed — the run must not
  silently emit raw ASR over it.
- What reproduces the current One Pace behaviour lives in a committed file, not shell history.

### A3 — Unvalidated-configuration warnings

Built alongside A2's guard, same code path. Loud, non-fatal, pasteable into an issue:

- no reference track and unanchored not declared for the show;
- a non-zero audio offset was corrected (A1);
- no glossary resolved for the show.

Rationale: "general code, One Pace supported" means users point it at unvalidated shows on day
one. The audio-offset defect was found on SAO, not One Pace.

### A4 — A skipped card never reaches the decision store

Todo: `.procoder/todo/20260830-a-skipped-card-never-reaches-the-decision-store.md`

`repair.process()` consults the decision store at `repair.py:722`, inside the per-card loop and
_after_ a proposal exists. A card the repair stage skips therefore never reaches the store, and
a human's typed correction for that card is discarded. Beta users losing review work is the
worst available first impression.

Acceptance: a card that the repair stage skips, but for which the store holds a `correct`
verdict, ships the human's text.

### A5 — Stale defaults

`repair.py:83-85`: `REPAIR_MODEL=qwen3:8b`, `REPAIR_BACKEND=ollama`,
`REPAIR_LLAMACPP_URL=http://192.168.1.232:8080/v1/chat/completions` — the last of which is
recorded as dead. A beta user's first run must work from documented defaults, and the
documented defaults must match what the README tells them to install.

### A6 — Review page: saving a verdict does not update the video

`mux.py` treats the `.dubtitles.done` stamp as its only skip guard and nothing re-opens an
episode. The page already has **"Apply decisions to this episode"**. Add a plain statement next
to the save control that saving records the verdict but does not rewrite the video, and point
at the button.

The automatic sweep and the `at`-timestamp policy stay out of scope: `review_apply.apply_episode`
runs unconditionally on a named episode, so neither is needed for anything in this release.

### A7 — Queue sorting

Todo: `.procoder/todo/20260828-review-page-user-selectable-sorting-options.md`. Small, and the
only review-stage polish in scope.

---

## Workstream B — release mechanics

Target: `https://github.com/xenarathon/DubTitlerr`, which already exists and has earlier
versions pushed but has never been released or shared.

1. **Secret scan of what is already public.** Force-pushing rewritten history does **not**
   remove the old commits from GitHub — orphaned commits stay reachable by SHA until GitHub
   garbage-collects, which requires a support request. The scan therefore covers the published
   history, and remediation is rotation plus a GitHub Support purge, not a force-push. The two
   credentials known to have leaked on 2026-08-28 were already rotated; the scan hunts unknowns.
   **Result, 2026-08-31: history is clean.** Four passes — gitleaks over 726 commits across
   all refs (no leaks); a targeted key-name-with-value scan; a Plex-token shape scan; and
   `procoder security` over the working tree (0 findings). `REVIEW_TOKEN` appears only as a
   variable name in docs and specs, never with a value. The 2026-08-28 leak went into a
   transcript, not a commit, and both credentials were rotated. **The public push is
   unblocked on secrets.**

   The scan did surface network topology: 22 of 280 tracked files name internal hosts
   (`192.168.1.232` 12x, `192.168.1.196` 5x, `192.168.1.209` 3x — all RFC1918 and not
   routable), plus `ourserver.party` in `README.md`. **Decision 15: scrub the current tree
   only**, accepting that history retains them. `repair.py`'s is the dead default A5 removes,
   and `README.md`'s is the wiki link B5 rewrites, so the remaining work is two comment lines
   in `punctuation.py` and `tools/bakeoff.py`.

2. **Force-push the attribution-stripped history** once the scan is clean. Backup tag
   `backup/pre-attribution-strip` stays.
3. **Tagged release** `v0.1.0-beta`; GHCR image published by tag, `:latest` pointing at the tag,
   never at `main`. `:edge` deferred.
4. **README rewritten** for the beta: One Pace quickstart, the supported-configuration
   statement, the VRAM findings from workstream E, and the stamp warning:

   > During beta, version stamps may be invalidated without notice. Pin your image tag. If you
   > have already pulled a newer image and are not ready to re-transcribe, stop the container
   > until you are.

5. **Wiki** currently lives on `git.ourserver.party` and must be mirrored or moved.
6. `.github/workflows/ci.yml` and `.github/workflows/test.yml` both run the suite on every push
   and pull request. Going public doubles that on every contributor PR; collapse to one.
7. **Working practice from here:** feature branches, PR into `main`.

---

## Workstream C — subtitle repository

A separate public repository, so a takedown reaches it and not the tool.

**Contents:** for each qualifying episode, the dialogue `.srt` and the merged `.ass`, plus the
episode's duration in seconds as a matching aid. One Pace is a single fan project with no
competing encodes, so the misalignment risk is low; durations are cheap insurance against
One Pace's own revised re-releases.

**Qualifying set:** every episode where every queued line has a human verdict (decision 11).
Computed from the review queue and the decision store. The count is not yet known — the library
holds roughly 455 One Pace episodes with completed dubtitles across 34 seasons, of which
Season 31 (47 episodes) is the set known to have been reviewed.

**Generation:** a fresh `review_apply` pass over the qualifying set, then export. Exporting the
currently muxed tracks would ship the same silent loss found on 2026-08-30, when 11 of 20 One
Pace corrections were in the store and absent from the video.

**The README states plainly:**

- only episodes with at least one human review pass are included;
- "reviewed" means every line the pipeline was unsure about was read and judged by a human —
  **not** that the whole episode was proofread;
- what the pipeline is, and that the remaining lines are machine output.

---

## Workstream D — glossary repository

A second public repository holding the per-show glossaries, keyed as they already are on disk:
`Show (Year) {tvdb-NNNNN}.json`.

The client side already exists: `decisions.py:21` documents `GLOSSARY_DIR` as a mount where
"a `git pull` on the host is what makes it current". No new pipeline code.

New: the repository, a README describing the pull-into-`GLOSSARY_DIR` flow, `CONTRIBUTING.md`,
and a pull-request template. **No CI gate.** `glossary_verify` hits show wikis, and `gen_loop.sh`
already treats a slow wiki as a real, timeout-bounded failure mode; a flaky gate on a
contributor's first pull request is worse than no gate. Verification stays local and manual
until the failure rate in Actions is known.

---

## Workstream E — quantisation A/B

**Question:** can Whisper and the repair model be co-resident on one card, and at what quality
cost?

**Current state, measured 2026-08-31:** fasc serves `nanbeige4.2-3b-Q8_0.gguf`, 4.43 GB, 16k
context, via llama.cpp on port 8090.

| Host   | Card           | Total    | In use at probe            |
| ------ | -------------- | -------- | -------------------------- |
| fasc   | GTX 1060 6GB   | 6144 MiB | 4717 MiB (Q8_0 resident)   |
| xenapc | RTX 2070 SUPER | 8192 MiB | 1609 MiB (Windows desktop) |
| vm102  | GTX 1050 Ti    | 4096 MiB | 0                          |

Q8_0 leaves ~1.4 GB on the 1060 — not enough for Whisper. Q4_K_M or Q5_K_M plausibly fits
beside it.

**Two arms, one overnight run each. Both on llama.cpp**, so the inference engine is held
constant and the quantisation is the only variable:

- **6 GB arm, fasc.** llama.cpp already serving on port 8090.
- **8 GB arm, xenapc.** llama.cpp is installed on the box; no server was listening on the
  standard endpoints at probe time (port 8080 there is bound to `192.168.1.196` and belongs to
  another service, PID 17320). A server is started for the run. The box is Windows
  (`cmd.exe`, no POSIX shell) and loses ~1.6 GB to the desktop, which makes this arm
  conservative: what fits here fits a headless 8 GB card comfortably.

`tools/bakeoff.py` needs NO change. An earlier claim in this spec that it "speaks Ollama
only" was wrong: it already carries `--llamacpp` (raw `/completion`, mirroring `repair.py`)
and `--llamacpp-chat` (`/v1/chat/completions`, which applies the chat template and disables
thinking — nanbeige returns nothing but newlines through the raw endpoint). It is also
model-outer so each candidate loads once, explicitly to avoid reload thrash on an 8 GB card.
The A/B is a configuration exercise, not an implementation one.

**Card contention on xenapc.** The `qwen-tagger` container serves a 28.2B Q3_K_M model
(13.68 GB, `n_ctx` 32768) via llama.cpp on host port 8091, reading its GGUF out of
`/ollama-data/models/blobs`. On an 8 GB card that means heavy CPU offload, and it holds
~7.1 GB of the 8 GB while up. It is already taken down nightly, so the 8 GB arm runs inside
that existing window rather than needing new orchestration.

The scheduled 07:30 restart did not fire on 2026-08-31 (the container was started by hand),
so the window cannot be trusted at either end. **The A/B therefore guards on free VRAM
rather than on the clock**: it checks the card before each arm, aborts with a clear message
if a model is resident, and re-checks between quantisations.

**Candidates:** Q4_K_M, Q5_K_M, Q6_K, against Q8_0 as control.

**Model selection runs at the LARGEST quant that fits, not at the deployment quant.** Judging
a candidate at Q4 risks eliminating it for quantisation damage rather than model quality,
which is not the question being asked. Whisper is not resident during a bake-off -- the
harness only talks to the LLM endpoint -- so the whole 6 GB card is available and every
candidate in the pool fits at Q8_0 (largest is Qwen3-4B at 3.99 GB).

Finalists then go into the overnight quant sweep to find the smallest quant that still holds
their quality. This deliberately splits one question into two: _which model_ is decided at
each model's best, and _which quant_ is decided per finalist afterwards. Doing both at once
would confound them, and the answer to the second is per model anyway, since a 1.1B model
fits at Q8_0 where a 4B needs Q4_K_M to leave room for Whisper.

**Two runs, separated on purpose.**

The overnight window is the scarce resource, so it holds NANBEIGE QUANTS ONLY. That is what
the README's VRAM line is blocked on, and it varies one thing.

Candidate MODELS (Ling, TinyLlama, LFM) are judged separately, by eye, on fasc during the day
while the tagger holds xenapc.

**The quant baseline is per model, not global.** Each candidate gets its own quant, chosen as
the largest that fits the VRAM budget beside whisper -- a 1.1B model may fit at Q8_0 where a
3B needs Q4_K_M. So the comparable unit is never "the model", it is "the model at the largest
quant its size allows in the budget", and the deliverable table is per model rather than one
envelope for all of them. The nanbeige sweep answers that question for nanbeige and for
nothing else.

TinyLlama at 1.1B is well under nanbeige's 3B and the measured failure mode on this prompt is
inaction (nanbeige itself returned 0 safe fixes across 120 targets before the prompt was
fixed), so expect it to go inert. Cheap to include, not to be counted on.

**Judged on:** safe-fix count **and** name-edit count on the existing target set — both, because
a model that makes more edits is not thereby better; VRAM at 16k context; latency.

**Deliverable:** a PER-MODEL table of documented deployment routes with quality expectations
for each —
single 8 GB card, single 6 GB card, split across two cards, and sequential model swap on a
smaller card. Sequential swap is likely close to free already: `generate.py` loads Whisper
lazily and its process exits between shows, and repair talks to an HTTP endpoint. Confirm
before documenting it.

---

## Out of scope, and why

| Item                           | Reason                                                                                                                                                             |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Card splitting                 | Largest of the open todos, architectural, needs its own brainstorm, and blocked on the machine-vs-human bar — which real reviewers will answer better than a guess |
| Glossary CI gate               | Zero submitters on day one; the gate would be flaky against live wikis                                                                                             |
| Automatic re-open sweep        | The manual button exists and works; the sweep is new code on a write path during release week                                                                      |
| `at`-timestamp policy          | Only needed by the sweep                                                                                                                                           |
| Machine-vs-human worsening bar | Only needed by card splitting                                                                                                                                      |
| `PIN_VERSIONS` env var         | Splits users across pipeline versions and makes bug reports harder to read                                                                                         |

---

## Sequence and estimate

| Order | Work                                       | Estimate      |
| ----- | ------------------------------------------ | ------------- |
| 1     | A1 audio offset                            | 3h            |
| 2     | A2 + A3 unanchored, guard, warnings        | 1d            |
| 3     | A4 skipped card, A6 page warning           | 5h            |
| 4     | A5 stale defaults                          | 1h            |
| 5     | A7 queue sorting                           | 3h            |
| 6     | C subtitle repository                      | 6h            |
| 7     | B tool repository public                   | 1d            |
| 8     | D glossary repository                      | 2h            |
| —     | E quant A/B (parallel; two overnight runs) | 4h + 2 nights |

**Roughly five working days, with no slack.** E runs alongside, and its result feeds B's README.

---

## Risks

- **The qualifying-episode count is unknown.** If very few episodes outside Season 31 qualify,
  the subtitle drop is Season 31 plus a handful. That is an acceptable outcome and does not
  change the design, but it should be measured before the repository README is written.
- **The secret scan may find something.** Remediation is rotation plus a GitHub Support purge,
  and it can delay the public push. Run the scan first, not last.
- **A2 changes a durable artifact's shape** (the glossary file gains a field). Existing
  glossary files must keep loading with the field absent.
- **`procoder format` empties an already-formatted file** when used with the documented
  `tail -n +2` recipe. Capture output, assert non-empty, then replace.
