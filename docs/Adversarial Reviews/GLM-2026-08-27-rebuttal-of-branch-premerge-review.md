# Rebuttal — `feat/phonetic-name-guard` pre-merge review

> Rebuttal artifact: answers
> [`PROMPT-2026-08-27-branch-premerge.md`](PROMPT-2026-08-27-branch-premerge.md)
> finding by finding. Traced against the checkout at `1f9298e`; all 266 tests in the seven
> named test files were re-run green on 2026-08-27. Every `file:line` below was re-verified
> against the current checkout; three of the review's own anchors were wrong and are
> corrected inline.

Verification basis: every file in the review's required list was read; all 266 tests in
`test_decisions.py`, `test_unresolved.py`, `test_review_apply.py`, `test_review_server.py`,
`test_mux.py`, `test_repair.py`, `test_dockerfile_copy.py` pass (`pytest -q`, 266 passed,
0 failed); two targeted probes were run outside the repo: (a) the browser's
attribute-then-JS double decode of `review_server.py:320-322`, (b) `http.server`'s
timeout/threading defaults.

## Executive conclusion

**Recommendation: Merge only after code fixes** — one small fix, in the review server.

- **Conceded and gating:** Finding 1 is real. `BaseHTTPRequestHandler.timeout` is `None`
  (verified), so `rfile.read(n)` at `review_server.py:402` blocks forever and
  `ThreadingHTTPServer` (`review_server.py:416`) spawns unbounded daemon threads — an
  unauthenticated LAN client can pin workers indefinitely. Fix is ~3 lines.
- **Rejected as stated:** Finding 4's "held forever" and Finding 5's "not guaranteed to
  re-run repair"/"signs silently absent" do not survive the trace. `mux.py:365-369` makes
  the durable verdict — not the queue flag — the hold's authority, and `merge_pass.sh:52`
  re-runs repair on every write-back pass.
- **Downscoped:** Finding 2 is a downstream-only documentation gap (the maintainer's 576 v4
  stamps are turbo-produced); Finding 3 is the designed S-1 contract plus one real CLI gap;
  Finding 6 is a latent renderer bug that no current input can reach (`OFFERED` is a closed
  constant set, `review_server.py:94-101`).
- **Invalid:** Finding 8 — `os.replace` renames the directory entry and does not follow a
  symlink; the reviewer's own body concedes no exploit was established.
- **Answers to A–I** are folded into the findings below; the empty-store claim survives for
  shipped bytes and is correctly *not* claimed for observability.

## Finding-by-finding rebuttal

### 1. Unbounded POST body before authentication (slow-drip) — **VALID**

**Verdict:** The mechanism is confirmed exactly as described; the impact is
availability-only, LAN-scoped, and does not reach data or auth.

**Production trace.** `Handler.do_POST` (`review_server.py:386-410`) validates
`Content-Length` (411 on absent/negative/unparseable, 413 on >1 MiB — all before any read),
then `self.rfile.read(n)` at `:402`, then `route()` at `:404`, where `authorised()` runs
first (`:277-278`). The handler class (`:361`) sets no `timeout`; verified live:
`http.server.BaseHTTPRequestHandler.timeout is None`, and
`ThreadingHTTPServer.daemon_threads is True` (`:416`). So each slow connection holds one
thread + one fd + ≤1 MiB buffer with no deadline. Distinguishing production from test: the
transport tests (`tests/test_review_server.py:425-510`) drive `do_POST` with a fake
`rfile`, so framing is covered but socket lifetime and concurrency are not.

**Attack reconstruction.** N LAN connections declaring `Content-Length: 1048576`, dripping
bytes: each worker blocks in `read()` indefinitely; the review server becomes unresponsive
until the drip stops. It **does** produce the claimed worker exhaustion. It does **not**
produce anything else: no auth bypass, no write, no subtitle mutation; the merge and
generate loops are separate processes and survive (`container_run.sh:15-19, 29`; the server
is a restart-wrapped subshell at `:22-27`, so even a killed server self-heals in 15 s).

**Rebuttal.** None on mechanism — conceded in full. Severity correction: this is a DoS of a
single-user review convenience whose failure the spec already declares non-fatal ([S-8]);
the review's closing claim that this is "the most damaging current risk" to a 20,000-episode
library overstates it — it cannot corrupt data, release a hold, or end the container.

