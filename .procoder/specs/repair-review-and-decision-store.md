# repair-review-and-decision-store

Status: complete

## Problem

`accept_repair` (`repair.py`) decides whether an LLM repair replaces a transcribed
subtitle line. Its own docstring states the acceptance bar -- same referent, same sense --
and then says plainly that NOTHING BELOW ENFORCES THAT. This is measured, not feared:
`factory -> needle` and `VIVRA card -> Vivi card` both pass every mechanical gate, and the
word-deletion class found on 2026-08-27 (`the flame flame fruit` -> `the flame fruit`,
length ratio 0.88, inside the 0.6-1.5 band, shorter so `fits_card` passes, no new token for
`invents_name`) is structurally invisible to it. The enforcement is a human read.

That read currently has no home in the software. The 45 unanchored repairs from One Pace
S31E01-E03 were reviewed on 2026-08-27 by hand-annotating a Markdown file that an agent
generated and an agent parsed back. The owner's verdicts -- 41 accepted, 4 rejected, 5 of
the 41 silently hand-corrected -- exist only as prose in `docs/Adversarial Reviews/`. They
cannot be applied to the episodes, cannot survive a re-run, and cannot reach anyone else
running this pipeline on their own library.

Why now: `REPAIR_UNANCHORED` is the last gate holding back [S-12] of the arc-scoped spec.
Every card in One Pace S31 is unanchored (6,492 `no_reference`), so a regression shipped
there has no downstream repair path -- recovery today is edit-glossary-and-re-run. Opening
that gate without a review loop makes each regression permanent. Building the loop first
makes it correctable per line.

## Users

- **The maintainer, reviewing.** Needs the ~25 judgement-worthy lines per episode in front
  of him with their evidence, an approve / reject / hand-correct action per line, and the
  result written into the episode without an agent as intermediary. Reviews in batches in
  the evening, not while the pipeline runs.
- **The maintainer, operating.** Needs the review loop to never stall the GPU sweep, never
  fail an episode, and never require attention on shows he has not opted into gating.
- **A downstream user who wants dubtitles and nothing else.** Runs the container, gets the
  maintainer's committed decisions applied automatically, reviews nothing, configures
  nothing, and never sees this subsystem.
- **A downstream user who cares about their library.** Opts into reviewing their own
  episodes, and (phase 2, out of scope here) contributes decisions back.

## In scope

- [S-1] Queue accepted repairs for human confirmation. `unresolved.py` already implements
  the human rung of the deterministic -> LLM -> human ladder, but only records what the
  pipeline COULD NOT settle. An accepted repair was settled -- by a gate that does not check
  meaning. Add stage `repair_applied`, reason `accepted`, recorded on the success path
  alongside the existing `audit.append`, carrying the same evidence the rejection paths do.
- [S-2] A decision store, `decisions.py`: per-show JSON keyed on the normalised
  `(orig, proposed)` TEXT PAIR, never on episode or card index. Load, lookup, record, save.
  Auto-creates a show's file on first verdict, the way `mine_glossary.py` creates a
  glossary. Atomic writes, mirroring `unresolved._rewrite`.
- [S-3] Promote term-level verdicts into the show glossary. Where a decision's lesson is a
  TERM (`Samadai -> Samurai`) rather than a line, write it to `hard_fixes` so it applies
  show-wide through `glossary.correct()` and ships in the already-committed glossary. A
  decision records what it promoted.
- [S-4] Consult the store inside `repair.py`, after `glossary.correct()` and before
  `accept_repair`. A `reject` verdict keeps the ASR text; a `correct` verdict substitutes
  the human's wording; an `accept` verdict applies and suppresses the [S-1] queue entry; a
  `force` verdict admits a repair `accept_repair` refused. `DECISIONS_APPLY` (default 1)
  switches the whole path to suggestion-only.
- [S-5] Write-back for episodes already generated, `review_apply.py`: rebuild the `.srt`
  from `conf.json` with decisions applied -- the mechanism `recreate_srt.py` already uses --
  then invalidate the `.dubtitles.done` stamp so the existing merge loop re-muxes. Operates
  on one episode or sweeps a whole show.
