# Second independent review — is this ready to be broken into implementation tasks?

**Reviewer:** GLM-5.2 (Buffy), 2026-08-21.
**Scope:** answer the owner's question: *is this ready to be broken into implementation tasks, and in what order?*

I read the source. The three deliverables are in the order the owner asked for.

---

## 1. Attacking Luna's three load-bearing recommendations

### (a) `data/pipeline_contract.json` manifest + CI test asserting every declared rule is live, disabled, or measured-unobservable

**Verdict: correct in principle, wrong in shape, wrong in priority. Over-engineered for this system.**

The diagnosis — that rules can become inert without any signal — is real and demonstrated three times today. Luna's proposed cure is a static manifest plus an AST-parsing CI test that verifies every declared output has a writer and a named consumer. That is a compiler-writing exercise for a 5,200-LOC codebase with one operator.

Consider what actually killed the three dead paths:

1. `music` rule fired zero times: a runtime counter (`hallucination.drop_reason` returns `"music"` zero times across 353,879 cards) would have caught this in one QC aggregation.
2. `flag` field has no consumer: a grep for `c.get("flag")` or `\.get\("flag"\)` across production modules would have caught this in 30 seconds.
3. Vestigial shell scripts: the Dockerfile already declares exactly which scripts are COPY'd — the gap between "scripts that exist" and "scripts in the image" is visible in one file.

A manifest + AST CI test would catch all three, but so would: (i) a runtime liveness counter on every gated rule (`evaluated` / `activated` / `error`), which Luna mentions as a secondary add but which is actually the primary instrument; and (ii) a one-time dead-code audit, which is a script you run once, not infrastructure you maintain.

The manifest approach has a specific failure mode that makes it dangerous here: it creates a **second source of truth** for what the pipeline does. In a one-operator system, the manifest will rot. A rule gets added in code; the developer forgets to update `pipeline_contract.json`; the CI test now certifies a *stale* contract as passing — which is worse than no contract, because it provides false confidence that the system is verified. The brief's §5.5 ("configuration that looked applied and wasn't") is exactly this failure shape: a thing that says "verified" while being stale.

**Cost of getting wrong:** medium. The manifest becomes a maintenance burden that the single operator will not keep current, and its presence will discourage the cheaper, more reliable approach (runtime counters + a dead-code grep).

**What to do instead:** add `evaluated` and `activated` counters to every gated rule in the QC sidecar — `hallucination.drop_reason`, `hallucination.flag_reason`, `punctuation.restore`, `repair.is_target`. A rule where `evaluated > 0` and `activated == 0` across N episodes is your dead-path detector, and it rides on infrastructure that already exists. Then delete `common.dialogue_event_count()` and `mux.partners()` / `DELETE_BROKEN_HARDLINKS` — Luna found these, they are confirmed dead, and removing them is the one-time audit that proves the process works.

### (b) A single `unresolved` queue for subtitle-quality decisions, mirroring glossary `--review`

**Verdict: correct, right priority, ship it. This is the one recommendation that is not over-engineering.**

The glossary `--review` CLI (`glossary_acquire.py:865`) is the strongest implementation of the deterministic → LLM → human ladder in the codebase. It works: it has a queue (`flagged`), evidence (`context`, `variant_count`, `bound`), and an interactive walk with `record_decision()`. The owner built the right tool for names and then never built the equivalent for lines.

Luna's finding that repair increments `skipped_no_ref` and `rejected` without recording per-line evidence is confirmed by the source. `repair.py:398-406` increments `skipped_no_ref` and continues. `repair.py:451-464` stores only aggregate counts in the summary and only accepted repairs in `repaired_lines`. The rejected proposals — the cases where the model tried and the guard refused — vanish.

This is not just observability. It is the missing rung of the ladder. The architecture principle says a human sees what the model cannot settle. Today the model's failures are absorbed silently: `common.llm_chat()` returns `""` on every transport error (`common.py:410-442`), and the caller treats that as "no edit." A dead Ollama endpoint looks like a clean run. An `unresolved` queue written at the same points that currently only increment counters would make those cases visible and actionable.

**Cost of getting wrong:** low. The queue is append-only and never blocks the pipeline. The worst case is that it accumulates entries nobody reviews — which is strictly better than today, where those cases vanish entirely. The `--review` CLI is a known pattern from glossary_acquire, so the implementation risk is minimal.

