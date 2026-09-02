# Final adversarial review — repository-wide, public-beta readiness

## START NOW — do not acknowledge this brief, do not ask where the files are

You are already in the repository root. Begin reading immediately and reply only with
findings. Do not reply "I'll review this" or ask to be told to start; there is no second
message coming.

First commands, in order:

```sh
git log --oneline de4f49e..HEAD                 # today's 14 commits, the primary target
git diff --stat de4f49e..HEAD                    # 41 files, +3247/-463
.venv/bin/python -m pytest -q                    # must be green before you start
.venv/bin/ruff check .
cat .procoder/todo/20260829-*.md .procoder/todo/20260830-*.md   # the 4 tasks closed today
cat "docs/Adversarial Reviews/BUFFY-GLM-REVIEW-2026-09-02-repository-wide-beta-readiness.md"
```

Everything named below is a path relative to this directory. Read the source, not this
brief, for anything you intend to cite.

**Repo:** DubTitlerr — faster-whisper transcription → reflow into Netflix-profile cards →
per-show glossary correction → optional local-LLM repair → mux back into the MKV, plus a
human review loop over repaired lines.
**Branch:** `feat/review-sorting` @ HEAD, caught up to `main` as of `de4f49e` then 14
commits ahead.
**Suite:** run it yourself and report the number; it must be 0 failures or this review
stops there.

You are the fourth repository-wide adversarial pass on this codebase in six days
(DEEPSEEK, 2026-08-31; GPT5.6-LUNA — you — 2026-09-01; BUFFY/GLM, this morning). **Do not
re-derive their findings from scratch.** Read the GLM review (command above) for the
current beta-readiness baseline, then verify **specifically what changed today** against
its claims. Your job is to find what today's session got wrong, missed, or introduced —
not to re-run a general sweep.

**What you have consistently found that the other two miss.** Your standout findings in
this repo's history have not been "there is a bug in this function" — they have been bugs
in the INTERACTION CONTRACT between two pieces of code that each look correct on their
own: the branch-premerge review's unbounded-POST-before-auth finding needed HTTP/1.1
framing knowledge (`Transfer-Encoding: chunked` vs `Content-Length`, socket lifetime under
`ThreadingHTTPServer`) that a pure code-read misses; the A/B-findings rebuttal caught that
a `SequenceMatcher` opcode diff is a DIVERGENCE metric, not a RECALL metric — a name
misheard identically in both experimental arms produces zero opcodes, so "no differences
found" can hide the exact failure the measurement was built to catch. That is the register
to work in here: not just "does this function do what it says," but "what protocol,
concurrency, or statistical assumption does this interaction rest on, and is it true."
Sections 2.6 and 3 below are where that register matters most (`card_split`'s two
independent write-time re-derivations of the same split, and the two-writer lock).

**Your own known pattern, from the per-episode-acquisition review: first-pass severity
inflation, corrected by your own rebuttal.** 5 of 8 findings marked BLOCK on the first
pass there were downgraded to P1/P2 once you argued against them. Do that here as a
REQUIRED second pass, not an optional one — see §5's deliverable shape.

---

## 1. What today's session claims to have done

Fourteen commits, in dependency order (`git log` above gives the exact hashes):