**Required action:** Code fix required (pre-merge). `timeout = <n>` on `Handler`
(StreamRequestHandler applies it to the socket in `setup()`, so `read()` raises and the
thread frees), optionally a concurrency bound.

**Confidence:** HIGH.

### 2. Default model change without a `TRANSCRIBE_VERSION` bump — **PARTIALLY VALID**

**Verdict:** Mechanically true and correctly scoped by the reviewer's own Section B, but it
is a downstream documentation/migration gap, not a production defect, and the review's
`common.py` anchor is wrong.

**Production trace.** `TRANSCRIBE_VERSION = 4` (`common.py:154`); `stale_tiers()`
(`common.py:291-311`, **not** `common.py:138-154` as cited — that range is the
version-history comment) compares only numeric tier versions; `stamp_valid()`
(`common.py:313-321`) and `read_words()` (`common.py:163-196`, transcribe-version check
only) consult no model identity anywhere. The fallback is `generate.py:104`
(`large-v3-turbo`), the baked default `Dockerfile.builder:53-54` (**not** `:64-71`),
pinned together by `tests/test_dockerfile_copy.py:104-121`. The known-gap comment is at
`generate.py:95-103`.

**Attack reconstruction.** A downstream install whose v4 stamps came from `large-v3`
rebuilds: stamps stay valid, muxed episodes are skipped, new episodes transcribe with
turbo, and nothing detects the split. Confirmed — no input needed beyond the rebuild.

**Rebuttal.** Two premises need correction. First, scope: for the maintainer the reasoning
is sound — the image has been turbo-built since the 1050ti swap, so every v4 stamp already
names a turbo-produced transcript; the spec's out-of-scope section records exactly this
decision and the ~2-GPU-day cost of a cosmetic bump. Second, "documented only beside the
fallback constant" is now only partly true: `README.md:31-32` tells the operator the
default is `large-v3-turbo` and how to build `large-v3` back in. What the README lacks is
the one sentence about stale-stamp implications for installs that built on the *old*
default. That is a real, small documentation gap. The proposed alternatives (bump the
version, hash the model into the stamp) were weighed and declined on the record;
re-litigating them is not a defect finding.

**Required action:** Documentation only (README/release-note caveat for old-default
downstream rebuilds).

**Confidence:** HIGH.

### 3. S-1 persistent sidecar I/O, re-run amplification, competing proposals — **PARTIALLY VALID**

**Verdict:** The side-effect inventory is accurate; it is framed as a defect where the
contract specifies audit behavior, one factual sub-claim (summary semantics) is wrong, and
the rebuttal concedes a related suppression hole the review missed.

**Production trace.** Every admitted repair appends `repair_applied/accepted`
(`repair.py:801-812`) unless the pair is already held by this episode's queue —
`queued_pairs` (`repair.py:631-636`) is matched against **every** entry, resolved or not.
The queue stays until review; `unresolved.record` is an O(1) append
(`unresolved.py:177-196`); `resolve()` rewrites the file keeping all entries
(`unresolved.py:146-167, 198-206`). merge_pass discovers work by globbing srt/ass only
(`merge_pass.sh:46-49`) — the unresolved sidecar is never globbed. The gate reads pending
entries plus the sidecar mtime (`mux.py:352-356, 392-403`).

**Attack reconstruction.** Run repair with proposal X for orig O; change model/glossary so
the same card now yields Y: `(O,Y) ∉ queued_pairs` → second pending entry. Reviewer sees
two cards. Confirmed. But trace the end state: ruling on `(O,X)` stores a verdict for that
pair; `(O,Y)` is a *different* proposal and `decisions.lookup` (`decisions.py:104-115`)
correctly requires both sides — the human judges Y on its own merits, the same way the
store judges any new proposal. After both are ruled, repair consults the store
(`repair.py:709`) and neither re-queues. Stable end state, no oscillation, no stuck gate
(release paths: review, gate removal, orphan filter `mux.py:371-390`).

**Rebuttal.** Three corrections. (a) Competing proposals are noise the spec explicitly
priced in — "a re-run can show a reviewer the same line twice — noisy, never wrong" (spec,
Edge cases); coalescing is a UI improvement, not a correctness fix. (b) The claim that
`repaired` "no longer corresponds to newly changed output" is **wrong**:
`repair.process()` re-runs on every sweep while an srt exists and `conf.json` is never
rewritten (`repair.py:600-610`), so `fixed` counted re-admissions per run *before* this
branch too; the branch did not change that semantics. (c) "May hold an opted-in episode
indefinitely" describes the gate doing what [S-6] specifies, with a loud stale alert
(`mux.py:397-403`, tested `tests/test_mux.py:471-493`) and two explicit release paths.

