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
import string
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
# ...but a TTL that expires faster than the walk it is hiding is not a cache at all. Measured
# 2026-08-28: 297s over 989 episodes against a 30s TTL, so every request re-walked the whole
# tree and the cache had never once been hit. The cost is a property of someone else's
# filesystem, so the floor stays configurable and the ceiling is derived from what the walk
# actually took. A list this expensive to rebuild is allowed to be an hour stale; a fresh
# episode still appears within that, and immediately on restart.
STEMS_TTL_FACTOR = float(os.environ.get("REVIEW_STEMS_TTL_FACTOR", "20"))
_STEMS_CACHE = None
# One episode's open queue, filled by the same pass that discovers the episodes and dropped
# when that pass is redone. The index reads every episode's queue jsonl AND its conf.json --
# ~200s across the live library, on top of the walk.
#
# NOT validated per request. The first version stat-ed both files each time to check
# freshness and that measured 176s warm: 989 episodes x 2 stats x ~90ms, almost exactly the
# read it was avoiding. On a mount like this ANY per-episode touch costs the same, so
# validation cannot be cheaper than the thing validated. The cache is therefore tied to the
# walk's lifetime, and a WRITE drops the one stem it wrote -- the writer knows which, and
# dropping everything would make each save cost a full walk exactly when the reviewer is
# working.
#
# Deliberately holds the entries BEFORE the decisions store is consulted. The store is one
# small file read per request, so a verdict shows up everywhere immediately.
_QUEUE_CACHE: dict = {}
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


def _stems_ttl(elapsed: float) -> float:
    """How long the stem list stays valid, given what discovering it cost."""
    return max(STEMS_TTL, elapsed * STEMS_TTL_FACTOR)


def open_entries(stem: str) -> list:
    """This episode's primary, still-live queue entries. Read once per walk, then held.

    NOT filtered by the decisions store. That file is small, is read once per request, and
    changes on every save -- so filtering stays live and a verdict is reflected everywhere
    the moment it lands. Callers apply unresolved.undecided themselves."""
    if stem in _QUEUE_CACHE:
        return _QUEUE_CACHE[stem]
    entries = unresolved.live_only(stem, unresolved.pending(stem, primary_only=True))
    _QUEUE_CACHE[stem] = entries
    return entries


def forget(stem: str) -> None:
    """Drop one episode's cached queue, after writing to it."""
    _QUEUE_CACHE.pop(stem, None)


def known_stems() -> list:
    """Every episode stem this process can see, discovered by walking MERGE_ROOTS.

    The allow-list for every route. A stem is a FILE PATH, so honouring one from a request
    would let any caller read or overwrite anything this root process can reach."""
    global _STEMS_CACHE
    now = time.monotonic()
    # An EXPIRY, not a stamp: how long this list stays good depends on what it cost, and the
    # caller cannot know that before the walk.
    if _STEMS_CACHE and now < _STEMS_CACHE[0]:
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
    # Filled together, dropped together. Nothing else expires a queue entry, so a re-repaired
    # episode would otherwise keep its old queue until the container restarted.
    _QUEUE_CACHE.clear()
    _STEMS_CACHE = (time.monotonic() + _stems_ttl(time.monotonic() - now), stems)
    return stems


def _resolve(stem: str):
    """The stem, only if it is one we already knew about. Never trust the client's path."""
    return stem if stem in known_stems() else None


def _store_for(stem: str, cache: dict) -> dict:
    """This episode's show store, loaded once per show per request.

    The index walks the whole library -- 294 episodes on the live one -- and a store load
    per episode would be 294 reads of a handful of files. Read at CALL time, not bound as a
    default, for decisions.load's reason: DECISIONS_DIR is captured in its signature at
    import, so the mount cannot be redirected after this module loads unless passed through."""
    show = show_for(stem)
    if show not in cache:
        cache[show] = decisions.load(show, decisions.DECISIONS_DIR) if show else {}
    return cache[show]


def handle_index() -> dict:
    """Every episode with something pending, split by what kind of question it is.

    ADMITTED and REFUSED are not the same job and one number for both misleads. An admitted
    repair is a change nothing checked the meaning of -- it SHIPPED, and `factory -> needle`
    passes every gate; that is the reason this whole loop exists. A refusal means the ASR
    text shipped, which is the safe outcome, and reviewing it asks the audit question of
    whether the guard was too strict. Measured on the live library 2026-08-27: 8,662 pending
    items, every one of them a refusal and none an admitted repair -- a single count read as
    thousands of the urgent kind."""
    out, stores = [], {}
    for stem in known_stems():
        live = open_entries(stem)
        # A verdict settles the LINE, show-wide, not the one queue row that raised it. The
        # opening song is 24 episodes of the same question; without this the count here
        # keeps promising work that the episode page no longer has.
        live = unresolved.undecided(live, _store_for(stem, stores))
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


