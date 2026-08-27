# GPT-5.6 Luna — adversarial review of `feat/phonetic-name-guard` (pre-merge)

Run 2026-08-27 against `1f9298e` from the prompt in
`PROMPT-2026-08-27-branch-premerge.md`. GLM 5.3 Flash is rebutting it separately.

VERBATIM AND UNAUDITED. Every claim below still needs checking against the source before it
is acted on; this repo's norm is that a review's reasoning and its `file:line` anchors are
judged separately, and a previous external round produced nine anchors that were all wrong
while its reasoning was sound.

Recovered from inside `PROMPT-2026-08-27-branch-premerge.md`, where the review was written
in place rather than to its own file. Attribution is the owner's account of which tool was
running, not something derivable from the text.

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
