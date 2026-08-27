# With `REVIEW_TOKEN` unset, the server generates a token, persists it 0600, and a write route without it is REFUSED -- the unsafe default is the one being tested away. With `REVIEW_TOKEN` set explicitly empty, the same request succeeds. Read routes are unaffected either way.

Status: open
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: -

## Description

Task 7. This was the adversarial review's one surviving BLOCK. The container runs as root so
`generate.py` can chown into the media tree, and this server's write routes rewrite subtitle files
and force re-muxes from inside that process tree. An unset token must not mean an open endpoint.

Done means unset generates a token, persists it 0600, prints it once, and REFUSES a write without it;
only an explicitly empty `REVIEW_TOKEN` disables auth. The maintainer's friction stays at reading the
log once.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [ ] With `REVIEW_TOKEN` unset, the server generates a token, persists it 0600, and a write route without it is REFUSED -- the unsafe default is the one being tested away. With `REVIEW_TOKEN` set explicitly empty, the same request succeeds. Read routes are unaffected either way.

## Evidence

<!-- Filled at close time: the commands run and what their output proved,
     one line per criterion. Empty evidence keeps the story open. -->