**One correction to Luna:** the queue should not be "one queue for all stages." It should be per-stage (`repair_unresolved`, `punctuation_unresolved`, `hallucination_unresolved`) because the operator's triage action differs by stage: a repair rejection needs a fansub reference check, a punctuation rejection needs a read of the run, a hallucination flag needs an audio listen. A flat queue loses the signal that tells the operator what to do with each entry. The `--review` CLI can still be unified (walk all queues in one pass), but the storage should be stage-keyed.

### (c) The 63-variable config surface is a real risk, with scope/path variables ranked highest

**Verdict: correct that it is a real risk. Correct that scope/path variables are highest. But the proposed fix (a validated runtime manifest) is over-engineered and lower priority than Luna ranks it.**

Luna is right that the risk is not the number 63 but the fact that the same logical setting is read in different modules with different overrides. The source confirms every example Luna cites:

- `REQUIRE_ENG` is hardcoded `=1` in `gen_loop.sh:54`, overriding any container-level value. Confirmed.
- `DUB_SUFFIX` is read by `dub_signs_merge.py:40` but hardcoded as `".eng.dubtitles.srt"` in `generate.py:84`, `mux.py:55`, `repair.py:80`, and `merge_pass.sh:34`. Confirmed.
- `DELETE_BROKEN_HARDLINKS` is read into `DELETE_BROKEN` at `mux.py:50` and never consumed. Confirmed.
- `REPAIR_BACKEND_SECONDARY` is in `IMPROVEMENTS.md` but the code reads `REPAIR_MODEL_SECONDARY` at `repair.py:72`. Confirmed (speculation: I did not read IMPROVEMENTS.md, but the pattern matches the source-level mismatch Luna describes).

But Luna's proposed fix — "define each accepted setting once in a stdlib schema, load and validate it before either loop starts, print and persist a redacted resolved manifest" — is a configuration management system for one person. The operator does not need a schema registry. They need:

1. **A startup log that prints every env var the pipeline actually reads**, with its resolved value and source (default / compose / command-line override). This is 30 lines in `container_run.sh` or a small Python function in `common.py`. It surfaces the `REQUIRE_ENG` override and the `DUB_SUFFIX` mismatch the moment the container starts, without any schema to maintain.
2. **Deletion of the dead variables** (`DELETE_BROKEN_HARDLINKS`, `REPAIR_BACKEND_SECONDARY` from docs, the audit-only `REPAIR_MODEL` / `VERIFY_MODEL` labels on the llamacpp path). Luna found these; remove them.
3. **A single `docker-compose` env-block audit** — the 3200g compose already comments every value with its rationale. The issue is not "no schema"; it is "nobody grepped for where each variable is read." A one-time cross-reference of compose vars against `os.environ.get` calls would settle it.

The `DUB_SUFFIX` mismatch is the highest-risk item in this category, and it is not a schema problem — it is a code bug. `generate.py`, `mux.py`, `repair.py`, and `merge_pass.sh` all hardcode the suffix. Only `dub_signs_merge.py` reads the env var. The fix is to either remove the env var (nobody changes this suffix) or make all four sites read it. A schema would not fix this; it would just document the mismatch while it continues to bite.

**Cost of getting wrong:** low-medium. The schema becomes another stale source of truth (same failure as the contract manifest). The startup log is cheaper, more honest, and catches the same bugs.

**Priority:** below the `unresolved` queue and the liveness counters. The config surface is a risk that compounds over time; the dead paths and missing human rung are failures that are happening *right now*.

---

## 2. What did both reviewers miss?

**The pipeline has no concept of "stages that did not run" vs "stages that ran and found nothing."**

Luna identified write-only observability (QC sidecars, lastrun.json, repair-summary.json are written but never consumed). That is correct but incomplete. The deeper problem is that the pipeline's skip/idempotency guards cannot distinguish between:

- "This episode was already processed at the current version" (skip, correctly), and
- "This episode was never processed because a prior stage silently failed" (skip, incorrectly, looking identical to the operator).

The specific mechanism is in `merge_pass.sh`. The script has no `set -e`. It runs `repair.py`, `dub_signs_merge.py`, and `mux.py` per episode without checking any exit status. The final `MERGE_PASS_DONE` line is printed regardless. Luna flagged this as "P1 — merge-stage failures are not propagated to the supervisor." That is the symptom. The miss is what it means for the system's self-model.