- [S-6] An optional pre-mux gate, and a stall alert so it can never hold silently. For a
  show named in `REVIEW_GATE_SHOWS`, `mux.py` skips
  any episode with pending `repair_applied` entries. Unlisted shows behave exactly as today.
  A held episode is NEVER auto-released -- releasing unreviewed repairs is the failure this
  spec exists to prevent -- but one held longer than `REVIEW_GATE_STALE_DAYS` is reported
  loudly by `mux.py`, and the merge sweep's summary carries the held count, so a backlog is
  visible rather than silent.
- [S-7] A review server, `review_server.py`: stdlib `http.server`, no new dependency. Lists
  episodes with pending counts, renders one episode's queue (primary filter by default, full
  unresolved walk on request), accepts a verdict per line, triggers [S-5]. Every route is a
  thin call into [S-2] and [S-5]; the server holds no durable logic. Every write route
  requires a token. `REVIEW_TOKEN` unset does NOT mean no auth: the server generates a
  random token on first start, writes it to `<DECISIONS_DIR>/../review_token` (0600) and
  prints it once to the container log. Only `REVIEW_TOKEN=` set explicitly empty disables
  auth, for a network the operator has decided is isolated.
- [S-8] Run the server as a third loop in `container_run.sh`, alongside the existing merge
  and generate loops. Its failure must not take down the container.
- [S-9] `DECISIONS_DIR` (default `/config/decisions`), a mount, sibling in role to
  `GLOSSARY_DIR`. The format is a plain per-show JSON file so a network fetcher can later
  sit behind `decisions.load()` without changing the format or any caller.

## Out of scope

- **The contribution channel.** Submitting decisions upstream -- own-token fork-and-PR when
  `GITHUB_TOKEN`/`FORGEJO_TOKEN` is set, an export bundle when it is not -- is phase 2 and
  gets its own spec. Decided 2026-08-27: no shared credential is ever baked into the image;
  a token in an image is extractable, is auto-revoked by secret scanning when it reaches a
  public repo, and makes one identity answerable for every install's submissions.
  **Precondition added 2026-08-27:** phase 2 may not open until the cross-model pair-hit
  rate is measured -- transcribe One Pace S31E01-E03 under a second configuration that
  bumps `TRANSCRIBE_VERSION`, replay repair on both, and count how many of arm A's
  `(orig, proposed)` pairs `lookup()` still hits in arm B. Shipping a contribution channel
  on an unmeasured hit rate would export a corpus nobody can be told the value of.
- **Tightening `accept_repair`.** Deferred by the owner pending more human-reviewed data.
  This spec BUILDS the instrument that produces that data; it does not change the gate.
- **Flipping `REPAIR_UNANCHORED`.** A separate decision, owned by the maintainer.
- **Changing the baked `WHISPER_MODEL` default.** Raised in the same conversation; it
  changes transcription and therefore stales the `TRANSCRIBE_VERSION` tier per ADR 0001.
  Its own commit, its own decision about re-transcription.
- **Re-evaluating the implementation language.** Parked by the owner as its own exercise.
- **The hallucination `flag` queue.** Still deferred for the reason `unresolved.py` records:
  `maybe_silence` fires on 67% of real cards, and a queue nobody can face is worse than none.
- **Any authentication stronger than a shared token.** No user accounts, no OAuth, no TLS
  termination inside this service. REVISED 2026-08-27 after the fifth adversarial review
  (`docs/Adversarial Reviews/GLM-2026-08-27-repair-review-and-decision-store.md`, Item 5 --
  its one surviving BLOCK). The original decision was "unset means no auth, which is the LAN
  default", justified by review friction. That reasoning was about the MAINTAINER's friction
  and did not transfer: `container_run.sh` runs as root so `generate.py` can chown into the
  media tree, [S-8] adds write routes to that same process tree, and a downstream user
  running with host networking would expose an unauthenticated root-owned endpoint that can
  rewrite subtitle files and force re-muxes. Auto-generating the token keeps the
  maintainer's friction at "read it from the log once" while removing the unsafe default.

## Constraints

- **No new runtime dependency.** `pyproject.toml` declares three (`pysubs2`,
  `faster-whisper`, `jellyfish`) and there has never been a web framework here. The server
  is stdlib `http.server`.
- **Card timing is immutable in repair (C1).** A human's corrected text is still subject to
  `fits_card`; the repair gives way, never the timing.
