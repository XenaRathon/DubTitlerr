# Project review — items 2, 1, and 5

**Scope:** item 2 first, then item 1, then item 5. This review does not revisit `PIPELINE_VERSION`, the next deployment silent-degradation bug, or the VAD hang-trim design.

## ITEM 2 — What else is dead?

### First, two claims in the brief are too broad

The source does not support calling all three original examples dead in the same sense.

1. **The `music` branch is reachable code, not an unreachable constant.** `hallucination.drop_reason()` has a live branch at `DubTitlerr/hallucination.py:104`, and `DubTitlerr/tests/test_hallucination.py:43` exercises it with `nsp=0.97`, `avg_logprob=-2.5`. The stronger claim supported by the data is: it fired zero times in the measured corpus, and the deployed turbo model's `no_speech_prob` makes it empirically inert (`DubTitlerr/hallucination.py:42`). That is a deployment-specific dead path, not dead logic for every model/configuration.
2. **The `flag` field is not unread anywhere.** The production pipeline writes it at `DubTitlerr/generate.py:640-661`, and the offline timing tool reads it at `DubTitlerr/tools/timing_compare.py:707` and `:724`. The correct criticism is narrower: no live generation/repair/human-review stage consumes it. It is an analytics input, not a production escalation path.
3. **Not copied into the image does not automatically mean dead.** `Dockerfile.builder` copies the current three shell entrypoints (`DubTitlerr/Dockerfile.builder:55-57`), while legacy host scripts can still be invoked outside the image. `run-dub-merge.sh` is the cleanest dead-script candidate: repository search finds its own definition but no caller. `anime_library.sh` is legacy but still calls `post_show.sh`; “not in the image” and “no longer in the intended image path” are more accurate than “dead.”

Those distinctions matter because a detector that is dormant in production needs a liveness measurement, while a function with no caller needs removal or an explicit tool-only owner. They are different repairs.

### Confirmed dead or write-only paths found in source

#### 1. `common.dialogue_event_count()` has no runtime caller

`DubTitlerr/common.py:357` defines `dialogue_event_count()`. Repository search finds it in its own doc/spec references and in `DubTitlerr/tests/test_common.py:114-127`, but no production module calls it. `tools/timing_compare.py` uses `common.dialogue_density_score()` at `DubTitlerr/tools/timing_compare.py:224`, not `dialogue_event_count()`.

This is a real dead helper, although it is probably leftover API from the timing-compare refactor rather than a live pipeline defect. The test suite preserves it, which makes it look maintained while no runtime path depends on it.

**Action:** either delete the helper and its tests/spec references, or make timing-compare call it and add a report-level test that proves the result affects track selection/reporting.

#### 2. `mux.partners()` and `DELETE_BROKEN_HARDLINKS` are a dead feature pair

`DubTitlerr/mux.py:50` reads `DELETE_BROKEN_HARDLINKS` into `DELETE_BROKEN`. `DubTitlerr/mux.py:171-194` defines and caches `partners()`. There is no call from `mux.process()` or any other production function that uses either value. The current process path explicitly leaves the old library file/hardlink policy to other code and never invokes partner deletion.

This is more serious than a harmless unused helper because the environment variable advertises a destructive safety control that does nothing. An operator can set `DELETE_BROKEN_HARDLINKS=1`, see no error, and falsely believe broken seeding partners will be removed.

**Action:** remove the variable/helper if the orphan-reaper owns this policy, or wire the feature in and add an integration test proving the setting changes the filesystem result. Do not leave a no-op safety knob exposed.

#### 3. `REPAIR_BACKEND_SECONDARY` exists in the operating story but not in runtime code

`DubTitlerr/IMPROVEMENTS.md:199-210` describes adding `REPAIR_BACKEND_SECONDARY`, and `:240` presents it as a deployment setting. The actual `repair.py` reads `REPAIR_MODEL_SECONDARY` at `DubTitlerr/repair.py:72`, but there is no `REPAIR_BACKEND_SECONDARY` read in the source. The second pass calls the same backend dispatch at `DubTitlerr/repair.py:421`.

This is a documented configuration path that cannot work. Setting it cannot move the secondary pass to another backend.

**Action:** delete the setting from the operating docs until implemented, or implement it and test that primary/secondary requests reach different mocked endpoints.

#### 4. QC and run-summary artifacts are production write-only