**Conceded sub-point** (the §6.2 question the review never closed): a pair the human
rejected **through the `--review` CLI** is a real suppression hole —
`unresolved.resolve(stem, idx, accept=False)` sets only the flag; no decision is stored;
the next run re-admits the repair, and because `queued_pairs` matches resolved entries too,
the line is never re-queued. Reachable only via the CLI on `repair_applied` entries (the
server records decisions *and* resolves, `review_server.py:253-258`); guard rejections
re-surface normally, so the asymmetry is branch-shaped. Test gap + a documented "use the
server for repair_applied" note.

**Required action:** Test gap (changed-proposal re-queue; CLI resolve-without-decision) +
documentation.

**Confidence:** HIGH (rebuttal); MEDIUM (severity of the CLI gap).

### 4. Decision store / queue not synchronized — **PARTIALLY VALID**

**Verdict:** The two writes are indeed independent and the success response can misreport a
failed flag write; the "held forever despite a saved decision" scenario is refuted by code
and test.

**Production trace.** `handle_decide` (`review_server.py:228-259`) saves the store first
(`:253-256`, error returned on failure — so a failed save never reaches `resolve()`), then
calls `unresolved.resolve()` at `:258` **ignoring its bool**, and returns `saved: True` at
`:259`. On the consumer side, `held_for_review` (`mux.py:326-404`) consults the store: an
entry whose pair has a decision is dropped from the hold (`:365-369`), then orphans whose
original no longer matches `conf.json` are dropped (`:371-390`, live set at `:382`), and
only then does the hold stand (`:392-404`).

**Attack reconstruction.** The review's scenario needs `decisions_for(stem)` to return
`{}` at mux time for a show the server just successfully saved. That requires
`DECISIONS_DIR`/`GLOSSARY_DIR` to differ between the server and mux — but
`container_run.sh:15-27, 29` starts all three loops in one container from one inherited
environment, and both sides resolve the show by the same ancestor walk
(`decisions.show_for`, `decisions.py:146-166`; the review's `mux.py:365-368` anchor is
correct here). I could not construct that state under the stated deployment; under
divergent envs the server's *own* `show_for` would have failed first (`:247-248`). What
*is* reachable: `resolve()` fails (read-only media mount, ENOSPC) after a successful save →
entry stays pending → **the gate still releases** on the pair lookup (`mux.py:365-369`;
regression-tested at `tests/test_mux.py:586-610`), repair applies the verdict on the next
pass, and the reviewer sees the entry still pending and retries — `decisions.record`
**replaces** the same pair (`decisions.py:84-89`), so retry is idempotent and heals the
flag.

**Rebuttal.** The finding's failure claim ("held indefinitely", "retry may replay the
verdict without repairing the queue state") is wrong under the deployment; the
permanent-hold class was anticipated and designed out via verdict-authority. What survives
is a one-line reporting inaccuracy: `saved: True` is returned even when the flag write
failed. Severity: cosmetic; the UI's reload still shows the unresolved entry.

**Required action:** Test gap (a partial-failure test pinning `resolve()`'s bool being
surfaced), optional one-line response fix.

**Confidence:** HIGH.

### 5. Signs-bearing write-back — **PARTIALLY VALID** (title wrong; severity overstated)

**Verdict:** Repair *is* guaranteed to re-run on the write-back pass; the traced `no-signs`
fallback is the correct dialogue-only path; the only residual is a transient-failure
cosmetic regression with no data loss.

**Production trace.** Write-back (`review_apply.py:85-139`) writes the srt (`:124`), drops
any stale `.ass` (`:127-131`), drops the stamp (`:134-138`). Next pass:
`merge_pass.sh:50-54` sees srt and no ass → runs `repair.py` (`:52`) — so the title "not
guaranteed to re-run repair" is contradicted by the review's own body and by
`merge_pass.sh` — then `dub_signs_merge.py` (`:53`). `build()` returns `"no-signs"` only
when the video has **no usable English ASS stream at all** (`dub_signs_merge.py:76-127`;
the stream set is `common.eng_sub_tracks`, `common.py:375-397`, which excludes only our own
old Dubtitles track, `common.py:354-358`), and `process_one` leaves the srt
(`dub_signs_merge.py:171-194`); mux then embeds it (`mux.py:405-412`).

