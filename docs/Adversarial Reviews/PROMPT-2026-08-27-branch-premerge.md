# Adversarial review — `feat/phonetic-name-guard`, pre-merge

## START NOW — do not acknowledge this brief, do not ask where the files are

You are already in the repository root. Begin reading immediately and reply only with
findings. Do not reply "I'll review this" or ask to be told to start; there is no second
message coming.

First five commands, in order:

```sh
git log --oneline -30                 # this leg is 3e39618..HEAD
git diff --stat 3e39618..HEAD
cat .procoder/specs/repair-review-and-decision-store.md   # the contract
cat merge_pass.sh container_run.sh    # short; they decide the whole lifecycle
wc -l decisions.py review_apply.py review_server.py unresolved.py repair.py mux.py
```

Everything named below is a path relative to this directory. Read the source, not this
brief, for anything you intend to cite.

> Review artifact: findings below were traced against the checkout and targeted tests were run on 2026-08-27.

## Findings

### CONFIRMED

1. **HIGH — the review server can be made to consume an unbounded POST body before authentication.**
   - **Anchor:** `review_server.py:386-410` (`Handler.do_POST`).
   - **What it does:** validates `Content-Length`, caps it at 1 MiB, reads exactly that many bytes, then dispatches to `route()` where authentication occurs.
   - **Failure:** HTTP/1.1 permits a request body to be sent using `Transfer-Encoding: chunked` without `Content-Length`. This handler returns 411, so that form is safe. However, a client can declare a valid length up to 1 MiB and keep the connection/socket occupied indefinitely while sending bytes slowly; `rfile.read(n)` has no socket/read deadline. With `ThreadingHTTPServer`, each unauthenticated connection consumes a worker thread and a request slot before `authorised()` is called.
   - **Concrete scenario:** send many POST requests with `Content-Length: 1048576` and drip one byte per minute from a LAN host. Each worker blocks in `read()` without checking a token. Enough concurrent requests exhausts server threads/file descriptors and prevents legitimate review requests. The byte cap bounds memory per request, not resource consumption or connection lifetime.
   - **Should do:** enforce a request/read timeout and a bounded number of concurrent requests, or authenticate before accepting a body through a protocol-safe mechanism. A 413/411 cap alone is not a complete unauthenticated DoS defense.

2. **CONFIRMED — the default model change is a real downstream decoder migration gap, not inert bookkeeping.**
   - **Anchors:** `common.py:138-154`, `generate.py:97-104`, `Dockerfile.builder:64-71`.
   - **What it does:** keeps `TRANSCRIBE_VERSION = 4` while changing the bare fallback and Docker build default from `large-v3` to `large-v3-turbo`.
   - **Failure:** `common.stale_tiers()` compares only the numeric stamp tier version; it does not compare the recorded `model` in `words.json` or any model identity in the `.done` stamp. A downstream install with v4 output produced by `large-v3` rebuilds and runs with turbo, but its v4 stamps remain current. Existing muxed files are skipped, and existing words caches are accepted as transcribe-current. New or otherwise stale episodes use turbo while old episodes remain large-v3, with no automatic detection or forced migration.
   - **Concrete scenario:** downstream generated `E01` under v4/large-v3, then pulls this branch and rebuilds. `stamp_valid()` still returns true for E01; `read_words()` accepts its v4 words; a later text-tier run mixes old large-v3 transcript data with new turbo-generated episodes. The review contract itself admits this at `generate.py:97-103`, but that is a code comment, not an operational migration warning in the user-facing deployment documentation.
   - **Should do:** bump `TRANSCRIBE_VERSION`, or include a cryptographic/model identity in the stamp and words-cache validity checks with an explicit migration path. Document the downstream incompatibility in the operator-facing README/release notes, not only beside the fallback constant.

