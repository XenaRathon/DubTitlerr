# Frontend review expansion: design

Written 2026-09-02. Supersedes nothing; this is the first frontend-scoped spec. The fifteen
decisions below were settled in a structured interview the same day — every branch of the
design tree was visited, none left assumed.

## TL;DR

The review page grows into the project's main front end: one **Svelte SPA** in front of the
existing Python backend. Four new human surfaces — settled-line editing, timing/split
editing, glossary proposals, and multi-user household review with admin approval — sit on
top of the decision/queue machinery that already works. **In-browser preview is the
load-bearing feature**: the reviewer judges a line by hearing it, not by re-muxing.
A **versioned API contract document** is a first-class deliverable, because the Python
backend is eventually rewritten in Go or Rust and the frontend is the layer that must
outlive it.

Staging is expected: this document maps the whole tree; individual build sessions may
implement it in the order suggested at the bottom.

---

## Settled decisions

| #   | Decision             | Answer                                                                                    |
| --- | -------------------- | ----------------------------------------------------------------------------------------- |
| 1   | Scope                | **One unified front end, phased** — review expansion first; dashboard folds in later       |
| 2   | Stack                | **Svelte + Vite SPA**; static build output is the durable artifact, no server rendering    |
| 3   | Edit data model      | **Per-episode edit store** (`.dubtitles.edits.jsonl`); decisions store untouched           |
| 4   | Regeneration         | **Held reapply items**: each prior edit resurfaces as its own reapply-or-not decision      |
| 5   | Artifact scope       | Full dialogue editing; signs hide/shift; dialogue position override; merge re-applies      |
| 6   | Apply path           | **Two-step everywhere**; in-browser preview is the verification loop; one mux per Apply    |
| 7   | Auth posture         | **Two modes**: token (today) and multi-user; password + OIDC are login methods inside it   |
| 8   | Member scope         | Queue verdicts + settled-line proposals; timing/splits/apply admin-only; **provisional**   |
| 9   | Accounts             | `users.json`, stdlib scrypt, token-as-enrollment-key bootstrap, admin-created accounts     |
| 10  | OIDC roles           | **Group-claim mapping** in config; auto-provision on first login; local promote/demote     |
| 11  | Glossary proposals   | From queue line or glossary page; wiki-verified auto-accept; else admin; hard_fixes admin  |
| 12  | Concurrency          | **Advisory locks for structural sessions only**; text verdicts stay lock-free              |
| 13  | Information arch.    | **Dashboard is the default landing**; left nav; per-episode tabs                           |
| 14  | Editor               | **Keyboard/playhead first**; layered canvas timeline; waveform additive later              |
| 15  | Preview media        | Audio proxy for all episodes; **lazy 540p video proxy** on first editor open               |
| 16  | Devices              | **Responsive to tablet** everywhere except the desktop-only editor                         |

---

## 1. Why this stack (the rewrite constraint)

A future version of this tool is expected to be rewritten in Go or Rust. That constraint
decides the frontend architecture before any feature does: the UI must be a **pure API
client**, because the Python backend is the disposable part and the browser layer is the
one that survives.

Requirements that follow from it, regardless of anything else in this document:

- All UI logic lives in the browser. The server is dumb: static files, JSON routes,
  range-request media. No server rendering, no templates carrying UI logic — that is the
  one architecture the rewrite would drag behind it.
- The UI speaks **documented HTTP JSON**. Stems are opaque IDs. Auth rides
  `X-Review-Token` for API calls and cookies for sessions/media (below).
- Static assets are embeddable by any backend: Go `embed`, Rust `include_dir`, Python
  `serve_directory` today — the same artifact, three hosts.
- Nothing client-side imports or assumes Python.

The consequence is that the **API contract is the real interface**. It gets its own
versioned document (`docs/api-contract.md`), written as something a rewrite re-implements
route by route, not as a description of whatever the Python happens to do.

Svelte + Vite over vanilla JS because the timeline editor is exactly what a component
model pays for, and because the investment now belongs in the surviving layer. The
toolchain tax lands entirely in the Docker build (node stage → copy static output →
final Python image), which the Go/Rust build replicates with the same two artifacts.
Concretely, this is a new stage in `Dockerfile.builder` (the container that already runs
`review_server.py` via `container_run.sh`) — not the top-level `Dockerfile`, which is a
separate, deprecated single-purpose image running only `dub_signs_merge.py`.

## 2. The edit store (decision 3)

New per-episode file beside the video: **`.dubtitles.edits.jsonl`** — append-only, atomic
replace on rewrite, the same idiom as `unresolved` and the decision stores. Human-readable,
git-commit-able, O(1) record.

The show-wide **decisions store stays exactly as it is.** Text verdicts keep flowing
through repair as they do today. The edit store holds everything that cannot be keyed on a
text pair, plus per-episode text edits:

| Record type | Keyed by                      | Payload                                        |
| ----------- | ----------------------------- | ---------------------------------------------- |
| `text`      | card text anchor              | `orig`, `proposed`, `by`, `at`, `status`       |
| `timing`    | card identity                 | field (`start`\|`end`), value or delta, `by`   |
| `split`     | card identity + split point   | `at_seconds`, `by`                             |
| `merge`     | card range                    | the undo path for a bad split                  |
| `position`  | card identity                 | `top`\|`bottom`\|offset                        |
| `sign`      | merged-`.ass` event identity  | `hide`\|`shift`                                |

Two properties matter more than the exact schema:

- **Attribution.** Every record carries `by`. Token mode writes an anonymous value.
- **Splits renumber cards**, so records reference card identity (index at edit time plus
  text anchor), and the apply pass replays records in order. A timing nudge against a card
  that a later split removed is a held-reapply item (decision 4), never a silent no-op.

Provisional member text proposals (decision 8) live here too, carrying
`status: "provisional"` until an admin acts.

## 3. Regeneration and reapply (decision 4)

Every episode needs review, so no episode becomes "human-owned" and the generate loop is
untouched. Regeneration (model swap, glossary improvement, a per-component version bump
such as `TRANSCRIBE_VERSION` — there is no single `PIPELINE_VERSION`; `stale_version_stamp()`
in `common.py` is what actually decides staleness, described there as "a deliberate operator
action") proceeds as it does today — and the edit store survives it, because it is an input
beside the video, not a pipeline output.

What changes is what happens *after*: each prior edit becomes a **held reapply item**,
presented in the UI in its own section — per-episode tab plus an admin-wide rollup — asking
**reapply or not**, one decision each, styled like today's verdict radios. Nothing
auto-applies; nothing silently vanishes. A stale timing nudge (the new transcription may
already have fixed the timing it nudged) is therefore a human judgement, not a corruption
risk.

## 4. Artifact scope and the apply path (decisions 5–6)

Dialogue cards get full editing: text, timing, splits (and merges, as the undo path for a
bad split). Signs get the minimal set — **hide/shift** — because fansub positioning is
usually intentional. Dialogue additionally gets a **position override** (e.g. lift dialogue
above a bottom-positioned sign).

The position override lives only in the `.ass`, which `dub_signs_merge.py` rebuilds from
the `.srt` every pass — so **the merge re-applies position and sign overrides on every
rebuild**. That is the one place the merge step learns about the edit store.

Everything else keeps today's two-step shape, because the verification loop moves into the
browser:

1. **Record** — edits and verdicts are recorded (Save). Nothing rewrites media.
2. **Preview** — the reviewer plays the card against the *edited* subtitle in-browser
   (decision 15). This is where "did I get the timing right?" is answered, cheaply,
   repeatedly, without a mux.
3. **Apply** — the explicit step rewrites the sidecar, drops the `.done` stamp, and the
   merge loop re-muxes once.

Half-finished edits are never briefly the shipped truth; a session costs exactly one mux.

## 5. Multi-user and auth (decisions 7–12)

Two postures, one flag apart:

- **Token mode** — exactly today's behavior. No accounts, no members, nothing new to
  configure. The default.
- **Multi-user mode** — accounts, roles, sessions, the approval surface. Password and
  OIDC are *login methods* inside it, not separate postures.

**Accounts** live in `users.json` beside `decisions/` — same atomic-write idiom, same
"plain readable files, git-commit-able" rule as the stores. Passwords hash with stdlib
scrypt (no new dependency). The store sits behind a thin interface so a future SQLite swap
touches nothing else. **Bootstrap:** on first switch to multi-user mode, the existing
`REVIEW_TOKEN` becomes the admin enrollment key — the first login with it claims admin #1
(username + password), after which the key retires. No CLI, no hand-edited files. Member
accounts are created by the admin in the UI; there are **no unauthenticated write routes**
for registration.

**OIDC:** auto-provision on first successful IdP login. Roles come from a **group-claim
mapping in config** (claim name + group→role table, covering the Authentik/Authelia/
Keycloak dialect differences), with a fallback role for unmapped users. The admin panel
promotes/demotes locally afterward. Identity stores `sub` + issuer; email is display only.

**Member scope (decision 8):** members work the verdict queue and propose changes to
settled lines and glossary terms. Member verdicts **settle provisionally** — today's
immediate behavior is preserved, but flagged and attributed. The admin surface is a
**review/revert list** (newest first), not a gate: approve upgrades the record, revert
drops it back to open and marks the episode for re-apply if a mux already shipped it.
Timing, splits, and Apply are admin-only — they need mux feedback and cannot merge.

**Sessions and media:** the SPA's login POSTs credentials (or completes OIDC) and receives
an HttpOnly session cookie. Media routes — video/audio proxies, subtitle sidecars, fonts —
are **cookie-gated**, because `<video>` cannot send headers and an ungated media endpoint
on the default `0.0.0.0` bind is an unauthenticated mirror of the whole library. The JSON
API keeps the header model. This is the one change to the "read routes never gated"
posture, and it is stated in the contract doc like everything else.

**Concurrency (decision 12):** locks only where merging is impossible. Opening the
timing/split editor takes an advisory edit-session lock (heartbeat + timeout; a crashed
browser times out instead of deadlocking the episode). Other users see read-only plus who
holds it. Verdicts and text proposals stay lock-free — they key on text pairs, conflicts
self-resolve, last write wins, visible in history.

## 6. Glossary proposals (decision 11)

The glossary-verification machinery (`glossary_verify.py`, built to be reusable on its
own) is the gate, exactly as the pipeline uses it:

- A proposal can start **from a queue line** (one click, prefilled
  original→proposed) or from the glossary page, free-form.
- If the wiki verifier confirms the term, it is **auto-accepted** into `names` —
  bypassing `ACQUIRE_GROWTH_MAX` (defined in `glossary_acquire.py`, the mining layer,
  and applied there), which throttles mining growth and makes no sense for a
  human who just verified against the wiki.
- Anything the wiki cannot confirm queues for **admin approval**.
- `hard_fixes`-class mappings (exact wrong→right replacements that fire on every future
  transcription) go to **admin regardless** of verification — the wiki confirms canonical
  spelling, not that a mapping is safe to fire show-wide.

## 7. Information architecture (decisions 13, 16)

**The dashboard is the default landing**: counts (total transcribed, episodes with pending
reviews, fully settled) plus **pipeline status and queue display**. One derived backend
fact: the loops currently write no state anywhere, so status needs the gen/merge loops to
publish a small status file that a read-only route serves. Staged, backend-side, small —
and the dashboard is read-only for now; controls (re-scan, reorder, GPU status, live logs)
stay roadmap scope.

Left nav: **Dashboard / Inbox / Shows / Glossary / Admin**.

- **Inbox** is today's work-first landing preserved as one nav item: episodes with open
  items, worst first.
- **Shows** is the library backbone — any episode reachable in two clicks, with per-episode
  status badges (pending count, provisional awaiting approval, reapply items, lock state).
- An episode opens into tabs: **queue / editor / history / reapply**.

Responsive layouts down to tablet for everything except the timing editor, which is
desktop-only with a "open this on a bigger screen" notice. The verdict flow — play the
line, pick a radio, save — is the household's tablet-shaped task; the editor is not.

## 8. Editor and preview (decisions 14–15)

The editor is keyboard-first, Aegisub-style, because the reviewer's job is
listen → adjust → listen: **space** plays the card, **arrows** nudge start/end, **S**
splits at the playhead. ASR word timings are "close enough to find the line, not
frame-accurate," so the tool optimizes the loop, not precision dragging.

The timeline is a **layered canvas** so the waveform is an additive later stage: the audio
peaks artifact is generated pipeline-side eventually, and no edit model or API changes
when it lands.

**Preview media**, tiered by what each surface actually consumes:

| Tier                        | Generated                     | Cost                    | Serves                          |
| --------------------------- | ----------------------------- | ----------------------- | ------------------------------- |
| Audio proxy (m4a)           | pipeline, all episodes        | ~15–20 MB/episode (~1%) | verdict playback, later peaks   |
| Video proxy (540p H.264)    | **lazily, first editor open** | ~50–80 MB/episode       | timing editor, position layout  |

The 540p height is a config knob (`PROXY_HEIGHT`). The subtitle is never burned into the
proxy: **JASSUB renders the edited `.ass` at the script's native resolution** over the
video, with fonts served from the mkv — signs and dialogue stay crisp while only the
underlying picture is soft, which timing review does not need sharp. First editor open
shows transcode progress; every open after is instant. Storage tracks *episodes someone
actually edited*, not library size.

## 9. Explicitly deferred

- Dashboard *controls* (re-scan, show ordering, GPU status, live logs) — status only.
- Full waveform timeline and the peaks artifact (stage 2 of the editor).
- SQLite user store (the interface is the prep).
- Enrollment codes for self-serve member signup.
- Full signs/songs editing beyond hide/shift.

## 10. Suggested build order

Deliberately independent stages; each leaves the app working.

1. **SPA shell + API contract v1** — Svelte/Vite build in the image, auth (token mode),
   dashboard shell with counts, Inbox/Shows over the existing API.
2. **Edit store + apply path + preview** — `.dubtitles.edits.jsonl`, audio proxies,
   cookie-gated media, JASSUB preview, Apply rewrites the sidecar and drops the stamp.
3. **Timing/split editor** — keyboard model, layered canvas, lazy 540p video proxy,
   advisory locks, per-episode reapply section.
4. **Multi-user** — `users.json`, bootstrap, OIDC group-claim mapping, provisional
   verdicts + admin review/revert list, sessions.
5. **Glossary proposals + admin surfaces** — wiki-gated proposals from queue and glossary
   page, approval queues, reapply rollups.
6. **Waveform layer, dashboard status/queue, later dashboard controls.**
