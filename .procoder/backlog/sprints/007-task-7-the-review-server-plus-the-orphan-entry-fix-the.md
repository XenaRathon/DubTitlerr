# Task 7: the review server, plus the orphan-entry fix the sprint-006 review surfaced

Status: active
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