3. **CONFIRMED — S-1 materially increases persistent sidecar I/O and re-run amplification.**
   - **Anchors:** `repair.py:600-859`, especially `repair.py:783-808`; `unresolved.py:122-151`.
   - **What it does:** every admitted repair appends a `repair_applied/accepted` JSONL entry, and the queue remains as a sidecar until review; repeated runs suppress only exact `(original, proposed)` pairs currently present in the queue.
   - **Failure:** this is not merely a counter change. Every admitted repair now causes a persistent file append, changes sidecar existence/mtime, affects `merge_pass.sh`'s glob-based work discovery, and may hold an opted-in episode indefinitely. If a later model/glossary/reference change produces a different proposal for the same original, the pair differs and a second pending entry is appended even though the first line is already awaiting human judgment.
   - **Concrete scenario:** run repair once with proposal `X`, then change the model or glossary so the same ASR line produces proposal `Y` before review. `queued_pairs` contains only `(orig,X)`, so `(orig,Y)` is recorded too. The reviewer sees two competing pending decisions for one card; an accept/reject of one pair does not settle the other, and a gated episode remains held. This also means the summary's `repaired` count no longer corresponds to newly changed output: it counts admitted cards on every repair rerun, while the queue has persistent historical entries.
   - **Should do:** define queue identity/merge semantics at the original-line level for pending review, or attach a run/version and make the gate/UI coalesce competing proposals. Keep separate audit history from the actionable pending worklist.

4. **CONFIRMED — the `repair_applied` queue is not synchronized with the decision store, so a saved decision can leave a gated episode held forever.**
   - **Anchors:** `review_server.py:223-245`, `mux.py:365-368`.
   - **What it does:** `handle_decide()` calls `decisions.save()` and only afterward calls `unresolved.resolve()`. If the second write fails, the decision remains durable but the queue entry remains unresolved. `mux.held_for_review()` attempts to suppress entries with matching decisions, but it calls `decisions_for(stem)` using the module's default directory and requires the glossary-resolution path to succeed.
   - **Concrete scenario:** the server successfully writes `<DECISIONS_DIR>/<show>.json`, then `_rewrite()` fails because the unresolved sidecar is read-only/full. The next mux sweep sees the unresolved entry. If its decision store is unavailable/misresolved (for example, `GLOSSARY_DIR` differs between processes), `store == {}` and the episode remains held indefinitely despite the human decision being saved. The UI has already returned an error after saving, so retrying may also replace/replay the verdict without clearly repairing the queue state.
   - **Should do:** make the pair of writes recoverable/idempotent: derive pending state from the durable decision store, or use an explicit reconciliation pass and report partial completion. Do not claim atomicity across independent files.

5. **CONFIRMED — the signs-bearing write-back path is not guaranteed to re-run repair.**
   - **Anchors:** `review_apply.py:69-80`, `review_apply.py:111-144`, `merge_pass.sh:49-53`.
   - **What it does:** write-back removes a stale `.ass`, writes an `.srt`, and drops the stamp. On the next merge pass, repair runs, then `dub_signs_merge.py` is called; `build()` returns `"no-signs"` when no source sign stream is usable, and `process_one()` leaves the newly written `.srt` in place.
   - **Concrete scenario:** an episode originally had signs, but the current media probe/extraction sees no usable source sign stream (or the only stream is filtered as the generated `Dubtitles` track). `dub_signs_merge.process_one()` returns `no-signs`/`empty` and does not remove the SRT or create an ASS. `mux.py` can still consume the SRT, so this is not necessarily a permanent data-loss state, but the episode oscillates between sidecar states and the original signs-bearing representation is not restored. If operators interpret `no-signs` as success, the human verdict is applied to dialogue while signs are silently absent.
   - **Should do:** distinguish “no source signs exist” from “sign extraction failed,” fail closed for a previously signs-bearing episode, and persist the prior source/track state.

