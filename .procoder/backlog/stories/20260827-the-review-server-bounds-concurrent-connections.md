# [F-4] The review server bounds concurrent connections, not only request duration

Status: open
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

- [ ] Concurrent request handling is bounded by a configurable limit with a sane default.
- [ ] Exceeding it is refused promptly and cheaply, not queued unboundedly -- a queue is the
      same exhaustion with an extra step.
- [ ] The generate loop is unaffected under the limit being hit: [S-8] holds that the review
      server's failure must never reach the container's foreground process.
- [ ] The limit is asserted by a test that does not open a real socket, matching the rest of
      this suite.
