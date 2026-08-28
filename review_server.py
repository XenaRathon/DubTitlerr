#!/usr/bin/env python3
"""[S-7] The review server: rule on the repairs `accept_repair` admitted.

`accept_repair` states its acceptance bar in its own docstring and then says plainly that
nothing below it enforces that -- `factory -> needle` and `VIVRA card -> Vivi card` pass
every gate. An accepted repair is therefore a decision no code has checked, and this is
where the one reviewer who can check it does so, without the verdict having to travel back
through a markdown diff.

Stdlib http.server, no new dependency. Every route is a thin call into decisions.py,
unresolved.py and review_apply.py; nothing durable is decided here.

SECURITY. `container_run.sh` runs as root so `generate.py` can chown into the media tree.
[S-8] puts this server in that same process tree, and its write routes rewrite subtitles and
force re-muxes. A downstream user on host networking would therefore be exposing an
unauthenticated root-owned endpoint, so:

  REVIEW_TOKEN unset       -> a token is GENERATED, persisted 0600, and printed once.
  REVIEW_TOKEN= (empty)    -> auth disabled. Only an explicit empty value does this, and it
                              is the operator's decision about their own network.
  REVIEW_TOKEN=<value>     -> that token, and it wins over any persisted one.

"Unset" and "set to empty" are distinguished by MEMBERSHIP in os.environ, never by
falsiness: the entire posture rests on telling those two apart. Read routes are never gated
-- they expose only what is already on the operator's disk -- and every write route is.

Episode identity NEVER comes from the client. A stem is accepted only if it appears in the
set this process discovered by walking MERGE_ROOTS; anything else is refused. The stems are
file paths, so trusting one from a request would be a path traversal into any file this
root process can read or overwrite.

Env:
  REVIEW_PORT    default 8842
  REVIEW_TOKEN   see above
  DECISIONS_DIR  default /config/decisions   (the token lives beside it)
  MERGE_ROOTS    default /data/Media/Anime Library  (colon list; the only stems accepted)
"""

import html
import http.server
import json
import os
import secrets
import tempfile
import threading
import time
from urllib.parse import quote

import decisions
import review_apply
import unresolved
from common import log
from decisions import show_for

REVIEW_PORT = int(os.environ.get("REVIEW_PORT", "8842"))


# Beside DECISIONS_DIR rather than inside it: that directory is the artifact a user may
# later publish or sync, and a credential must not ride along with it.
def token_dir_for(decisions_dir: str) -> str:
    """Where the token lives: beside DECISIONS_DIR, never inside it and never at /.

    Beside, because DECISIONS_DIR is the artifact a user may later publish or sync, and a
    credential must not ride along with it. Never at the filesystem root, because
    os.path.dirname("/decisions") is "/" -- truthy, so an `or "/config"` fallback silently
    does not fire and the credential is written to /review_token."""
    parent = os.path.dirname((decisions_dir or "").rstrip("/"))
    return parent if parent not in ("", "/") else "/config"


TOKEN_DIR = token_dir_for(os.environ.get("DECISIONS_DIR", "/config/decisions"))
ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
# Read routes are ungated by design, and each one resolved a stem by walking the whole media
# root. On a 20,000-episode library over CIFS that is a full recursive walk per
# unauthenticated request. Cached with a SHORT ttl rather than forever, so an episode
# generated mid-session still appears without restarting the container.
STEMS_TTL = float(os.environ.get("REVIEW_STEMS_TTL", "30"))
_STEMS_CACHE = None
CONF_SUFFIX = ".dubtitles.conf.json"
# A HEADER, never a query parameter: a token in a URL lands in proxy logs, browser history
# and any Referer the page emits.
TOKEN_HEADER = "X-Review-Token"
# 0.0.0.0 because the container is the point -- the operator reaches this from their LAN.
# That is exactly why an unset REVIEW_TOKEN generates one instead of meaning "open".
REVIEW_BIND = os.environ.get("REVIEW_BIND", "0.0.0.0")
# [F-4] How many requests may be in flight. The Handler.timeout below bounds how LONG one
# unauthenticated request can hold a worker; this bounds HOW MANY. ThreadingHTTPServer
# spawns a daemon thread per connection with no cap of its own, so without this a LAN client
# opens many at once and each dies after the deadline rather than never -- an indefinite pin
# becomes a sustained churn. A review is one person clicking buttons; 16 is generous.
MAX_CONCURRENT = int(os.environ.get("REVIEW_MAX_CONCURRENT", "16"))
# The token minted this process. authorised() calls resolve_token() per request, so without
# this a persistence failure would mint a FRESH random token every time -- none of them the
# one printed at startup -- and every write would 401 forever, including for the operator
# holding the logged token. Failing closed is right; failing closed against yourself is not.
_GENERATED = None