# Leading/trailing only. `don't` and `it's` are ONE word each; stripping punctuation inside
# them would split most contractions and file them as word changes -- the exact 78% this
# ordering exists to push down the page.
_TRIM = string.punctuation + "\u2014\u2013\u2026\u201c\u201d\u00ab\u00bb\u00a1\u00bf"


def _words(text: str) -> list:
    """The word sequence, with punctuation and case discarded.

    The apostrophe fold is decisions.key's, for decisions.key's reason: U+2019 and U+0027 are
    two renderings of one character and English dub dialogue is mostly contractions."""
    folded = (text or "").replace(chr(0x2019), chr(0x27)).lower()
    # A DASH separates, a HYPHEN does not. This stage's commonest single act is turning a
    # run-on into sentences, and `it--that's` becoming `it. That's` adds a token on one side
    # only; filed as a word change, pure punctuation would sort to the top of the queue. The
    # hyphen is left alone because Flame-Flame, non-stop and CP-0 are one word each.
    for sep in ("\u2014", "\u2013", "\u2026"):
        folded = folded.replace(sep, " ")
    return [w for w in (t.strip(_TRIM) for t in folded.split()) if w]


# Worst first. `words` is where the flame-flame deletion lives -- ratio 0.88 inside a 0.6-1.5
# band, shorter so fits_card passes, no new token for invents_name to see: accept_repair
# cannot detect it, and on an unanchored card neither can anything downstream.
RISK_ORDER = {"words": 0, "substitution": 1, "punctuation": 2}

# What the reviewer is being asked to look for, in that order.
RISK_LABEL = {
    "words": "a word added or dropped",
    "substitution": "a word swapped",
    "punctuation": "punctuation only",
}


def risk_class(original: str, proposed: str) -> str:
    """What the repair actually DID, as the axis the queue is ordered on.

    Measured over the 682 admitted repairs of the 2026-08-28 run: 529 punctuation, 85
    substitution, 68 words. Every regression in the owner's 45-line read changed a word;
    none of the 529 could. This is NOT a safety gate -- accept_repair already ran and
    admitted all of these -- it is the reading order that puts the reviewer's attention
    where a mistake is still possible."""
    a, b = _words(original), _words(proposed)
    if a == b:
        return "punctuation"
    return "substitution" if len(a) == len(b) else "words"


def hms(seconds) -> str:
    """A card start as a seek target. Hours only when there are hours."""
    total = int(float(seconds))
    h, m, sec = total // 3600, (total // 60) % 60, total % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _triage_key(e: dict) -> tuple:
    """Stage, then risk, then position in the episode.

    STAGE OUTRANKS RISK, and that is the point: an admitted repair SHIPPED with nothing
    checking its meaning, while a refusal means the ASR text shipped -- the safe outcome --
    and asks the separate audit question of whether the guard was too strict. Ordering the
    two together by risk would make the reviewer change jobs line by line. Time last, so a
    bucket reads in episode order and the reviewer scrubs forwards."""
    return (
        0 if e.get("stage") == "repair_applied" else 1,
        RISK_ORDER.get(e.get("risk", ""), 1),
        (e.get("starts") or [float("inf")])[0],
        e["index"],
    )


def _decorate(stem: str, e: dict, index: int, starts: dict, context: dict | None = None) -> dict:
    """One queue entry as the page needs it: its own index, what may be done to it, whether
    doing it is reversible, what the repair changed, where in the episode to hear it, and
    the cards either side of it."""
    d = dict(e)
    d["index"] = index
    d["risk"] = risk_class(e.get("original_text", ""), e.get("proposed_text", ""))
    # DERIVED, not stored: repair.py records no timing on an accepted repair. Every card the
    # line appears on, because duplicate-pair suppression makes repeats a single entry.
    d["starts"] = starts.get(decisions.key(e.get("original_text", "")), [])
    # A card is not a sentence: reflow splits on duration and line length, so a queued line
    # routinely starts or ends mid-clause and cannot be judged on its own. Same key as
    # `starts`, one entry per occurrence, so context and seek target stay paired.
    d["context"] = (context or {}).get(decisions.key(e.get("original_text", "")), [])
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
    wanted = open_entries(ep) if not all_reasons else unresolved.live_only(ep, unresolved.pending(ep))
    # Settled elsewhere. Decided once on the episode it first appeared in, a shared line is
    # not a question here -- the same rule mux.held_for_review has applied since [S-6].
    seen = len(wanted)
    wanted = unresolved.undecided(wanted, _store_for(ep, {}))
    starts = unresolved.card_starts(ep)
    context = unresolved.card_context(ep)
    entries = [_decorate(ep, e, items.index(e), starts, context) for e in wanted]
    # Sorted for the READER only: index still addresses the jsonl row, so a verdict posted
    # from the page lands on the same entry whatever order it was displayed in.
    entries.sort(key=_triage_key)
    # Named, not silently dropped -- the same reason the index's toggle names the backlog it
    # conceals. A queue that quietly shrank would read as work lost, not work already done.
    return {"stem": ep, "name": os.path.basename(ep), "entries": entries, "settled_elsewhere": seen - len(wanted)}


