# LUNA final adversarial review — repository-wide public-beta readiness

Target reviewed: `3e4824d` (`de4f49e..HEAD`, 14 commits on `feat/review-sorting`).

## Verification gate

The required changed-checkout run completed with **0 test failures**. Ruff also completed
with **0 violations**. The target snapshot contains 1,316 `test_*` functions by source
count. The checkout was subsequently reset by another process to `de4f49e`; all source
anchors below were therefore re-read from the immutable `3e4824d` Git snapshot, not from
the mixed live worktree.

## Pass One — Findings

### Confirmed

1. **P1 — Song-span policy is not propagated to already stamped output.**

   **Location:** [common.py:143-162](../../common.py:143), [mux.py:455-479](../../mux.py:455),
   [dub_signs_merge.py:123-129](../../dub_signs_merge.py:123).

   `TEXT_VERSION` explicitly covers the merge stage, but it remains `8`, while the new
   song policy is implemented after the existing v8 output was produced. A v8 episode with
   a valid `.dubtitles.done` stamp takes mux's `already-muxed` path and has no sidecar for
   `dub_signs_merge` to rebuild. Its old whisper song cards and missing fansub translation
   remain in the shipped track.

   **Failing scenario:** an existing SAO S01E02 has a current v8 stamp. Deploy today's
   code and run the normal loop. The episode is skipped; it does not acquire the new
   song-span drop or restored translation. The production verification quoted in the todo
   cannot mean that the existing library was corrected unless those episodes were
   explicitly reopened or a text-version migration was run.

   **Should:** either bump the text output version and document the watch-gated migration,
   or explicitly record and execute a targeted reopen of affected episodes. The changelog
   should say that the behavior is forward-only if that is intentional; it currently lists
   the fix without stating that existing stamped output is unchanged.

   **Disposition:** **P1** — existing users can continue shipping the exact hallucinated
   song output this change claims to fix; this is a material correctness gap, not merely
   release bookkeeping.

2. **P1 — `review_apply` and `repair` do not implement the same word-window contract, and
   Apply can crash on a valid untimed word record.**

   **Location:** [review_apply.py:121-137](../../review_apply.py:121),
   [repair.py:401-415](../../repair.py:401).

   `repair._card_words` deliberately excludes words unless both timestamps are present and
   applies `reflow.EPS` at both boundaries. `review_apply` independently filters with
   `w.get("start", 0) >= start and w.get("end", 0) <= end`. A persisted `words.json` is
   allowed to contain `None` timestamps: the reflow data contract and the transcription
   adapter permit that, and repair's helper is specifically written to handle it. The
   inline Apply filter compares `None` with a float and raises `TypeError` before
   `find_legal_split` can use its fallback. Even when timestamps are numeric, boundary
   values inside `EPS` can make the two writers choose different word sets and therefore
   different duration allocation.

   **Failing scenario:** a muxed episode has a human correction too wide for one cue and a
   `words.json` entry `{start: 12.0, end: None}` in that card. The review server's Apply
   endpoint calls `review_apply.apply_episode`; the list comprehension at line 134 raises,
   so no SRT is written and the stamp is not dropped. The same correction through
   `repair.process` would exclude the untimed word and fall back proportionally.

   **Should:** call one shared helper from both writers, or make the inline implementation
   reproduce `_card_words` exactly. A focused test must use a persisted word record with
   missing timestamps and assert that Apply degrades to proportional splitting rather than
   crashing.

   **Disposition:** **P1** — a core human-review write path can fail on a production-valid
   sidecar shape, leaving the reviewed correction out of the video; the blast radius is
   limited to split-requiring corrections, so it is not P0.

