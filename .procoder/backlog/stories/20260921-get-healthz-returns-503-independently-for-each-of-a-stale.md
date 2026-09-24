# `GET /healthz` returns 503 independently for each of: a stale `last_sweep_end` (> `3 * RESCAN_INTERVAL`), `roots_readable=False`, and `order_file_present=False`; returns 200 otherwise; the response body never contains a filesystem path.

Status: done 2026-09-23
Created: 2026-09-21
Epic: v0-2-0-hardening
Sprint: 013-v0-2-0-work

## Description

Scope S-16 of `.procoder/specs/v0-2-0-hardening.md`: Add a heartbeat file, `GET /healthz`, and a Dockerfile HEALTHCHECK: `common.HEARTBEAT_PATH`, `common.heartbeat(**fields)` (atomic merge-write), `common.read_heartbeat()`.

Delivered by Task 16 of `.procoder/plans/v0-2-0-hardening.md` (sprint 013); the task holds the literal test and implementation steps. Done means the criterion below is observably true and the evidence names the command and its output.

## Acceptance criteria

<!-- Each criterion is testable. Check a box ONLY when it is verifiably
     true — the closer will ask for the evidence. -->

- [x] `GET /healthz` returns 503 independently for each of: a stale `last_sweep_end` (> `3 * RESCAN_INTERVAL`), `roots_readable=False`, and `order_file_present=False`; returns 200 otherwise; the response body never contains a filesystem path.

## Evidence

- `review_server.py:1108-1133` — `handle_healthz()` builds `reasons` independently: `hb is None` → `"no heartbeat yet"`; missing `last_sweep_end` → `"stale: no sweep has completed yet"`; `(now - last_sweep_end) > 3 * RESCAN_INTERVAL` → `"stale: last sweep ended <n>s ago (threshold <3*RESCAN_INTERVAL>s)"`; `not hb.get("roots_readable", True)` → `"roots_readable is false"`; `not hb.get("order_file_present", True)` → `"order_file_present is false"`. `RESCAN_INTERVAL` defaults to `21600`, so the threshold is `64800s`. Response shape is `{"ok": True}` on 200 and `{"ok": False, "reasons": [...]}` on 503 — never a bare `{"error": ...}` and never a filesystem path.
- `review_server.py:691` — `/healthz` is dispatched inside `route()` above the gate at `:693`, which is what makes it reachable without a token.
- Live probe, this session, `python3` from the repo root with `common.read_heartbeat` monkeypatched and `handle_healthz()` called directly: `no heartbeat -> 503 {"ok": false, "reasons": ["no heartbeat yet"]}` / `stale sweep -> 503 {"ok": false, "reasons": ["stale: last sweep ended 1000000s ago (threshold 64800s)"]}` / `roots_readable false -> 503 {"ok": false, "reasons": ["roots_readable is false"]}` / `order_file_present false -> 503 {"ok": false, "reasons": ["order_file_present is false"]}` / `all good -> 200 {"ok": true}`. All three failure branches are independent and each reason string names its own cause.
- Coverage caveat: the plan's `test_get_healthz_is_never_gated_by_the_token` (`.procoder/plans/v0-2-0-hardening.md:~4489-4500`) was never ported — `grep -rn "healthz" tests/` returns no hits, so `/healthz` is currently exercised only by `Dockerfile.builder:61`'s `HEALTHCHECK` and by the live probe above.