Consider: `generate.py:process()` returns `"ok"` and writes the `.eng.dubtitles.srt` + `.dubtitles.conf.json`. The merge loop then picks up the episode. If `repair.py` fails (Ollama down, `common.llm_chat` returns `""`, every target is `skipped_no_ref`), the srt is never rewritten — but the *original* srt from generation is still there. `dub_signs_merge.py` runs on that un-repaired srt. `mux.py` embeds it. The `.dubtitles.done` stamp is written. The episode is "done."

Nobody knows repair didn't run. The QC sidecar records `flagged` and `low_conf` counters from *generation*, but the repair summary (`*.repair-summary.json`) is either not written (repair returned `"skip"` because no srt/conf) or written with `targets=0, repaired=0` — which looks identical to "this episode was clean, nothing needed repair."

The repair summary is the only artifact that could distinguish "repair ran and found nothing" from "repair didn't run." But `repair.py:process()` returns `"skip"` (no srt/conf — the episode was never generated) or `"clean"` (no targets found) or `"repaired"` — and `merge_pass.sh` ignores all three. The `.dubtitles.done` stamp records `{size, mtime, muxed, version}` — nothing about which stages ran.

This is the same class as the `tools/vad.py` example the owner gave: a thing that exists and works (`tools/vad.py` with webrtcvad, better against loud music/SFX) was missed by the author designing a Silero VAD stage, because the Dockerfile's `|| echo` swallowed the webrtcvad install failure, and the module is absent from the running image. The system *lies about its own state* — it says "webrtcvad installed" in the Dockerfile comment, says "use --vad ffmpeg-silencedetect" in the fallback, and the running image has neither. The pipeline contract between "what the Dockerfile says is installed" and "what the running container can import" is unverified.

The same lie happens at the stage level: the `.dubtitles.done` stamp says "this episode is complete" without recording whether repair actually examined it. A version bump (`PIPELINE_VERSION = 4`) would re-transcribe everything, but if the Ollama endpoint is still down, every re-transcribed episode would be muxed without repair again, and the stamp would say "v4, done."

**The one thing to act on:** add a stage-execution record to the `.dubtitles.done` stamp (or a sibling sidecar) that records `{repair_ran: bool, repair_targets: int, signs_merge_ran: bool}`. An episode where `repair_ran == False` but `repair_targets > 0` in the conf is a silent failure. Today it is indistinguishable from a clean episode.

---

## 3. Sequencing

### Ordered work items with dependencies

**Item 0: Fix the webrtcvad install in the Dockerfile (prerequisite, blocks Item 5)**

The `Dockerfile.builder` wraps `webrtcvad` install in `|| echo`, so a silent failure leaves the module absent. `tools/vad.py` already exists with a webrtcvad backend chosen specifically for being better against loud music/SFX — the exact failure mode that killed the author's Silero tests. The VAD hang-trim design (§3.1) proposes Silero VAD, which is "already vendored inside `faster_whisper.vad`." But `tools/vad.py`'s webrtcvad backend is a *different* detector that was deliberately chosen for the *exact* failure mode the Silero tests hit (§4: "Silero VAD as a drop gate deleted 19.8% of real dialogue").

Before implementing the hang trim, the owner should either (a) fix the webrtcvad install (remove the `|| echo`, fail the build if it is absent, verify `import webrtcvad` in the running container), or (b) explicitly document why Silero is preferred over the existing webrtcvad for the *locator* use case (§3.2 step 2) despite webrtcvad being better for the *drop gate* use case (§4). The design does not address this.

**Wasted effort if skipped:** if the hang trim is built on Silero and then Silero turns out to be inferior to the already-existing webrtcvad for the same reason it was inferior in §4, the implementation is wasted.

---

**Item 1: Add liveness counters to every gated rule (independent, no dependencies)**

Add `evaluated` / `activated` / `error` counters to:
- `hallucination.drop_reason` (the `blocklist`, `repetition`, `music` branches — `music` is already known to be zero)
- `hallucination.flag_reason` (the `low_conf` / `maybe_silence` branches)
- `punctuation.restore` (the `restore_runs_sent` / `restore_accepted` / `restore_empty` / `restore_rejected_guard` counters already exist — this is done)
- `repair.is_target` (the `targets` count exists; add `no_eng_ref` and `llm_empty` as distinct from `rejected_guard`)

