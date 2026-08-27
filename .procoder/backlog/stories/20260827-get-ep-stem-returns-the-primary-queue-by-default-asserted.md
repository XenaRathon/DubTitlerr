# `GET /ep/<stem>` returns the primary queue by default -- asserted on the ABSENCE of `no_reference` and `llm_empty` entries, since `unresolved.pending()` applies no stage filter of its own and a server returning everything would otherwise pass -- and the full walk with `?all=1`; `POST /decide` persists through `decisions.py` and the entry becomes resolved; `POST /apply/<stem>` invokes the write-back of Task 5. Handlers are tested directly, no socket.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 007-task-7-the-review-server-plus-the-orphan-entry-fix-the

## Description

Task 7. The owner asked for the judgement-worthy lines by default with a full deep-dive available. Done
means the default view carries neither `no_reference` nor `llm_empty` and `?all=1` includes them.

Asserted on the absence, for the same reason as the queue filter: `unresolved.pending()` filters
nothing on its own.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `GET /ep/<stem>` returns the primary queue by default -- asserted on the ABSENCE of `no_reference` and `llm_empty` entries, since `unresolved.pending()` applies no stage filter of its own and a server returning everything would otherwise pass -- and the full walk with `?all=1`; `POST /decide` persists through `decisions.py` and the entry becomes resolved; `POST /apply/<stem>` invokes the write-back of Task 5. Handlers are tested directly, no socket.

## Evidence

- `test_the_default_view_omits_non_primary_reasons` -- asserted on the ABSENCE of
  no_reference and llm_empty, since `unresolved.pending()` applies no stage filter of its own
  and a server returning everything would pass a presence-only check. `?all=1` still reaches
  the full walk.
- `test_decide_persists_a_verdict_and_resolves_the_queue_entry` -- BOTH writes: the decision
  is what stops repair.py re-applying and re-queueing, the resolved flag is what empties the
  reviewer's queue. Sprint 006 found the gate holding forever when only one happened.
- `test_apply_invokes_the_write_back` asserts the delegation to [S-5], not just a success
  payload, because a route that reported success while doing nothing looks identical outside.
- `test_the_verdicts_offered_depend_on_the_entry` and
  `test_decide_refuses_a_verdict_the_entry_does_not_offer` -- enforced SERVER-side; a client
  is not a trust boundary, and `accept` on a refused entry would be a force with no distinct
  record.
- `test_forcing_an_unanchored_card_is_labelled_permanent` -- every S31 card is unanchored, so
  this is the common case rather than an edge.
- `test_an_unknown_stem_is_refused_by_every_route` -- a stem is a file path and this process
  runs as root; /etc/passwd, ../../etc/shadow and stem/../ep are all refused before a file is
  touched. Plus `test_a_symlinked_conf_outside_the_roots_is_not_in_the_allow_list`.
- Found by attacking the page: html.escape is right for HTML text and wrong for the JS and
  URL contexts -- a show directory containing "&" produced a STEM the browser posted back
  that no _resolve() recognised, refusing every verdict on that show.
- The transport layer is now covered too (`_Wire`), which is where the review's HIGH finding
  lived: a negative Content-Length defeated the pre-auth body cap.
