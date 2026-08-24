# DubTitlerr — whole-project review brief

Prepared 2026-08-21 for an external architectural review. The reviewer has **no access to the
source**, so every claim here is stated so it can be challenged on its own terms, and file:line
references are given where a claim rests on specific code.

---

## 1. What the system is

A self-hosted pipeline that watches an anime library and, for each episode carrying an English
dub, produces an English subtitle track derived from **the dub's own audio** ("dubtitles") —
not from the Japanese-derived fansub, whose wording differs from what the dub actually says.

Per episode:

    transcribe (faster-whisper)
      -> punctuation restoration (local LLM, on the WORD LIST, before any splitting)
      -> reflow  (words -> timed cards; runt cascade; layout)
      -> glossary name correction (mined + wiki-verified, deterministic)
      -> hallucination gate (drop / flag)
      -> repair (local LLM, only where a fansub anchor exists)
      -> merge signs & songs track
      -> mux back into the MKV as a default `Dubtitles` track
      -> Plex refresh

Idempotency is a single sidecar, `<stem>.dubtitles.done`, holding
`{size, mtime, muxed, version}`. `stamp_valid()` is the only skip guard; bumping
`PIPELINE_VERSION` marks the whole library stale.

## 2. Scale

    17 Python modules      ~5,200 LOC
    23 test files           9,242 LOC     1,045 tests, all passing
    9 shell scripts         (only 3 reach the image — see §6.1)
    63 environment variables read across the codebase
    250 commits, 12 branches
    9 design specs in docs/superpowers/specs/ (Jul 26 - Aug 21)

Deployment: one container running two loops in parallel (`container_run.sh`) — a GPU generate
sweep and a CPU/LLM merge sweep every `MERGE_INTERVAL` (600 s). Currently on a Ryzen 3 3200G
node with a GTX 1050 Ti 4 GB, running `large-v3-turbo`.

## 3. Standing architectural principle

The owner's stated default for every project: **deterministic → LLM → human**. Rules decide
everything rules can decide; the model sees only what rules cannot settle; a human sees only
what the model cannot. Each layer records why it escalated.

**A central review question is whether this codebase actually honours that, or merely says so.**

## 4. Load-bearing invariants

Worth attacking, because much of the design hangs off them:

1. **A caption may be late, never early.** `reflow` may move a card's start later or its end
   earlier, never the reverse, because an early reveal spoils a punchline.
2. **Timing is immutable in repair.** `repair.py` may rewrite text but never re-time; when a
   repair doesn't fit the card, the repair gives way, not the timing.
3. **Never delete known-good output before its replacement exists.** Stale sidecars are
   _parked_ (renamed `.stale`), not removed. Writes are temp-file + `os.replace`.
4. **The LLM may never originate a proper noun.** The wiki owns every canonical string; the
   transcript only decides which entities to ask about. Repair without a fansub anchor is
   restricted to punctuation/casing, guarded by a deterministic token-identity check.
5. **Lost content is worse than noise.** From a revert message: _"An early caption is noise a
   viewer can ignore; a caption that never covers its line is lost content. That is the worse
   failure."_ This is the tie-breaker used throughout.

## 5. What today's investigation established

Full detail in `2026-08-21-vad-hang-trim-design.md`. Summary of the findings that bear on
architecture rather than on the one feature:

**5.1 Three rules in the hallucination gate; one has never fired.**
`drop_reason` has `blocklist`, `repetition`, and `music`. The `music` rule
(`no_speech_prob > 0.95 AND avg_logprob < -2.0`) caught **exactly zero** cards across 859
episodes / 353,879 cards — the observed nsp ceiling is ~0.95. It was loosened to 0.90 today,
then reverted once a labelled set showed the looser setting deletes 25 real cards to catch 6
hallucinations.

**5.2 A written field that nothing reads.** `flag_reason` produces `low_conf` / `maybe_silence`
onto every card and into `conf.json`. Grepping every module: **no downstream stage consumes
`flag`.** `repair.py` re-derives its own targets with its own thresholds. So one of the gate's
two outputs is decorative.