This rides on the existing QC sidecar infrastructure (`qc.Recorder`). No new files. No manifest. A rule where `evaluated > 0` and `activated == 0` across N episodes is dead.

**Dependency:** none. Can be done now.
**Blocked by:** nothing.

---

**Item 2: Delete confirmed dead code (independent, no dependencies)**

- `common.dialogue_event_count()` (`common.py:357`) — no runtime caller, only tests.
- `mux.partners()` and `DELETE_BROKEN_HARDLINKS` (`mux.py:50`, `mux.py:171-194`) — dead feature pair, advertises a destructive safety control that does nothing.
- The six vestigial shell scripts (`all_seasons.sh`, `anime_library.sh`, `merge_watcher.sh`, `post_season.sh`, `post_show.sh`, `run-dub-merge.sh`) — only `container_run.sh`, `gen_loop.sh`, and `merge_pass.sh` are COPY'd into the image.
- `REPAIR_BACKEND_SECONDARY` from `IMPROVEMENTS.md` if confirmed not in source.

**Dependency:** none. This is the one-time dead-code audit that proves the process works. Do it before building the contract manifest Luna proposes, because it may turn out that a grep-and-delete is sufficient and no manifest is needed.

---

**Item 3: Build the `unresolved` queue for subtitle-quality decisions (independent, highest value)**

Implement per-stage unresolved queues at the points that currently only increment counters:
- `repair.py`: when `skipped_no_ref` or `rejected` is incremented, write an entry to `<show>.unresolved.json` with `{stage: "repair", reason, original_text, proposed_text, source_start, source_end, confidence_fields}`.
- `punctuation.py`: when `restore_empty` or `restore_rejected_guard` is incremented, write an entry.
- `hallucination.py` / `generate.py`: when `flag` is written but no drop occurs, write an entry (or simply consume the existing `flag` field that nothing reads).

Add a `--review` CLI mirroring `glossary_acquire.py`'s pattern. The operator walks the queue, decides, and the decision is recorded.

**Dependency:** none. This is the missing human rung of the ladder.
**Blocked by:** nothing. But it should be done *before* the VAD hang trim, because the hang trim's 11 no-op cards (§3.2 step 3, the 36.7% of gated cards that get no VAD result) are exactly the kind of case that should flow into this queue rather than silently keeping their 7-second hang.

---

**Item 4: Fix the stage-execution gap in the `.dubtitles.done` stamp (independent)**

Add `{repair_ran, repair_targets, signs_merge_ran}` to the stamp (or a sibling `<stem>.dubtitles.stages.json`). An episode where `repair_ran == False` but the conf has targets is a silent failure that is today indistinguishable from a clean episode.

This is the "next §5.5" the owner asked about in item 4 of the brief. The healthcheck/autoheal mismatch Luna found (P0) is real but is a deployment problem; this is a *pipeline* problem of the same shape — the system says "done" without recording what "done" means.

**Dependency:** none. But it should be done before any `PIPELINE_VERSION` bump, because a bump without this information re-transcribes everything and still cannot tell you whether repair ran on the re-transcribed output.

---

**Item 5: VAD hang trim (depends on Item 0)**

The design in `2026-08-21-vad-hang-trim-design.md` is implementable, but only after:
1. Item 0 (webrtcvad install fix or explicit Silero-vs-webrtcvad justification).
2. The 30-card candidate set is run read-only with the actual implementation, as Luna's self-critique and the design's own §6.6 ("No end-to-end validation yet. That is the first implementation step, not a later one") both require.

The design's ordering decision — trim after the runt cascade, as the last pass in `time_cards()` — is the right call. Luna's objection that it can violate timing invariants is mechanically possible but empirically untested, and the 0.57% fire rate bounds the blast radius. The design's own §6.6 acknowledges the validation gap. Luna's self-critique retracted the strongest version of the objection. Implement with the invariant checks Luna's Prediction 4 specifies (start < end, end ≤ audio_duration, end ≤ next_start − MIN_GAP, start ≥ previous_end + MIN_GAP), run the 30-card read-only pass, and ship.

**The 11 no-op cards (§3.2 step 3) should feed into Item 3's `unresolved` queue**, not be left as a known hole. The design says "no speech located → no-op" and "§5 supplies no new drop action." That is safe for the trim, but the 11 cards should be written to the unresolved queue so a human can adjudicate whether they are real dialogue VAD missed or hallucinations over silence. Without Item 3, those 11 cards are invisible.