- **Never fail an episode.** The queue side inherits `unresolved.py`'s contract: it is
  observability and must never raise. The apply side is behavioural, so it fails CLOSED --
  an unreadable store means today's behaviour, not a crashed run.
- **ADR 0001 (two-tier idempotency).** With an empty store [S-4] is a no-op, so shipping it
  needs no `TEXT_VERSION` bump. Applying decisions to already-generated episodes is done by
  per-episode stamp invalidation ([S-5]), not a global version bump -- targeted re-mux
  instead of a library-wide re-run.
- **The generate loop is the container's foreground process.** [S-8] must not be able to
  end it.
- **Decisions must degrade safely, and recur within a run.** REVISED 2026-08-27 after the
  fifth adversarial review (Item 1). The original claim was "decisions must be portable...
  the text pair does [survive]" -- an invariant the spec asserted and never measured. What
  is actually delivered, and all that may be relied on:
  - **A miss is a no-op.** An `orig` that no longer matches falls through to
    `accept_repair`, which is today's behaviour, not a misapplied stale verdict.
  - **Within one transcription run, the same line recurs byte-identically across
    episodes** -- measured in `REVIEW-2026-08-27-unanchored-repair-45-lines.md`:
    `"Roger's treasure belongs to me"` appears in E01, E02 AND E03 with an identical fix,
    and `"That come together."` in E01 and E02. One verdict settles all of them. This is
    the store's immediate, evidenced value and it does not depend on cross-model stability.
  - **Cross-model and cross-`TRANSCRIBE_VERSION` portability is UNMEASURED.** Card index
    still cannot be used -- it does not survive a `TEXT_VERSION` bump -- so the text pair
    remains the right key. But no claim is made about the hit rate in another user's
    library, and none may be made until it is measured. See "Out of scope".
- **`procoder check` clean and `procoder test` green** before any task closes.

## Interfaces

### `decisions.py`

    load(show, dir=DECISIONS_DIR) -> dict          # {} when absent or unreadable
    lookup(store, orig, proposed) -> dict | None    # normalised pair match
    record(store, orig, proposed, verdict, text="", note="", promoted=None) -> dict
    save(store, show, dir=DECISIONS_DIR) -> bool    # atomic temp + os.replace
    key(text) -> str                                # lowercase, collapse whitespace,
                                                    # PUNCTUATION PRESERVED

`decisions_for(path)` mirrors `repair.glossary_for()`: walk up to the first ancestor
directory with a matching `<Show>.json`. Show identity is that DIRECTORY'S BASENAME, not
`gloss["show"]` -- corrected 2026-08-27 during implementation. `gloss["show"]` is a display
name: `glossaries/Cowboy Bebop (1998) {tvdb-76885}.json` carries `show == "Cowboy Bebop"`.
Keyed on the display name, a show's decision store and its glossary would be two
differently named artifacts for one show and every lookup would miss without ever erroring.

### `review_apply.py`

    python3 review_apply.py <episode-stem>          # one episode
    python3 review_apply.py --show <show-dir>       # sweep, for a newly pulled store
    --apply                                         # dry-run by default, per repo convention

### `review_server.py`

    GET  /                     episodes with pending counts
    GET  /ep/<stem>            queue; primary by default, ?all=1 for the full walk
    POST /decide               {stem, index, verdict, text?, note?} -> [S-2]
    POST /apply/<stem>         -> [S-5]

### Environment

    DECISIONS_DIR      default /config/decisions
    DECISIONS_APPLY    default 1     (0 = suggestion-only; matches never change output)
    REVIEW_GATE_SHOWS      default ""   (colon list, idiom shared with MUX_ROOTS)
    REVIEW_GATE_STALE_DAYS default 7    (a held episode older than this is reported loudly;
                                         it is NEVER auto-released -- see [S-6])
    REVIEW_PORT            default 8842
    REVIEW_TOKEN           unset = GENERATE one and print it to the log; set = use it;
                                         set-but-empty = auth disabled, operator's choice

## Data

`<DECISIONS_DIR>/<Show>.json`, one file per show, sibling in role and naming to
`glossaries/<Show>.json`, committed to git the same way:

    {
      "show": "One Pace",
      "version": 1,
      "decisions": [
        { "orig": "we're looking for a factory.",
          "proposed": "we're looking for a needle.",
          "verdict": "reject",
          "note": "different referent",
          "run": "review" },

        { "orig": "i relied on the brave assistance of my fellow samadai,",
          "proposed": "i relied on the brave assistance of my fellow samadai.",
          "verdict": "correct",
          "text": "I relied on the brave assistance of my fellow Samurai.",
          "promoted": { "hard_fix": { "Samadai": "Samurai" } },
          "run": "review" }
      ]
    }