6. **CONFIRMED — `render_page()` creates a client-side script-injection context for offered verdict text.**
   - **Anchors:** `review_server.py:318-333`.
   - **What it does:** interpolates `v` into an HTML attribute as `onclick="decide(...,&apos;{html.escape(v)}&apos;)"`.
   - **Failure:** `html.escape()` is not JavaScript-string escaping. The current built-in offered values are fixed safe constants, so an attacker cannot reach this solely through a normal stored queue entry today. But the renderer's contract accepts queue data and the code explicitly treats media/model text as untrusted; adding a future offered verdict or making offers data-driven turns a quote/backslash/newline into executable or malformed JavaScript. This is a confirmed context bug in the renderer, though currently latent under the constant `OFFERED` set.
   - **Concrete scenario:** if an entry's offered value becomes `x');alert(1);//`, the generated handler contains attacker-controlled JavaScript despite HTML escaping. Use `data-*` attributes plus event listeners or a JS literal encoder, not `html.escape()` inside a JS string.
   - **Should do:** remove inline handlers and encode values for the actual JS context.

### SUSPECTED

7. **SUSPECTED — `handle_decide()` indexes the full unresolved list while the UI displays the filtered list.**
   - **Anchors:** `review_server.py:215-245`, `review_server.py:245-257`.
   - **Why it looks wrong:** `handle_episode()` creates `entries` from `unresolved.pending(..., primary_only=...)`, but computes each displayed index with `items.index(e)`, i.e. the full-file index. `handle_decide()` separately indexes `items[index]`, so the intended mapping is currently consistent. It becomes wrong if duplicate/equal dictionaries occur or if the server changes the default filter independently; no confirmed failure was established in the current code.
   - **Scenario to validate:** two byte-identical queue dictionaries or a client retaining a stale filtered page while a new entry is inserted before submission. The numeric index can then identify a different entry than the reviewer saw.
   - **Should do:** use stable entry IDs/pair keys in the POST payload and revalidate the displayed entry before mutation.

8. **SUSPECTED — token persistence can overwrite a token file through a symlink.**
   - **Anchors:** `review_server.py:116-146`.
   - **Why it looks wrong:** `os.replace(tmp, path)` replaces the symlink itself rather than following it, so the straightforward symlink attack does not overwrite the symlink target. However, the parent token directory is created/used as root-owned shared state, and no ownership/type check is performed; a pre-existing directory or mount race may still redirect token persistence or cause denial of service. I did not establish an exploitable write-outside-directory path under the exact `mkstemp` + `os.replace` sequence.
   - **Should do:** verify directory ownership/permissions and reject symlink/non-regular token paths; use an already-open directory fd where practical.

## Inertness and interaction conclusions

- Empty decision store: **behaviorally a no-op on the repair decision branch**. `repair.process()` still calls `decisions.lookup({}, orig, proposal)` for each non-empty LLM result, then falls through to `accept_repair`; no verdict is applied. It is not byte-identical in observability: admitted repairs now append `repair_applied` entries and write additional queue sidecars, so filesystem state, merge discovery, timing, and summaries differ even when SRT text is unchanged.
- `WHISPER_MODEL` reasoning: valid only for the maintainer's already-turbo-produced 576-stamp library. It is **not** valid as a general downstream compatibility argument; the code explicitly leaves that install split undetected.
- `unresolved.record()` changes more than counters: persistent queue files and mtime are now part of the operational state.
- `review_apply.py` does not call the LLM and its conf-to-SRT rewrite does preserve the repair on the normal path because `merge_pass.sh` invokes `repair.py` afterward. For a signs-bearing episode, it only preserves that correction if signs merge succeeds; no-signs/empty/error paths leave a dialogue SRT and require explicit handling.
- The punctuation exclusion rationale is mostly correct for the current card-based S-4 implementation: punctuation restoration mutates the pre-reflow word list and `punctuation._apply()` requires token correspondence, so a generic card-level verdict cannot safely be replayed. It is not a reason to hide those entries from all actionable review forever; they remain reachable only through the unfiltered walk.