3. **P2 — The acquisition cache permanently memoises transient LLM failures as decisions.**

   **Location:** [glossary_acquire.py:350-373](../../glossary_acquire.py:350),
   [glossary_acquire.py:394-404](../../glossary_acquire.py:394),
   [acquire_cache.py:89-108](../../acquire_cache.py:89).

   `adjudicate_merge` returns `{"same_entity": False, "confidence": "none"}` for an
   unavailable, empty, malformed, or unparseable LLM response. `escalate` then stores that
   result in the per-pair cache. On the next run, `escalation_for` returns the non-empty
   dictionary, so `if not adj` is false and the LLM is never retried. There is no TTL,
   failure marker, cache version, or automatic invalidation.

   **Failing scenario:** a transient Ollama/llama.cpp outage occurs while the pair
   `Dothamingo -> Doflamingo` is being escalated. The pair is saved with confidence
   `none`. The backend is healthy on every later sweep, but the cached `none` keeps the
   proposal in its pre-escalation state forever. `ACQUIRE_NO_CACHE=1` is a manual escape
   hatch, not recovery behavior, and the normal `gen_loop.sh` invocation does not set it.

   **Should:** cache only parsed adjudications that are eligible for reuse, or record a
   retryable failure separately and retry it on the next run. The existing tests verify
   that low-confidence/negative answers are cached, but do not distinguish a valid model
   answer from a transport or parse failure.

   **Disposition:** **P2** — it silently strands valid glossary candidates rather than
   shipping corrupted subtitles; the impact persists until an operator knows to clear or
   bypass the cache, so it is more than a performance issue.

4. **P2 — `--pin` can bypass the zero-match refusal by inserting a nonexistent directory.**

   **Location:** [watch_queue.py:179-193](../../watch_queue.py:179).

   `match_dirs` returns only library directory names, but `build` inserts every pin after
   matching without validating it against `order` or the library directory list. Thus the
   new `if not order` refusal in `watch_queue.main` is defeated by any invalid pin.

   **Failing scenario:** WatchState reports only `One Pace (renamed)`, the library contains
   only `One Pace`, and the operator leaves `--pin One Pace` in the configured queue. The
   source data has real entries, matching produces no directory, and the pin is inserted as
   `One Pace`; `main` writes it successfully. `gen_loop.sh` then skips the nonexistent
   directory on every pass. An arbitrary typo in a pin has the same effect and can replace
   a previously useful order file with a queue containing only missing paths.

   **Should:** resolve pins through the same exact/clean/fold matching used for source
   titles, reject ambiguous or missing pins, and include only actual library directories in
   the returned order. The refusal should remain active when all source matches fail.

   **Disposition:** **P2** — it causes a recoverable queue starvation/configuration failure,
   not media corruption, but it directly weakens the behavior shipped to prevent silent GPU
   idling.

5. **P2 — Applying a `reject` verdict needlessly reopens and re-muxes the episode.**

   **Location:** [review_apply.py:121-145](../../review_apply.py:121).

   `changed` increments for any `decisions.for_orig` hit. That includes `reject`, which
   intentionally leaves the ASR text unchanged. `apply_episode` nevertheless writes a new
   SRT, drops the ASS if present, and drops the mux stamp, forcing the merge loop through a
   full remux. The same applies to any already-shipped verdict whose output is unchanged;
   the `at` timestamp is not read to determine whether the verdict is newer than the last
   mux.

   **Failing scenario:** a reviewer rejects an admitted repair in an already-muxed episode.
   `for_orig` returns the reject, `changed` becomes 1, and Apply reopens the episode even
   though `want` remains the original text. A multi-gigabyte remux follows with no visible
   text change. Repeating the same review sweep repeats the cost because the queue/store
   decision remains present.

   **Should:** classify verdicts by whether they can change the emitted text before
   reopening. A reject is a no-op for this write path. For accepted repairs, an explicit
   shipped-state check is needed before using `at` as an optimization; the previous
   measurement showing corrections missing after mux means mtime alone cannot be trusted
   as a correctness proof.

   **Disposition:** **P2** — the defect is bounded to unnecessary I/O and latency and does
   not by itself alter subtitle text; it is not P1 unless the remux cost causes operational
   outage.

