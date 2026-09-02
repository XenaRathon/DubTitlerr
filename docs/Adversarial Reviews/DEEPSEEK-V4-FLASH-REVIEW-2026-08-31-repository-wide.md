# Repository-wide adversarial review — DEEPSEEK-V4-FLASH — 2026-08-31

Reviewed 2026-08-31, HEAD `c3464e7` on `feat/review-sorting` (tree dirty only with
untracked review artifacts — no code changed for this review). This is a fresh
adversarial pass over the whole production surface, written independently of the
`GPT5.6-LUNA` and `2026-08-29` reviews; where a finding overlaps one of theirs it
carries new evidence or a new mechanism, and I say which.

## Scope and method

Read in full: all top-level Python modules (`common`, `generate`, `reflow`,
`punctuation`, `hallucination`, `repair`, `dub_signs_merge`, `mux`, `review_apply`,
`review_server`, `unresolved`, `decisions`, `qc`, `glossary`, `glossary_acquire`,
`glossary_verify`, `mine_glossary`, `acquire_cache`, `watch_queue`, `plex_refresh`,
`ordering`, `recreate_srt`, `boxxo_voice_extract`), both Dockerfiles, all four shell
scripts, and the decision/queue/glossary/QC sidecar formats. The offline tools
(`timing_compare`, `vad`, `bakeoff`, `model_bakeoff`, `reclaim_orphans`,
`recover_dub_srt`, `glossary_doctor`, `reapply_glossary`) were read for contract and
for every place the pipeline crosses into them (e.g. who consumes `glossary.stale_tier`,
who may re-open an episode).

Commands run: `pytest -q` (**1,425 passed**), `python -m compileall -q -- *.py tools tests`,
`sh -n container_run.sh gen_loop.sh merge_pass.sh shell/lib.sh`, `ruff check .`.

Priority labels, same scheme as the prior repo-wide review:

- **P0:** can corrupt/overwrite media, expose privileged mutation, or cause sustained outage.
- **P1:** can silently ship materially wrong/incomplete output or strand operational state.
- **P2:** correctness/availability weakness with bounded or recoverable impact.
- **P3:** maintainability, performance, or testability debt.

## Executive summary

The codebase is internally consistent about its idioms — atomic writes, fail-safe
sentinel returns, "never fail an episode" contracts, and a genuinely impressive
self-review culture (measured claims, ADRs, rebuttals committed next to findings). The
headline risk is not a crash bug: it is **state that is recorded and then never read**.
Three times in recent sessions the code wrote the exact field a failure mode needed,
and no code reads it back: the verdict `at` timestamp (built so a sweep can tell a shipped verdict
from an unshipped one), the stamp `stages` record (built so "repair died" stops looking
like "repair ran"), and the stored `initial_prompt`/`model` in `words.json` (built so a
decoder-affecting glossary change marks the transcript stale). Each is a write-only
artifact today, and each write-only artifact papers over a real, reachable wrong
behavior: redundant re-muxing of settled episodes, silent stage death reaching the
stamp, and glossary/model changes that never invalidate cached transcripts.

The second theme is that the pipeline's two most safety-critical hand-offs — the GPU
queue file that drives `gen_loop.sh`, and the human decision store the whole review
loop derives its authority from — are the two places the otherwise-universal locking
and atomicity discipline is weakest.

## Findings

### F1 — P1: the re-open path ignores the `at` timestamp, so "Apply decisions" re-muxes episodes whose verdicts are already shipped or change nothing

**Evidence.** `decisions.record` writes `at: time.time()` on every verdict
(`decisions.py`), and its docstring states the entire reason: *"`at` is what lets a
sweep tell a verdict that has NOT shipped from one that has… Without a time on the
entry, a sweep can only ask 'has this line ever been ruled on', which is true forever,
so it would re-open every eligible episode on every pass."* The measured motivation is
in the same comment: 11 of 20 One Pace corrections were still absent from the shipped
track after a mux.

No production code reads `at`. I grepped for consumers: only two tests assert it is
written. `review_apply.apply_episode` decides eligibility with
`decisions.for_orig(store, orig)` — "any verdict exists for this original line" — and
`changed` counts **every** ruled card, `accept` included. On `--apply` it then rewrites
the SRT, drops the stamp, and hands the episode back to the merge loop for a full
multi-GB re-mux. Three consequences follow:

1. A batch of `accept` verdicts (the queue's most common outcome — measured 78% of
   admitted repairs change no word) changes no text, yet triggers exactly the re-mux
   cycle the `at` field exists to avoid.
2. A verdict recorded **before** the last mux already shipped; Apply still re-opens it.
3. Because the shipped text lives only inside the muxed track, the SRT is rebuilt from
   `conf.json` (original ASR text) and repair must re-derive the accepted proposal to
   restore what is already in the file — a full LLM pass per episode to reproduce the
   current state.

**Impact.** A single review session on an already-muxed library can cost multiple
useless GPU/CPU cycles, and the "Apply" button's cost is unbounded by the actual
amount of work it performs. Not corruption — waste plus a design intent (`at`) left
unfulfilled exactly where its docstring says it belongs.

**Recommendation.** In `apply_episode`, compare each ruling's `at` against the stamp's
mtime (and the mux log's) and skip verdicts that predate the last mux; count only
verdicts that can change the shipped text (`reject`/`correct`/`force`, or an `accept`
whose proposal differs from conf) toward `changed`; say so in the response.

### F2 — P1: decoder-affecting glossary/model state is stored but never validated on read; the comparator that exists is manual-only

**Evidence.** `generate.write_words` persists `initial_prompt` and `model` with the
words. `generate.load_glossary`'s docstring promises: *"the text tier compares a
stored prompt against it to decide whether a glossary edit needs the GPU."* The
comparator exists — `glossary.stale_tier(stored_prompt, gloss, show)` — and it is the
right one (string-compare is the decoder's only route in). But its only production
caller is `tools/reapply_glossary.py`, a manual, out-of-band tool that *reports*
"transcription-stale → needs the GPU" and cannot itself re-transcribe. The mainline
paths never call it: `read_words` validates only `transcribe_version`; `partition_todo`
and `needs_work` consult the numeric tier versions only. `model` is never compared to
anything.

So the promised behavior does not exist: a glossary `initial_prompt` edit — or a
`SHOW_NAME` change, since the show name is embedded in the neutral prompt — leaves
every episode's two-tier stamp current, the cached `words.json` replays words produced
under a different prompt, and nothing marks the transcript stale. The numeric
`TRANSCRIBE_VERSION` comment remains the only guard, exactly as it was before the
stored-state machinery was built.

**Impact.** Silent mixed-regime library: episodes transcribed under prompt A coexist
with episodes under prompt B, with no automatic migration or warning. This is the F4
class from the 2026-09-01 review, but with a sharper mechanism: the mitigation that
was built for it is dead code in the production path, and a future developer reading
`load_glossary`'s docstring will believe it works.

**Recommendation.** Call `glossary.stale_tier` from the mainline (cheapest correct
place: `read_words`, which already has the stored prompt and can reach the glossary via
the show key), and mark the transcribe tier stale on mismatch; or delete the docstring
claim and make the manual tool the documented contract.

### F3 — P1: the GPU queue file is the one non-atomic write in the repo, and a truncated queue reads as "sweep complete"

**Evidence.** `watch_queue.main` writes the order file with a plain
`open(a.out, "w")` — no temp file, no `os.replace` — in a codebase where every other
durable write (`decisions.save`, `unresolved._rewrite`, `generate._atomic_write`,
`qc.write`, `acquire_cache.save`, token persistence) is atomic. The file it writes is
the single control input of the GPU sweep: `gen_loop.sh` re-reads `$ORDER` every
sweep, and treats the file as authoritative. If the write is interrupted (killed
container, ENOSPC, power loss between open and flush), the file can be truncated or
contain a half-written directory name. `gen_loop.sh`'s only guard is
`[ ! -f "$ORDER" ]` — an *existing but empty* file is a legal, completely silent
"nothing to do": the `while read` loop iterates zero times, the script prints
`SWEEP COMPLETE — idle 21600s`, and generation stops for up to a `RESCAN_INTERVAL`
(default 6 hours). A half-written show name is worse: that show silently drops out of
the queue with no message at all. Note also that `build()` only refuses to write when
*both* sources are unreachable; all-watched-titles-matching-nothing (a library rename)
produces an empty order file through this same legal path.

**Impact.** Sustained invisible generation outage, or a silently narrowed queue,
recovering only at the next successful watch-queue pass — exactly the "empty answer
looks like nothing to do" failure the module's own tri-state design exists to prevent.

**Recommendation.** Use `tempfile.mkstemp` + `os.replace` (the house idiom); in
`gen_loop.sh`, treat an empty `$ORDER` as suspicious (log, idle, don't silently complete
the sweep).

### F4 — P1: the decision store has two concurrent writers and no cross-process lock; the "server is the only writer" premise is false

**Evidence.** `decisions.save`'s own docstring is explicit: *"ATOMIC WRITE, NOT ATOMIC
READ-MODIFY-WRITE. Two callers that both load() before either save()s will lose one of
the two verdicts… The review server is the only writer and handles one request at a
time, which is what makes this safe today — if that ever stops being true this needs a
lock."* It already stopped being true. `unresolved.main` (`--review` CLI) writes the
*same* store through `decisions.record` + `decisions.save`, and rewrites the *same*
per-episode queue JSONL through `resolve`/`resolve_many` — in a separate process, with
no lock. The server's `_WRITE_LOCK` is an in-process `threading.Lock` that cannot see
the CLI. `mux.held_for_review` and the review page read the store concurrently with
either writer. The CLI is not hypothetical: it is the documented alternative review
surface and the tool the operator is told to run over SSH.

**Impact.** A load-modify-write collision loses a human verdict with no error and no
log entry — the exact failure this module's docstrings say the project will not paper
over ("a review that silently discards the human's verdict is worse than one that
errors"). Same race on the queue file's whole-file rewrite.

**Recommendation.** A lockfile around `decisions.save`/`load` and `unresolved`'s
rewrites (fcntl on Linux), or route the CLI's writes through one process; at minimum,
detect and report an mtime change between load and save.

### F5 — P2: merge_pass still swallows stage exit codes, and the two observability fields built to compensate are write-only

**Evidence.** `merge_pass.sh` invokes `repair.py` and `dub_signs_merge.py` with no
return-code check (no `set -e`; each is a bare `python3 …` line), so a stage that
crashed mid-episode still hands the SRT to `mux.py --apply`, which stamps. Two
mitigations were added — `write_stamp(..., stages=_stages_ran(...))` and the repair
summary — and neither is read: grep shows `stamp["stages"]` has **no reader anywhere**
in production code (`stamp_valid`/`stale_tiers` deliberately ignore it, and nothing
else touches it), and `_stages_ran` infers "repair ran" from the existence of the
summary file, which `repair.process` writes unconditionally at the end even when every
target was skipped or the endpoint was down. So "stages" can say `repair: true` for a
pass that repaired nothing and died nothing, and can say `signs_merge: true` for a
sidecar that exists only because a transient failure fell back to dialogue-only —
exactly the ambiguity `stages` was introduced to dissolve.

**Impact.** A crashed repair or signs pass reads identically to a successful one on
disk — the observed state, not the intended one. GPT5.6's F2 and the 2026-08-29
carry-forward both flagged the same shell hole; the new evidence is that the
observability half remains unclosed on the *read* side.

**Recommendation.** Check exit codes in `merge_pass.sh` (or make each stage return a
structured status and gate the mux call); and either make `stamp_valid` or an
aggregator actually consume `stages`, or stop writing it.

### F6 — P2: subrip fansub tracks are mineable but invisible to every reference consumer, and the shared extractor burns a guaranteed-failed copy attempt

**Evidence.** `common.eng_sub_tracks` accepts only `codec_name in ("ass", "ssa")`, so
an embedded **subrip** English track yields: no dialogue anchor for
`dialogue_intervals` (repair goes unanchored), no signs source for `dub_signs_merge`,
no reference for timing-compare. Yet `mine_glossary.eng_sub_text` *does* accept
`codec_name == "subrip"` — the pipeline's own miner treats a subrip track as real
fansub worth mining names from, while the repair stage treats it as not worth anchoring
dialogue on. That is two policies about one track format, and the pipeline picks the
pessimistic one for the stage where anchoring matters most (unanchored repair is the
least verifiable class).

Second, the shared extractor still serves every consumer the 2026-08-29 review
challenged: `common.extract_sub` attempts `-c:s copy` into a `.ass` first (physically impossible for a subrip source — the ass muxer refuses (rc 234, measured in
the 2026-08-29 review), leaving a 0-byte file), then re-encodes, discarding the
failure's rc and stderr. It is unchanged
at HEAD. The miner's own comment documents a 60x discrepancy on the same class of file
and bypasses the helper — internal evidence the shared default is wrong for a sibling
consumer.

**Impact.** Correct-and-in-scope releases lose anchoring (quality regression, silent),
and every subrip-signs episode pays a wasted ffmpeg invocation before the work it
always had to do. Bounded, but the asymmetry makes the policy look accidental.

**Recommendation.** Probe the stream codec and only attempt `-c:s copy` for ASS input;
check rc/stderr; and make an explicit decision (documented or code-encoded) about
whether a subrip fansub is an anchor: if the answer is yes (the miner's position),
accept subrip in `eng_sub_tracks` for the dialogue-anchor uses.

### F7 — P3: queue files grow without bound and every consumer re-reads them whole

**Evidence.** `unresolved` entries are append-only; `resolve`/`resolve_many` flip
`resolved` in place and never compact. Re-transcriptions and text-tier re-runs append
new `repair_applied` entries each pass; `live_only` hides the old ones from view but
not from disk. The review page (`open_entries`), the mux gate (`pending`), and the CLI
all re-read the whole JSONL per episode — already ~200s across the library at
2026-08-28 measurements — and that cost grows monotonically with every episode re-run,
which the tier split makes the normal steady-state event. The audit-trail intent is
deliberate and defensible; nothing bounds it.

**Impact.** Slow, predictable operational decay on a long-lived library; the warm-time
number in the README is a floor, not a ceiling.

**Recommendation.** Age-out and archive resolved entries (or rotate per text-version),
keeping the audit trail in a separate location if retention is the point.

### F8 — P3: branch hygiene — `feat/review-sorting` is behind `main`, and working artifacts live in the tree

**Evidence.** `git merge-base main HEAD` equals `HEAD`: `main` (at `22ef82f`) is
ahead of the branch under review and already carries "clear a verdict back to
undecided (A7)" and "per-episode acquire plan (D)" merges this branch will need.
Untracked in-tree: `.claude/worktrees/agent-ac3be5ad706056049/` (a full second working
copy of the repo, including its own `.git` and venv-sized artifacts), `skills-lock.json`,
and two in-flight docs. `git status` is permanently dirty and repository-glob file
discovery (this review's own `code_search`) matches the worktree's duplicate sources —
I had to exclude `.claude/**` to avoid finding the *same bug twice in two checkouts*.

**Impact.** Merge risk (the branch's review-sorting feature and main's A7 feature both
touch `review_server.py` and `decisions.py`), and reviewer/finder confusion from
duplicated trees.

**Recommendation.** Move worktrees out of the tree (or `sparse`/exclude them),
catch this branch up, and treat the review-sorting + A7 intersection as a
conflict-tested pair before merge.

## Prioritized remediation

1. Make the re-open path at-aware and work-aware — stop re-muxing shipped/no-op
   verdicts (F1).
2. Wire `stale_tier` into the mainline read path, or delete the promise (F2).
3. Atomic watch-queue write + empty-queue guard in gen_loop (F3).
4. Lock (fcntl) or single-writer the decision store and queue files (F4).
5. Exit-code awareness in `merge_pass.sh` and a reader for `stages` (F5).
6. Codec-probe `extract_sub`; decide the subrip policy explicitly (F6).
7. Bounding the queue growth (F7); branch catch-up and worktree hygiene (F8).

## Rebuttal — arguing against every finding

Written against my own findings, same bar as the review: what I verified in source,
and where the severity depends on deployment assumptions I don't control. Standing per
finding: SURVIVES / WEAKENED / NIT.

### F1 — WEAKENED: the waste is real; the "unbounded" framing overstates today's reach

- **The mechanism is source-verified** (`for_orig` + `changed` counting every verdict;
  `at` unread anywhere). That part survives.
- **But who hits it?** Apply is a *manual click* on an episode page, and the page
  shows the reviewer exactly which lines were queued. A reviewer who only accepted
  clean punctuation fixes (the 78% case) will typically not click Apply at all — it
  is a separate, clearly-labelled button positioned beside "Save", and the UI text
  warns it costs a re-mux. The redundant-mux blast radius is therefore bounded by
  operator behavior, not by the code path. The *automated* consumers
  (`reapply_glossary.py`) drop the stamp only when `changed_cards > 0`, i.e. only when
  `correct()` actually altered text.
- **The sharpest surviving claim is the design one:** `at` exists, has a docstring
  explaining exactly what it is for, and is read by nothing. Even if today's operator
  never mis-clicks, the artifact is inert, and a future "re-open everything with
  pending verdicts" automation will re-introduce the 11-of-20 class. That stands.
- Severity: the mechanism is P1 *in proportion to how often Apply runs on
  already-shipped episodes*; at today's usage it is P2.

### F2 — SURVIVES, with one softening

- Every link in the chain is source-verified: stored prompt/model, read path ignoring
  both, `stale_tier` reachable only from a manual tool, the docstring promise. The
  finding is accurate and mechanical.
- **The softening:** is a stale prompt *actually harmful* in today's deployment? The
  glossary `initial_prompt` is a single line per show; the measured production shows
  transcribe with a stable glossary between bumps, and the mainline already requires an
  explicit `TRANSCRIBE_VERSION` bump for a model change, *documented as the known gap*
  in `generate.py`. So F2 describes a gap the operators already know about — the
  difference my review adds is that the mitigation they *built* (stored prompt +
  `stale_tier`) quietly doesn't run, and a reader of `load_glossary`'s docstring would
  believe it does. That is the part worth fixing, at near-zero cost.
- One claim I did not verify: that any *real* glossary edit since the two-tier split
  changed the prompt in production. If none ever did, this is latent rather than
  active. Standing downgraded from active to latent-but-load-bearing.

### F3 — SURVIVES, with the window measured honestly

- **The mechanism survives unqualified:** plain `open("w")` on the file that drives
  the whole GPU loop, everywhere else atomic. A killed container between open and
  flush is a normal docker restart event, not a freak.
- **The contra case:** the file is tiny (a few hundred bytes, one `write()` call), so
  the truncated-window is a few milliseconds wide; the OS will usually flush it
  coherently or not at all. The *more likely* failure is not a torn write but the
  empty-but-legal queue from `match_dirs` returning no hits after a library rename —
  and that path *also* writes an empty file through code, not a crash. The empty-file
  guard belongs in `gen_loop.sh` regardless of atomicity, and is the higher-value half
  of the fix.
- Practical harm is bounded: the queue is rewritten every sweep window, so the outage
  self-heals within a day even if unattended. It is a silent 6-hour stop, not
  corruption. Survives as P1 for *silence of failure* rather than for duration.

### F4 — SURVIVES in mechanism; the reach is narrower than the prose implies

- **The mechanism is uncontestable:** two processes, no lock, read-modify-write,
  docstring admits it and asserts a premise that is false. That is a factual error in
  the code's own safety reasoning.
- **But the collision is hard to hit.** The CLI is interactive: a human, one verdict
  at a time, over an SSH session; the server saves whole batches when a page is
  submitted. The lost-verdict window is a few milliseconds per CLI verdict and exists
  only when both are writing the same show file at the same moment. A solo operator
  doing one or the other is the documented workflow — the *simultaneous* use is the
  edge case, not the norm. The `--review` CLI is also not reachable from the running
  container's start scripts (gen_loop doesn't launch it), so this is operator-vs-UI,
  not pipeline-internal.
- Value of the finding is therefore preventive: it kills a false invariant before a
  future sync tool flakes on it, rather than fixing a measured loss. Keep the lock;
  drop the "two writers today lose verdicts routinely" implication.

### F5 — SURVIVES as "the fix is half-built"; the *severity claim* needs care

- **Write-only `stages`, unchecked exit codes: both verified.** The strongest part is
  the asymmetry: the codebase built two artifacts specifically to make stage death
  visible, and neither is consumed.
- **Against:** the failure is caught one level up regardless. If repair dies, the SRT
  it never rewrote is the *previous* (generate-produced, un-repaired) one — still a
  valid subtitle, still better than nothing; the next sweep retries; nothing is
  *published wrong*, it is published *unimproved*. `dub_signs_merge` falling back to a
  dialogue-only SRT with a stamp saying `signs_merge: true` is the one case with a
  real quality cost, and it is GPT5.6's F7 boundary, already on the owner's radar.
  So the residual harm is a *misleading-on-disk attribution*, not wrong media.
- Standing: observability debt, P2, and genuinely cheap to close — but it has now
  survived three reviews, which is itself evidence that it should be closed or
  explicitly declined.

### F6 — WEAKENED: one prong proven, one prong policy-shaped

- **The failing-copy-then-fallback is proven only for subrip sources** — the 2026-08-29
  review measured rc 234 on its fixture; for the ASS sources the copy branch is the
  correct fast path, and the library's fansub mix is ASS-dominant. The 60x number is
  the miner's measurement on **its** content, which differs from the shared helper's
  typical callers. So "burns a guaranteed-failed attempt" is true per-suffix but not
  per-library.
- **The subrip policy asymmetry is real but defensible in one direction:** the miner only
  needs *plaintext names* (safe from subrip), while the repair anchor and the signs
  merge need *positioning/style* (ASS). Excluding subrip from those two is a coherent
  position — it is just not a *stated* one. The finding's real payload is "pick a
  policy and say it", not "the code is wrong".
- Steady state: WEAKENED to a robustness/consistency debt; the only unambiguous item
  is logging the copy attempt's rc.

### F7 — NIT: real, but indistinguishable from "the design working"

- The queue is bounded in the dimension that matters to a human: `live_only` hides
  orphaned entries (6,364 measured), `primary_only` hides non-actionable reasons, and
  `undecided` hides settled pairs. What grows is the *audit trail* — which the module
  explicitly sells as the point ("the entry KEEPS its evidence"). Re-reading a few MB
  of JSONL per episode is a seconds-scale cost against the page's documented ~200s
  walk. By the repo's own "a queue nobody can face" bar, this is the least urgent
  item on the list.
- Keep it as a rot-watch, not a task.

### F8 — NIT, with one non-negotiable half

- The catch-up and merge-intersection risk on `review_server.py`/`decisions.py` is
  real and worth doing before merge — but "main is ahead" is the *normal state of a
  feature branch about to merge*, not a defect.
- The worktree-in-tree is the only part I'd call a defect: it doubles every
  repository-wide search result and permanently dirties `git status`. Move it out —
  everything else is cosmetic.

### Meta-rebuttal — what this review actually adds

- F1 (at-awareness) and F2 (stale_tier wiring) are the only findings with a
  **code-level gap** that the maintainers did not already name in a comment. Both are
  "the mitigation exists but is not wired", which is the class this codebase's culture
  most values catching.
- F3, F4, F5 are each writing down a *known or half-known* gap (non-atomic watch-queue
  write was never documented; the save-docstring admits the lock gap; merge_pass
  swallowing exits has been flagged twice) — the review's contribution is confirming
  they are still open and pinning why.
- F6-F8 are debt and hygiene; none should gate a release.
- I did not read every line of `tools/bakeoff.py`/`model_bakeoff.py`/`vad.py`'s audio
  paths, `glossary_doctor`, or `reclaim_orphans` in full, and the `specs/` tree only
  for cross-references — an unread tool could hold something worse than F1-F8.

## Final assessment after rebuttal

The review's structural claim survives its own rebuttal: **three fields the codebase
wrote for exactly the failure modes it fears (`at`, `stages`,
`initial_prompt`-comparison) are written and never read**, and the two most
authoritative state files (the watch queue, the decision store) sit outside the
atomicity/locking discipline applied everywhere else. None of this is shown to have
*damaged media* — the failure states are all "silently less than intended", and all
self-heal or recover under the current operator's workflow.

The highest-confidence, lowest-assumption actions, in order:

1. Make `review_apply` at-aware (F1) — one function, deletes a whole class of
   redundant re-muxes.
2. Wire `glossary.stale_tier` into `read_words` or correct the docstring (F2) — one
   call, or one sentence.
3. fcntl-lock `decisions.save` and watch-queue atomic write + empty-guard (F3/F4) —
   the two authoritative files.
4. Read exit codes in `merge_pass.sh` and give `stages` one consumer (F5).

This will not be the last adversarial review this repo needs — but the next one should
not be able to say "three observability fields are write-only", because that sentence
is the one durable finding in this pass.