`orig` and `proposed` are stored normalised (they are the key). `text` carries the human's
wording verbatim, un-normalised, and only for `verdict: "correct"`.

The verdict set, decided 2026-08-27:

    accept    the repair was right; apply it and stop asking
    reject    the repair was wrong; keep the ASR text
    correct   neither was right; use `text` instead
    force     `accept_repair` refused this repair and was wrong to; admit it

`force` overrides the JUDGEMENT gates -- the length-ratio band, the ref-borrow cap,
`invents_name` and the phonetic guard. It does NOT override `fits_card`: card timing is
immutable in repair (C1), so a forced repair that cannot be rendered is still refused, on
the same terms as a `correct` verdict that does not fit. Force verdicts are recorded
distinctly from `accept` precisely so they can be counted -- they are the evidence for the
deferred `accept_repair` tightening, which is exactly the record of the gate being wrong in
the direction the gate cannot see.

**The stakes of `force`, added 2026-08-27 after the fifth adversarial review (Item 2).** On
an ANCHORED card a forced repair is recoverable: the fansub reference still exists, so a
later review can judge it again. On an UNANCHORED card it is not -- the spec's own Problem
section is that nothing downstream can reach those cards. The verdict itself stays editable
by a human through [S-7], and R4 only protects it from being reverted by an AUTOMATED sweep;
but any episode muxed while a wrong `force` stood carries that text until someone notices.
The review UI must show this on the force action for an unanchored card. The review's
audio-based objection was withdrawn on its own rebuttal and is not the reason: the owner's
bar is text-based, the 45-line read was text-based, and `accept` on an unanchored card is
equally audio-free. Permanence is the reason.

**What each verdict means per entry type.** The queue carries two question shapes, so the
mapping is pinned here rather than left to the UI:

    entry              accept          reject            correct        force
    repair_applied     keep the        restore the ASR   use `text`     n/a (already
      /accepted        repair          text                             applied)
    rejected_guard     n/a -- use      uphold the gate;  use `text`     admit the
      /_name_invented  `force`         keep the ASR                     refused proposal

`accept` is not offered on a refused entry and `force` is not offered on an applied one.
Without this, `accept` on a refused entry would silently be a `force` with no distinct
record, defeating the counting `force` exists for.

**`orig` is the PRE-correction ASR text** -- `c["text"]` as it stands before
`glossary.correct()` runs, which is also what a `reject` verdict restores. It is NOT the
post-correction proposal. This matters: keyed on post-correction text, every stored `orig`
would be invalidated by an unrelated `hard_fixes` addition to the show glossary, which
`mine_glossary.py` appends on every sweep of a watched show.

**`promoted` is set by the human at review time and is an audit trail, not a classifier.**
No rule auto-decides whether a verdict is term-level or line-level. The review considered
auto-classification on a single-token proper-noun difference and it fails on this spec's own
examples: `factory -> needle` is a single-token difference between two ordinary English
words and would be promoted show-wide, which is the exact regression the store exists to
catch. The human classifies; `promoted` records what they chose.

Decided with the owner 2026-08-27. The reasoning: the gate provably errs in BOTH directions.
[S-14] and [S-15] blocked nothing across 21 repairs, and the 4 proposals the gate did refuse
have never been judged by anyone. Making the human the authority in one direction only would
leave a correct repair the gate wrongly refused permanently unreachable -- and on an
unanchored card, nothing downstream can reach it either.

`run: "review"` mirrors `glossary_acquire`'s R4: a human's decision is durable and is never
reverted by an automated sweep.

No `by` or `at` provenance in phase 1 -- an earlier draft of this example showed both and
nothing implemented or tested them. Authorship matters when a store is merged with someone
else's, which is the contribution channel, so those fields belong to phase 2 and will be
specified there rather than half-carried here.

Queue entries live where they already do -- `<stem>.dubtitles.unresolved.jsonl`, owned by
`unresolved.py`, per-episode, JSONL, resolved entries retained as an audit trail.