# One writer at a time. Both writes below are read-modify-write over a WHOLE file -- the
# decisions store and the queue jsonl -- and ThreadingHTTPServer serves each connection on
# its own thread, so two open tabs (or one reviewer double-clicking) could interleave and
# lose each other's verdicts with no error anywhere. A review is one person clicking, so the
# contention this serialises is real but tiny.
_WRITE_LOCK = threading.Lock()


def handle_shared() -> dict:
    """Every still-open line that appears in MORE than one episode, listed once.

    The opening song is the same repair in 24 episodes and the closing song in 23. Read
    per episode that is 23 further decisions carrying no information, and they are mixed in
    with the lines that only exist there. Measured on the live library 2026-08-28: 665 open
    admitted entries against 487 distinct text pairs.

    Grouped on decisions.key of BOTH texts -- the store's own identity -- so what collapses
    here is exactly what one stored verdict settles. It does NOT collapse the same sung line
    transcribed two ways (`our minds will never give up` and `our mods will never give up`
    are 7 episodes each); different ASR text is a different proposal, and a reviewer reading
    one has not read the other.

    Only `repair_applied`. A guard refusal left the ASR text in place and asks the separate
    audit question; batching those across episodes would hide which release they came from."""
    groups: dict = {}
    stores: dict = {}
    for stem in known_stems():
        show = show_for(stem)
        if not show:
            continue  # a decision has nowhere to go without one, so there is nothing to offer
        for e in unresolved.undecided(open_entries(stem), _store_for(stem, stores)):
            if e.get("stage") != "repair_applied":
                continue
            orig, prop = e.get("original_text", ""), e.get("proposed_text", "")
            g = groups.setdefault((show, decisions.key(orig), decisions.key(prop)), {"stems": set(), "e": e})
            g["stems"].add(stem)
    rows = []
    for (show, _ko, _kp), g in groups.items():
        if len(g["stems"]) < 2:
            continue  # a line in one episode is that episode's question, not a shared one
        e = g["e"]
        rows.append(
            {
                "show": show,
                "original_text": e.get("original_text", ""),
                "proposed_text": e.get("proposed_text", ""),
                "episodes": len(g["stems"]),
                "risk": risk_class(e.get("original_text", ""), e.get("proposed_text", "")),
                "offered": list(OFFERED[("repair_applied", "accepted")]),
            }
        )
    # DETERMINISTIC, because `pair` below is an index into this list and the client sends it
    # back: render and submit must agree even across processes. Most-repeated first is also
    # the order that clears the most work per decision.
    rows.sort(key=lambda r: (-r["episodes"], RISK_ORDER.get(r["risk"], 1), r["show"], r["original_text"]))
    for i, r in enumerate(rows):
        r["pair"] = i
    return {"pairs": rows}


def handle_shared_decide(verdicts: list) -> dict:
    """Record verdicts from the shared list. One store write per show.

    NO QUEUE FILE IS TOUCHED, and that is the design rather than an omission: the verdict is
    show-wide, and unresolved.undecided already hides a settled line wherever it appears --
    including in mux.held_for_review, which has trusted the verdict over the queue flag since
    [S-6]. Marking 24 episodes' rows resolved would be 24 rewrites to reach a state the
    pipeline already agrees on.

    The client sends an INDEX into the list this module just built, never the text. A client
    is not a trust boundary, and accepting raw text here would let it write a decision for
    any line in the show -- including one nobody was ever shown."""
    rows = handle_shared()["pairs"]
    errors: list = []
    by_show: dict = {}
    with _WRITE_LOCK:
        for d in verdicts if isinstance(verdicts, list) else []:
            if not isinstance(d, dict):
                errors.append({"pair": None, "error": "not a verdict"})
                continue
            pair, verdict = d.get("pair"), str(d.get("verdict", ""))
            if isinstance(pair, bool) or not isinstance(pair, int) or not (0 <= pair < len(rows)):
                errors.append({"pair": pair, "error": "no such shared line"})
                continue
            r = rows[pair]
            if verdict not in r["offered"]:
                errors.append({"pair": pair, "error": "verdict not offered for this entry"})
                continue
            by_show.setdefault(r["show"], []).append((r, verdict, str(d.get("text", ""))))
        saved, ddir = 0, decisions.DECISIONS_DIR
        for show, wanted in by_show.items():
            store = decisions.load(show, ddir)
            for r, verdict, text in wanted:
                store = decisions.record(store, r["original_text"], r["proposed_text"], verdict, text=text)
            if not decisions.save(store, show, ddir):
                # Named per show, not swallowed: with two shows on the page one store can
                # fail while the other lands, and the reviewer must know which.
                errors.append({"pair": None, "error": f"the decisions for {show} could not be saved"})
                continue
            saved += len(wanted)
    return {"saved": saved, "errors": errors}