**Attack reconstruction.** For the claimed "originally signs-bearing → signs silently
absent," the muxed mkv would have to have lost its sign streams between first mux and
write-back. It cannot: every stream the first signs-merge read is eng/en/und ASS
(`common.py:375-397`), and `keep_sub` keeps eng, `mul`, and signs-named tracks at mux
(`mux.py:93-109`) — so the sources survive the remux and are re-extracted on the write-back
pass, restoring the merged `.ass` with verdicts applied. What remains real: a *transient*
signs-merge failure (ffmpeg hiccup → `"build-error"`, `dub_signs_merge.py:175-178`) on the
write-back sweep leaves the srt and mux embeds it that same pass — but `build_cmd` still
keeps the source sign tracks (`mux.py:93-109`), so the release carries signs as separate
tracks and merely regresses to a dialogue-only *merged* track until another write-back.
That failure class is pre-existing: the first-generation flow of a signs-bearing mkv
behaves identically when the merge fails.

**Rebuttal.** The concrete scenario as written requires a state (`mux` dropped the sign
tracks it kept) the pipeline does not produce; "oscillates between sidecar states" is one
deterministic pass (srt → ass → removed-at-stamp, `mux.py:469-485`); "signs silently
absent" is false at the file level. The review's own §6 correction already conceded repair
re-runs every sweep.

**Required action:** Test gap (write-back × no-signs/empty/build-error fixtures).

**Confidence:** MEDIUM.

### 6. `render_page()` offered-verdict injection context — **PARTIALLY VALID**

**Verdict:** The escaping-context defect is real and confirmed mechanically; it is
currently unreachable because `OFFERED` is a closed constant set, so this is a latent
hardening defect, not an exploitable vulnerability.

**Production trace.** `review_server.py:320-322` interpolates `html.escape(v)` inside
`onclick="decide(0,&apos;...&apos;)"`. Verified by simulation: after HTML attribute
entity-decoding, `&#x27;` becomes a raw `'` *before* the JS engine compiles the attribute,
so `v = "x');alert(1);//"` yields `decide(0,'x');alert(1);//')` — breakout. `html.escape`
is the wrong encoder for a JS-string-inside-attribute context; the correct construction is
`html.escape(json.dumps(v))` or a `data-*` attribute.

**Attack reconstruction.** No input reaches `v`: it comes only from
`OFFERED.get((stage, reason), DEFAULT_OFFERED)` (`:210`, constants at `:94-101`), and
`e["index"]` is an `int` from `items.index(e)`. Queue data — the untrusted ASR/model text —
is confined to HTML-text slots that use `html.escape` correctly (`:327-331`, tested at
`tests/test_review_server.py:352-366`). The other three contexts are done right and tested:
JS string via `_js()` (`:298-308`, json.dumps + `<` escape; ampersand and angle-bracket
tests at `tests/test_review_server.py:369-417`), URL query via `quote()` (`:334-337`, test
at `:419-440`).

**Rebuttal.** The finding's own body concedes latency; classifying it CONFIRMED next to a
live DoS inflates it. It is a confirmed *code smell with a verified failure mode under
hypothetical future data*, zero exploitability today.

**Required action:** Code fix (one line; can be the same commit as finding 1), plus the
named test.

**Confidence:** HIGH.

### 7. Full-list index vs filtered display — **PARTIALLY VALID** (latent; no wrong outcome)

**Verdict:** The index mapping is currently consistent and self-heals in the one reachable
edge case; no input decides a different line than the reviewer saw.

**Production trace.** `handle_episode` decorates each pending entry with `items.index(e)`
against the *full* file (`review_server.py:217-225`, index at `:222`); `handle_decide`
indexes the same full list (`:234-239`). Both writers preserve order and append only
(`unresolved.record`, `unresolved.py:177-196`; `_rewrite` preserves order, `:146-167`), so
indices cannot shift between render and decide — a later entry appends at the end.