**5.3 The current model cannot produce one of the gate's two inputs.** `large-v3-turbo`'s
`no_speech_prob` is collapsed to ~1e-10 on every card (verified identical across two
independent CT2 conversions, so it is the distilled decoder, not packaging). Both nsp-based
rules are therefore inert on the model now in production.

**5.4 Detection is bounded by prevalence, not signal.** On a labelled set of 207 certain
hallucinations vs 57,572 real cards, the best discriminators are `no_speech_prob` (0.929
separation) and `avg_logprob` (0.913) — both already in the pipeline. Twelve additional audio
features were measured; the best reached 0.894, below `avg_logprob`. Yet **precision never
exceeds ~20% at any operating point**, because positives are 0.31% of cards. More features
cannot fix this.

**5.5 Two silent-degradation bugs, same shape.** (a) A compose file declared
`WHISPER_MODEL: large-v3` while the image carried only turbo — faster-whisper does not error on
a missing model, it _downloads_ it, on every container start. (b) A Docker volume's
`driver_opts` fix sat in the compose for two days doing nothing, because Docker never re-reads
them for an existing volume. Both were configuration that _looked_ applied and was not.

**5.6 A rendering bug that also disabled a correction layer.** `reflow._text()` joined
whisper's word tokens with spaces, so a hyphenated word split into two tokens rejoined as
`"Gas -Gas"`. That is cosmetic on its own — but `glossary.correct()` matches with
`\b<escaped>\b`, so every hyphenated canonical term silently failed to match. Fixed today.

## 6. Suspected debt, not yet acted on

**6.1 Six of nine shell scripts are vestigial.** Only `container_run.sh`, `gen_loop.sh` and
`merge_pass.sh` are COPY'd into the image. `all_seasons.sh`, `anime_library.sh`,
`merge_watcher.sh`, `post_season.sh`, `post_show.sh` are host-era leftovers; `run-dub-merge.sh`
is referenced by nothing at all.

**6.2 A 63-variable configuration surface** with no single schema, no validation, and defaults
scattered across modules. Several are audit-only labels that are never sent anywhere
(`REPAIR_MODEL`, `VERIFY_MODEL` on the llama.cpp path).

**6.3 Two parallel spec systems.** `specs/` (older) and `docs/superpowers/specs/` (current).

**6.4 285 of 861 sidecars are orphaned** because an external transcoder renamed the videos.
Since idempotency keys on the filename stem, those episodes read as never-processed and are
queued for full re-transcription (~12 GPU-hours of redundant work). The pipeline has no
detection for "my sidecar's video was renamed."

**6.5 No cross-host locking.** `flock|fcntl|lockfile|O_EXCL` matches nothing. Two workers on
one library would race on `<stem>.muxtmp.mkv`. Currently mitigated only by convention (one
worker at a time).

## 7. What I want from this review

Ranked. The reviewer has one session.

1. **Does the deterministic → LLM → human ladder actually hold?** §5.2 and §5.3 suggest the
   deterministic layer has accumulated rules that are decorative or inert while the LLM layer
   was extended. Is the ladder inverting in practice?
2. **What else is dead?** §5.1, §5.2 and §6.1 were all found by accident today, each while
   looking for something else. Three independent dead paths in one day suggests a systemic
   gap — most likely that nothing ever asserts a rule still fires. What would catch the rest?
3. **Is `PIPELINE_VERSION` the right idempotency key?** It is global: any bump invalidates the
   entire library, forcing full re-transcription even for changes that affect only text
   (§5.6's glossary fix needs no re-transcription, only a re-mux). Combined with §6.4 this is
   the largest recurring cost in the system.
4. **Where is the next §5.5?** Two silent-degradation bugs surfaced today, both "configuration
   that looks applied but isn't." Where else can this codebase or its deployment lie about its
   own state?
5. **Is the 63-variable surface (§6.2) a real risk or acceptable for a single-operator system?**
   Argue it either way, but pick one.

**Please do not** re-derive the VAD hang-trim design; it has its own adversarial review. Treat
it as one data point about how decisions get made here, not as the subject.
