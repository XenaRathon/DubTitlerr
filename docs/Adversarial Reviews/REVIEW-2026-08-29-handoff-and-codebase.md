# Post-SAO-pass review — handoff verification + five findings

Reviewed 2026-08-29, HEAD `d74e44e`, tree clean, suite green (100% before this document —
no code was changed for this review). Scope: verify the 2026-08-29 session handoff against
source, then an adversarial pass over the modules the session touched (`glossary_acquire.py`,
`acquire_cache.py`, `repair.py`, `common.extract_sub`, `reflow._text`, `review_server.py`,
`gen_loop.sh`, `merge_pass.sh`).

## 0. Handoff claims — all verified in source

| handoff claim | verdict |
|---|---|
| acquire cache not gated on `apply`; dry run banks verdicts; later `--apply` proposes nothing | **confirmed** (`glossary_acquire.py:745-760`, `propose` skip at `:595-597`) |
| `gen_loop.sh` never sets `ACQUIRE_APPLY` | **confirmed** (`gen_loop.sh:100-103`, default dry-run-and-log) |
| `[S-4]` invariant false; unchanged lines counted and recorded nowhere | **confirmed** (`repair.py:861` comment; `accept_repair` returns False on `new.lower() == orig.lower()` at `repair.py:488-489`; inner guard false by construction at `repair.py:773`) |
| `common.extract_sub` tries `-c:s copy` first | **confirmed** (`common.py:466-480`) |
| `reflow._text` comma-weld fixed in `c2be862` | **confirmed** (`reflow.py:151-167`, test pinned at `test_reflow.py:889-900`) |
| the three `mine_glossary` fixes committed | **confirmed** (`44ecd6f`, `86dce36`, `b56879c` on HEAD) |

No test pins the false `[S-4]` arithmetic, so the proposed counter fix has no test to
break. `test_repair.py:863` pins `accept_repair` rejecting unchanged lines — the fix must
count the unchanged case *without* touching that rejection.

## R1 — `acquire_cache` disarms `--apply` **and** the dry-run report (decision 1, sharpened)

The handoff's mechanism is right and I add one consequence it does not state: **the disarm
is permanent, not per-run.** `remember()` stores `apply` verdicts as non-junk
(`acquire_cache.py:136-146`), `is_fresh` serves non-junk entries forever subject only to
`stale_canonical` (`acquire_cache.py:107-110`), and `propose()` skips anything in
`settled` (`glossary_acquire.py:595-597`). So once a dry run banks an `apply` verdict,
*no* later `--apply` run can ever materialise it — even after `ACQUIRE_APPLY=1` is finally
set — unless the cache file is deleted or the canonical disappears. The banked caches
(One Pace 10,238, SPY x FAMILY 701, SAO 641) are therefore a library-wide standing
disarm, not a per-sweep cost.

Second consequence: production's stated mode is "dry-run-and-log until the Punk Hazard
verification run has passed" (`gen_loop.sh:96-99`). After the first sweep the log half is
gone too — `proposed 0` every sweep thereafter, so the proposals the owner wants to read
before enabling `--apply` are invisible. The cache does not merely suppress the write; it
suppresses the evidence the enable decision was to be based on.

Third: the cache's own docstring contract ("must never raise and **never change what the
pipeline decides**", `acquire_cache.py:37-39`) is violated on its first production sweep.
`ACQUIRE_NO_CACHE=1` is a correct but manual escape hatch — it is not a fix.

Fix options (owner decision, not picked here):

- **(a)** gate `acquire_cache.save()` on `apply` — restores the dry-run convention (the
  cache *is* on-disk state), at the cost of the original perf goal for dry runs;
- **(b)** keep saving always, but on `--apply` runs replay cached verdicts into
  `apply_proposals` instead of folding them into `settled` — preserves the memo while
  making apply work;
- **(c)** stamp each entry with the `run_id` it was applied under; only skip cached
  verdicts that actually landed.

Whichever is chosen, the three existing cache files must be handled — deleting the SAO
file alone restores SAO, not One Pace.

## R2 — the `[S-4]` invariant is false (decision 3, confirmed; fix is unblocked)