| #   | Commit prefix                 | Claim                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `e8a13d1`                     | Repo hygiene: removed a stale-but-merged agent worktree, fast-forwarded onto `main`, committed 3 review docs                                                                                                                                                                                                                                                                                                                                      |
| 2   | `8abea7f`,`b56398d`,`ff83c66` | README truth pass: removed a reference to a script that doesn't exist, fixed a Dockerfile/Dockerfile.builder contradiction, updated a stale model-default mention across 3 wiki pages, documented the review-token empty-value opt-out                                                                                                                                                                                                            |
| 3   | `8c9a8cf`                     | **`decisions.py` cross-process lock** — claims `unresolved.py`'s CLI writer and `review_server.py`'s HTTP writer could lose a verdict to a race; added an `fcntl` lock                                                                                                                                                                                                                                                                            |
| 4   | `0231a49`                     | CHANGELOG.md, SECURITY.md, a minimal issue template — no git tag pushed                                                                                                                                                                                                                                                                                                                                                                           |
| 5   | `31ab90d`                     | **`review_server.py` startup warning** when `REVIEW_TOKEN=` (empty) combines with `REVIEW_BIND=0.0.0.0`                                                                                                                                                                                                                                                                                                                                           |
| 6   | `1bf78a8`                     | **`acquire_cache.py` rewritten** — claims the OLD cache suppressed dry-run verdicts (including flag verdicts meant for human review) by folding a cached verdict into `settled`; replaced with caching only `escalate()`'s LLM adjudication, keyed per `(variant, canonical)` pair. Deletes the entire staleness/recycling apparatus (`is_fresh`, `stale_canonical`, `recycles`, `STRUCTURAL_REASONS`, `JUNK_RECHECK_GROWTH`) as no longer needed |
| 7   | `166e88d`                     | **`dub_signs_merge.py`**: reverses a prior policy (stopped dropping the fansub's own song translation), adds a NEW mechanism (`_song_spans`) that drops whisper-transcribed dub cards overlapping a detected song span                                                                                                                                                                                                                            |
| 8   | `20dd588`                     | **`watch_queue.py`**: atomic order-file write (was a plain `open(..., "w")`), refuses to write when 0 shows match a library directory (was silently written)                                                                                                                                                                                                                                                                                      |
| 9   | `a0dfb29`                     | **New module `card_split.py`**: splits an over-long human `correct`/`force` verdict across two subtitle cues at write time (never written to `conf.json`), wired into `repair.py` (two call sites) and `review_apply.py`                                                                                                                                                                                                                          |

Three findings from this morning's GLM review (F2 — mux stamp-before-remove ordering, F5 —
Apply-button re-mux cost) were **deliberately left unfixed** after investigation, on the
judgment that the existing code's failure mode was already better than the proposed fix.
**Do not take that judgment on faith — re-derive it independently** (`mux.py::process`
around the `os.remove(orig)`/`write_stamp` ordering; `review_apply.apply_episode`'s
`changed` counting against the 2026-08-29 measurement that 11/20 corrections never reached
the shipped track).

---

## 2. The single most important claim to falsify

**"Every one of today's six behavior changes (items 3, 5, 6, 7, 8, 9 above) is correct,
and none of them silently reintroduces a class of bug an earlier version of the code was
built to prevent."**

Attack each one specifically:

1. **The `decisions.py` lock (`card_split`'s sibling problem, solved earlier today).**
   `decisions.locked()` takes an `fcntl.flock` on a sidecar file (`<store>.json.lock`),
   deliberately NOT the store file itself, because `save()`'s `mkstemp`+`os.replace` gives
   the store file a new inode every write. Is the sidecar file itself created durably and
   atomically enough that two processes racing to create it for the first time can't each
   believe they hold an uncontended lock? Trace `os.open(..., os.O_CREAT | os.O_RDWR)` —
   is `O_EXCL` needed, or does `flock` make the race safe regardless of creation order?

2. **`acquire_cache.py`'s rewrite deleted real logic, not just renamed it.** The OLD
   `is_fresh`/`recycles`/`JUNK_RECHECK_GROWTH` machinery existed to let a `below-floor`
   junk verdict be RECONSIDERED as more episodes are harvested (a token seen twice in 20
   episodes might be a real name recurring 200 episodes later). The new cache never stores
   a verdict at all — every token re-runs `propose()`/`source_gate()` fully every time. Is
   that actually equivalent, or does something downstream now behave differently for a
   token whose candidacy previously depended on accumulated evidence across runs? Is there
   any remaining code path that reads `acquire_cache` expecting the OLD per-token verdict
   shape (`{token: {verdict, count, reason, canonical, floor_anchor}}`) and would silently
   misread the new per-pair shape (`{variant: {canonical: {same_entity, confidence}}}`)?

3. **`dub_signs_merge.py`'s new song-span drop is a blanket time-window cut.** `_song_spans`
   merges any song-family-styled event into a span and drops every whisper dub card
   overlapping it, with NO check for whether real spoken dialogue happens to fall in that
   window (documented as an accepted `debt:`, not solved). Is the merge-gap heuristic
   (2000ms) actually safe on a release where a song's per-syllable events have LARGER
   natural gaps than that (a slow ballad, a spoken-word bridge) — would `_song_spans`
   incorrectly split one song into multiple spans, or merge two SEPARATE songs (OP and ED)
   into one span if they are less than 2 seconds apart in some edited release?

4. **`watch_queue.py`'s zero-match refusal.** Verify `build()` genuinely cannot return an
   empty `order` in any case other than "real watched-show data matched zero library
   directories." Is there a starvation case — e.g., every pinned show (`--pin`) matching
   but every non-pinned show failing to match — that the refusal now blocks when it
   shouldn't?

5. **`review_server.py`'s new startup warning is advisory-only, not a gate.** Confirm the
   warning cannot be bypassed by a caller that never invokes `serve()`'s normal startup
   path, and that the warning condition (`bind == "0.0.0.0"`) doesn't miss an equally-open
   bind address (`::`, `0.0.0.0/0` variants, or a hostname that resolves to all
   interfaces).

6. **`card_split.py` is brand new and touches three call sites plus a shared write-time
   contract between two files (`repair.py`, `review_apply.py`).** This is the highest-risk
   change today by surface area. Specifically:
   - Does `_card_words`'s window filter (`repair.py`) and the equivalent inline filter in
     `review_apply.py` actually implement the SAME word-selection logic? They are two
     independent implementations of "words in this card's time window" — find the
     divergence, if there is one, the same way `fits_card` itself is imported rather than
     reimplemented to prevent exactly this class of drift.
   - `find_legal_split` is called with `orig=None` implicitly dropped — does ANY code path
     let a split happen for a correction that would otherwise be judged against `fits_card`'s
     leniency branch (an already-over-cps card), i.e., does the interaction between the
     `not fits_card(new, dur, c["text"])` check and the SEPARATE `find_legal_split` call
     ever let an `over_cps`-shaped correction through a split when it shouldn't (scope was
     explicitly "over_line_len/over_chars only")? Construct a concrete counter-example if
     one exists — a card whose fault is a MIX of both (e.g. `over_line_len` AND `over_cps`
     simultaneously).
   - The `c["_split"]` marker on a `conf.json`-loaded dict: is `conf` ever passed to
     anything else in `repair.py`'s `process()` after the marker is set, where a transient
     key on the dict could leak into a summary, a log line, or a JSON-serialized field the
     marker was never meant to reach?

---

## 3. Interactions — where every real defect in this repo has historically been found

Per this repo's own review history (see the `PROMPT-2026-08-27-branch-premerge.md` brief
in this directory), every serious bug in this codebase was found in an interaction, never
in a diff. Trace these end to end, in the code:

**A. The full episode lifecycle, with TODAY's changes inserted.** `merge_pass.sh` →
`repair.py` (now calling `card_split` and consulting a locked decision store) →
`dub_signs_merge.py` (now dropping song-span cards) → `mux.py` → (`review_apply.py`, now
also calling `card_split`) → back to `merge_pass.sh`. Does a split card interact correctly
with `mux.py`'s duration-mismatch check (`DUR_TOL`), the `.dubtitles.qc.json` counters, or
`dub_signs_merge.py`'s own event count logging (`signs=N dub=N`, now potentially
undercounting because a split card produces 2 SRT cues from 1 dub-loop iteration)?

**B. Two independent per-episode caches, one rewritten today.** `acquire_cache.py` (per
pair) and `decisions.py` (per line, now lock-guarded) are siblings in role. Does anything
assume they share a locking or staleness model that the rewrite made them stop sharing?