`DubTitlerr/generate.py:452` writes the QC sidecar through `qc.write()`. `DubTitlerr/qc.py:91` only defines the writer. Repository search finds tests and stale-sidecar handling, but no production reader that aggregates `*.dubtitles.qc.json` counters.

Likewise, `generate.py:781-797` writes `<show>.lastrun.json`, and `repair.py:464-479` writes `*.repair-summary.json`; repository search finds their tests and documentation, but no live consumer that turns those artifacts into an operator queue or alert.

These are not “dead” in the sense that humans cannot inspect them. They are **write-only observability**: the pipeline pays to produce evidence but does not use it to detect a rule going inert or a stage failing open. That is the most important dead-path pattern in the repository.

### Tests that certify local behavior but not liveness

The suite has many valuable unit tests, but the relevant tests do not assert that a rule fires in the deployed configuration or that its output is consumed:

- `test_hallucination.py:43-46` proves the music branch works for synthetic `nsp` values, not that the active model supplies values reaching that branch.
- `test_generate.py:753-772` proves the `flagged` counter reaches the QC sidecar and console output, not that a repair, queue, or human workflow consumes it.
- `test_dockerfile_copy.py` checks Python local-import closure, but neither `.github/workflows/ci.yml` nor `test.yml` builds the image or executes `container_run.sh`/`merge_pass.sh`.
- The CI workflows run unit tests (`DubTitlerr/.github/workflows/ci.yml:12-16`, `test.yml:10-13`) with external model/media paths stubbed or absent. There is no liveness assertion against the active compose/model configuration and no coverage threshold that would force orchestration seams to execute.

### The structural mechanism

The mechanism is **uncontracted, write-only data flow at stage boundaries**:

1. Rules and stages communicate through untyped dictionaries, JSON sidecars, counters, and environment variables.
2. Producers can add a field, counter, branch, or configuration variable without declaring a consumer.
3. Tests call the producer in isolation and assert its local return value.
4. The orchestrator swallows many failures and continues (`gen_loop.sh:24-43`; `common.llm_chat()` returns `""` on every transport/parse failure at `DubTitlerr/common.py:410-442`).
5. Zero activation is not an error: a rule can produce zero drops, zero flags, or zero repairs and still yield a successful episode and a current sidecar.

There is no compiler-like break when a consumer disappears, and no runtime invariant saying “this configured rule must either be active, deliberately disabled, or measured as unobservable.” The system therefore confuses **successfully executed** with **still doing useful work**.

### What would catch the next one

Add one checked **pipeline contract manifest** and a CI test around it; do not rely on a general “monitoring” task.

`data/pipeline_contract.json` should declare, for each production stage:

```json
{
  "hallucination.music": {
    "owner": "hallucination.drop_reason",
    "input": ["no_speech_prob", "avg_logprob"],
    "outputs": ["drop_reason=music"],
    "consumers": ["generate.process"],
    "liveness": "must_be_measurable"
  }
}
```

The CI test should:

1. parse Python AST to verify every declared output has a writer and a named consumer or an explicit `observability_only` disposition;
2. run each branch with a minimal synthetic fixture and assert its counter/event/output is observable at the declared boundary;
3. reject a contract entry when the consumer disappears;
4. require every `observability_only` output to name the report/CLI that reads it;
5. scan `os.environ` reads and fail when a documented setting is not in the manifest or is marked `dead` without an owner.

Add one runtime counter to the existing `lastrun`/QC output: for every gated rule, record `evaluated`, `activated`, and `fallback/error`. A zero activation then reads as “zero on this model/config” rather than silently looking like a healthy rule. This would have surfaced the music branch and the unused flag consumer without depending on someone to grep at the right moment.

## ITEM 1 — Does the deterministic → LLM → human ladder hold?

**Partially. The deterministic → LLM boundary mostly holds. The LLM → human boundary does not hold for subtitle quality failures.**

### Where the ladder does hold

#### Punctuation restoration

The deterministic layer decides which work is eligible: `punctuation.find_runs()` only sends consecutive unpunctuated segment runs meeting `RESTORE_MIN_RUN` to the model (`DubTitlerr/punctuation.py:163-174`). The prompt restricts the model to punctuation/casing (`:177-190`), and `accept_restoration()` rejects word changes before `_apply()` mutates the word list (`:207-211`, `:251-266`). This is rules deciding the scope and the guard, with the LLM supplying the inference rules cannot deterministically recover.

#### Glossary acquisition and verification

