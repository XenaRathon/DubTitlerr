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
- **`REVIEW_TOKEN=` (empty)** — treated exactly the same as unset: a token is still
  generated. Too many operators left this blank by accident and got an unauthenticated
  root-owned endpoint without meaning to; an empty value can no longer opt out of auth.
- **`REVIEW_AUTH=off`** — the only way to disable auth. This is a deliberate operator
  opt-out for a network you already trust completely, **not** something to set if you plan
  to expose the port beyond your LAN (a reverse proxy, a port-forward, a VPN with other
  members). If you do that, put your own auth in front of it instead.

GET routes on `/api/` paths (e.g. `/api/episodes`, `/api/episode`, `/api/shared`) require the
token and return 401 without it. Rendered pages (`/`, `/index.html`, `/shared`) are gated the
same way through a `dubtitlerr_token` cookie the token box sets alongside its localStorage
write — without a valid header or cookie they render only the token box, never a stem or
repair text. `/healthz` stays open and unauthenticated for liveness checks; its response body
never contains a filesystem path. Write routes (recording a verdict, applying decisions)
require the token as before.

The `0.0.0.0` bind above is a **deliberate choice**, not an oversight: it was confirmed as the
correct default at sprint 010's opening (v0.2.0 hardening) alongside the auth-hardening work
in this section, on the same trusted-LAN assumption stated at the top of this section.

## Review workspace audio previews

The optional `/review` workspace serves an inert public application shell; library data
and `/api/audio` require the same token as verdict writes. The workspace holds its token
in tab-scoped `sessionStorage` and sends it as a header, never in a URL. Sign out clears
the workspace token but does not revoke the server token or sign out the classic page.

Audio previews decode short clips from allow-listed episodes in memory, capped at 20
seconds, with two concurrent extraction slots and bounded probe/decode timeouts. They
select English-tagged non-commentary audio and reject media paths outside the configured
roots. No whole-file media-serving endpoint is provided. Responses are marked `no-store`.
The configured `REVIEW_AUTH=off` opt-out also disables audio authorization; do not expose
that mode outside a trusted network. See [workspace security details](docs/review-workspace.md#authentication-and-media-safety).

## Optional password login for the review workspace

The review token is, and stays, the credential every route checks. `REVIEW_USERNAME` with
`REVIEW_PASSWORD` or `REVIEW_PASSWORD_FILE` adds `POST /api/login`, which returns that token
to someone who knows the password; unset (or empty, or half set) it does not exist. Both
fields are compared in constant time, failures are throttled in memory (five in five
minutes, then 429 for 60 s per client address) and the password is never logged. The login
route accepts only small JSON bodies. Use a strong password: the lockout allows 5 guesses per
minute per client address. Behind a reverse proxy all clients share one address, so repeated
bad guesses lock password login for everyone for 60 seconds while the token still works. **Over plain HTTP the password is sent in clear
text**: use it on a trusted LAN or behind TLS. It is a convenience for fetching the token,
not an additional protection, and `REVIEW_AUTH=off` still disables everything.

## Scope

This tool transcribes audio you already have and merges subtitle tracks you already have.
It does not fetch external media or phone home. Authenticated reviewers can request the
short local audio previews described above; it does not serve whole media files. The per-show glossaries
and dubtitle repositories it publishes to are separate, explicitly public projects — see
their own repositories for their content policies.