def handle_decide_batch(stem: str, verdicts: list) -> dict:
    """Record many verdicts and take their lines out of the queue, in ONE pass.

    The page hands back a whole episode at once. Done one at a time this was a store load, a
    store save and a queue rewrite PER VERDICT, every one of them a round trip over the media
    mount, with a full page reload between each.

    BOTH writes matter and they are not interchangeable: the decision is what stops repair.py
    re-applying and re-queueing the line, the resolved flag is what empties the queue. Sprint
    006 found the [S-6] gate holding an episode forever when only one of the two happened.

    PARTIAL SUCCESS IS REPORTED, not swallowed. A malformed twentieth verdict must not cost
    the reviewer the nineteen good ones, and a verdict that vanished silently is the exact
    failure this loop exists to prevent -- so refused items come back named, with their
    index, and the caller can show them."""
    ep = _resolve(stem)
    if ep is None:
        return {"error": "unknown episode"}
    show = show_for(ep)
    if not show:
        return {"error": "cannot resolve a show for this episode"}
    errors: list = []
    with _WRITE_LOCK:
        items = unresolved.items(ep)
        # Read at CALL time, not bound as a default: decisions.load/save capture
        # DECISIONS_DIR in their signatures at import, so the mount cannot be changed (or
        # pointed at a test directory) after this module loads unless it is passed through.
        ddir = decisions.DECISIONS_DIR
        store = decisions.load(show, ddir)
        updates: list = []
        for d in verdicts if isinstance(verdicts, list) else []:
            if not isinstance(d, dict):
                errors.append({"index": None, "error": "not a verdict"})
                continue
            index, verdict = d.get("index"), str(d.get("verdict", ""))
            # bool is an int in Python, and `True` would index item 1 of somebody else's queue.
            if isinstance(index, bool) or not isinstance(index, int) or not (0 <= index < len(items)):
                errors.append({"index": index, "error": "no such entry"})
                continue
            e = items[index]
            # Enforced here, not merely rendered: a client is not a trust boundary, and
            # `force` on an accepted entry would be an unlabelled bypass of the gate.
            if verdict not in OFFERED.get((str(e.get("stage", "")), str(e.get("reason", ""))), DEFAULT_OFFERED):
                errors.append({"index": index, "error": "verdict not offered for this entry"})
                continue
            text, note = str(d.get("text", "")), str(d.get("note", ""))
            store = decisions.record(store, e.get("original_text", ""), e.get("proposed_text", ""), verdict, text=text, note=note)
            updates.append((index, verdict != "reject", note))
        if not updates:
            return {"saved": 0, "errors": errors}
        if not decisions.save(store, show, ddir):
            # Reported as NOT saved rather than swallowed: a review that silently discards
            # the human's decisions is worse than one that errors, because they believe they
            # are settled. Nothing is cleared from the queue either, so they stay reviewable.
            return {"error": "the decisions could not be saved", "errors": errors}
        # The verdicts are durable from here. The queue flags are a SECOND file and the two
        # cannot be made atomic across them -- but the report can be honest. The gate is
        # unaffected either way: mux trusts the durable verdict, not this flag.
        cleared = unresolved.resolve_many(ep, updates)
        forget(ep)
    out = {"saved": len(updates), "show": show, "errors": errors, "queue_cleared": bool(cleared)}
    if not cleared:
        out["warning"] = "verdicts saved, but the queue could not be cleared — they will still be listed"
    return out


def handle_decide(stem: str, index: int, verdict: str, text: str = "", note: str = "") -> dict:
    """One verdict, as a batch of one. The --review CLI and the single-entry tests keep this
    shape; there is deliberately no second implementation of the two writes behind it."""
    res = handle_decide_batch(stem, [{"index": index, "verdict": verdict, "text": text, "note": note}])
    if res.get("error"):
        return {"error": res["error"]}
    if res.get("errors"):
        return {"error": res["errors"][0]["error"]}
    out = {"saved": True, "verdict": verdict, "show": res["show"], "queue_cleared": res["queue_cleared"]}
    if res.get("warning"):
        out["warning"] = res["warning"]
    return out


