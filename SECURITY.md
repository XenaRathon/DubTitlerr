# Security

## Reporting a vulnerability

Open a [GitHub issue](https://github.com/XenaRathon/DubTitlerr/issues) for anything that
isn't sensitive. For something you'd rather not post publicly (a real exploit path, not a
hardening suggestion), email the maintainer — see the GitHub profile for contact — and
allow a reasonable window to land a fix before public disclosure.

## The review server's auth model

`review_server.py` runs as root (it rewrites subtitle sidecars) and binds to `0.0.0.0` by
default, on the assumption that the container's LAN is the operator's own trusted network —
the same trust boundary as the Plex/Jellyfin server it sits next to.

- **`REVIEW_TOKEN` unset** — a token is generated, persisted `0600` beside `DECISIONS_DIR`
  (default `/config/review_token`, never inside `DECISIONS_DIR` itself, since that
  directory may later be published or synced), and printed once to the container's logs.
  Recover it later with `docker exec dubtitle-builder cat /config/review_token`. This is
  the default and requires no action.
- **`REVIEW_TOKEN=<value>`** — use your own token instead of the generated one.
- **`REVIEW_TOKEN=` (empty)** — disables auth entirely. This is a deliberate operator
  opt-out for a network you already trust completely, **not** something to set if you plan
  to expose the port beyond your LAN (a reverse proxy, a port-forward, a VPN with other
  members). If you do that, put your own auth in front of it instead.

GET routes (the episode/queue listing) are unauthenticated by design — they disclose show
names and episode counts, the same information any DLNA browse or Plex share on the same
network already exposes. Only the write routes (recording a verdict, applying decisions)
require the token.

## Scope

This tool transcribes audio you already have and merges subtitle tracks you already have.
It does not fetch, host, or proxy media, and does not phone home. The per-show glossaries
and dubtitle repositories it publishes to are separate, explicitly public projects — see
their own repositories for their content policies.