Ownership: the maintainer owns the committed store; a downstream user's local store is
theirs, and nothing leaves their machine in this phase.

## Edge cases

- **The same line appears on several cards.** Pair-keyed decisions apply to all of them.
  This is intended: the word-deletion regression occurred on two separate cards with
  identical text, and one verdict should settle both.
- **A human's corrected text does not fit the card.** Timing is immutable, so the text
  cannot win. The ASR text is kept AND an unresolved entry is recorded -- the human is told
  their correction was refused rather than having it silently dropped.
- **A `correct` verdict whose text equals the original ASR text.** Semantically a
  rejection; normalised to `reject` at record time so lookup has one meaning per outcome.
- **Empty `orig` or `proposed`.** Refused at record time; an empty key would match broadly.
- **The model's output changes, so `proposed` no longer matches.** No match, falls through
  to `accept_repair`. Degrades to today's behaviour rather than misapplying a stale verdict.
- **Punctuation-only repairs.** The majority of this stage's work. Punctuation is preserved
  in the key, so `CP-0.` and `CP?` remain distinct pairs.
- **A downstream user pulls a store for a show they already generated.** Their episodes
  carry valid `.dubtitles.done` stamps and nothing would re-trigger. `review_apply.py
--show` is the mechanism: it matches stored pairs against existing `conf.json` rows and
  invalidates only the episodes that actually change.
- **Two shows whose directories share a basename.** Resolved the way `glossary_for()`
  already resolves it -- nearest ancestor wins.
- **`repair.py` reading the store while the server writes it.** Atomic temp + `os.replace`,
  so a reader sees the old file or the new one, never a partial.

## Failure modes

- **`DECISIONS_DIR` missing or unreadable** -> empty store, logged once, episode proceeds
  with today's behaviour. Absence of decisions is the pre-existing state, so this is safe.
- **A show's JSON is corrupt** -> that show's store refuses to load, logged LOUDLY, and the
  run continues with an empty store. Never half-loaded: a partially-read decision file is
  indistinguishable from a smaller one, which is the failure `unresolved.items()` avoids by
  dropping only a torn final line.
- **Store write fails** -> the verdict is reported as NOT saved. A review that silently
  discards the human's decision is worse than one that errors, because the human believes
  the line is settled.
- **The server's port is in use, or the server crashes** -> logged; the merge and generate
  loops continue. The container's foreground process is unaffected.
- **`review_apply.py` cannot rebuild the srt** (no `conf.json`) -> refuses that episode and
  says why, matching `repair.py`'s "skip" when the srt is absent. The stamp is NOT
  invalidated, so nothing is left in a half-applied state.
- **`REVIEW_GATE_SHOWS` names a show that never produces queue entries** -> nothing is ever
  gated. The pending check is the only RELEASE condition -- an episode is held while and only
  while it has a pending entry.
- **A gated show is left unreviewed for weeks** -> every episode with a pending entry stays
  held, and the backlog grows. This is the designed behaviour, not a fault: auto-releasing
  unreviewed repairs is the failure the spec exists to prevent. What must not happen is the
  backlog being SILENT, so `REVIEW_GATE_STALE_DAYS` makes it loud ([S-6]). The operator
  releases it by reviewing, or by removing the show from `REVIEW_GATE_SHOWS` -- both explicit.
- **The LLM backend is down** -> unchanged. `llm_empty` already records it; no repairs are
  proposed, so no queue entries are created.

## Acceptance criteria

- [ ] [S-1] An accepted repair writes one `repair_applied`/`accepted` entry to
      `<stem>.dubtitles.unresolved.jsonl` whose `original_text` equals the card's
      pre-repair text and whose `proposed_text` equals the text actually applied -- asserted
      on the FIELDS, not only on the count, which a pair of empty strings would satisfy.
      The entry count also equals the summary's `repaired` count for that episode.
- [ ] [S-1] `unresolved.pending()` filtered to the primary stages returns exactly the
      accepted repairs plus the guard rejections, and the unfiltered walk additionally
      returns `no_reference`, `llm_empty` and the punctuation stages.
- [ ] [S-2] `decisions.key()` maps `"  We're  Looking  For A Factory. "` and
      `"we're looking for a factory."` to the same key, and maps `"CP-0."` and `"CP?"` to
      different keys.