6. **P2 — `review_apply` selects the first correction for an original line while `repair`
   selects the newest dated correction.**

   **Location:** [review_apply.py:121-137](../../review_apply.py:121),
   [decisions.py:160-185](../../decisions.py:160).

   The decision store deliberately permits multiple corrections for one `orig` when the
   proposed sides differ, and `decisions.corrected_text` chooses the maximum `at` value.
   `review_apply` instead uses `next(...)` over file order. It can therefore write an older
   human wording into the reopening SRT. A subsequent normal repair pass often masks this
   by calling `corrected_text` again, but a crash, manual mux, or an interrupted stage can
   ship the stale intermediate wording, and the two writers plainly disagree about which
   human decision is authoritative.

   **Failing scenario:** the store contains dated `correct` entries for the same original,
   first `old wording` at `100`, then `new wording` at `200`, against different proposals.
   `apply_episode` writes `old wording`; `repair.process` would choose `new wording`.
   If the merge pass stops after the reopened sidecar is written, the visible artifact is
   the wrong human decision.

   **Should:** use `decisions.corrected_text(store, orig)` in `review_apply` as well, and
   add a test with two dated corrections in reverse list order.

   **Disposition:** **P2** — normal end-to-end reruns commonly repair the intermediate
   artifact, so this is not a guaranteed wrong final track; it remains a real write-path
   contract violation with a recoverable interruption window.

### Suspected

7. **SUSPECTED — the auth-disabled startup warning does not recognize every possible
   wildcard spelling.**

   **Location:** [review_server.py:178-204](../../review_server.py:178).

   The warning fires only when the bind string is exactly `0.0.0.0`. It would not fire for
   `::` or a hostname that an operator believes resolves to all interfaces.

   **Failing scenario:** an operator sets an empty `REVIEW_TOKEN` and configures a wildcard
   IPv6 bind; the startup warning is absent even though the operator intended an open
   listener.

   **Disposition:** **P3 preliminary** — this is an advisory visibility gap, not an auth
   bypass, and the runtime's `HTTPServer` is IPv4-oriented, so the actual reachability of
   the `::` scenario was not established.

## Pass Two — Rebuttal

1. **Song version propagation:** The strongest defense is that the owner may intentionally
   want a forward-only change and can reopen selected episodes later. That makes the
   changelog omission a documentation problem, not an unsafe automatic migration. It does
   not rescue the factual claim that existing stamped output receives the fix: it does not.
   **Survives P1** for a public beta because the measured production case remains wrong for
   existing users; downgrade only if forward-only behavior is explicitly accepted and the
   affected-library migration is part of the launch procedure.

2. **Split writer divergence:** The strongest defense is that `repair._card_words` itself
   already excludes missing timestamps and `card_split._duration_split` has a proportional
   fallback. That is exactly why the independent Apply filter is wrong: it prevents the
   fallback from being reached. The `EPS` difference also produces a genuine boundary
   mismatch. **Survives P1.** The separate `fits_card` leniency branch does not admit an
   over-CPS output by itself: `find_legal_split` validates both halves with
   `layout_faults`, including CPS. A mixed original that is over CPS may split only when
   the human replacement's own halves are legal; that is not an over-CPS output silently
   passing.

3. **Failed acquisition cache:** A pair-level cache is the right shape for a successful
   adjudication, and keeping a valid low-confidence answer can avoid repeated work. The
   failure result is different: it is not an adjudication and the code has no way to tell
   it apart. A manual `ACQUIRE_NO_CACHE=1` escape exists, and acquisition is dry-run by
   default, so this is not data corruption. **Survives, downgraded from a possible P1 to
   P2.** It strands candidates and can prevent a later human-visible acquisition outcome,
   but does not directly rewrite subtitle text.

4. **Invalid pin:** A pin is intentionally an operator override, so inserting it is not
   surprising if the operator knowingly wants a show that will appear later. The CLI help
   says “always queue this show,” not “validate it now.” However, a typo and a renamed
   directory are indistinguishable from an intentional future path, and `gen_loop.sh`
   silently skips missing entries. The new zero-match guarantee is therefore not true for
   the actual CLI behavior. **Survives P2.** Valid pins do not block valid non-pinned shows;
   the starvation is specifically an invalid or stale pin bypassing the empty-result guard.

5. **Apply cost:** The strongest defense is correct: mtime is not proof that a previous mux
   contains the approved proposal, and the measured 11/20 missing-correction result means
   a broad “already shipped” optimization could strand a real correction. That defense does
   not apply to `reject`, whose output is definitionally unchanged. **Survives P2**, narrowed
   to no-op verdicts and not upgraded to a general “trust `at`” prescription.

