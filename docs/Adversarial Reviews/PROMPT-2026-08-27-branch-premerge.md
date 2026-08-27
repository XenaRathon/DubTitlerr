# Adversarial review — `feat/phonetic-name-guard`, pre-merge

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