**Attack reconstruction.** The only reachable aliasing: two byte-identical pending entries
(a re-run before [S-4] settles the line re-appends the same evidence fields,
`repair.py:801-812`), where `list.index` returns the first for both. Clicking the second
resolves the first — but both carry the identical `(orig, proposed)` pair, so the recorded
verdict is textually the same; the surviving duplicate is re-rendered with its true index
on reload and one more click settles it. A stale page + mid-session insertion cannot
misidentify: insertion is append-only. No wrong line, no wrong verdict, no stuck state.

**Rebuttal.** The review itself found "no confirmed failure in the current code" — the
classification should reflect that: robustness debt (stable pair IDs would be better), not
a defect.

**Required action:** Test gap.

**Confidence:** HIGH.

### 8. Token persistence symlink — **INVALID**

**Verdict:** The alleged overwrite does not exist; `os.replace` renames the directory entry
and does not traverse a symlink, and the reviewer's own body concedes no exploit was
established.

**Production trace.** `resolve_token` (`review_server.py:108-146`) reads any existing
token, then persists via `mkstemp` in the dir (`:133`), `chmod 0600` (`:137`),
`os.replace(tmp, path)` (`:138`). POSIX `rename(2)` replaces the *entry* — a pre-planted
symlink at `<TOKEN_DIR>/review_token` is unlinked and replaced by the regular file, never
written through. The token dir is `/config` (`token_dir_for`, `:64-76`), root-owned in the
container; planting anything there already implies root-equivalent access, at which point
the token is beside the point. The *related* symlink risk the review worried about
elsewhere — a planted conf symlink entering the stem allow-list — is handled for real:
`known_stems` enforces realpath containment (`:174-177`), tested at
`tests/test_review_server.py:557-573`.

**Attack reconstruction.** Attempted and failed: no sequence of `mkstemp`/`os.replace`
under this layout writes outside the token dir; the review's concrete scenario is absent
from its own text ("I did not establish an exploitable write-outside-directory path").

**Rebuttal.** The residual suggestion (ownership/type check on the directory) is optional
hardening, not a fix for a found vulnerability. The persistence *failure* mode, by
contrast, is handled and tested: an unwritable dir keeps the process token stable
(`:123-125`, test at `tests/test_review_server.py:508-522`).

**Required action:** No change.

**Confidence:** HIGH.

## Answers to the review prompt's specific questions (A–I)

- **A. Empty-store inertness.** `repair.process()` (`repair.py:600`) loads the store once
  (`:618`), consults it per non-empty LLM result (`:709`, runs even on `{}` — spied on by
  `tests/test_repair.py:1853-1875`), and falls through to `accept_repair`. (1) Subtitle
  output **is byte-identical** with an empty store for the same conf.json and LLM outputs.
  (2) Queue files/mtimes **do differ** (new `repair_applied` entries; two new summary keys
  at `repair.py:826-847`); merge discovery does **not** differ (merge_pass globs only
  srt/ass, `merge_pass.sh:46-49`). (3) In an install with no review gate those differences
  are the S-1 observability feature and touch nothing release-affecting. (4) "Inert in
  production" therefore holds for behavioral output (subtitle text, mux decisions) and is
  deliberately false for operational side effects — which are the feature.
- **B. Whisper model default.** See finding 2: real for downstream rebuilds off the old
  default, inert for the maintainer's turbo-produced 576-stamp library; no code detects
  model identity (`common.py:291-311`, `common.py:163-196`); the residual gap is recorded
  at `generate.py:95-103` and the spec, missing only from the README.
- **C. Queue side effects.** See finding 3: an admitted repair appends one JSONL entry
  (`repair.py:801-812`), touches the sidecar mtime (read only by the gate's stale alert,
  `mux.py:392-403`), is suppressed on exact-pair re-runs (`repair.py:631-636`), and a
  changed proposal queues a second entry that the human judges independently. Audit
  behavior by contract, not a correctness failure — except the CLI hole conceded above.
- **D. Full lifecycle.** Dialogue-only: srt → repair (`merge_pass.sh:52`) →
  `dub_signs_merge` `"no-signs"` (`dub_signs_merge.py:127`) leaves the srt → mux embeds it
  (`mux.py:405-412`), stamps (`:469`), removes sidecars (`:482-485`). Write-back re-enters
  the same cycle deterministically (`review_apply.py:124-138` → `merge_pass.sh:50-54`).
  Signs-bearing: the sign streams survive the first mux (`mux.py:93-109`), so the write-back
  pass re-derives the `.ass` with verdicts applied. `no-signs`/`empty`/`build-error` leave
  the srt for mux that same sweep — the pre-existing first-generation behavior. No episode
  gets stuck: gate holds release via review, gate removal, the orphan filter
  (`mux.py:371-390`), or verdict-authority (`:365-369`), and the stale alert fires loudly
  (`:397-403`). The "oscillation" is the designed re-open cycle.