def handle_apply(stem: str) -> dict:
    """Push this episode's stored decisions into the video, via [S-5]."""
    ep = _resolve(stem)
    if ep is None:
        return {"error": "unknown episode"}
    store, _ = decisions.decisions_for(ep)
    forget(ep)  # apply_episode drops the stamp and rewrites sidecars; the cached queue is stale
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
        # Two shapes on one route, so there is ONE authorised write path for a verdict
        # rather than two that could drift apart. The page sends the batch; `index` is the
        # single-verdict form the tests and any scripted caller still use.
        if isinstance(body.get("decisions"), list):
            return 200, handle_decide_batch(str(body.get("stem", "")), body["decisions"])
        idx = body.get("index")
        return 200, handle_decide(
            str(body.get("stem", "")),
            idx if isinstance(idx, int) else -1,
            str(body.get("verdict", "")),
            text=str(body.get("text", "")),
            note=str(body.get("note", "")),
        )
    if method == "GET" and path == "/api/shared":
        return 200, handle_shared()
    if method == "POST" and path == "/api/shared":
        d = body.get("decisions")
        return 200, handle_shared_decide(d if isinstance(d, list) else [])
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


# Shared by both pages, so the shared-lines list and an episode queue cannot drift apart
# visually -- the risk colours in particular have to mean the same thing in both.
_CSS = (
    "body{font:14px system-ui;max-width:52em;margin:2em auto}"
    "li{margin:1em 0;border-left:3px solid #ccc;padding-left:.8em}"
    ".o{color:#900}.p{color:#060}small{color:#666}"
    "details{margin:.4em 0}summary{cursor:pointer}details.season{margin-left:1.4em}"
    "li.ep{border:0;margin:.25em 0}.adm{color:#060;font-weight:600}.ref{color:#888;font-size:90%}"
    "#filter{padding:.3em}"
    "#bar{position:sticky;bottom:0;background:#fff;border-top:2px solid #333;padding:.6em 0;margin-top:1em}"
    "#bar button{padding:.4em .8em;margin-right:.5em}#tally{color:#888}"
    "label:has(input[type=radio]){margin-right:.9em;cursor:pointer}"
    "li.rwords{border-left-color:#c00}li.rsubstitution{border-left-color:#e90}"
    "li.rpunctuation{border-left-color:#ccc}"
)