## Tests attacked

Targeted command run:

```text
pytest -q tests/test_decisions.py tests/test_unresolved.py tests/test_review_apply.py tests/test_review_server.py tests/test_mux.py tests/test_repair.py
```

Result: **all targeted tests passed**. Python AST parsing also passed for the affected modules.

The suite is strongest on pure helpers and direct handlers. It does not exercise:

- a slow-drip authenticated/unauthenticated POST or concurrent worker exhaustion;
- the partial-success ordering where `decisions.save()` succeeds and `unresolved.resolve()` fails;
- model identity changes with unchanged `TRANSCRIBE_VERSION` and existing v4 stamps;
- a signs-bearing write-back where sign extraction returns `no-signs`, `empty`, or `build-error`;
- competing proposals for one original across repair runs;
- inline-JavaScript escaping with a non-constant offered value.

Several fixtures intentionally model states the pipeline cannot normally leave behind (for example, a stamp plus ASS in `tests/test_review_apply.py:_muxed(..., ass=True)`), but the test uses that as an interrupted-between-stages state rather than as a normal completed mux state. The direct-handler tests also bypass HTTP parsing, so they cannot validate socket lifetime, request framing, or concurrency behavior.

## One change to gate/revert

**Gate the review server and pre-mux feature from production until the write path is made fail-safe and the server has request-lifetime/concurrency limits.** The most damaging current risk is not an empty-store behavior change; it is exposing a root-owned, LAN-bind HTTP server whose POST body read can tie up unbounded-duration worker threads before authentication, while its two durable writes are not transactional. A reviewer decision must never leave the system both believing it was saved and holding the episode indefinitely.

**Repo:** DubTitlerr — a pipeline that generates English "dubtitles" for anime:
faster-whisper transcription → reflow into Netflix-profile cards → per-show glossary
correction → optional local-LLM repair → mux back into the MKV.
**Branch:** `feat/phonetic-name-guard` @ `1f9298e`, 209 commits ahead of `main`.
**Suite:** 1339 passing. `procoder check` 0 blocking, `lint --types` 0, `security --deep`
0 findings in anything this leg added.

You are reviewing this branch **before it merges to `main`**. Your job is to find defects,
not to approve. A review that returns "looks good" is a failed review unless you can show
what you attacked and why it held.

---

## 1. What you are being asked to attack

The branch's newest leg (26 commits, `3e39618..HEAD`) adds a **human review loop for
LLM-repaired subtitle lines**. That is the focus. The earlier legs are in scope only where
they interact with it.

The problem it exists to solve, in the code's own words: `repair.accept_repair()` states its
acceptance bar in its docstring and then says plainly that **nothing below it enforces
that**. Two measured examples pass every mechanical gate and destroy meaning:
`"We're looking for a factory."` → `"a needle."`, and `"It's a VIVRA card?"` →
`"a Vivi card?"`. So an accepted repair is a decision no code has checked, and this leg
builds the path for a human to check it.

Nine scope items, `[S-1]`–`[S-9]`, specified in
`.procoder/specs/repair-review-and-decision-store.md` (read it — it is the contract):

| Item | What it added                                       | Files                                    |
| ---- | --------------------------------------------------- | ---------------------------------------- |
| S-1  | Queue every ADMITTED repair for review              | `unresolved.py`, `repair.py`             |
| S-2  | A per-show decision store, pair-keyed               | `decisions.py`                           |
| S-3  | Promote a term-level verdict into the show glossary | `decisions.py`                           |
| S-4  | Consult the store inside repair; apply verdicts     | `repair.py`                              |
| S-5  | Write-back for episodes already muxed               | `review_apply.py`                        |
| S-6  | Optional per-show pre-mux gate + stall alert        | `mux.py`                                 |
| S-7  | The review server (HTTP, token auth)                | `review_server.py`                       |
| S-8  | Run it as a third container loop                    | `container_run.sh`, `Dockerfile.builder` |
| S-9  | `DECISIONS_DIR` mount                               | `decisions.py`                           |

