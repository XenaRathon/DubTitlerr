# Task 7: the review server, plus the orphan-entry fix the sprint-006 review surfaced

Status: closed 2026-08-27
Created: 2026-08-27

## Goal

The interface the owner asked for at the start of this epic: a page that shows the repairs
`accept_repair` admitted and lets a human rule on them, so approval reaches the software
directly instead of arriving as a markdown diff. Stdlib `http.server`, no new dependency.
Every route is a thin call into [S-2] and [S-5]; the server holds no durable logic of its
own.

The security posture is the part that is not negotiable, and it was REVISED once already
after adversarial review. `REVIEW_TOKEN` unset does NOT mean no auth: the server generates a
token, persists it 0600 and prints it once. Only `REVIEW_TOKEN=` set explicitly empty
disables auth, for a network the operator has decided is isolated. The reason is concrete --
`container_run.sh` runs as root so `generate.py` can chown into the media tree, this server
adds write routes to that same process tree, and a downstream user on host networking would
otherwise expose an unauthenticated root-owned endpoint that rewrites subtitles and forces
re-muxes.

The verdicts offered depend on the entry: an `accepted` entry offers accept/reject/correct
and NOT force; a `rejected_guard` entry offers force/reject/correct and NOT accept. Without
that, `accept` on a refused entry is a `force` with no distinct record, which defeats the
counting `force` exists for.

Also lands the orphan-entry fix decided by the owner after the sprint-006 review: a pending
queue entry describing text that no longer exists in `conf.json` must not hold an episode
forever.

## Carried from the sprint 006 retro

For any control-flow claim about a function, read from its `def` line -- an early return is
invisible from below, and that miss has now cost two sprints. And of anything that holds,
pauses or retries, ask what the surrounding code assumed would end soon.

This sprint adds an authenticated write surface, so `/procoder:security` runs over it before
the stories close, in addition to the adversarial review.

## Retro

What slowed us down: nothing, and that is worth naming rather than celebrating. This sprint
went cleanly BECAUSE the two habits the previous retros forced were applied up front -- the
on-disk state was written down before the design, and the review ran before the stories
closed. The six defects the review found were all in code that looked obviously correct, and
the highest-severity one lived in the single layer the suite did not cover.

The pattern across all six: every one was a case where a check EXISTED and did not do what
its own comment said. The body cap was documented as bounded and was not, because int("-1")
does not raise. The token was documented as persisted and was not, on the path where that
mattered most. The allow-list was documented as a boundary and was not, for a symlink. Three
separate places where the comment was the specification and the code disagreed with it, and
no test noticed because every test exercised the happy value.

What we change next sprint: for each guard, ask what input makes the guard PASS while the
property it protects is FALSE -- not what makes it fail. A cap tested with a big number and
a small one never sees the negative one. That question is different from "what mutation
breaks this test", which was already being asked and did not catch these.

Adaptation worth keeping: the untested layer is where the worst finding was. The suite's own
docstring said "handlers only, no socket is ever opened", which read as a scoping decision
and was actually a coverage hole with a rationale attached. When a test file states what it
does not cover, that sentence is a to-do, not a boundary. `_Wire` closes it without opening
a socket, which is what the original constraint was really about.

## Result

committed: 3
done: 3 (20260827-a-queue-entry-orphaned-by-a-version-bump-does-not-hold, 20260827-get-ep-stem-returns-the-primary-queue-by-default-asserted, 20260827-with-review-token-unset-the-server-generates-a-token)
carried: 0