- **E. Independent settled states.** A partial write cannot cause a permanent hold or a
  wrong subtitle: the store is the hold's authority (`mux.py:365-369`), `lookup()` requires
  both sides of the pair (`decisions.py:104-115`), `fits_card` still gates every applying
  verdict (`repair.py:713-726`), and a failed `save()` never reaches `resolve()`
  (`review_server.py:253-258`). Both processes use the same configured directories in real
  deployment (one container, one env, `container_run.sh`). Recoverable error and a
  transiently stale UI flag are the worst outcomes; retry is idempotent
  (`decisions.py:84-89`).
- **F. Decision-pair staleness.** `decisions.key` (`decisions.py:44-58`) folds
  case/whitespace/apostrophe form and keeps punctuation. Glossary edits, model changes,
  re-transcription and punctuation changes all change one side of the pair → `lookup()`
  misses → fall-through to `accept_repair`, i.e. today's behavior. A stale pair can only
  apply where the same orig yields the same proposal again — the same textual situation —
  and `fits_card` still gates it. No path applies a stale verdict to a different line.
- **G. Review server security.** Auth: `compare_digest` (`review_server.py:156`), unset →
  generated token persisted 0600 (`:108-146`), only explicit empty disables, writes gated
  before dispatch (`:276-278`); no bypass found. Bodies: negative/unparseable → 411,
  >1 MiB → 413, all pre-read (`:388-401`); chunked → 411 (no Content-Length). Slow-drip:
  confirmed DoS (finding 1). Tokens: stable across restart (persisted) and across
  persistence failure (`_GENERATED`, `:123-125`). Path traversal: stems are allow-listed
  with realpath containment (`:159-186, 174-177`); symlinked confs excluded (tested). Token
  symlink: invalid (finding 8). XSS: HTML text, JS string, URL query correct and tested;
  the onclick JS-string context is the one latent defect (finding 6). LAN exposure + root
  are the stated posture; impact is bounded to the review service by process separation
  (`container_run.sh`).
- **H. Tests.** The six named gaps are real; the highest-value one is the non-constant
  offered value through `render_page` (it would fail today — the breakout is verified). The
  `_muxed(..., ass=True)` fixture is legitimate, not impossible: stamp + sidecar together
  is the crash window between `write_stamp` (`mux.py:469`) and sidecar removal
  (`:482-485`), and the test asserts the stale `.ass` is dropped, which is the required
  behavior. Source assertions are appropriate where behavior cannot distinguish (e.g.
  `compare_digest`, `tests/test_review_server.py:279-290`).
- **I. Punctuation exclusion.** Justified as a deliberate safe deferral, not a defect:
  `accept_restoration` is word-identity (`punctuation.py:134`), `_apply()` requires exact
  token correspondence past the guard (`punctuation.py:228`), restoration runs on the
  pre-reflow word list while repair and [S-5] operate on cards, so a card-level verdict has
  no replay path — and of the four verdicts only `reject` is implementable. The entries
  remain reachable through `?all=1` and the `--review` CLI (`unresolved.py:58-88`).

## Claims conceded

- **Finding 1 in full** — unauthenticated slow-drip worker exhaustion is real
  (`review_server.py:402`, `timeout=None`, unbounded daemon threads); only the severity
  framing is corrected.
- **Finding 2's mechanics and downstream scope** — nothing detects a decoder change
  (`common.py:291-311`); the README lacks the stale-stamp caveat for old-default downstream
  rebuilds.