Core diff to read (3,068 insertions across 9 files):

```
decisions.py      264 (new)      review_apply.py   197 (new)
review_server.py  422 (new)      unresolved.py     282 (new)
repair.py        +690           mux.py           +389
generate.py     +1058           container_run.sh  +30    Dockerfile.builder +51
```

---

## 2. The single most important claim to falsify

**"This branch is inert in production until the owner turns it on."**

The owner has NOT yet flipped the feature on, and the merge is being made on the strength of
that claim. It rests on:

- `REPAIR_UNANCHORED` defaults off (`repair.py`), so unanchored cards are still not repaired.
- `REVIEW_GATE_SHOWS` defaults **empty** (`mux.py`), so no episode is ever held.
- `DECISIONS_APPLY` defaults **1**, but the decision store is empty on every install that has
  never reviewed anything, and an empty store is meant to be a no-op.
- `TEXT_VERSION`/`TRANSCRIBE_VERSION` were NOT bumped, so nothing re-runs across the library.

**Attack every clause.** Specifically:

1. Is an empty store genuinely byte-identical to the pre-branch behaviour, on the real path
   — not just in the test? Trace `repair.process()` from `def` to `return`.
2. `WHISPER_MODEL`'s baked default changed from `large-v3` to `large-v3-turbo` **without** a
   `TRANSCRIBE_VERSION` bump. `common.py` says a whisper-model change is decoder-affecting
   and that **nothing detects it mechanically**. The justification is that the production
   image has been turbo-built since a hardware swap, so the library's 576 v4 stamps were
   produced by that decoder already. Is that reasoning sound? What happens to a DOWNSTREAM
   install that built on the old default and then rebuilds — and is the residual gap
   documented where someone would find it?
3. `unresolved.record()` now fires on an additional path (every ADMITTED repair, not only
   refusals). Does that change any counter, sidecar, summary, or timing that something else
   consumes?

---

## 3. Interactions — where every real defect in this leg was found

Every serious bug found during development was in an **interaction**, never in a diff. Five
subagent review rounds found: a secondary model silently overwriting human verdicts; a
verdict re-judged and silently reverted on later runs; a module that could not run on a
single real episode; a hold that could never be escaped; a body-size cap that did not bound
anything. None were visible from the changed lines alone.

So trace these end to end, in the code, not from the docs:

**A. The full episode lifecycle.** `merge_pass.sh` → `repair.py` → `dub_signs_merge.py` →
`mux.py` → (`review_apply.py`) → back to `merge_pass.sh`. Note that `merge_pass.sh` finds
work by GLOBBING for sidecars, `mux.py` DELETES both sidecars when it stamps, and
`dub_signs_merge.build()` has an early return that writes no `.ass`. Which states can an
episode get stuck in, or oscillate between? What runs more than once that assumes it runs
once?

**B. Two stores of "settled".** `unresolved.resolve()` sets a flag on a queue entry;
`decisions.record()` writes the verdict `repair.py` actually consults. They are independent
writes. Find every place that trusts one and not the other.

**C. Anything that assumed a state was brief.** `[S-6]` can hold an episode indefinitely.
Sidecars that were always transient now persist. What else in this pipeline assumed an
episode moves on promptly?

**D. The `(original, proposed)` key.** Verdicts are keyed on a normalised text pair
(`decisions.key`). When does a key stop matching what it was recorded against — a glossary
edit, a model change, a re-transcription, punctuation? Is a miss always a safe no-op, or is
there a path where a stale verdict is applied to the wrong line?

---

## 4. Security — `review_server.py`

Assume the hostile case, because it is the real one: the container **runs as root** (so
`generate.py` can chown into the media tree), `[S-8]` puts this server in that process tree,
its write routes rewrite subtitles and force re-muxes of multi-GB files, and a downstream
user may run with host networking, so treat the port as LAN-reachable.