Verified exactly as handoff describes: `targets == repaired + skipped_no_ref + llm_empty +
rejected_guard + verdict_reject + verdict_unfittable` cannot hold because the unchanged
outcome (model returned the line verbatim → `accept_repair` False → inner guard
`new.lower() != c["text"].lower()` false) counts nothing and records nothing — and it is
the single most common outcome (568 of 836 on SAO). The comment at `repair.py:861` states
a false invariant as fact and the summary is the only artifact where the case can ever
appear (the queue correctly refuses to flood on it).

The proposed fix — an `unchanged` counter plus a corrected comment — is right and has no
test blocker. Worth doing with the TDD skill per the gate, RED first on the arithmetic.

## R3 — `common.extract_sub`: copy-first is guaranteed waste on subrip tracks, and failure is silent (new, measured)

Measured locally (ffmpeg 6.x): copying an `srt` (subrip) subtitle stream into a `.ass`
file with `-c:s copy` **always fails** — rc=234, "ass muxer supports only codec ass for
type subtitle" — leaving a 0-byte file, after which the fallback re-encode succeeds.
The ass muxer can only hold ass, so the copy attempt can only ever succeed when the
source stream is already ASS. On the common srt-source fansub track, `extract_sub` burns
a full ffmpeg invocation (spin-up, probe, mux attempt, failure) before doing the work it
always had to do — consistent with the handoff's measured 60x. Every real caller pays it:
`dialogue_intervals`/repair via `_load_stream_events` (`common.py:505-514`),
`dub_signs_merge.py:38`, `tools/recover_dub_srt.py`. `mine_glossary.py:143` already
bypasses the helper with its own extraction — internal evidence the default is wrong for
a sibling consumer.

Second issue, same function: both attempts discard `stderr` (`capture_output=True`) and
never check the return code; success is inferred from `getsize > 0`. A both-fail
extraction is indistinguishable from "this release has no subs" — the same silent-failure
class flagged for `llm_chat()` in the 2026-08-21 GLM review. `_load_stream_events` turns
it into `[]` and repair proceeds unanchored without a word.

Fix direction (no owner decision needed): probe the stream codec once and only attempt
`-c:s copy` when the source is ass; otherwise go straight to the transcode; log the
first attempt's failure reason and return code. The copy-first branch should be deleted
or made conditional, not kept as a hopeful try.

## R4 — the acquire cache is consulted *after* the join, so the module's dominant cost is repaid every sweep (new)

`acquire()` runs `_resolve_tokens(counts, titles)` — the 8202×8109 token×title join its
own docstring calls "the module's dominant cost" (`glossary_acquire.py:552-555`) — *before*
the cache is even loaded (`glossary_acquire.py:745-750`). The cache removes only the
escalate LLM tier; the join is fully re-paid every sweep even when 10,238 One Pace tokens
are already settled. `skippable`'s `anchor_for` closure forces this: the floor-anchor
check re-resolves the token's canonical via the fresh join instead of using the canonical
`remember()` already stored on the entry (`acquire_cache.py:119-124`).

Fix (independent of R1, safe with or without it): consult the cache first, restrict
`_resolve_tokens` to tokens the cache did not settle, and feed `settled_target` the
cached canonical — which `stale_canonical` already guards for disappearance, and
re-resolution is documented as a human re-litigation case. Perf-only; verify with the
existing timing instrumentation rather than assuming.

## R5 — the `c2be862` comma fix welds a *decimal* onto a word (new, measured)

The new branch in `_text` (`reflow.py:163-166`) joins any token starting `,`/`.` followed
by a digit onto the previous token without checking that the previous token ends in a
digit. Measured on the real function:

    reflow._text("It weighs .5 kilos")  ->  "It weighs.5 kilos"   (wrong)
    reflow._text("version 2 .5")        ->  "version 2.5"         (right)

Same character-welding class the fix was written to eliminate — the guard should be
`out[-1][-1:].isdigit()`-shaped (or the reduced-form check the hyphen branch uses). Rare
in practice (the measured sample held one `.N` token in 6,346, usually following a
digit) but it is one line plus a test, and the class was just fixed once this week.

## 1. The three owner decisions — not picked here, per handoff

1. **R1 — acquire-cache disarm.** Fix (a/b/c above) or is the skip intended? And do the
   three cache files get deleted, restoring pre-bank state?
