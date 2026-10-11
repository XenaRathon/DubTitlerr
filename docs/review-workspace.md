# Human review workspace

The new workspace is at `/review` on the existing review-server port (8842 by default).
The classic pages remain at `/` and `/shared`. Both interfaces use the same queues and
show-wide decision store; there is no migration or alternate source of verdicts.

## Open it

Images built with `Dockerfile.builder` include the compiled Svelte + Vite application.
Open `http://<your-container-host>:8842/review` and enter your existing review token, or,
if the operator enabled the optional login, the username and password (see
[Optional password login](#optional-password-login)).
This feature branch has not been deployed or published automatically.

For a source checkout, build the static assets first (Node 24):

```sh
cd web
npm ci
npm run check
npm run build
cd ..
python3 review_server.py
```

The last command starts **only the review server**, not a transcription or merge worker.
Set your usual `MERGE_ROOTS`, `GLOSSARY_DIR`, and `DECISIONS_DIR` before starting it.
Do not run this alongside another server that writes the same decision store unless you
understand the existing coordination limits. Do not start another media worker.

For frontend development, `npm run dev` inside `web/` serves `/review/` and proxies `/api`
and `/healthz` to the Python server at `127.0.0.1:8842`.

## Review a line

1. Find a show or episode in **Review inbox**. Admitted repairs appear first; enable
   **Include refusal-only episodes** to audit episodes where the guard retained ASR.
2. Filter changes by risk or search the text. Compare the highlighted original and proposal,
   neighboring cards, and reference text. The reference is a different translation, not
   proof of what was spoken.
3. Choose **Listen to dub** to hear a short English audio clip. When a line repeats, select
   its occurrence. Clips contain up to 1.5 seconds of context on each side, capped at 20
   seconds total. Playback is on demand, not a library-wide precomputation.
4. Choose **Keep repair**, **Keep original**, **Write correction**, or **Override guard**
   when offered. Corrections need visible text. Overrides require confirmation at save.
   Choices remain staged while you navigate lines or change filters. Choosing **Keep repair**,
   **Keep original** or **Override guard** (button or key) moves on to the next line that has no
   choice yet, and stays on the last line when none follows; **Write correction** stays put so
   you can type.
5. **Save choices** records the batch. It does not rewrite media. A network or save failure
   keeps your staged choices available in the tab. Partial failures are displayed; refresh
   reconciles successful choices against the server's authoritative queue.
6. For an episode already muxed, **Apply saved decisions** is a separate confirmed action.
   It rebuilds sidecars and queues the existing merge loop to remux. It does not run a mux
   in the browser request. Existing timing/layout guards still apply.

A saved decision is show-wide, keyed on the original/proposed text pair. **Shared lines**
lets you settle an admitted pair appearing in multiple episodes once. This first version
has audio evidence on episode reviews, not the shared-line view. Use the episode inbox
when a repeated line needs occurrence-specific listening.

There is no automatic approval, bulk approval by risk category, or timing editor.
Drafts live in memory, not durable storage: navigation warns before discarding them, but
browser crashes can still lose unsaved choices. Save periodically.

## Keyboard controls

| Key | Action |
| --- | --- |
| J / Down | Next line |
| K / Up | Previous line |
| A | Keep repair, when offered |
| R | Keep original |
| C | Write correction |
| Space | Play / pause audio evidence |
| Escape | Clear current choice |
| Ctrl / Command + S | Save staged choices |
| ? | Open shortcut help |

Single-key shortcuts do not fire in form controls. Save works while typing. The help
window traps focus using a native modal dialog and closes with Escape. Layout adapts to
phone and tablet widths and respects reduced-motion preferences.

## Authentication and media safety

The SPA document and bundled assets are public, inert files containing no library data.
Every data, verdict, apply, and audio request uses the existing token authorization; the only
open API routes are `/healthz`, `/api/auth-mode` and `/api/login`.
The workspace holds its token in tab-scoped `sessionStorage`, not a query string. Sign out
clears that token and loaded data. This does not revoke the server token or sign out the
separate classic page. Use HTTPS at your reverse proxy outside a trusted local network.
`REVIEW_AUTH=off` remains an explicit server-wide opt-out; do not expose it publicly.

Audio is extracted only from allow-listed episodes with English-tagged, non-commentary
audio. Missing English tags produce an error rather than falling back to another language.
The preview validates the exact review identity and occurrence, rejects media outside the
configured roots, permits two concurrent extractions, and applies subprocess timeouts.
Audio is returned as mono 16 kHz WAV, held only in memory, and marked `Cache-Control:
no-store`. Browser blob URLs are revoked when evidence changes or you sign out.
There is no full-file streaming or arbitrary media path endpoint.

New workspace verdict requests include an entry identity as well as the legacy queue
index. A stale question is refused rather than applied to a replacement row. Older API
clients retain their existing index-only behavior. This is not an episode lock: existing
single-worker restrictions still apply, and preview does not make concurrent media
replacement or review apply safe.

Discovery retains the existing review cache behavior. **Refresh queue** reloads API data;
it does not force a costly full media-tree rescan. Health reflects the existing `/healthz`
heartbeat checks, not a GPU or repair-backend probe.

No external fonts, poster services, CDNs, or analytics are required by the workspace.

## Optional password login

The server's one credential is still the review token. A human login can sit in front of it
so nobody has to copy the token from a log: set `REVIEW_USERNAME` and either
`REVIEW_PASSWORD` or `REVIEW_PASSWORD_FILE` (a file read once at start; one trailing newline
is stripped; it wins over `REVIEW_PASSWORD`). The sign-in page then shows username and
password fields, with **Use a token instead** always one click away. A correct pair returns
the same token the other routes take, which the tab keeps in `sessionStorage` as before.

Empty values, only one of the two, or an unreadable password file leave login switched off
(logged at start); an empty password never means "open". After five failures in five
minutes from one address the server answers 429 for 60 seconds. Scripts and the classic
pages keep sending the token and are unaffected.

Choose a strong password: the lockout still allows 5 guesses per minute per client address.
Behind a reverse proxy every client shares the proxy's address, so repeated bad guesses lock
password login for everyone for 60 seconds; the token keeps working meanwhile.

**Over plain HTTP the password crosses the network in clear text.** Use it only on a
trusted LAN or behind TLS (a reverse proxy). It is a convenience for fetching the token,
not a stronger lock than the token.

## Development checks

```sh
cd web
npm ci
npm run check
npm test
npm run build
npx playwright install chromium
npm run test:browser
```

Browser tests need Python with `pysubs2` and `jellyfish`, plus `ffmpeg`/`ffprobe` on PATH.
They start a loopback-only fixture server on port 18842 against temporary synthetic shows
and a generated sine-wave audio stream. They do not discover or process your media library.
Screenshots and traces are written under ignored `web/test-results/`.

Run the backend suite from the repository root:

```sh
pytest
ruff check .
```

CI checks TypeScript/Svelte, helper tests, the production build, and desktop/mobile
Chromium workflows. The Docker build compiles the same static output in a Node stage;
Node is not required in the runtime image. Svelte/Vite are MIT-licensed, the diff utility
is BSD-3-Clause, Lucide is ISC-licensed, and Playwright is Apache-2.0-licensed.