- **Finding 3's side-effect inventory** — persistent queue appends, mtime churn,
  competing-proposal entries, and the CLI resolve-without-decision suppression hole
  (volunteered; the review's §6.2 open question).
- **Finding 4's non-atomicity** — two independent writes, and `handle_decide` returns
  `saved: True` regardless of `resolve()`'s result (`review_server.py:258-259`).
- **Finding 5's residual** — a transient signs-merge failure on a write-back sweep ships a
  dialogue-only *merged* track that pass (source sign tracks remain embedded;
  recoverable).
- **Finding 6's escaping-context bug** — verified breakout under a crafted value; latent
  only.
- **Finding 7's duplicate-index aliasing** — reachable via byte-identical re-queued
  entries; self-healing.
- **Empty-store non-inertness in observability** — queue sidecars, mtimes, and two new
  summary keys differ even when SRT bytes are identical; "inert" is true of shipped output
  and mux decisions, deliberately false of the S-1 audit trail.
- **All six named test gaps** are genuine gaps, including that the transport tests bypass
  sockets and the `compare_digest` test is a source assertion (appropriate there — `==` and
  `compare_digest` are behaviorally identical; `tests/test_review_server.py:279-290`
  documents why).

## Claims rejected

- **Finding 4's "held forever" / divergent-`GLOSSARY_DIR` scenario** — decisive evidence:
  `mux.py:365-369` releases on a stored pair verdict regardless of the flag (tested
  `tests/test_mux.py:586-610`), and one container = one environment for all three loops
  (`container_run.sh`).
- **Finding 5's title and impact** — repair is unconditionally re-run
  (`merge_pass.sh:50-53`); `no-signs` on a previously signs-bearing mkv requires sign
  streams `keep_sub` demonstrably keeps (`mux.py:93-109`, sources bounded to eng/en/und at
  `common.py:375-397`); no oscillation, no signs data loss.
- **Finding 3's summary-count claim** — `repaired` counted per-run re-admissions before
  this branch; the branch did not change it.
- **Finding 8 in full** — `rename(2)` does not follow symlinks; no write-outside path
  exists.
- **Any unlisted XSS/auth/traversal claim in Section G** — HTML text, JS string (STEM), and
  URL query contexts are correctly encoded and tested
  (`tests/test_review_server.py:343-440`); writes gate before dispatch
  (`review_server.py:277-278`); negative/oversize/chunked bodies are refused pre-read
  (`:388-401`); stems are realpath-contained (`:174-177`).
- **"The gate can strand an episode"** — release paths: review (server or store), gate
  removal, orphan filter (`mux.py:371-390`), all tested; the unreadable-conf hold is
  deliberate fail-closed (`:377-390`, `tests/test_mux.py:651-659`).

## Residual risks

1. **Unauthenticated DoS** until the timeout fix lands (finding 1) — review-service
   availability only.
2. **Latent onclick injection** if `OFFERED` ever becomes data-driven (finding 6).
3. **CLI/`repair_applied` asymmetry** — a `--review` CLI rejection of an admitted repair
   never reaches the store and is suppressed from future queues; the shipped text is
   unaffected today (repair re-applies), but the human's "needs fixing" is not honored.
4. **Cross-model store portability is unmeasured** (spec-recorded precondition for phase
   2) — a downstream install pulling the committed store onto a differently transcribed
   library has an unquantified pair-hit rate; misses are safe no-ops
   (`repair.py:709-726`).
5. **Downstream decoder split** after an old-default rebuild, undetected until documented
   (finding 2).
6. **Transient signs-merge failure during a write-back** ships a dialogue-only merged
   track that pass; recoverable by re-running `review_apply`.

## Minimal remediation plan

1. **`review_server.py` (code fix, pre-merge):** add a socket/read deadline to `Handler`
   (e.g. `timeout = 30`, which `StreamRequestHandler.setup()` applies to the connection)
   and optionally bound concurrent connections; pin with a source-level guard alongside the
   existing `compare_digest` one.
2. **`review_server.py` (same commit, one line):** encode the offered verdict for the real
   context — `html.escape(json.dumps(v))` or a `data-verdict` attribute — and keep the
   repaired `handle_decide` response honest by checking `unresolved.resolve()`'s return.
3. **Documentation (pre-merge):** one README sentence next to the existing `large-v3`
   build-arg note (`README.md:31-32`): rebuilding an install whose v4 stamps came from the
   old default changes the decoder without a `TRANSCRIBE_VERSION` bump.
4. **Test follow-up (may land post-merge):** changed-proposal re-queue;
   `decisions.save()`-succeeds/`resolve()`-fails; write-back × `no-signs`/`empty`/
   `build-error`; a non-constant offered value through `render_page`.

Everything else in the review is either the contract working as specified (S-1 audit trail,
gate holds, punctuation exclusion per `unresolved.py:58-88` and `punctuation.py:134/228`),
already-designed fail-closed behavior, or hardening.