2. **Episode-page scoping** (todo `20260829-acquire-scope-wiki-titles-per-episode.md`).
   The Plot-section primitive measured well (26-30 entities/episode vs 1,281
   franchise-wide, ~45x tighter, no `Whale`/`Horse`). Three open questions gate it:
   per-wiki `episode_page_pattern` config key, missing-episode fallback policy, and
   allpages-as-spelling-authority vs replacement. The `superpowers:brainstorming` skill's
   stop-and-approve gate is the right shape before building.
3. **R2 — `[S-4]` unchanged counter.** Add counter + correct the comment; no behaviour
   change.

## 2. Carry-forward status (handoff §carry-forward, all still accurate)

- **SAO E01 second pass** — `todo=1`, same command. Still pending.
- **`TEXT_VERSION` bump for `c2be862`** — safe now (no transcription in flight), repairs
  ~40 SAO lines, text-tier only.
- **`extract_sub`** — now R3 above; the measurement is partially done.
- **Force-push to origin** — 183 rewritten commits, `backup/pre-attribution-strip` tag
  exists. Unchanged.
- **Review queue** — 321 live SAO entries / 19 episodes, 45 `rejected_name_invented`.
  Unchanged (no review runs since handoff).
- **`merge_pass.sh` stage exit codes** — still swallowed (no `set -e`, return values
  ignored), the 2026-08-21 GLM review's Item-4 gap. Still open, unchanged.
- **`review_server` auth** — auto-generate posture confirmed in place
  (`review_server.py:134-201`), writes gated, `secrets.compare_digest`; the earlier GLM
  finding was adopted, nothing to do.

## Bottom line

The handoff is accurate on every point I could verify from source and measurement — it is
safe to treat as the record of where things stand. The one thing it understates is R1:
the acquire cache is not a per-run nuisance but a **permanent, library-wide disarm of
both `--apply` and the dry-run report**, already banked into all three shows. It is the
right first question for the owner, as the handoff orders. R3 (extract_sub) and R4
(join-before-cache) are fixable without any decision and R5 is a one-line completion of a
fix committed this week.

## 3. Self-rebuttal — attacking the five findings above

Written against my own review, same bar as the findings: source-verified or measured, or
marked unknown. Standing per finding: SURVIVES / WEAKENED / NIT.

### R1 — SURVIVES, with a severity correction and one unmeasured claim

- **"Permanent" is exact, but only for `apply`/`known` verdicts.** `is_fresh` never
  recycles a non-junk entry (acquire_cache.py:114-123), so a banked `apply` verdict is
  suppressed until the cache file is deleted or its canonical disappears from the wiki.
  That part stands. What I did NOT verify: the distribution of `apply` vs `junk` entries
  inside the three existing cache files. All three were banked by dry runs (`gen_loop.sh`
  never passes `--apply`), and a dry run computes and stores the same verdicts, so `apply`
  entries are certainly present — but I never opened the files to count them. The disarm's
  blast radius at apply time is the `apply` entries specifically. Unmeasured, as stated.
- **Severity: today's harm is observability, not corruption.** Production runs dry until
  the Punk Hazard verification passes, so nothing is silently lost right now — the live
  cost is the empty report (`proposed 0`), and the real footgun lands the day
  `ACQUIRE_APPLY=1` is set. The handoff calls it "the urgent one" and I inherited that
  framing. Corrected: it is the highest-priority *decision* (it silently disarms a feature
  the owner is about to enable), not an active failure. `ACQUIRE_NO_CACHE=1` and a
  one-command cache deletion both restore prior state.
- **The design tension is real, and the code comment anticipated half of it.** The
  "DELIBERATELY NOT gated on `apply`" comment (glossary_acquire.py:894-900) argues the
  memo must not starve on dry runs — sound for the memo's purpose, and it is exactly why
  the disarm exists: the memo and the write path share the `settled` skip key they should
  not. R1 is a design bug, not a logic error, which is why it is an owner decision.

### R2 — SURVIVES, trivially. One figure is inherited, not re-measured.

- The mechanism is source-confirmed and the fix (an `unchanged` counter plus a corrected
  comment) is blocked by no test. "568 of 836" is the handoff's measurement; I did not
  re-run SAO. The one nuance the review understated: adding the counter changes the
  repair-summary JSON schema — additive and backward-compatible, but any aggregator
  reading it should tolerate the new key. Nothing else to attack; this was never a
  controversial finding.