# Which verdicts the reviewer may give, per queue entry. Not cosmetic: `accept` on an entry
# the gate REFUSED would be a `force` with no distinct record, and counting forces is the
# only way anyone will later learn how often the gate was wrong.
OFFERED = {
    ("repair_applied", "accepted"): ("accept", "reject", "correct"),
    ("repair", "rejected_guard"): ("force", "reject", "correct"),
    ("repair", "rejected_name_invented"): ("force", "reject", "correct"),
    ("repair", "decision_unfittable"): ("correct", "reject"),
}
DEFAULT_OFFERED = ("reject", "correct")


def auth_required(token_dir: str = "") -> bool:
    """False ONLY when REVIEW_TOKEN is present in the environment and empty."""
    return not ("REVIEW_TOKEN" in os.environ and os.environ["REVIEW_TOKEN"] == "")


def resolve_token(token_dir: str = "") -> str:
    """The token: the env var, else the persisted one, else a fresh one written 0600.

    Persisted so a restart does not lock the operator out of their own queue, and 0600
    because the media tree this process writes to is deliberately group-writable."""
    global _GENERATED
    d = token_dir or TOKEN_DIR
    env = os.environ.get("REVIEW_TOKEN")
    if env:
        return env
    path = os.path.join(d, "review_token")
    try:
        existing = open(path, encoding="utf-8").read().strip()
        if existing:
            return existing
    except OSError:
        pass
    if _GENERATED:
        return _GENERATED  # persistence failed earlier; keep the one already printed
    tok = secrets.token_urlsafe(32)
    _GENERATED = tok
    try:
        os.makedirs(d, exist_ok=True)
        # 0600 from the moment it exists, via a temp file plus os.replace -- the same
        # atomic idiom decisions.save and unresolved._rewrite use. A direct O_TRUNC write
        # leaves a window where the file exists and is empty, and a reader in that window
        # regenerates a second token that only one of the two writers will keep.
        fd, tmp = tempfile.mkstemp(dir=d, prefix="review_token.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tok + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        log(f"review server: generated an access token, stored {path} (0600)")
        log(f"review server: token = {tok}")  # printed ONCE, at startup, to the operator's own log
    except OSError as e:
        log(f"review server: could not persist a token ({e}); it holds for this process only")
        log(f"review server: token = {tok}")
    return tok


def announce_token(token_dir: str = "") -> None:
    """Say WHERE the token is on every start; say what it IS only when it is new.

    resolve_token prints the value at the moment it generates one, and never again -- so an
    operator returning after the container log had rotated had no way to find it short of
    knowing the docker exec incantation. A path and a command are not a credential."""
    d = token_dir or TOKEN_DIR
    if "REVIEW_TOKEN" in os.environ:
        log("review server: using REVIEW_TOKEN from the environment")
        return
    path = os.path.join(d, "review_token")
    log(f"review server: token file {path} (0600, root) — read it with:")
    log("review server:   docker exec <container> cat " + path)


def authorised(method: str, presented) -> bool:
    """Write routes require the token; read routes never do."""
    if method.upper() in ("GET", "HEAD"):
        return True
    if not auth_required():
        return True
    # compare_digest, not ==: a plain comparison leaks the shared prefix through timing,
    # and this token is the only thing between a LAN and a root-owned write endpoint.
    return bool(presented) and secrets.compare_digest(str(presented), resolve_token())


def known_stems() -> list:
    """Every episode stem this process can see, discovered by walking MERGE_ROOTS.

    The allow-list for every route. A stem is a FILE PATH, so honouring one from a request
    would let any caller read or overwrite anything this root process can reach."""
    global _STEMS_CACHE
    now = time.monotonic()
    if _STEMS_CACHE and now - _STEMS_CACHE[0] < STEMS_TTL:
        return _STEMS_CACHE[1]
    out = []
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        real_root = os.path.realpath(root)
        for dp, _dns, fs in os.walk(root):
            for f in fs:
                if not f.endswith(CONF_SUFFIX):
                    continue
                full = os.path.join(dp, f)
                # os.walk does not follow symlinked DIRECTORIES but does list symlinked
                # FILES. The media tree is deliberately group-writable, so a planted
                # symlink would otherwise put a path outside the roots into the allow-list
                # that every route trusts -- and handle_apply would follow it back out.
                if not os.path.realpath(full).startswith(real_root + os.sep):
                    continue
                out.append(full[: -len(CONF_SUFFIX)])
    stems = sorted(out)
    _STEMS_CACHE = (now, stems)
    return stems


def _resolve(stem: str):
    """The stem, only if it is one we already knew about. Never trust the client's path."""
    return stem if stem in known_stems() else None


def handle_index() -> dict:
    """Every episode with something pending, split by what kind of question it is.

    ADMITTED and REFUSED are not the same job and one number for both misleads. An admitted
    repair is a change nothing checked the meaning of -- it SHIPPED, and `factory -> needle`
    passes every gate; that is the reason this whole loop exists. A refusal means the ASR
    text shipped, which is the safe outcome, and reviewing it asks the audit question of
    whether the guard was too strict. Measured on the live library 2026-08-27: 8,662 pending
    items, every one of them a refusal and none an admitted repair -- a single count read as
    thousands of the urgent kind."""
    out = []
    for stem in known_stems():
        live = unresolved.live_only(stem, unresolved.pending(stem, primary_only=True))
        if not live:
            continue
        admitted = sum(1 for e in live if e.get("stage") == "repair_applied")
        season = os.path.basename(os.path.dirname(stem))
        out.append(
            {
                "stem": stem,
                "name": os.path.basename(stem),
                # Path-derived for DISPLAY only. decisions.show_for is the identity the store
                # and the gate key on, but it needs a glossary to resolve and returns "" when
                # there is none -- a page that silently dropped those episodes would be worse
                # than one whose grouping label is occasionally a directory name.
                "season": season,
                "show": os.path.basename(os.path.dirname(os.path.dirname(stem))),
                "pending": len(live),
                "admitted": admitted,
                "refused": len(live) - admitted,
            }
        )
    # Most admitted first. With everything at 0 the flat list had no meaningful order at all,
    # so the episode that gains an accepted repair has to surface without being hunted for.
    out.sort(key=lambda e: (-e["admitted"], -e["refused"], e["name"]))
    return {"episodes": out}


def _decorate(stem: str, e: dict, index: int) -> dict:
    """One queue entry as the page needs it: its own index, what may be done to it, and
    whether doing it is reversible."""
    d = dict(e)
    d["index"] = index
    d["offered"] = list(OFFERED.get((str(e.get("stage", "")), str(e.get("reason", ""))), DEFAULT_OFFERED))
    # No reference means nothing downstream can repair this card again -- a bad force here
    # is permanent. Every S31 card is unanchored, so this is the common case, not an edge.
    d["permanent"] = not (e.get("reference") or "").strip()
    return d


def handle_episode(stem: str, all_reasons: bool = False) -> dict:
    """One episode's queue. Primary view by default; the full unresolved walk on request."""
    ep = _resolve(stem)
    if ep is None:
        return {"error": "unknown episode"}
    items = unresolved.items(ep)
    # Entries orphaned by a re-transcription describe text this episode no longer contains.
    # Nothing will re-queue them so nothing will ever resolve them; the mux gate has ignored
    # them since [S-6] and the page was still listing them.
    wanted = unresolved.live_only(ep, unresolved.pending(ep, primary_only=not all_reasons))
    entries = [_decorate(ep, e, items.index(e)) for e in wanted]
    return {"stem": ep, "name": os.path.basename(ep), "entries": entries}


def handle_decide(stem: str, index: int, verdict: str, text: str = "", note: str = "") -> dict:
    """Record a verdict and take the line out of the reviewer's queue.

    BOTH writes matter and they are not interchangeable: the decision is what stops repair.py
    re-applying and re-queueing the line, the resolved flag is what empties the queue. Sprint
    006 found the [S-6] gate holding an episode forever when only one of the two happened."""
    ep = _resolve(stem)
    if ep is None:
        return {"error": "unknown episode"}
    items = unresolved.items(ep)
    if not isinstance(index, int) or not (0 <= index < len(items)):
        return {"error": "no such entry"}
    e = items[index]
    # Enforced here, not merely rendered: a client is not a trust boundary, and `force` on an
    # accepted entry would be an unlabelled bypass of the gate.
    if verdict not in OFFERED.get((str(e.get("stage", "")), str(e.get("reason", ""))), DEFAULT_OFFERED):
        return {"error": "verdict not offered for this entry"}
    show = show_for(ep)
    if not show:
        return {"error": "cannot resolve a show for this episode"}
    # Read at CALL time, not bound as a default: decisions.load/save capture DECISIONS_DIR
    # in their signatures at import, so the mount cannot be changed (or pointed at a test
    # directory) after this module loads unless it is passed through explicitly.
    ddir = decisions.DECISIONS_DIR
    store = decisions.load(show, ddir)
    store = decisions.record(store, e.get("original_text", ""), e.get("proposed_text", ""), verdict, text=text, note=note)
    if not decisions.save(store, show, ddir):
        # Reported as NOT saved rather than swallowed: a review that silently discards the
        # human's decision is worse than one that errors, because they believe it is settled.
        return {"error": "the decision could not be saved"}
    # The verdict is durable from here. The queue flag is a SECOND file and the two cannot
    # be made atomic across them -- but the report can be honest. Saying "saved" when the
    # entry did not clear tells the reviewer the line is settled while their queue still
    # shows it. The gate is unaffected either way: mux trusts the durable verdict, not this
    # flag (mux.held_for_review), so this is a reporting fix rather than a correctness one.
    cleared = unresolved.resolve(ep, index, accept=(verdict != "reject"), note=note)
    out = {"saved": True, "verdict": verdict, "show": show, "queue_cleared": bool(cleared)}
    if not cleared:
        out["warning"] = "verdict saved, but the queue entry could not be cleared — it will still be listed"
    return out


def handle_apply(stem: str) -> dict:
    """Push this episode's stored decisions into the video, via [S-5]."""
    ep = _resolve(stem)
    if ep is None:
        return {"error": "unknown episode"}
    store, _ = decisions.decisions_for(ep)
    return review_apply.apply_episode(ep, store, apply=True)


# --- HTTP ----------------------------------------------------------------------------
# route() is the entire request surface and is a pure function of (method, path, body,
# token), so every test drives it directly and no socket is ever opened in the suite.


def route(method: str, path: str, body: dict, token) -> tuple:
    """(status, payload) for one request."""
    if not authorised(method, token):
        return 401, {"error": "a token is required for writes"}
    if method == "GET" and path == "/api/episodes":
        return 200, handle_index()
    if method == "GET" and path == "/api/episode":
        return 200, handle_episode(str(body.get("stem", "")), all_reasons=bool(body.get("all")))
    if method == "POST" and path == "/api/decide":
        idx = body.get("index")
        return 200, handle_decide(
            str(body.get("stem", "")),
            idx if isinstance(idx, int) else -1,
            str(body.get("verdict", "")),
            text=str(body.get("text", "")),
            note=str(body.get("note", "")),
        )
    if method == "POST" and path == "/api/apply":
        return 200, handle_apply(str(body.get("stem", "")))
    return 404, {"error": "no such route"}


def _js(value: str) -> str:
    """A value as a JS string literal, safe inside a <script> block.

    NOT html.escape: that is for HTML text, and running a file path through it turns
    `Tom & Jerry` into `Tom &amp; Jerry`, which the page then posts back as a stem no
    `_resolve()` will recognise -- every verdict on that show refused, with no explanation
    the reviewer can act on. json.dumps produces the correct literal; `<` is escaped on top
    of it because json.dumps does not touch `/`, so any value containing `</script>` would
    otherwise close the block early."""
    return json.dumps(value).replace("<", "\\u003c")


def render_page(stem: str = "") -> str:
    """The review page. Deliberately plain -- this is the functional half, not the final UI.

    Every value drawn from an episode goes through html.escape: the card text is ASR output
    and model output, data this pipeline did not author, rendered by a root process. The
    token is never embedded; the operator pastes the one printed to the container log."""
    doc = handle_episode(stem) if stem else handle_index()
    rows = []
    for e in doc.get("entries", []):
        warn = " <b>PERMANENT — this card has no reference</b>" if e.get("permanent") else ""
        # data-* attributes plus a delegated listener, NOT an inline handler. html.escape is
        # HTML escaping, and an HTML parser DECODES entities in an attribute value before the
        # JS inside it is parsed -- so `&#x27;` becomes a quote and closes the string anyway.
        # Nothing reachable exploits this today (OFFERED is a closed constant set); it is
        # fixed because the renderer's contract is that it handles queue data.
        buttons = "".join(
            f'<button data-i="{e["index"]}" data-v="{html.escape(v)}">{html.escape(v)}</button> ' for v in e.get("offered", ())
        )
        rows.append(
            "<li><div class=o>{}</div><div class=p>{}</div><small>{}/{}{}</small><div>{}"
            '<input id="t{}" placeholder="corrected text"></div></li>'.format(
                html.escape(e.get("original_text", "")),
                html.escape(e.get("proposed_text", "")),
                html.escape(e.get("stage", "")),
                html.escape(e.get("reason", "")),
                warn,
                buttons,
                e["index"],
            )
        )
    # Grouped show -> season, because rendered flat against the real library this was 294
    # rows of links with no way to find anything. One Pace alone is 457 episodes, so grouping
    # by show is not sufficient on its own.
    groups: dict = {}
    for ep in doc.get("episodes", []):
        groups.setdefault(ep["show"], {}).setdefault(ep["season"], []).append(ep)
    for show, seasons in sorted(groups.items(), key=lambda kv: -sum(e["admitted"] for s in kv[1].values() for e in s)):
        eps_all = [e for s in seasons.values() for e in s]
        adm, ref = sum(e["admitted"] for e in eps_all), sum(e["refused"] for e in eps_all)
        inner = []
        for season, eps in sorted(seasons.items()):
            sa, sr = sum(e["admitted"] for e in eps), sum(e["refused"] for e in eps)
            lis = []
            for ep in eps:
                href = "/?stem=" + html.escape(quote(ep["stem"], safe="/"))
                # data-adm drives the toggle client-side: hiding server-side would make the
                # count on the toggle a claim the page could not back up.
                lis.append(
                    f'<li class=ep data-adm="{ep["admitted"]}"><a href="{href}">{html.escape(ep["name"])}</a> '
                    f"<span class=adm>{ep['admitted']} admitted</span> "
                    f"<span class=ref>{ep['refused']} refused</span></li>"
                )
            inner.append(
                f'<details class=season data-adm="{sa}"><summary>{html.escape(season)} — '
                f"<b>{sa}</b> admitted, {sr} refused</summary><ul>{''.join(lis)}</ul></details>"
            )
        rows.append(
            f'<details class=show data-adm="{adm}"{" open" if adm else ""}>'
            f"<summary>{html.escape(show)} — <b>{adm}</b> admitted (shipped unchecked), "
            f"{ref} refused by the guard</summary>{''.join(inner)}</details>"
        )
    # Only on an episode page. A verdict already changes what the NEXT repair run ships;
    # this is for an episode that has ALREADY been muxed, where nothing would re-trigger it.
    # It costs a re-mux of a multi-GB file, so the button says so rather than just doing it.
    apply_html = (
        '<hr><p><button id="apply">Apply decisions to this episode</button> '
        "<small>rewrites the subtitle and drops the stamp, so the merge loop will re-mux it. "
        "Only needed for an episode that has already been muxed.</small></p>"
        if stem
        else ""
    )
    zero_adm = sum(1 for e in doc.get("episodes", []) if not e["admitted"])
    hidden_refusals = sum(e["refused"] for e in doc.get("episodes", []) if not e["admitted"])
    controls = (
        ""
        if stem
        else (
            '<p><input id="filter" size=32 placeholder="filter by show or episode…"> '
            f'<label><input type="checkbox" id="showall"> also show the {zero_adm} episodes with nothing '
            f"admitted ({hidden_refusals} guard refusals — the audit backlog)</label></p>"
        )
    )
    return (
        "<!doctype html><meta charset=utf-8><title>DubTitlerr review</title>"
        "<style>body{font:14px system-ui;max-width:52em;margin:2em auto}"
        "li{margin:1em 0;border-left:3px solid #ccc;padding-left:.8em}"
        ".o{color:#900}.p{color:#060}small{color:#666}"
        "details{margin:.4em 0}summary{cursor:pointer}details.season{margin-left:1.4em}"
        "li.ep{border:0;margin:.25em 0}.adm{color:#060;font-weight:600}.ref{color:#888;font-size:90%}"
        "#filter{padding:.3em}</style>"
        "<h1>Review</h1><p>Token: <input id=tok size=44 placeholder='paste from the container log'></p>"
        f"{controls}"
        f"<div id=list>{''.join(rows)}</div>"
        f"{apply_html}"
        "<script>"
        f"const STEM={_js(doc.get('stem', ''))};"
        # Restored on load and saved on every edit. The server never renders the value --
        # the browser holds it, which is where it already was the moment it was pasted.
        "const TOK=document.getElementById('tok');"
        "try{TOK.value=localStorage.getItem('dubtitlerr_token')||''}catch(e){}"
        "TOK.addEventListener('input',()=>{try{localStorage.setItem('dubtitlerr_token',TOK.value)}catch(e){}});"
        "async function post(p,b){return (await fetch(p,{method:'POST',headers:{'Content-Type':'application/json',"
        f"'{TOKEN_HEADER}':TOK.value}},"
        "body:JSON.stringify(b)})).json()}"
        "async function decide(i,v){const t=document.getElementById('t'+i).value;"
        "const r=await post('/api/decide',{stem:STEM,index:i,verdict:v,text:t});"
        "if(r.error){alert(r.error)}else if(r.warning){alert(r.warning)}else{location.reload()}}"
        "document.addEventListener('click',e=>{const b=e.target.closest('button[data-v]');"
        "if(b){decide(Number(b.dataset.i),b.dataset.v)}});"
        "const ap=document.getElementById('apply');"
        "if(ap){ap.addEventListener('click',async()=>{ap.disabled=true;"
        "const r=await post('/api/apply',{stem:STEM});"
        "alert(r.error?r.error:(r.changed?('re-opened: '+r.changed+' card(s) changed'):"
        "'nothing to apply for this episode'));ap.disabled=false})}"
        # Hiding is right -- the refusal backlog is work the owner explicitly deferred -- but
        # hiding it SILENTLY would make thousands of real items invisible to anyone who did
        # not know the toggle existed, so the control names the count it conceals.
        "const F=document.getElementById('filter'),SA=document.getElementById('showall');"
        "function apply(){const q=(F&&F.value||'').toLowerCase(),all=SA&&SA.checked;"
        "document.querySelectorAll('#list li.ep').forEach(li=>{"
        "const t=li.textContent.toLowerCase(),adm=+li.dataset.adm;"
        "li.style.display=((all||adm>0)&&(!q||t.includes(q)))?'':'none'});"
        "document.querySelectorAll('#list details').forEach(d=>{"
        "const vis=[...d.querySelectorAll('li.ep')].some(li=>li.style.display!=='none');"
        "d.style.display=vis?'':'none';if(q&&vis)d.open=true});}"
        "if(F){F.addEventListener('input',apply);SA.addEventListener('change',apply);apply()}"
        "</script>"
    )


class Handler(http.server.BaseHTTPRequestHandler):
    # BaseHTTPRequestHandler.timeout is None, and socketserver.StreamRequestHandler.setup()
    # only calls connection.settimeout() when it is not None -- so without this rfile.read()
    # blocks with no deadline. The 1MB cap bounds MEMORY per request and nothing else: a
    # client declaring a legal length and dripping a byte a minute pins a worker thread
    # BEFORE authorised() is reached, and ThreadingHTTPServer spawns those threads uncapped.
    # 30s is long for a review POST (a verdict is a few hundred bytes) and short for a drip.
    timeout = 30

    def _send(self, status, payload, ctype="application/json"):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        # No framing, no sniffing, no referrer: the page renders text this pipeline did not
        # author, and the token must not ride out on a Referer header.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            stem = (parse_qs(u.query).get("stem") or [""])[0]
            return self._send(200, render_page(stem).encode(), "text/html; charset=utf-8")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        status, payload = route("GET", u.path, q, self.headers.get(TOKEN_HEADER))
        self._send(status, payload)

    def do_POST(self):
        # The body is read BEFORE authorised() runs, so this bound is what stands between an
        # unauthenticated caller and this root process's memory. int("-1") does NOT raise, so
        # a declared length of -1 slipped past a `> cap` test and rfile.read(-1) then read to
        # EOF -- unbounded, which is exactly what the check existed to prevent. Anything not
        # a non-negative integer is refused without reading a byte.
        raw = self.headers.get("Content-Length")
        try:
            n = int(raw or "")
        except (TypeError, ValueError):
            return self._send(411, {"error": "a valid Content-Length is required"})
        if n < 0:
            return self._send(411, {"error": "a valid Content-Length is required"})
        if n > 1 << 20:
            return self._send(413, {"error": "body too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        status, payload = route("POST", self.path, body, self.headers.get(TOKEN_HEADER))
        self._send(status, payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - the base class names it this
        log("review server: " + (format % args))


class BoundedHTTPServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer with a ceiling on requests in flight.

    Over the ceiling the connection is CLOSED rather than queued: an unbounded accept queue
    is the same resource exhaustion with an extra step, and a reviewer would rather see a
    dropped connection than a page that hangs. The slot is released in
    process_request_thread's finally, which is the only place that runs for both the served
    and the errored path -- releasing in process_request would return the slot before the
    work it is guarding had started."""

    daemon_threads = True

    def __init__(self, *a, **k):
        self._slots = threading.Semaphore(MAX_CONCURRENT)
        super().__init__(*a, **k)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            log(f"review server: refusing {client_address[0]} — {MAX_CONCURRENT} requests already in flight")
            self.close_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def serve(port: int = 0):
    resolve_token()  # generates and prints the VALUE on first start, before anything is served
    announce_token()  # and on every start, says where to find it
    srv = BoundedHTTPServer((REVIEW_BIND, port or REVIEW_PORT), Handler)
    log(f"review server: listening on {REVIEW_BIND}:{port or REVIEW_PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    serve()
