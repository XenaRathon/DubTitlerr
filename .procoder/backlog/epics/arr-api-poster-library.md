# arr-api-poster-library

Status: roadmap, not started
Created: 2026-10-13

## Why

The web UI main page should read like the Sonarr and Radarr libraries: a grid of show posters,
each with a status bar underneath. Clicking a poster opens that show with its episodes, so the
episodes that need review (and later the full-pass proofreading view) are one click away.

The user decided on 2026-10-13 to connect to the arrs through their **API**, the way other
supplementary arr apps do, rather than webhook-first. A webhook stays an optional "do it now"
fast path (secret in the URL, already decided).

## Scope

- **[A-1]** Arr API client for Sonarr (v3) and later Radarr: base URL and API key as masked
  settings, a connection test, and a poll on start plus every N minutes.
- **[A-2]** Poster proxy: fetch cover art through the review server and cache it, so the API key
  never reaches the browser. Shows not found in an arr get a placeholder poster.
- **[A-3]** Map a library folder to a series through the `{tvdb-NNNN}` tag already in the folder
  name; path mapping for arrs that see different mount points.
- **[A-4]** Poster grid as the main page, replacing the current inbox landing view.
- **[A-5]** Status bar under each poster with three segments: unprocessed (no `.done` stamp),
  processed but not reviewed (`.done` with pending review items), fully reviewed. Optional fourth
  segment "processing now" from the builder heartbeat.
- **[A-6]** Show page: seasons and episodes, each with its state, ordered by what needs review.
  The full-pass proofreading view slots in as another tab once it exists.
- **[A-7]** Retire the slow filesystem tree walk for show discovery once the list comes from the
  API (per-episode state still reads the stamps).
- **[A-8]** Movies tab through Radarr, same shape.
- **[A-9]** Set the wiki for any show from its poster page, even before it has a glossary (user,
  2026-10-15). Builds on the Glossary page wiki field. Decide then whether a missing glossary gets a
  stub `{"wiki": ...}` file the pipeline later fills, or a separate per-show settings store; MINE
  and ACQUIRE must keep a pre-set wiki when they create the glossary.

## Notes

- The bar counts episodes, so a show with few pending reviews shows a thin sliver; Sonarr's bars
  behave the same way.
- Confirm the exact v3 endpoints, the cover-art URL format and what `mediaInfo` exposes for audio
  languages before building (`reader` or `scout`).
- Related: sortable repair queue, login with user and admin roles, transcript proofreading view.
  See the memory notes `project-backlog-arr-api-library-view`,
  `project-backlog-webui-login-roles-and-sorting` and `project-backlog-webui-transcript-proofread`.
- The public README roadmap and the docs are frozen until the release; add a line to the README
  Roadmap in the release docs pass.