The deterministic layer supplies candidate tokens, wiki candidates, recurrence counts, source provenance, expansion checks, and dominance/frequency gates. `source_gate()` prevents an unanchored transcript term from auto-applying even after LLM escalation (`DubTitlerr/glossary_acquire.py:430-466`). Low-confidence/no-match glossary decisions become `flagged`, and `--review` exposes an actual interactive human queue (`:685-745`, `:865-888`). This is the strongest implementation of the stated ladder.

#### Subtitle repair

`repair.is_target()` gates the model on speech confidence plus low log probability, low word probability, or a name suspicion (`DubTitlerr/repair.py:108-114`). It requires an overlapping fansub reference before calling the model (`:398-410`), and `accept_repair()` is a deterministic post-model gate. The model is not being asked to decide every card.

### Where the ladder fails

#### Human escalation exists for glossary terms, not for bad subtitle lines

When repair has no reference, it increments `skipped_no_ref` and continues (`DubTitlerr/repair.py:398-406`). When the model proposes a change the guard rejects, the code increments `rejected`, but the summary stores only the aggregate count and only accepted repairs in `repaired_lines` (`:451-464`). There is no per-line queue containing the original text, rejected proposal, reason, timestamp, and source window.

The same pattern appears in punctuation restoration: `_ask()` converts model/transport failure to an empty string, and `restore()` records `restore_empty` but leaves the old text in place (`DubTitlerr/punctuation.py:203-211`, `:251-259`). That is a safe fallback, but not a human escalation.

The hallucination `flag` is also not a live human queue. It is written by `generate.py` (`:640-661`), counted in QC/lastrun (`:686-704`), and read by the offline timing comparator (`DubTitlerr/tools/timing_compare.py:702-725`). No active repair, review CLI, or operator-facing report consumes flagged subtitle cards.

Therefore the actual ladder is:

```text
rules -> bounded LLM -> keep old text / write aggregate evidence
```

not:

```text
rules -> bounded LLM -> human sees unresolved cases
```

The model is not primarily “absorbing work the rules should do.” The more serious inversion is that the human stage is missing, so model refusal, model failure, no-anchor cases, and weak deterministic flags disappear into a successful-looking no-op.

#### The inert `no_speech_prob` branches do not prove the LLM layer is replacing them

The deployed-model observation that `no_speech_prob` makes `music` and `maybe_silence` ineffective is a real liveness problem for those branches, but it does not show that the LLM is now doing their work. The LLM repair gate actually treats low `no_speech_prob` as speech and proceeds to its other deterministic conditions (`repair.py:110-114`). The model may see more candidates, but the source does not measure whether those candidates are the cases the inert detector was supposed to reject.

That distinction matters: “rule inert” is not equivalent to “model substituted for rule.” It is a missing measurement and fallback-policy problem.

### The single action to restore the ladder

Create one `unresolved` queue for subtitle-quality decisions, written at the same points that currently only increment counters:

```text
stage: punctuation | repair | hallucination
reason: llm_empty | no_reference | rejected_guard | low_conf_flag | maybe_silence
original_text
proposed_text, if any
source/display timing
confidence fields
model/backend
```

Give it a small CLI like glossary `--review`, and make the per-show summary count both queue entries and resolved entries. Until that exists, the deterministic→LLM discipline is real, but the claimed three-level ladder is not operational for the subtitle path.

## ITEM 5 — Is the 63-variable configuration surface a real risk?

**Pick: real risk.** A single operator reduces process overhead, but it increases the chance that one person changes a variable without a second configuration contract or a smoke test. The dangerous property is not the number 63; it is that the same logical setting is read in different modules and orchestration layers with different defaults, overrides, and fallback behavior.

### Highest blast-radius variables

#### 1. Scope and path variables — total-work or wrong-library risk

`ANIME_ROOT` and `ANIME_ORDER` control generation in `gen_loop.sh:10-19`; `MERGE_ROOTS` controls repair/signs/mux scanning (`merge_pass.sh:13-18`, `repair.py:78`); `GLOSSARY_DIR` controls dictionary discovery. A wrong root can produce zero work while the loops remain alive, or generate sidecars in one tree while the merge loop scans another.

`SEASON_PRIORITY_FILE` changes ordering rather than correctness, but a wrong order can starve the intended watch queue for a long time. These variables need startup validation against a readable manifest and at least one expected media directory.

#### 2. Transcription identity and quality — library-wide content risk