def render_shared() -> str:
    """The shared-lines page. Same radios and same Save as an episode page.

    NO APPLY BUTTON. A verdict here spans episodes; re-muxing is a per-episode act with a
    per-episode cost, so it stays on the episode page where the reviewer can see which file
    they are about to rebuild."""
    rows = handle_shared()["pairs"]
    lis = []
    for r in rows:
        buttons = "".join(
            f'<label><input type="radio" name="p{r["pair"]}" value="{html.escape(v)}"> {html.escape(v)}</label> '
            for v in r["offered"]
        )
        lis.append(
            '<li class="r{}" data-pair="{}" data-risk="{}" data-repeats="{}"><div class=o>{}</div><div class=p>{}</div>'
            "<small><b>in {} episodes</b> \u2014 {} \u2014 {}</small><div>{}"
            '<input id="t{}" placeholder="corrected text"></div></li>'.format(
                html.escape(r["risk"]),
                r["pair"],
                html.escape(r["risk"]),
                r["episodes"],
                html.escape(r["original_text"]),
                html.escape(r["proposed_text"]),
                r["episodes"],
                html.escape(RISK_LABEL.get(r["risk"], "")),
                html.escape(r["show"]),
                buttons,
                r["pair"],
            )
        )
    saved = sum(r["episodes"] - 1 for r in rows)
    return (
        "<!doctype html><meta charset=utf-8><title>DubTitlerr shared lines</title>"
        f"<style>{_CSS}</style>"
        '<h1>Shared lines</h1><p><a href="/">← all episodes</a></p>'
        '<p><label>Order: <select id="shared-sort">'
        '<option value="repeated" selected>most repeated first</option>'
        '<option value="risk">risk first</option>'
        "</select></label></p>"
        "<p>Token: <input id=tok size=44 placeholder='paste from the container log'></p>"
        f"<p><small>{len(rows)} line(s) that appear in more than one episode. Deciding them "
        f"here settles them everywhere and removes {saved} repeat question(s) from the "
        "episode queues. Grouped on the exact text pair, so the same sung line transcribed "
        "two ways is still two decisions.</small></p>"
        f"<div id=list>{''.join(lis)}</div>"
        '<hr><div id=bar><button id="save">Save verdicts</button> <small id=tally></small></div>'
        "<script>"
        "const SS=document.getElementById('shared-sort'),SR={words:0,substitution:1,punctuation:2};"
        "function sortShared(mode){const list=document.getElementById('list');"
        "const rows=[...list.querySelectorAll('li[data-pair]')];"
        "rows.sort((a,b)=>{let d=mode==='risk'?SR[a.dataset.risk]-SR[b.dataset.risk]:"
        "Number(b.dataset.repeats)-Number(a.dataset.repeats);"
        "return d||Number(a.dataset.pair)-Number(b.dataset.pair)});rows.forEach(row=>list.appendChild(row))}"
        "const SHARED_SORT_KEY='dubtitlerr_shared_sort';"
        "try{const saved=localStorage.getItem(SHARED_SORT_KEY);if(['repeated','risk'].includes(saved))SS.value=saved}catch(e){}"
        "sortShared(SS.value);SS.addEventListener('change',()=>{sortShared(SS.value);"
        "try{localStorage.setItem(SHARED_SORT_KEY,SS.value)}catch(e){}});"
        "const TOK=document.getElementById('tok');"
        "try{TOK.value=localStorage.getItem('dubtitlerr_token')||''}catch(e){}"
        "TOK.addEventListener('input',()=>{try{localStorage.setItem('dubtitlerr_token',TOK.value)}catch(e){}});"
        "async function post(p,b){return (await fetch(p,{method:'POST',headers:{'Content-Type':'application/json',"
        f"'{TOKEN_HEADER}':TOK.value}},"
        "body:JSON.stringify(b)})).json()}"
        "function chosen(){return [...document.querySelectorAll('#list input[type=radio]:checked')]"
        ".map(r=>({pair:Number(r.name.slice(1)),verdict:r.value,"
        "text:(document.getElementById('t'+r.name.slice(1))||{}).value||''}))}"
        "const SV=document.getElementById('save'),TAL=document.getElementById('tally');"
        "function tally(){const n=chosen().length,"
        "t=new Set([...document.querySelectorAll('#list input[type=radio]')].map(r=>r.name)).size;"
        "SV.textContent=n?('Save '+n+' verdict'+(n==1?'':'s')):'Save verdicts';SV.disabled=!n;"
        "TAL.textContent=(t-n)+' still undecided'}"
        "document.addEventListener('change',e=>{if(e.target.type==='radio')tally()});"
        "tally();SV.addEventListener('click',async()=>{const d=chosen();if(!d.length)return;"
        "SV.disabled=true;const r=await post('/api/shared',{decisions:d});"
        "if(r.error){alert(r.error);SV.disabled=false;return}"
        "if(r.errors&&r.errors.length){alert('saved '+r.saved+', REFUSED '+r.errors.length+':\\n'+"
        "r.errors.map(x=>'line '+x.pair+': '+x.error).join('\\n'))}"
        "location.reload()});"
        "</script>"
    )


