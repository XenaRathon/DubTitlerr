# The acquisition cache memoises a transient LLM failure as if it were a decision

Status: closed 2026-09-02
Created: 2026-09-02

## Description

`glossary_acquire.adjudicate_merge` returns `{"same_entity": False, "confidence": "none"}`
for FOUR different situations (glossary_acquire.py:345-371): the backend raised, the
backend returned nothing, the response held no JSON object, and the JSON did not parse.
Only the last two are even arguably an answer; none of them is the model saying "these are
not the same entity". `escalate` then hands that dict to
`acquire_cache.remember_escalation` (glossary_acquire.py:394-398), and the next run's
`escalation_for` returns it non-empty, so `if not adj` is false and the LLM is never asked
again. There is no TTL, no failure marker, no cache version, no invalidation.

A transient Ollama/llama.cpp outage during one sweep therefore strands a valid glossary
candidate permanently. `ACQUIRE_NO_CACHE=1` is a manual escape hatch an operator has to
know to reach for; `gen_loop.sh` does not set it.

Deferred deliberately on 2026-09-02 (beta-readiness triage): acquisition is dry-run by
default and this strands candidates rather than corrupting subtitle text, so it does not
block the public beta.

Done looks like: a transport or parse failure is distinguishable from a model answer, and
only a real adjudication is memoised. Recording the failure separately and retrying it on
the next run is equally acceptable -- what must not survive is a failure that is
indistinguishable from a decision.

## Acceptance criteria

- [x] A raising backend leaves nothing reusable in the cache: the next run calls the LLM
      again for that pair.
      `tests/test_acquire_cache.py::test_an_unavailable_result_is_not_memoised`
- [x] An unparseable response is treated the same way -- all four unusable paths covered.
      `tests/test_glossary_acquire.py::test_every_unusable_llm_response_is_marked_unavailable`
- [x] A genuine low-confidence / negative model answer is still cached; the existing
      caching tests pass unchanged.
      `tests/test_acquire_cache.py::test_a_genuine_none_confidence_answer_is_still_cached`
      and `test_a_parsed_answer_is_never_marked_unavailable`
- [x] Mutation-checked: removing the guard in `remember_escalation` fails the first test.

## Evidence

Implemented on `feat/review-sorting`, 2026-09-02.

- `adjudicate_merge`'s four unusable paths (backend raised, empty response, no JSON object
  found, object does not parse) now return the negative shape plus `"unavailable": True`.
  The shape is unchanged for every existing caller's `same_entity`/`confidence` reads.
- `acquire_cache.remember_escalation` drops an `unavailable` result instead of storing it.
  The guard is there rather than at the call site because that is where every path which
  could write a failure converges -- a caller that forgets the check cannot reintroduce it.
- The marker never reaches a stored entry, so a later reader of the cache file does not
  have to know what it means.
- 6 new tests; full suite green, `ruff check .` clean.

Deliberately NOT done: no TTL, no cache version, no invalidation. None is needed once a
failure is never written -- and each would be a second mechanism to get wrong.