`WHISPER_MODEL`, `MODEL_DIR`, `COMPUTE_TYPE`, `WHISPER_BEAM_SIZE`, `WHISPER_AUDIO_FILTER`, and `REQUIRE_ENG` affect every new transcript (`generate.py:74-83`, `:162`, `:573`). The Dockerfile explicitly warns that a model mismatch makes faster-whisper download a missing model rather than fail (`Dockerfile.builder:28-44`), which can turn a deployment typo into a slower or OOM-prone run.

`REQUIRE_ENG` is particularly misleading in the active loop: `gen_loop.sh:54` hardcodes `REQUIRE_ENG=1` for every `generate.py` invocation, so setting a different container-level value does not change the live generator. A variable that looks configurable but is overwritten at the call site is a configuration bug, not merely a default.

#### 3. LLM routing and admission — silent quality degradation

`REPAIR_BACKEND`, `REPAIR_LLAMACPP_URL`, `REPAIR_MODEL`, `REPAIR_MODEL_SECONDARY`, `RESTORE_BACKEND`, `RESTORE_MODEL`, `VERIFY_BACKEND`, `VERIFY_LLAMACPP_URL`, `LOGPROB_MIN`, `NSP_MAX`, and `ACQUIRE_APPLY` can alter which lines reach a model, which endpoint receives them, or whether glossary changes are written.

The routing has no enum validation: `common.llm_chat()` uses the llama.cpp path only when `backend == "llamacpp"`; every other value falls into the Ollama branch (`DubTitlerr/common.py:410-428`). A typo such as `llamacpp ` silently selects Ollama rather than failing closed. Transport errors return an empty answer (`:429-442`), and the callers treat that as “no edit,” so a dead endpoint can look like a clean run.

`ACQUIRE_APPLY` is a particularly high-consequence switch because `gen_loop.sh:31-36` turns it into `--apply`; it changes the glossary state used by later episodes. It deserves an explicit startup log and a refusal unless the operator passes an intentional apply mode.

#### 4. Mux and filesystem safety — destructive or permanently noisy outcomes

`MIN_FREE_GB`, `DUR_TOL`, `KEEP_LANGS`, `HARDLINK_ROOTS`, and `DELETE_BROKEN_HARDLINKS` affect mux acceptance and track/file handling (`DubTitlerr/mux.py:40-52`). The last variable currently has no effect because `DELETE_BROKEN` is never consumed; that is itself a risk because an operator may believe it controls cleanup.

A too-low free-space threshold can allow repeated failures or leave no recovery headroom; a too-large duration tolerance can accept a truncated remux; a wrong keep-language set can remove or retain entire classes of subtitle tracks. These need bounds and a dry-run assertion against one representative file.

#### 5. Suffix/language/refresh variables — stage-disconnect risk

`SUB_LANGS`, `DUB_SUFFIX`, `PLEX_URL`, `PLEX_TOKEN`, `PLEX_SECTION`, and `PLEX_PATH` have narrower or downstream blast radius. `DUB_SUFFIX` is especially dangerous because `dub_signs_merge.py:39-41` reads it, while `merge_pass.sh:35-41` searches and passes the hardcoded `.eng.dubtitles.srt` suffix. Changing the environment value can make the merger derive the wrong stem even though generation still writes the hardcoded suffix.

### Why this is not acceptable just because one operator owns it

A single operator can remember intended values, but cannot reliably remember which module overrides which value or which values are audit-only. The source already contains examples of that failure shape:

- `REQUIRE_ENG` is set in the live shell command rather than honored from the container environment.
- `REPAIR_BACKEND_SECONDARY` is documented but not read.
- `DELETE_BROKEN_HARDLINKS` is read but not consumed.
- unknown LLM backends silently fall back to Ollama.
- `DUB_SUFFIX` and the merge shell's suffix disagree.

These are not hypothetical multi-user coordination failures. They are single-operator state-interpretation failures.

### One concrete fix

Replace the scattered environment contract with a validated, emitted runtime manifest:

1. Define each accepted setting once in a stdlib schema (`name`, type, allowed values/range, default, owner, stage, secret/non-secret).
2. Load and validate it before either loop starts; reject unknown backends, invalid numeric ranges, missing required paths, and conflicting suffix/root values.
3. Print and persist a redacted resolved manifest beside the per-show run summary, including the source of each value: default, compose, or command-line override.
4. Add a test that loads the active production environment fixture and asserts every stage sees the same root, suffix, backend, and model identity.
5. Remove variables with no consumer instead of carrying them in documentation.

That is enough to make a one-operator system safe without requiring a configuration service.