### R3 — WEAKENED. The mechanism is proven for subrip; the magnitude and the library's track mix are not.

- **My "consistent with the measured 60x" is speculation and should be retracted.** The
  mechanism I proved locally (failed copy attempt → fallback) costs roughly one extra
  ffmpeg invocation — ~2x a single transcode, not 60x. Two invocations cannot explain
  60x. Either the handoff's measurement is on different content or conditions (PGS remux,
  container quirks, CIFS), or something about this content makes the copy attempt
  pathological. I did not reproduce 60x. The magnitude stays the handoff's claim; mine
  was the wrong mechanism to attribute it to.
- **"Guaranteed waste" is proven only for subrip-source tracks** (my rc=234 fixture). If
  the library's fansub tracks are predominantly ASS, the copy branch is the correct fast
  path and the finding is largely moot for the library's own content. I have no data on
  the library's track-format mix — the handoff's "60x on this content" implies copy is
  wrong for THIS content, but that is their measurement, not mine.
- **The durable part of R3 is the observability gap, and it holds regardless of format:**
  both attempts swallow stderr and return codes; success is inferred from file size; a
  both-fail extraction reads identically to "no subs". That is the same silent-failure
  class the 2026-08-21 GLM review flagged for `llm_chat()`, and it depends on none of the
  contested magnitude. R3 as written over-weighted the headline; the fix direction
  (probe the codec once, check return codes, log failures) is right for the observability
  finding and merely optional for the perf one.

### R4 — SURVIVES as an observation; the proposed fix is INCOMPLETE, which the review itself should have caught.

- **The hole: the join serves two consumers.** `propose()` gets `resolved`;
  `unmatched()` needs the full join to know which tokens resolve to NOTHING
  (`t not in resolved`, glossary_acquire.py:629-640). The cache stores only proposed
  tokens — non-resolutions are never remembered. Restricting `_resolve_tokens` to
  non-cached tokens therefore saves `propose` but not `unmatched`, which still walks every
  harvested token against every title. My fix is half a fix; the other half is caching
  unmatched-ness itself, which the design (ABSENCE IS THE CACHE MISS) explicitly refuses
  to do.
- **"Dominant cost" is the module's own docstring, not a measurement I took.** The
  acquire_cache docstring claims escalate is 71% of runtime; if true, the join is the
  largest REMAINING cost once escalate is cached, but its share is unmeasured. Downgrade:
  the finding is "the cache does not remove the join" (true, code-verified) — the fix is
  not as ready as R4's section implies.

### R5 — SURVIVES as a nit; self-assessed as the weakest finding in the review.

- The weld is constructible and measured on the real function; the guard
  (`out[-1][-1:].isdigit()`) is correct and does not break the legit `2,000`/`2.5` cases.
- What I did not show: that whisper ever emits the triggering shape (a digit-initial token
  after a non-digit word) in real output. The measured SAO sample held one `.N` token in
  6,346, predecessor unknown. The fix is one line plus a test and closes the class
  `c2be862` was written to eliminate — but by the repo's own "no point in over-filtering"
  bar, this is polish that can wait for evidence the shape recurs. Keep the test idea;
  drop the urgency.

### Meta-rebuttal — what this review actually added

- **Nothing outside the handoff's own radar.** R1 is handoff decision 1, R2 is decision 3,
  R3 is a handoff carry-forward item. The only genuinely new findings are R4 (a perf
  observation with an incomplete fix) and R5 (a nit). The handoff was a better adversarial
  review of its own state than mine was. That is a compliment to the author and a modest
  result for this review.
- **Scope honesty:** I read the handoff-touched surface (glossary_acquire, acquire_cache,
  repair, common, reflow, review_server, the loop scripts) plus their tests. I did not
  read generate.py's core, qc.py, hallucination.py, punctuation.py, mux.py's muxing path,
  or glossary_verify.py in depth. "Review of the codebase" is really "review of the
  handoff's surface"; an unread module could hold a worse bug than any of R1-R5.
- **The Bottom line above overstates R4** ("fixable without any decision") — R4's fix is
  incomplete per its own rebuttal. Corrected bottom line: R3's observability part and R5
  are the only decision-free, ready-to-ship items; R1 stays the owner's call; R4 needs
  measurement before it needs a design.
