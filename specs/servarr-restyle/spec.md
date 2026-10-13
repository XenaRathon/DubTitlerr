# Spec — Servarr-Aligned Review UI Restyle

## Context and problem

The review UI is a single Svelte 5 component (`web/src/App.svelte`) with two views
(`type View = 'inbox' | 'shared'`, `web/src/App.svelte:31-32`) and purple/teal tokens
(`--purple: #b493ff; --teal: #50ddbc`, `web/src/app.css:13-18`), while sibling specs add
dashboard, glossary, and settings views (`specs/webui-status-dashboard`,
`specs/webui-glossary-editor`, `specs/webui-settings`). Operators live in Sonarr/Radarr/Prowlarr
all day; one dark-grey visual language plus real navigation removes the context-switch cost.

## Acceptance criteria (verifiable)

- [ ] Step 1 (tokens): `web/src/app.css` `:root` (`web/src/app.css:1`) carries the Servarr token
  table below; no markup file changes; `npm run build` passes (`web/package.json:9`).
- [ ] Step 2 (nav): the existing sidebar (`<aside class="sidebar">`, `web/src/App.svelte:485`, with `mobileNav` state and an inbox count badge) is extracted unchanged into new `web/src/lib/Sidebar.svelte`, then extended; `view` extends to
  `inbox | shared | dashboard | glossary | settings` (`web/src/App.svelte:31-32`); hash routes
  below resolve, unknown hashes fall back to inbox, and the back button works.
- [ ] Step 2 responsive: below 768px the sidebar collapses behind a top-bar toggle into a slide-in drawer (the existing mobileNav pattern; decided 2026-10-12) (responsive pattern exists: `max-width` queries at
  `web/src/app.css:1253,1316,1368`, smallest at 650px); nav stays reachable by keyboard.
- [ ] Step 3 (polish): tables, toolbars, empty states, and toasts use only the token table;
  active nav item carries `aria-current="page"`; the visible focus ring
  (`web/src/app.css:61-65`) survives on every interactive element.
- [ ] All four gates stay green: `npm test`, `npm run check`, `npm run test:browser`,
  `npm run build` (`web/package.json:6-13`); image build still runs
  `npm run check && npm run build` (`Dockerfile.builder:5-10`).

## Out of scope (explicit)

- Any backend or API change; no new routes in `review_server.py`.
- Light mode or theme switching: no `prefers-color-scheme` exists anywhere in `web/` today,
  so dark-only like Servarr.
- New runtime dependencies or a CSS framework: plain CSS custom properties only
  (`svelte` plus dev tooling are the only install, `web/package.json:15-27`).
- Touching the glossary/dashboard/settings page contents planned by sibling specs.

## Data contracts

- **Token table** (name, value, use; ratios computed against WCAG relative luminance):
  - `--bg: #202020` page background; body text `#e9e8f3` on it: **13.42:1**.
  - `--panel: #2a2a2a` cards, sidebar, dialogs; `#e9e8f3` on it: **11.83:1**.
  - `--surface: #333333` inputs, hover, table rows; `#e9e8f3` on it: **10.41:1** (computed
    for `#e9e8f3` itself).
  - `--border: #3f3f3f` dividers (decorative, no ratio claim).
  - `--text: #e9e8f3` primary text; `--muted: #b4b4b4` secondary text, lowest pair
    `#b4b4b4` on `--surface`: **6.09:1**.
  - `--accent: #2e6ea8` primary buttons/links; white on it: **5.37:1**.
  - `--ok: #7cd48a` (**7.96:1**), `--warn: #e8b45c` (**7.60:1**), `--bad: #f08a8a`
    (**5.95:1**), `--info: #6cb2f0` (**6.33:1**) — all ratios on `--panel`.
  - `--focus: #4cc2ff` focus ring on `--bg`: **8.12:1**.
  - Font stack: `Roboto, Inter, ui-sans-serif, system-ui, sans-serif` — extends the current
    stack (`web/src/app.css:2-9`); Roboto resolves only if installed locally, zero network.
- **Route table** (hash, view, component): `''` or `#/inbox` → `inbox` (existing inbox section);
  `#/shared` → `shared` (existing shared section); `#/dashboard` → `dashboard` (sibling spec);
  `#/glossary` → `glossary` (sibling spec); `#/settings` → `settings` (sibling spec).
- **External dependencies:** none.

## Authorization

- **Who can execute:** no change; the login gate in `App.svelte` stays the only gate.
- **Behavior without permission:** deep link while unauthenticated shows the login panel, then
  returns to the requested hash after unlock (same post-login render path as today).

## Edge cases and failure modes

