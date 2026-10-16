# Parallel build rules for the webui specs (boss, 2026-10-12)

- `review_server.py` `route()` registration is edited by ONE owner per merge (the boss merges registrations); each feature puts its handlers in its own module (`review_glossary.py`, `review_status.py`, `review_requests.py`, `review_settings.py`, `review_webhooks.py`) and exposes `handle(method, path, body, token, ...)`.
- Land `servarr-restyle` steps 1-2 (tokens, Sidebar.svelte, hash routing) before any page component; pages are standalone components mounted by hash route, none adds its own `$state` tab in App.svelte.
- Order: admin-token helper first (settings writes, run-control, and its tests depend on it).
