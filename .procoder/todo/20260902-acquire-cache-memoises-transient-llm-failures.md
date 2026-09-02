# The acquisition cache memoises a transient LLM failure as if it were a decision

Status: open
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

- [ ] A raising backend leaves nothing reusable in the cache: the next run calls the LLM
      again for that pair.
- [ ] An unparseable response is treated the same way.
- [ ] A genuine low-confidence / negative model answer is still cached (the existing tests
      for that behaviour keep passing unchanged).
- [ ] Each of the above has a test that fails against the current unconditional
      `remember_escalation`.

## Evidence

<!-- filled at close -->
