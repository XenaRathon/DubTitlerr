# Task 1 and 2 -- the decision store and glossary promotion

Status: active
Created: 2026-08-27

## Goal

At the end of this sprint a human verdict on a repaired subtitle line is a durable object
rather than a sentence in a Markdown file: it can be recorded, found again from the same
line next run, and shipped in git the way a glossary is.

Concretely: `decisions.py` exists and owns a per-show JSON store keyed on the normalised
`(orig, proposed)` text pair -- never on episode or card index, which does not survive a
`TEXT_VERSION` bump and means nothing in another library. It creates a show's file on first
use, appends without losing an earlier verdict, survives a torn write, refuses the two
malformed verdicts that would poison lookups, and resolves a show from an episode path by the
same ancestor walk `repair.glossary_for()` already uses. Where a verdict's lesson is a TERM
rather than a line it promotes into the show glossary's `hard_fixes`, where it applies
show-wide and ships in an artifact that is already committed -- and never over a curated entry,
because a human's glossary outranks a promotion.

Nothing in this sprint changes what any episode ships. `repair.py` is untouched; the consult
that would read this store is Task 4. That is deliberate: the store is the one piece every
later task depends on, and it is the piece that can be built and proven with no pipeline, no
GPU and no LLM.

Deliberately excluded: the queue, the consult, write-back, the mux gate, the server and the
container wiring -- Tasks 3 through 8. Each depends on this store existing and none of them
can be proven while its shape is still moving.
