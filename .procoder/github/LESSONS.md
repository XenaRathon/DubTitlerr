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