- [ ] [S-2] `lookup()` on a store built from a recorded verdict returns that verdict for the
      same pair and `None` for a pair differing only in `proposed`.
- [ ] [S-2] Recording a verdict for a show with no existing file creates the file; a second
      verdict appends without losing the first; a crash-simulating partial write leaves the
      previous file intact.
- [ ] [S-2] `record()` refuses an empty `orig` or `proposed`, and converts a `correct`
      whose text equals the original into a `reject`.
- [ ] [S-3] A decision promoted as a term writes `hard_fixes[variant] = canonical` into the
      show glossary, the decision records what it promoted, and a curated entry already
      present is not overwritten.
- [ ] [S-4] With a `reject` verdict stored for the pair, the card's text equals the
      POST-`glossary.correct()` ASR text and no `repair_applied` entry is written -- pinning
      the consult between `glossary.correct()` (`repair.py:634`) and `accept_repair`
      (`repair.py:649`), so a consult placed before the correction fails this.
- [ ] [S-4] With a `correct` verdict stored, the card carries the human's text.
- [ ] [S-4] A `correct` verdict whose text fails `fits_card` leaves the ASR text in place
      and records an unresolved entry naming the refusal.
- [ ] [S-4] With a `force` verdict stored for a pair `accept_repair` refuses, the repair is
      applied; the same pair with no verdict is still refused.
- [ ] [S-4] A `force` verdict whose text fails `fits_card` is still refused, and records an
      unresolved entry naming the refusal -- force does not override card timing.
- [ ] [S-4] `DECISIONS_APPLY=0` produces byte-identical output to an empty store for the
      same episode and the same NON-empty stored decisions, and no verdict is applied --
      asserted on the application, not only on the bytes, since identical output proves the
      flag works without proving it is read before the verdict takes effect.
- [ ] [S-4] An empty store produces byte-identical output to the code before this change,
      AND the lookup is observably called -- a `return` short-circuiting before the consult
      would otherwise satisfy the byte-identical half on its own.
- [ ] [S-5] `review_apply.py` on an episode with a stored `reject` rewrites the `.srt` with
      the ASR text restored and invalidates the `.dubtitles.done` stamp, WITHOUT invoking the
      LLM -- it rebuilds from `conf.json` the way `recreate_srt.py` does. Asserted on the
      backend never being called, because re-running `repair.py` also rebuilds the srt from
      `conf.json` and would otherwise satisfy this criterion.
- [ ] [S-5] Without `--apply` it writes nothing and prints the plan.
- [ ] [S-5] `review_apply.py --show` invalidates only the episodes whose text actually
      changes, leaving the rest of the show's stamps valid.
- [ ] [S-5] An episode with no `conf.json` is refused by name, and its stamp is untouched.
- [ ] [S-6] With a show listed in `REVIEW_GATE_SHOWS`, `mux.py` skips an episode holding a
      pending `repair_applied` entry and muxes it once that entry is resolved; with the list
      empty, both episodes mux.
- [ ] [S-6] An episode held longer than `REVIEW_GATE_STALE_DAYS` is reported loudly and
      counted in the sweep summary, and is still NOT muxed -- the alert must not become a
      release.
- [ ] [S-7] `GET /ep/<stem>` returns the primary queue by default -- asserted on the
      ABSENCE of `no_reference` and `llm_empty` entries, since `unresolved.pending()` applies
      no stage filter of its own and a server returning everything would otherwise pass --
      and the full walk with `?all=1`; `POST /decide` persists through `decisions.py` and the entry becomes
      resolved; `POST /apply/<stem>` invokes [S-5]. Handlers are tested directly, no socket.
- [ ] [S-7] With `REVIEW_TOKEN` unset, the server generates a token, persists it 0600, and
      a write route without it is REFUSED -- the unsafe default is the one being tested away.
      With `REVIEW_TOKEN` set explicitly empty, the same request succeeds. Read routes are
      unaffected either way.
- [ ] [S-8] `container_run.sh` starts the server as a background loop; killing the server
      leaves the merge and generate loops running.
- [ ] [S-9] `decisions_for()` resolves a show's store by the same ancestor walk
      `glossary_for()` uses, and returns an empty store when `DECISIONS_DIR` does not exist.
- [ ] All of the above verified by `procoder test` green and `procoder check` with zero
      blocking findings.

## Open questions
