# Lessons — findings that escaped our own gates

One entry per finding caught downstream (bot review, human review,
production) — the escape is the bug; the finding is its symptom. Every
entry names which layer should have caught it and the adaptation that now
does. `procoder lessons` flags entries with no adaptation.

Entry shape (unindented in real entries):

    ## <date> <where caught> — <one-line finding>

    - Class: mechanical | judgment | taste
    - Missed by: linter | rubric | controller | test | ci
    - Adaptation: <the concrete change that catches this class from now on>

== then register the commit template (once per clone):
git config commit.template .procoder/github/COMMIT_TEMPLATE.md

## 2026-08-27 subagent review — a re-decided verdict was silently unreachable

- Class: judgment
- Missed by: rubric
- Finding: `decisions.record()` appended and `lookup()` returned the first match, so a
  reviewer changing their mind wrote a second entry that was stored, shipped to git, and
  permanently unreachable. The sibling module documents this exact failure as its I3/C2
  invariant (`glossary_acquire.py:668`, "the both-states bug this module exists to avoid
  reintroducing") and the new module reintroduced it anyway.
- Missed because: all six acceptance criteria described a FIRST verdict. Nothing described
  a second one, so nothing tested one, and the story closed correctly against criteria that
  were incomplete rather than wrong.
- Adaptation: when a new module has a sibling with hard-won invariants, read that sibling's
  invariants BEFORE writing the criteria, not before writing the code. The scout sweep that
  surfaced I3 was run for Task 2 and would have caught this in Task 1 had it come first.

## 2026-08-27 subagent review — guards validated the shape of input but never its value

- Class: mechanical
- Missed by: test
- Finding: `record()` guarded an empty pair and a no-op `correct`, but accepted any verdict
  string at all (`"aceptt"`, `""`, `None`) and accepted a `correct` carrying no replacement
  text. The latter would have raised `KeyError` inside `repair.py` mid-episode, against this
  project's never-fail-an-episode contract, or rendered a blank card.
- Missed because: the criterion named the two guards to build. Having built exactly those
  two, the story was complete — a criterion that enumerates cases silently asserts the list
  is exhaustive.
- Adaptation: for any function taking untrusted input, the criteria enumerate the VALUE
  space (which values are legal), not just the failure cases already thought of. The
  test now passes `[..., None, 0, ["reject"]]` because the value arrives from a JSON body.

## 2026-08-27 subagent review — two tests asserted half of their guard's contract

- Class: mechanical
- Missed by: test
- Finding: the no-op-`correct` test asserted the verdict flipped to `reject` but not that
  the correction text was dropped; the empty-pair test used literal `""` and would have
  passed had the guard checked the raw argument instead of the normalised key.
- Missed because: each test was written from the criterion's wording rather than from the
  mutation that should break it.
- Adaptation: every guard test is mutation-checked before its story closes — break the
  production line, watch the test fail, restore. Applied to five behaviours in this sprint,
  and it caught two claims that had been implemented before their test existed
  (`save()`'s atomicity and `record()`'s `promoted` handling), both of which were passing
  on code nobody had proven.

## 2026-08-27 subagent review — three mutation checks that all moved the same direction

- Class: judgment
- Missed by: test
- Finding: the new `unresolved.record()` call in `repair.process()` was pinned by three
  hand-run mutations — below `c["text"] = new`, and into the reject branch — all of which
  failed correctly. The untested direction was UP, above the secondary-model block. Moved
  there, the whole suite stayed green while the queue recorded the discarded first-pass text
  for a card that shipped the secondary model's. A reviewer would have approved text the
  viewer never saw, on exactly the name-change-then-re-verified case the two-pass gate exists
  to catch.
- Missed because: three mutations felt like coverage. They were one mutation run three ways —
  every one of them moved the call later or sideways, none earlier.
- Adaptation: enumerate mutation directions before running them. For a call site, that means
  earlier and later than EVERY branch boundary it sits between, not only the boundary the
  author was already worried about.

## 2026-08-27 subagent review — a comment stated a reason the code contradicts

- Class: taste
- Missed by: rubric
- Finding: `unresolved.PRIMARY` excludes `punctuation`/`rejected_guard`, and the comment
  justified it by claiming those entries cannot be judged by reading two texts.
  `punctuation.py:290-296` records `original_text` and `proposed_text` exactly as the repair
  rejection that IS included does. The exclusion is right; the reason was invented.
- Missed because: nothing executes a comment, so no test, gate or lint can contradict one. It
  read plausibly and matched the shape of the surrounding real rationales.
- Adaptation: a comment explaining WHY something is excluded or refused is verified against
  the code it describes before the story closes, like any other claim. A false rationale is
  worse than none — it stops the next reader from looking.

## 2026-08-27 subagent review — a new authority did not disable the old ones

- Class: correctness
- Missed by: plan
- Finding: `[S-4]` made a human verdict outrank `accept_repair`. Two pieces of code written
  before that concept existed still ran afterwards and both silently undid it. The
  secondary-model pass reassigns `new` INSIDE the admitted branch, so an approved line was
  replaced by the second model's wording — and the sprint's own new suppression rule then
  wrote no queue entry, because the line counted as settled, so the substitution reached the
  viewer with nothing recording it. Separately, `accept` was left out of the bypass tuple and
  so was re-judged by `accept_repair` on every run; its answer is not stable over time
  (`LEN_RATIO_*`/`MAX_REF_BORROW` are operator knobs, the glossary changes, `ref` moves on a
  re-mux), so drift could revert an approved line AND re-queue it as a fresh `rejected_guard`.
- Missed because: a diff shows the code that was added, never the code that still runs after
  it. Both defects were downstream of the consult and looked untouched.
- Adaptation: when a change introduces an authority, enumerate every EXISTING actor that can
  still write the same value after the new authority has spoken, and write a test per actor.
  Corollary for suppression: any "don't record this" branch needs its own check that the
  thing suppressed is genuinely settled — a wrong suppression is silent by construction.

## 2026-08-27 self — a partial mock that did not mirror the real input

- Class: test-quality
- Missed by: rubric
- Finding: a three-card accounting test keyed its fake `llm` on substrings of the prompt
  (`if "spondum" in prompt`). `build_prompt` embeds the PREVIOUS and NEXT card as context, so
  every card's prompt contains its neighbours' text; card 2 received card 1's proposal, its
  stored verdict missed, and the counter under test stayed at 0. The test failed for a reason
  that had nothing to do with the code it was testing.
- Missed because: the mock mirrored the input's type but not its structure. It looked precise.
- Adaptation: a mock keyed on the content of a real payload must be checked against what that
  payload actually contains. Prefer keying on call ORDER when the sequence is deterministic —
  it cannot be fooled by context the mock's author did not know was there.

## 2026-08-27 self — a fixture that described a world the pipeline never produces

- Class: test-quality
- Missed by: rubric
- Finding: `review_apply.py` was designed and fully tested against a fixture that hand-wrote
  `conf.json`, `.eng.dubtitles.srt` and `.dubtitles.done` together. That combination cannot
  exist: `mux.py:367-371` removes both sidecars immediately after writing the stamp, and
  `dub_signs_merge.py:188` removes the srt earlier still. The module read the srt to learn
  what had shipped, so against the real library it would have refused every episode it was
  written for. Five green tests proved nothing, because all five described the same
  non-existent world.
- Missed because: the fixture was built from what the module needed to read, not from what
  the pipeline actually leaves behind. Nothing in a green suite can contradict that — the
  fixture IS the claim being tested against.
- Adaptation: before the first test of a module that touches existing files, write down the
  on-disk state of a REAL instance and verify each file against the code that creates and
  deletes it. The sidecar lifecycle was one grep away in `mux.py` and never read.

## 2026-08-27 self — reasoning forward from an unchecked premise to a confident wrong claim

- Class: correctness
- Missed by: rubric
- Finding: I observed correctly that `conf.json` holds pristine ASR text (repair never
  writes it back) and inferred that `[S-5]`'s "rebuild from conf.json" would revert every
  LLM repair in the library. I reported that to the owner as a defect in the plan. It was
  wrong: `merge_pass.sh:59` re-runs `repair.py` whenever an srt exists with no ass, which
  re-derives the repairs and applies the stored verdicts on the same pass. The observation
  was true; the inference was not; the plan was right.
- Missed because: I traced the code I was WRITING and not the code that runs after it —
  the identical failure the previous lesson names, applied to `fits_card` and then missed
  for the pipeline itself. A correct observation made the conclusion feel verified.
- Adaptation: when a finding contradicts the spec, treat the spec as the stronger prior
  until the contradiction is traced end to end. Say "observed X, therefore suspect Y,
  tracing now" rather than reporting Y as established. Three greps separated the two here.

## 2026-08-27 self — read the function from its def line, not from the interesting part

- Class: correctness
- Missed by: rubric
- Finding: checking whether `dub_signs_merge` always writes an `.ass` (which decides whether
  `merge_pass.sh` re-runs repair on a held episode), I read from line 160, saw
  `base.save(out_ass)`, and reported that repair never re-runs. `build()` returns
  `"no-signs", 0, 0` at line 126 for any episode with no signs track — the ordinary case for
  every dialogue-only episode. Repair therefore re-ran every 600s on a held episode,
  appending a duplicate queue row each time and refreshing the mtime the [S-6] stall alert
  uses as its clock, so that alert could never fire for exactly the stuck episodes.
- Missed because: I started reading where the relevant code appeared to be. An early return
  is invisible from below, and control flow is precisely what the question was about. Worse,
  I had suspected this exact failure, "checked" it, and reported the suspicion refuted.
- Adaptation: for any control-flow claim about a function, read from its `def` line. A
  function too long to read whole is itself a finding, not a licence to skim.

## 2026-08-27 subagent review — a hold finds every bug that assumed a state was transient

- Class: correctness
- Missed by: plan
- Finding: `repair.py` re-queueing an already-queued line on every merge sweep was always
  true, and always harmless: episodes were muxed promptly, their sidecars removed, and the
  queue never read twice. The [S-6] gate holds an episode indefinitely, and the same
  re-append became unbounded queue growth (~144 copies/day at the default MERGE_INTERVAL),
  a reviewer seeing one line repeatedly, and a disarmed stall alert.
- Missed because: the defect was not in the new code and not in the diff. It was a
  pre-existing assumption — "this state does not last" — that the new feature falsified.
- Adaptation: of any new hold, pause, gate or retry, ask directly: what did the surrounding
  code assume would end soon? Then check each of those assumptions against an indefinite
  duration. Also worth pairing with the sprint-004 lesson: enumerate what else writes the
  value, AND what else assumed the state was brief.

## 2026-08-27 subagent review — a guard that passed while the property it protects was false

- Class: correctness
- Missed by: rubric
- Finding: three separate guards in `review_server.py` were documented as enforcing
  something and did not, on inputs no test used. The 1MB body cap: `int("-1")` does not
  raise, `-1 > 1<<20` is False, and `rfile.read(-1)` reads to EOF — unbounded, pre-auth,
  from any LAN client, in the one check whose comment claimed the read was bounded. The
  token: a persistence failure returned a fresh random token on every call, so every write
  401'd forever including for the operator holding the token printed at startup. The
  allow-list: `os.walk` lists symlinked FILES, so a planted symlink entered the set every
  route trusts as its security boundary.
- Missed because: every test exercised a happy value — a small body and an oversized one, a
  writable token dir, a real conf.json. Mutation testing asks "what change breaks this
  test", which none of these were; the guards were present and the mutations would have been
  caught.
- Adaptation: for each guard, ask what input makes the GUARD PASS while the property it
  protects is FALSE. That is a different question from the mutation one and finds a
  different class of defect. Negative and absent values first, for any numeric bound.

## 2026-08-27 self — "this file does not cover X" is a to-do, not a boundary

- Class: test-quality
- Missed by: rubric
- Finding: `tests/test_review_server.py` opened with "handlers only, no socket is ever
  opened", which read as a deliberate scoping decision. The review's highest-severity
  finding lived entirely in the layer that sentence excluded — `Handler.do_POST`, where the
  body cap is enforced before authentication.
- Missed because: the exclusion had a good rationale (do not open sockets in a unit suite),
  and a good rationale for not testing something reads as a decision rather than a gap. The
  rationale was about SOCKETS, not about the handler, and those were conflated.
- Adaptation: when a test file states what it does not cover, treat that sentence as a
  to-do. Ask whether the stated reason actually forces the exclusion — here a handler can be
  driven with fake streams and no socket at all, so it never did.

## 2026-08-27 self — a test that checked the dependencies of a list but never its membership

- Class: test-quality
- Missed by: rubric
- Finding: `tests/test_dockerfile_copy.py` exists because `qc.py` passed 987 tests and
  ImportError'd on container start, having never been added to the image. Its check walks
  what each entrypoint IMPORTS and asserts each import is COPY'd — and never asks whether
  the entrypoint itself is. Removing `review_server.py` from the COPY line broke no test.
  The exact failure the file was written to prevent survived inside it, for every entrypoint
  added since it was written.
- Missed because: the test's name and docstring describe the qc.py incident convincingly, so
  it reads as covering that class. It covers one half of it.
- Adaptation: when a test enforces a rule over a LIST, assert the list's own membership as
  well as the per-item property. "Is everything X depends on present" is not "is X present".
  Worth sweeping wherever a test iterates a registry.

## 2026-08-27 external review — the oldest entry point was the one nobody checked

- Class: correctness
- Missed by: rubric
- Finding: five internal review rounds examined the decision store, the repair consult, the
  write-back, the mux gate and the HTTP server. None looked at `unresolved.py --review`, the
  CLI that predates all of them. It does not import `decisions` at all, so a human answering
  "needs fixing" set a flag, wrote nothing durable, and had the repair re-applied on the next
  run and suppressed from the queue — their judgement dropped in silence while the audit
  trail recorded that they had made one. The CLI's reject was indistinguishable from its
  accept.
- Missed because: every internal round reviewed the code that had just changed. The CLI had
  not changed, so nothing drew attention to it — but the NEW concept (a durable verdict)
  changed what the old code was required to do.
- Adaptation: when a change introduces a durable concept, list every existing entry point
  that produces the same KIND of decision and check each one writes it. This is the
  sprint-004 lesson (enumerate the other actors) applied to inputs rather than to writes.

## 2026-08-27 self — a mutation that changes nothing may be pointing at dead code

- Class: code-quality
- Missed by: rubric
- Finding: `repair.py`'s supersession loop was written with an `if prop_old != pair[1]`
  guard. A mutation flipping it to `if True` changed no test result. The reflex is "a test is
  missing"; the truth was that an identical pair can never reach that line, because
  `pair not in queued_pairs` already skipped it and `queued_pairs` includes pending entries.
  The condition could never be false.
- Missed because: an uncaught mutation is habitually read as a coverage gap, and that reading
  is usually right — so the other possibility does not get considered.
- Adaptation: when a mutation changes no behaviour, check whether the mutated line is
  reachable in the false case before writing a test for it. Dead code is worth deleting, not
  covering, and a test written for it would have asserted something that cannot happen.