**Dependency:** Item 0 (webrtcvad/Silero decision), Item 3 (the 11 no-op cards need somewhere to go).
**Wasted effort if done first:** the VAD parameters (`threshold`, `min_silence_duration_ms`, `speech_pad_ms`) are not pinned. If the implementation is built before the read-only 30-card validation, the parameters will be guesses that may need to be re-tuned after the validation reveals the actual interval shapes.

---

**Item 6: Fix `PIPELINE_VERSION` idempotency (depends on Item 4)**

Luna's item 3 analysis is correct: global `PIPELINE_VERSION` is too coarse. A glossary fix should not require re-transcription. But implementing stage-specific fingerprints (Luna's proposed `transcript_fingerprint` / `render_fingerprint`) is a significant refactor that should not be started until Item 4 (stage-execution recording) is done, because the fingerprint system needs to know what a "stage" is and whether it ran — which is exactly what Item 4 establishes.

**Dependency:** Item 4.
**Drop:** do not implement the full fingerprint system now. Instead, add a `glossary_hash` to the stamp (the `_glossary_version()` function at `generate.py:131` already computes it for `lastrun.json` but not for the stamp), so a glossary-only change can be detected without a version bump. This is 5 lines and unblocks the most common case (§5.6's glossary fix needs no re-transcription, only a re-mux).

---

**Item 7: Config surface cleanup (independent, low priority)**

- Add a startup env-var dump to `container_run.sh` (print every `os.environ.get` the pipeline reads, with resolved value).
- Fix `DUB_SUFFIX`: either remove the env var from `dub_signs_merge.py` or make all four sites read it.
- Fix `REQUIRE_ENG`: either remove the hardcoded `=1` in `gen_loop.sh:54` or remove the env var from `generate.py` (it is always `1` in production).
- Remove `REPAIR_MODEL` / `VERIFY_MODEL` from the llamacpp compose (they are audit-only labels, never sent).

**Dependency:** none. Lowest priority. The startup dump is 30 lines of shell and catches the same bugs a schema would, without the maintenance cost.

---

### Summary of the order

```
Item 0  (fix webrtcvad install)          ← blocks Item 5
Item 1  (liveness counters)             ← independent, do now
Item 2  (delete dead code)              ← independent, do now
Item 3  (unresolved queue)              ← independent, highest value
Item 4  (stage-execution record)        ← independent, do before Item 6
Item 5  (VAD hang trim)                 ← depends on 0 + 3
Item 6  (PIPELINE_VERSION refinement)   ← depends on 4
Item 7  (config cleanup)                ← independent, low priority
```

Items 1, 2, 3, and 4 are all independent and should be done first. They are small, they address the failures happening *right now* (dead paths, missing human rung, silent stage skips), and they establish the infrastructure that Items 5 and 6 need. Item 5 (the VAD hang trim the owner is about to act on) should not be the first thing implemented, because it depends on the webrtcvad decision (Item 0) and because its 11 no-op cards need the unresolved queue (Item 3) to not be a known hole.

### What to drop

- **Luna's `data/pipeline_contract.json` manifest + AST CI test.** Replace with liveness counters (Item 1) + dead-code deletion (Item 2). The manifest is a second source of truth that will rot.
- **Luna's full config schema/registry.** Replace with a startup env-var dump (Item 7). The schema is configuration management infrastructure for a one-person system.
- **Luna's full stage-fingerprint system** (proposed in item 3 of Luna's follow-up). Defer to after Item 4. For now, add `glossary_hash` to the stamp — 5 lines, unblocks the most common case.
- **The autoheal container** (Luna's P0 from item 4). This is real but it is a deployment task, not a code task, and production is currently stopped. Do it when production restarts, not before.

---

### One-line answer to the owner's question

Not yet. The VAD hang trim is implementable but should be third in line, not first. Fix the webrtcvad install (Item 0), add liveness counters (Item 1), and build the unresolved queue (Item 3) first — the first because the hang trim's VAD choice depends on it, the second and third because the hang trim's no-op cards and the pipeline's dead paths need somewhere to surface. The hang trim itself (Item 5) is then a focused, well-bounded piece of work whose risks Luna already bounded and the design already acknowledged.