| Case | Expected behavior |
| --- | --- |
| Unknown hash (`#/nope`) | Falls back to inbox; hash is normalized, no error toast. |
| Deep link while logged out | Login panel first; requested hash restored after unlock. |
| Narrow screen (<768px) | Sidebar becomes a slide-in drawer opened from the top bar (focus moves into it, Escape closes it, the page behind is inert); no nav item is unreachable or clipped. |
| `prefers-reduced-motion` | Already honored globally (`web/src/app.css:1543`); new transitions inherit it. |
| Existing sidebar CSS (`.sidebar`, `web/src/app.css:117`; `.nav-active`, `web/src/app.css:184`) | Step 2 moves these rules into `Sidebar.svelte` scoped styles or keeps the shared classes; no duplicate competing selectors. |

## Decisions taken

| Decision | Rejected alternative | Why |
| --- | --- | --- |
| Three independently shippable steps (tokens → sidebar+hash routing → polish) | One big-bang restyle | Each step is reviewable and revertable; step 1 is zero-risk CSS variables. |
| Hash routing (`#/glossary`) over history routing | `pushState` paths | The review page is served as static assets; hashes need no server rewrite rules. |
| Roboto-first stack with system fallback, no download | Webfont `<link>` or `@import` | A CDN font is a load-time dependency and a LAN-privacy leak; fallback covers hosts without Roboto. |
| Dark-only, no `prefers-color-scheme` | Dual light/dark themes | The app has no theme hook today; Servarr itself is dark-first and one palette halves QA. |
| Plain CSS custom properties, no framework | Tailwind/Bootstrap | Zero new dependencies keeps `npm ci` in the image (`Dockerfile.builder:5-10`) unchanged. |

## Constraints

- Performance: no webfont fetch, no framework JS; CSS delta must not regress build output size by more than 20%.
- Privacy: no CDN or external request of any kind from the UI.
- Compatibility: unit tests import pure helpers only (`web/tests/review.test.mjs:1-3`), so they are
  markup-blind; browser specs assert visible text and roles
  (`web/tests/browser/review.spec.ts:12,33-37`: headings, `Search episodes` label, `evidence`
  testid) plus login alerts (`web/tests/browser/stale-token.spec.ts:8-35`) — step 3 must not
  rename those strings, roles, or testids.

## Open questions (risks)

- [x] Decided (boss, default): Roboto first, Inter second, system fallback. Revisit if the user prefers Inter.
- [x] Decided (boss, default): keep the existing count badge on the inbox item (App.svelte:496); other items show none in v1.
- [x] Decided (boss, default): reuse the existing mobile menu (`mobileNav`, App.svelte:485), a hamburger that opens the same sidebar.
- [x] Decided (boss, default): no; hash routes name views only in v1.
- [x] Decided (boss, default): reuse the existing inline message pattern; no toast component in v1.

## Step 3 design direction (boss, 2026-10-12, from the frontend-design review)

Subject: a media-server operator tool used by people who already live in Sonarr, Radarr and Prowlarr. The job is scanning state quickly (what ran, what failed, what needs a decision) and making a few careful writes. The brief pins the look to the Servarr family, so the plan follows it exactly and spends its one deliberate choice elsewhere.

- **Color (tokens already in `app.css`):** `--bg #202020`, `--panel #2a2a2a`, `--surface #333333`, `--border #3f3f3f`, `--text #e9e8f3`, `--muted #b4b4b4`, `--accent #2e6ea8`. Status: `--ok #7cd48a`, `--warn #e8b45c`, `--bad #f08a8a`, `--info #6cb2f0`. Step 3 replaces the roughly 200 remaining old-palette hex values (sidebar `#15151f`, hover `#e8dcff`, the purple and teal aliases) with these tokens and then deletes the aliases.
- **Type:** one family, `Roboto, Inter, ui-sans-serif, system-ui, sans-serif`, no webfont download. Hierarchy by size and weight, sentence case everywhere, no all-caps labels, no letter-spaced eyebrows. Tabular figures (`font-variant-numeric: tabular-nums`) in every table so counts and ages line up.
- **Layout:** left sidebar plus a content column, left aligned, line length under 80 characters for prose, tables full width inside a scroll region. Dense rows (Servarr tables are dense), generous spacing only around forms and destructive actions.
- **Principles:**
  - Status is read before anything else: every state is a text badge with an icon shape, never colour alone, and the same status vocabulary (pending, running, done, failed, stale) is used on the dashboard, the runs page and the inbox.
  - One memorable element: the status badge and the per-episode state strip on the dashboard, because that is what the operator looks at all day. Everything else stays quiet.
  - No decorative cards, shadows or gradients; borders and surface steps carry the structure. One radius (4 px) for controls, none for table cells.
  - Motion only in answer to an action (drawer, confirm, saved), and none under `prefers-reduced-motion`.
  - Plain error text that says what happened and what to do next; an action keeps one name through its whole flow (Queue run, then "Run queued").
- **Acceptance for Step 3:** zero old-palette hex values in `app.css` (grep), contrast of every text/background pair actually used at least 4.5:1 (script), the 34-plus browser specs unchanged and green, no layout shift at 320, 768 and 1440 px, and screenshots of each page attached to the review.