Stated posture: `REVIEW_TOKEN` unset **generates** a token (0600, printed once); only
`REVIEW_TOKEN=` set explicitly empty disables auth; reads ungated, writes always gated;
comparison constant-time; a `stem` is a file path and is accepted only if it is in the set
discovered by walking `MERGE_ROOTS`.

Attack: auth bypass; anything reachable **before** the auth check; path traversal and
symlinks; resource exhaustion from an unauthenticated request; the token's lifetime,
persistence and failure modes; XSS and injection in `render_page` (HTML text, HTML
attribute, JS string and URL query are four different contexts); TOCTOU between the
allow-list walk and the write.

**Use this question on every guard, not only the mutation question:** _what input makes the
guard PASS while the property it protects is FALSE?_ That question — and not "what change
breaks this test" — is what found the highest-severity defect in this leg.

---

## 5. Tests — assume they are the weakest part

The suite is large and green, and that has already been misleading three times. Known
failure modes in this repo's own tests, all found after the fact:

- A fixture that hand-wrote `conf.json` + `.srt` + stamp **together** — a combination this
  pipeline never produces, because `mux.py` deletes the sidecars when it stamps. Five green
  tests proved nothing.
- Assertions on `conf.json`, which `repair.py` mutates **in memory only** and never writes
  back, so the assertion passed whether or not the repair shipped.
- An assertion on a full string that `reflow.wrap_balance` always breaks with a newline, so
  it passed unconditionally.
- A test enforcing a rule over a LIST that checked each item's dependencies and never the
  list's own membership.

Find more. For any test you doubt, name the production mutation that should break it and say
whether it does. Flag any fixture describing a state the pipeline cannot produce.

---

## 6. Claims I already got wrong — check my corrections, don't redo the work

Recorded so you do not spend effort re-deriving them, and so you can check whether the
**corrections** are right:

1. I claimed `[S-5]` rebuilding from `conf.json` would revert every LLM repair in the
   library. **Wrong** — `merge_pass.sh` re-runs `repair.py` immediately afterwards, which
   re-derives them and applies the verdicts. _Is that correction actually right in every
   path, including a signs-bearing mkv?_
2. I claimed the `[S-6]` stall alert could fire, having read `dub_signs_merge.py` from the
   middle and missed an early `return "no-signs", 0, 0`. **Wrong** — repair did re-run every
   sweep. Fixed by suppressing a re-queue of a pair the queue already holds. _Does that
   suppression itself have a hole — can a line that SHOULD be re-queued now never be?_
3. `punctuation`/`rejected_guard` is deliberately excluded from the default review view. The
   stated reason is that a reviewer's verdict has nowhere to go: `accept_restoration` is
   word-identity, not judgement, and `punctuation._apply()` requires exact token
   correspondence. _Is that reasoning correct?_

---

## 7. What to hand back

A numbered list, ordered by severity, splitting **CONFIRMED** (you traced it in the code and
can name the failing input) from **SUSPECTED** (it looks wrong, you could not confirm).

For each: `file:line`, what the code does, what it should do, and **a concrete failing
scenario** — the input or sequence of runs that produces the wrong outcome.

Three rules, because this repo's norm is that claims get attacked:

- **Verify every line number you cite.** A previous external review of this repo produced
  nine `file:line` anchors and every one was wrong, while its substantive reasoning was
  sound. Wrong anchors cost more than they are worth.
- **If you cannot confirm something, say SUSPECTED.** A confident wrong finding is worse
  than an admitted uncertainty; two of the three errors in §6 were exactly that.
- **Do not report style, naming, or "consider adding a docstring".** Correctness,
  interaction, security, data loss, and test honesty only.

Finally: name the ONE change on this branch you would most want reverted or gated before it
reaches a library of 20,000 episodes, and say why.
