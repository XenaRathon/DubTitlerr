# [F-4] The review server bounds concurrent connections, not only request duration

Status: done 2026-08-27
Created: 2026-08-27
Epic: review-loop-followups
Sprint: 009-review-loop-follow-ups-from-the-pre-merge-round-honour-a

## Description

The gating fix in `3bd20a4` gave `Handler` a 30s socket deadline, which bounds how long one
unauthenticated request can hold a worker. It does not bound HOW MANY. `ThreadingHTTPServer`
spawns a daemon thread per connection with no cap (`daemon_threads = True`, verified), so a
LAN client can still open many connections at once; each now dies after 30s instead of never,
which converts an indefinite pin into a sustained churn.

Lower severity than the deadline -- that one was unbounded in time, this is bounded and
self-limiting -- and it affects the review service's availability only, never the pipeline.
The rebuttal listed it as "optionally bound concurrent connections" for the same reason.

## Acceptance criteria

- [x] Concurrent request handling is bounded by a configurable limit with a sane default.
- [x] Exceeding it is refused promptly and cheaply, not queued unboundedly -- a queue is the
      same exhaustion with an extra step.
- [x] The generate loop is unaffected under the limit being hit: [S-8] holds that the review
      server's failure must never reach the container's foreground process.
- [x] The limit is asserted by a test that does not open a real socket, matching the rest of
      this suite.

## Evidence

- `test_concurrent_requests_are_bounded` and `test_the_slot_is_returned_after_a_request`,
  plus `test_serve_uses_the_bounded_server`. No socket is opened.
- `BoundedHTTPServer` acquires a slot in `process_request` and releases it in
  `process_request_thread`'s `finally` -- the only place that runs for both the served and
  the errored path. Releasing in `process_request` would return the slot before the work it
  guards had started.
- Over the ceiling the connection is CLOSED, not queued: an unbounded accept queue is the
  same exhaustion with an extra step. `REVIEW_MAX_CONCURRENT` defaults to 16, which is
  generous for one person clicking buttons.
- TWO of my own tests were too weak and are recorded as such in their comments. The
  slot-release test called only the releasing half, so it never took a slot and passed
  whether or not the release existed; it now drives the real acquire/release pair. And
  nothing covered `serve()`'s construction, so swapping in the unbounded server passed --
  both gaps found by mutation, not by design.
- Mutations caught: no cap (1 test), slot never released (1), `serve()` using the unbounded
  server (1).
