# With `REVIEW_TOKEN` unset, the server generates a token, persists it 0600, and a write route without it is REFUSED -- the unsafe default is the one being tested away. With `REVIEW_TOKEN` set explicitly empty, the same request succeeds. Read routes are unaffected either way.

Status: done 2026-08-27
Created: 2026-08-27
Epic: repair-review-and-decision-store
Sprint: 007-task-7-the-review-server-plus-the-orphan-entry-fix-the

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

- [x] With `REVIEW_TOKEN` unset, the server generates a token, persists it 0600, and a write route without it is REFUSED -- the unsafe default is the one being tested away. With `REVIEW_TOKEN` set explicitly empty, the same request succeeds. Read routes are unaffected either way.

## Evidence

- `test_an_unset_token_is_generated_persisted_0600_and_required` -- generated, >=32 chars,
  persisted 0600, and reused on a second start rather than rotated.
- `test_an_explicitly_empty_token_disables_auth_but_unset_does_not` -- the two are told
  apart by MEMBERSHIP in os.environ, never by falsiness, which is where the whole posture
  rests. Mutation to "unset means open" (the reverted default) fails 3 tests.
- `test_a_write_route_without_the_token_is_refused_and_a_read_route_is_not` and
  `test_the_router_gates_writes_and_passes_reads` -- 401 with no token and with a wrong one,
  200 with the right one, reads ungated throughout.
- `test_the_token_comparison_is_timing_safe` is a SOURCE assertion, labelled as the weaker
  kind in its own docstring: `==` and compare_digest are behaviourally indistinguishable, so
  no functional test can tell them apart, and this token is the only thing between a LAN and
  a root-owned write endpoint.
- `test_the_token_is_never_placed_in_a_url` -- carried in a header, never a query value, so
  it cannot land in proxy logs, browser history or a Referer.
- Two review findings fixed here: a persistence failure minted a fresh token per request
  (every write 401'd forever, including for the operator holding the logged one), and the
  token was written with a direct O_TRUNC instead of the temp+os.replace idiom the rest of
  the repo uses. `test_a_generated_token_is_stable_when_it_cannot_be_persisted`.
- `procoder security --deep`: zero findings in review_server.py; secrets clean. osv-scanner
  run directly against uv.lock -- no issues found.