6. **Newest correction selection:** The normal merge path often overwrites the stale
   intermediate with the newest `corrected_text`, and the common case has one correction per
   original. That limits the observable damage. It still contradicts the decision module's
   explicit timestamp rule and can matter across an interrupted write/rebuild boundary.
   **Survives P2**, not P1.

7. **Wildcard warning:** The warning is advisory and never intended to enforce security;
   callers that construct a server without `serve()` can bypass the log by design. More
   importantly, `http.server.HTTPServer` uses an IPv4 address family here, so `::` was not
   established as a valid open bind for this implementation. A hostname resolution policy
   is also outside what this string comparison can know. **Withdrawn.** The safe conclusion
   is to keep the warning finding as a test gap, not a beta-readiness defect.

## Closing Ledger

### Verified in this checkout or from the immutable target

- The changed checkout's `.venv/bin/python -m pytest -q` completed with zero failures.
- `.venv/bin/ruff check .` completed cleanly.
- The card-split fixture was independently evaluated with the real `reflow` functions:
  the 84-character text has `wrap_balance` output with one `over_line_len` fault at 10
  seconds, and `find_legal_split` returns two legal pieces with the configured minimum gap.
- The lock is correctly placed on a stable sidecar inode. `os.open(..., O_CREAT | O_RDWR)`
  is sufficient for first creation: racing callers refer to the same pathname/inode and
  `flock(LOCK_EX)` serializes them after open. `O_EXCL` is not needed for lock correctness.
- The old per-token cache shape is treated as a miss by `escalation_for`; no target-code
  caller was found that expects the deleted verdict API. The rewrite is not equivalent to
  recycling old verdicts, but it intentionally removes final-verdict caching so every token
  reaches proposal/source gating again.
- `c["_split"]` is transient. After it is set, `repair.process` only uses it while writing
  the SRT; the `conf` object is not serialized or passed into another summary/log writer.
- `DUR_TOL` compares video duration, not subtitle cue count. Splitting one SRT card into
  two cues does not itself affect that mux check, and the merge count reports emitted cues.
- Valid pins do not starve valid non-pinned matches; the defect is the unvalidated pin path.

### Not verified here

- No GPU transcription, live LLM backend, or production remux was available.
- No access to `vm102` or `fasc` was available. The SAO S01E02 numbers in the closed todo
  remain an uncommitted, one-off production-container verification, not a reproducible
  repository test. The current synthetic song tests prove classification on their fixture,
  not the 25-card/7-style production claim.
- No production release with a slow ballad, spoken-word bridge, narration over an OP, or
  an OP/ED pair separated by less than two seconds was available. The song-span defect is
  nevertheless reproducible from the pure function: two kept song events `[0,1000]` and
  `[2500,3500]` merge to `[0,3500]`, so a dub cue in `[1800,2200]` is dropped despite not
  overlapping either event.

## Finding Tried Hardest to Break

The hardest finding was the card-split interaction. I checked the independent fixture
against the actual wrapping/layout code, traced both call sites, tested the missing-timestamp
shape against the split fallback, and examined the mixed `over_line_len` plus `over_cps`
case. The split algorithm itself rejects halves whose resulting CPS is over the profile;
the surviving defect is narrower and more concrete: `review_apply` can raise before that
fallback, and its numeric window is not the same as `repair`'s. It survived at P1.

## Beta Verdict

**Not ready to announce a public beta this week.** The full suite is green, and the lock,
cache-shape migration, valid queue refusal, transient split marker, and mux duration
interaction are defensible. The remaining blockers are user-visible correctness failures:
existing stamped episodes do not receive the song policy, Apply can fail on valid word data,
and a rejected review can spend a full remux for no output change. The unrepeatable SAO
production claim also needs a committed or reproducible production-shaped verification
before advertising the new song behavior.

Of everything shipped today, the **one change I would require gated or re-tested before
beta is the new `_song_spans` drop**. It deletes dialogue from a blanket time interval, its
2-second merge assumption has no slow-song or inter-song regression test, and its production
verification is a scratch run that cannot be repeated from this repository. Re-test it on
multiple real releases, including narration over a song and short OP/ED separation, and
ensure the affected existing output is deliberately reopened or explicitly declared
forward-only.