def render_page(stem: str = "") -> str:
    """The review page. Deliberately plain -- this is the functional half, not the final UI.

    Every value drawn from an episode goes through html.escape: the card text is ASR output
    and model output, data this pipeline did not author, rendered by a root process. The
    token is never embedded; the operator pastes the one printed to the container log."""
    doc = handle_episode(stem) if stem else handle_index()
    rows = []
    for e in doc.get("entries", []):
        warn = " <b>PERMANENT — this card has no reference</b>" if e.get("permanent") else ""
        # Radios, not submit buttons. Every click used to be a POST and a full page reload,
        # so working one episode threw the reviewer back to the top thirty times; the answers
        # now sit on the page until they hand the whole episode back at once.
        #
        # Only the OFFERED verdicts are rendered -- the same closed set handle_decide_batch
        # enforces. Rendering `force` on an admitted entry would invite a click the server
        # then refuses, with the reviewer unable to tell why.
        buttons = "".join(
            f'<label><input type="radio" name="v{e["index"]}" value="{html.escape(v)}"> {html.escape(v)}</label> '
            for v in e.get("offered", ())
        )
        # Every card the line is on. Approximate by construction -- these are ASR word
        # timings -- but a seek target within a second or two is what checking a line needs.
        when = ", ".join(hms(t) for t in e.get("starts", ())) or "no card time"
        # The cards either side, so the reviewer can see whether the queued line is a whole
        # sentence or a fragment of one. Rendered per occurrence and in card order, with the
        # queued line itself marked, because a repeated line's neighbours differ each time.
        ctx = "".join(
            "<div class=ctx>{}<b>{}</b>{}</div>".format(
                "".join(f"<span>{html.escape(b)}</span> " for b in occ.get("before", ())),
                html.escape(e.get("original_text", "")),
                "".join(f" <span>{html.escape(a)}</span>" for a in occ.get("after", ())),
            )
            for occ in e.get("context", ())
        )
        rows.append(
            '<li class="r{}" data-index="{}" data-risk="{}" data-start="{}" '
            'data-length="{}">{}<div class=o>{}</div><div class=p>{}</div>'
            "<small><b>{}</b> \u2014 {} \u2014 {}/{}{}</small><div>{}"
            '<input id="t{}" placeholder="corrected text"></div></li>'.format(
                html.escape(e.get("risk", "")),
                e["index"],
                html.escape(e.get("risk", "")),
                min(e.get("starts") or [float("inf")]),
                max(len(e.get("original_text", "")), len(e.get("proposed_text", ""))),
                ctx,
                html.escape(e.get("original_text", "")),
                html.escape(e.get("proposed_text", "")),
                html.escape(when),
                html.escape(RISK_LABEL.get(e.get("risk", ""), "")),
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
    #
    # TWO buttons, deliberately. Saving verdicts is cheap and changes what the NEXT repair
    # run ships; applying costs a re-mux of a multi-GB file. One button for both would make
    # every partial pass through an episode trigger one.
    #
    # Sticky, because an episode's queue is long -- 31 rows on the first S31 episode -- and a
    # control the reviewer has to scroll to the end of the list to reach is a control they
    # will not use.
    apply_html = (
        '<hr><div id=bar><button id="save">Save verdicts</button> '
        '<button id="apply">Apply decisions to this episode</button> '
        "<small id=tally></small><br>"
        "<small>Save records your verdicts and stops repair re-applying those lines. Apply "
        "rewrites the subtitle and drops the stamp, so the merge loop re-muxes the file — "
        "only needed for an episode already muxed.</small></div>"
        if stem
        else ""
    )
    zero_adm = sum(1 for e in doc.get("episodes", []) if not e["admitted"])
    hidden_refusals = sum(e["refused"] for e in doc.get("episodes", []) if not e["admitted"])
    counts: dict = {}
    for e in doc.get("entries", []):
        counts[e.get("risk", "")] = counts.get(e.get("risk", ""), 0) + 1
    controls = (
        # On an episode page the order is a claim about what is below it, so the page backs
        # the claim with the counts rather than leaving the reviewer to take it on trust.
        '<p><label>Order: <select id="episode-sort">'
        '<option value="risk" selected>risk first</option>'
        '<option value="chronological">chronological</option>'
        '<option value="queue">queue order</option>'
        '<option value="longest">longest first</option>'
        "</select></label> <small>Reorders this page only; verdicts keep their JSONL indexes.</small></p>"
        "<p><small>Risk summary: "
        + ", ".join(f"<b>{counts.get(k, 0)}</b> {RISK_LABEL[k]}" for k in RISK_ORDER)
        + ". Times are the card start, approximate to the ASR word timings.</small></p>"
        if stem
        else (
            '<p><a href="/shared">shared lines →</a> — the ones in more than one episode, '
            "asked once instead of once per episode.</p>"
            '<p><input id="filter" size=32 placeholder="filter by show or episode…"> '
            f'<label><input type="checkbox" id="showall"> also show the {zero_adm} episodes with nothing '
            f"admitted ({hidden_refusals} guard refusals — the audit backlog)</label></p>"
        )
    )
    episode_sort_script = (
        "const ES=document.getElementById('episode-sort'),ER={words:0,substitution:1,punctuation:2};"
        "function sortEpisode(mode){const list=document.getElementById('list');"
        "const rows=[...list.querySelectorAll('li[data-index]')];"
        "rows.sort((a,b)=>{let d;if(mode==='chronological')d=Number(a.dataset.start)-Number(b.dataset.start);"
        "else if(mode==='queue')d=Number(a.dataset.index)-Number(b.dataset.index);"
        "else if(mode==='longest')d=Number(b.dataset.length)-Number(a.dataset.length);"
        "else d=ER[a.dataset.risk]-ER[b.dataset.risk];"
        "return d||Number(a.dataset.index)-Number(b.dataset.index)});rows.forEach(row=>list.appendChild(row))}"
        "const EPISODE_SORT_KEY='dubtitlerr_episode_sort';"
        "try{const saved=localStorage.getItem(EPISODE_SORT_KEY);"
        "if(['risk','chronological','queue','longest'].includes(saved))ES.value=saved}catch(e){}"
        "sortEpisode(ES.value);ES.addEventListener('change',()=>{sortEpisode(ES.value);"
        "try{localStorage.setItem(EPISODE_SORT_KEY,ES.value)}catch(e){}});"
        if stem
        else ""
    )
    return (
        "<!doctype html><meta charset=utf-8><title>DubTitlerr review</title>"
        f"<style>{_CSS}</style>"
        "<h1>Review</h1><p>Token: <input id=tok size=44 placeholder='paste from the container log'></p>"
        f"{controls}"
        f"<div id=list>{''.join(rows)}</div>"
        f"{apply_html}"
        "<script>"
        f"const STEM={_js(doc.get('stem', ''))};"
        f"{episode_sort_script}"
        # Restored on load and saved on every edit. The server never renders the value --
        # the browser holds it, which is where it already was the moment it was pasted.
        "const TOK=document.getElementById('tok');"
        "try{TOK.value=localStorage.getItem('dubtitlerr_token')||''}catch(e){}"
        "TOK.addEventListener('input',()=>{try{localStorage.setItem('dubtitlerr_token',TOK.value)}catch(e){}});"
        "async function post(p,b){return (await fetch(p,{method:'POST',headers:{'Content-Type':'application/json',"
        f"'{TOKEN_HEADER}':TOK.value}},"
        "body:JSON.stringify(b)})).json()}"
        # One request for the whole episode. Sequential per-verdict posts would each be a
        # read-modify-write of two whole files over the media mount, and concurrent ones
        # would race each other.
        "function chosen(){return [...document.querySelectorAll('#list input[type=radio]:checked')]"
        ".map(r=>({index:Number(r.name.slice(1)),verdict:r.value,"
        "text:(document.getElementById('t'+r.name.slice(1))||{}).value||''}))}"
        "const SV=document.getElementById('save'),TAL=document.getElementById('tally');"
        "function tally(){if(!TAL)return;const n=chosen().length,"
        "t=document.querySelectorAll('#list li input[type=radio]').length?"
        "new Set([...document.querySelectorAll('#list input[type=radio]')].map(r=>r.name)).size:0;"
        "SV.textContent=n?('Save '+n+' verdict'+(n==1?'':'s')):'Save verdicts';SV.disabled=!n;"
        "TAL.textContent=(t-n)+' still undecided'}"
        "document.addEventListener('change',e=>{if(e.target.type==='radio')tally()});"
        "if(SV){tally();SV.addEventListener('click',async()=>{const d=chosen();if(!d.length)return;"
        "SV.disabled=true;const r=await post('/api/decide',{stem:STEM,decisions:d});"
        # Errors are NAMED, not counted. A reviewer told "2 refused" cannot tell which two of
        # their thirty verdicts did not land, and a verdict that vanishes quietly is the
        # exact failure this loop exists to prevent.
        "if(r.error){alert(r.error);SV.disabled=false;return}"
        "if(r.errors&&r.errors.length){alert('saved '+r.saved+', REFUSED '+r.errors.length+':\\n'+"
        "r.errors.map(x=>'entry '+x.index+': '+x.error).join('\\n'))}"
        "else if(r.warning){alert(r.warning)}"
        "location.reload()})}"
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
        if u.path == "/shared":
            return self._send(200, render_shared().encode(), "text/html; charset=utf-8")
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


def warm_cache() -> None:
    """Walk the library and read every queue, so the first request does not have to.

    The walk is unavoidable once per cache lifetime; WHO waits for it is a choice. Measured
    on the live library, a cold index took over 900s -- and the reviewer was the one sitting
    in front of it, after every deploy. The container has those minutes anyway.

    NEVER RAISES. This runs on a background thread while the server is already accepting
    connections, and a media tree that is not mounted yet must delay the first page rather
    than take the process down."""
    try:
        t = time.monotonic()
        stems = known_stems()
        for stem in stems:
            open_entries(stem)
        log(f"review server: cache warm — {len(stems)} episodes in {time.monotonic() - t:.0f}s")
    except Exception as exc:  # noqa: BLE001 -- a warmer must not be able to end the process
        log(f"review server: cache warm failed ({exc}) — the first request will pay for it")


def serve(port: int = 0):
    resolve_token()  # generates and prints the VALUE on first start, before anything is served
    announce_token()  # and on every start, says where to find it
    srv = BoundedHTTPServer((REVIEW_BIND, port or REVIEW_PORT), Handler)
    log(f"review server: listening on {REVIEW_BIND}:{port or REVIEW_PORT}")
    # Started BEFORE serve_forever and as a daemon: the port must open immediately either
    # way, and a warm that is still running must not hold up a shutdown.
    threading.Thread(target=warm_cache, name="warm", daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    serve()