**C. What changed shape without a version bump.** Does today's `dub_signs_merge.py` policy
reversal (keep the fansub translation, drop whisper's song cards) require a
`TEXT_VERSION`/`PIPELINE_VERSION` bump to reach the existing library, the same way past
`dub_signs_merge` fixes required one (`common.py`'s own bump history, v2)? If it does not,
does the CHANGELOG.md written today (item 4 above) correctly reflect that this is a
forward-only behavior change, not a retroactive one?

---

## 4. Tests — assume they are the weakest part, including the ones written today

This repo's own history: a fixture hand-writing a state the pipeline never produces, an
assertion on a field mutated in memory only and never written back, an assertion on a full
string `wrap_balance` always breaks with a newline (passes unconditionally). Today's new
tests (`tests/test_card_split.py`, `tests/test_acquire_cache.py` rewritten,
`tests/test_dub_signs_merge.py` additions, `tests/test_watch_queue.py` additions) claim to
avoid these. Check specifically:

- `tests/test_card_split.py`'s `find_legal_split` fixture (`_FULL_TEXT`, 84 chars, 10.0s)
  was verified against real `reflow.wrap_balance`/`layout_faults` output before the
  assertions were written (per the commit message). Independently re-verify that claim —
  run the same check yourself — rather than trusting the commit message.
- The read-only SAO S01E02 verification claimed in the closed
  `20260830-drop-transcribed-song-lyrics-restore-fansub-translation.md` todo was run
  against a scratch script deployed to and then deleted from a production container on
  `fasc`, not captured as a committed test. Is the PRODUCTION verification claim (25 cards
  dropped, 4 named hallucinated lines absent, 7 song-family styles present) reproducible
  from what's in the repo today, or does it rest entirely on an unrepeatable one-off run?
- For any test you doubt: name the production mutation that should break it, and say
  whether it does.

---

## 5. What to hand back

Write it to `docs/Adversarial Reviews/LUNA-2026-09-02-beta-readiness-final-review.md` —
not chat output; the file is what gets read.

**Pass one — the findings.** A numbered list, ordered by severity, splitting
**CONFIRMED** (you traced it in the code and can name the failing input) from
**SUSPECTED** (it looks wrong, you could not confirm). For each: `file:line`, what the
code does, what it should do, a concrete failing scenario, and a closing
**`Disposition:`** line stating the severity you're assigning it and, in one sentence,
why that severity and not one tier up or down.

**Pass two — argue against your own pass one, before you finalize anything.** Your own
track record on this repo (the per-episode-acquisition review) shows a first pass that
marks 5 of 8 findings BLOCK, then a rebuttal pass that downgrades most of them once
argued against. Do that here explicitly, in the file, as its own section — not silently
in your head. For each finding from pass one, make the strongest case that it is wrong,
overstated, or already mitigated elsewhere; state which findings survive at their
original severity, which get downgraded, and which you'd withdraw outright. **The
post-rebuttal severity is the one that counts** for the numbered list and for the beta
verdict below.

**Closing ledger.** What you verified by running it yourself in this checkout, versus
what you could not verify (no GPU, no live LLM backend, no access to `vm102`/`fasc`) and
are reasoning about from the code and this session's own claims alone — say which is
which, the same distinction your A/B-rebuttal review already draws.

**The finding you tried hardest to break.** One paragraph: which finding got the most
adversarial effort from you, and did it survive?

Three rules:

- **Verify every line number you cite.** A previous external review of this repo produced
  nine `file:line` anchors and every one was wrong, while its substantive reasoning was
  sound. Wrong anchors cost more than they are worth.
- **If you cannot confirm something, say SUSPECTED.** A confident wrong finding is worse
  than an admitted uncertainty.
- **Do not report style, naming, or "consider adding a docstring."** Correctness,
  interaction, security, data loss, and test honesty only — and explicitly, whether the
  repo is ready to announce a public beta this week, separate from the code-correctness
  findings.

Finally: of everything shipped today, name the ONE change you would most want reverted,
gated, or re-tested with production data before this reaches a public beta user, and say
why.
