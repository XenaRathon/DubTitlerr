"""[S-7] the review server: handlers only, no socket is ever opened.

Security posture, and why it is not the LAN default: container_run.sh runs as root so
generate.py can chown into the media tree; this server adds WRITE routes to that same
process tree -- routes that rewrite subtitles and force re-muxes. A downstream user on host
networking would otherwise expose an unauthenticated root-owned endpoint. So an unset
REVIEW_TOKEN generates one; only an explicitly empty REVIEW_TOKEN disables auth."""

import json
import os
import stat
from typing import Any

import decisions
import review_server
import unresolved

# Card texts and queue entries are kept in CORRESPONDENCE on purpose. repair.py only ever
# queues a line it processed, so every entry's original_text is a real card of this episode.
# An earlier version of this fixture queued "a"/"c"/"d" against a single card -- a state the
# pipeline cannot produce, and the same class of trap that cost two earlier sprints. It also
# matters directly now: [S-6]'s orphan filter releases an episode whose queue entries match
# no current conf.json row, so a careless fixture would quietly describe an orphaned queue.
_CARDS = ["I saw spondum", "the ship sailed", "he went thataway", "we run this joint"]


def _episode(tmp_path, name="ep"):
    """An episode with a queue holding one of each reason that matters here."""
    stem = str(tmp_path / name)
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": i * 2.0, "end": i * 2.0 + 2.0, "text": t} for i, t in enumerate(_CARDS)], f)
    unresolved.record(stem, "repair_applied", "accepted", original_text=_CARDS[0], proposed_text="I saw Spandam")
    unresolved.record(
        stem, "repair", "rejected_guard", original_text=_CARDS[1], proposed_text="the ship has sailed", reference="ref"
    )
    unresolved.record(stem, "repair", "no_reference", original_text=_CARDS[2])
    unresolved.record(stem, "repair", "llm_empty", original_text=_CARDS[3])
    return stem


def test_an_unset_token_is_generated_persisted_0600_and_required(tmp_path, monkeypatch):
    """The unsafe default is the thing being tested away.

    An earlier draft of the spec had unset mean "no auth, which is the LAN default". That
    reasoning was about the MAINTAINER's convenience and did not transfer to a downstream
    install running as root on host networking. Reversed after adversarial review."""
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    tok = review_server.resolve_token(str(tmp_path))

    assert tok and len(tok) >= 32, "a generated token must not be guessable"
    path = os.path.join(str(tmp_path), "review_token")
    assert os.path.exists(path), "it must survive a restart, or every restart locks the operator out"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, "0600: the media tree is group-writable, this must not be"
    assert open(path).read().strip() == tok
    assert review_server.resolve_token(str(tmp_path)) == tok, "a second start reuses it rather than rotating"


def test_an_explicitly_empty_token_disables_auth_but_unset_does_not(tmp_path, monkeypatch):
    """ "Unset" and "set to empty" must be distinguished by MEMBERSHIP in os.environ, not by
    falsiness -- the whole security decision rests on telling those two apart."""
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    assert review_server.auth_required(str(tmp_path)) is True, "unset must NOT mean open"

    monkeypatch.setenv("REVIEW_TOKEN", "")
    assert review_server.auth_required(str(tmp_path)) is False, "explicitly empty is the operator's decision"

    monkeypatch.setenv("REVIEW_TOKEN", "hunter2")
    assert review_server.auth_required(str(tmp_path)) is True
    assert review_server.resolve_token(str(tmp_path)) == "hunter2", "an explicit token wins over the persisted one"


def test_a_write_route_without_the_token_is_refused_and_a_read_route_is_not(tmp_path, monkeypatch):
    """Read routes stay open: they expose only what is already on the operator's disk, and
    gating them would make the page useless without adding protection. WRITES are what
    rewrite subtitles and force re-muxes."""
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    assert review_server.authorised("POST", None) is False
    assert review_server.authorised("POST", "wrong-token") is False
    assert review_server.authorised("POST", review_server.resolve_token(str(tmp_path))) is True
    assert review_server.authorised("GET", None) is True, "reads are not gated"


def test_an_unknown_stem_is_refused_by_every_route(tmp_path, monkeypatch):
    """A stem is a FILE PATH. Honouring one from a request would let any caller read or
    overwrite anything this root process can reach -- /etc/shadow, another user's library,
    the decision store itself. Every route resolves against the set discovered by walking
    MERGE_ROOTS, and anything else is refused before a single file is touched."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    for probe in ("/etc/passwd", str(tmp_path / "../../etc/shadow"), stem + "/../ep", ""):
        assert review_server.handle_episode(probe).get("error") == "unknown episode", probe
        assert review_server.handle_decide(probe, 0, "reject").get("error") == "unknown episode", probe
        assert review_server.handle_apply(probe).get("error") == "unknown episode", probe


def test_the_default_view_omits_non_primary_reasons(tmp_path, monkeypatch):
    """Asserted on the ABSENCE. unresolved.pending() applies no stage filter of its own, so
    a server that simply returned everything would pass a presence-only check."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    reasons = {e["reason"] for e in review_server.handle_episode(stem)["entries"]}
    assert "no_reference" not in reasons and "llm_empty" not in reasons
    assert {"accepted", "rejected_guard"} <= reasons

    all_reasons = {e["reason"] for e in review_server.handle_episode(stem, all_reasons=True)["entries"]}
    assert {"no_reference", "llm_empty"} <= all_reasons, "the full walk is still reachable"


def test_the_verdicts_offered_depend_on_the_entry(tmp_path, monkeypatch):
    """An `accept` on an entry the gate REFUSED is a `force` with no distinct record, which
    defeats the counting force exists for -- the whole later argument about whether
    accept_repair is too strict rests on knowing how often a human overrode it."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    by_reason = {e["reason"]: e for e in review_server.handle_episode(stem)["entries"]}

    assert "force" not in by_reason["accepted"]["offered"]
    assert "accept" in by_reason["accepted"]["offered"]
    assert "force" in by_reason["rejected_guard"]["offered"]
    assert "accept" not in by_reason["rejected_guard"]["offered"], "an accept here would be an unlabelled force"


def test_forcing_an_unanchored_card_is_labelled_permanent(tmp_path, monkeypatch):
    """A card with no fansub reference cannot be repaired by anything downstream, so a bad
    force there is unrecoverable. Every S31 card is unanchored, which is why this warning
    exists rather than being a nicety."""
    stem = str(tmp_path / "ep_unanch")
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": 0.0, "end": 2.0, "text": "x"}], f)
    unresolved.record(stem, "repair", "rejected_guard", original_text="x", proposed_text="y", reference="the fansub line")
    unresolved.record(stem, "repair", "rejected_guard", original_text="p", proposed_text="q")
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    entries = review_server.handle_episode(stem)["entries"]
    assert entries[0]["permanent"] is False, "an anchored card can be repaired again later"
    assert entries[1]["permanent"] is True, "an unanchored one cannot"


def test_decide_persists_a_verdict_and_resolves_the_queue_entry(tmp_path, monkeypatch):
    """Both writes, or neither is useful: the DECISION is what stops repair.py re-applying
    and re-queueing the line, the RESOLVED flag is what takes it out of the reviewer's
    queue. Sprint 006 found the gate holding forever when only one of the two happened."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(review_server, "show_for", lambda p: "Show")

    res = review_server.handle_decide(stem, 0, "reject", note="regression")

    assert res.get("saved") is True
    assert unresolved.items(stem)[0]["resolved"] is True, "the entry leaves the reviewer's queue"
    hit = decisions.lookup(decisions.load("Show", str(tmp_path)), "I saw spondum", "I saw Spandam")
    assert hit is not None and hit["verdict"] == "reject", "and repair.py can see the verdict"


def test_decide_refuses_a_verdict_the_entry_does_not_offer(tmp_path, monkeypatch):
    """The offered set is enforced server-side, not merely rendered. A client is not a
    trust boundary, and `force` on an accepted entry would be an unlabelled bypass."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(review_server, "show_for", lambda p: "Show")

    res = review_server.handle_decide(stem, 0, "force")

    assert res.get("error") == "verdict not offered for this entry"
    assert unresolved.items(stem)[0].get("resolved") is False, "and nothing was written"


def test_apply_invokes_the_write_back(tmp_path, monkeypatch):
    """The server holds no durable logic: applying is [S-5]'s job, and this route is a call
    into it. Asserted on the delegation, because a route that reported success while doing
    nothing would look identical from outside."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    seen = {}

    def fake_apply(s, store, apply=False):
        seen.update({"stem": s, "apply": apply})
        return {"stem": s, "changed": 1}

    monkeypatch.setattr(review_server.review_apply, "apply_episode", fake_apply)

    res = review_server.handle_apply(stem)

    assert res["changed"] == 1
    assert seen == {"stem": stem, "apply": True}, "the route must actually write, not dry-run"


def test_the_index_lists_only_episodes_with_something_pending(tmp_path, monkeypatch):
    """An index padded with episodes that need nothing is how a review queue stops being
    read. Counted on the PRIMARY view, matching what the episode page opens with."""
    busy = _episode(tmp_path, "busy")
    quiet = str(tmp_path / "quiet")
    with open(quiet + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": 0.0, "end": 1.0, "text": "q"}], f)
    unresolved.record(quiet, "repair", "no_reference", original_text="q")
    monkeypatch.setattr(review_server, "known_stems", lambda: [busy, quiet])

    names = {e["name"]: e["pending"] for e in review_server.handle_index()["episodes"]}

    assert names == {"busy": 2}, "no_reference alone is not a reason to open an episode"


def test_known_stems_only_finds_episodes_under_the_configured_roots(tmp_path, monkeypatch):
    """The allow-list is built from MERGE_ROOTS, so an episode outside them is not merely
    unlisted -- it is unreachable by every route."""
    inside = tmp_path / "lib"
    inside.mkdir()
    (inside / ("a" + review_server.CONF_SUFFIX)).write_text("[]")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / ("b" + review_server.CONF_SUFFIX)).write_text("[]")
    monkeypatch.setattr(review_server, "ROOTS", [str(inside)])

    found = review_server.known_stems()

    assert found == [str(inside / "a")]
    assert review_server.handle_episode(str(outside / "b"))["error"] == "unknown episode"


def test_the_router_gates_writes_and_passes_reads(tmp_path, monkeypatch):
    """route() is the whole request surface, tested directly -- no socket is opened."""
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    tok = review_server.resolve_token(str(tmp_path))

    assert review_server.route("GET", "/api/episodes", {}, None)[0] == 200
    assert review_server.route("POST", "/api/decide", {"stem": stem, "index": 0, "verdict": "reject"}, None)[0] == 401
    assert review_server.route("POST", "/api/decide", {"stem": stem, "index": 0, "verdict": "reject"}, "nope")[0] == 401
    assert review_server.route("POST", "/api/apply", {"stem": stem}, tok)[0] == 200
    assert review_server.route("GET", "/api/nothing-here", {}, None)[0] == 404


def test_episode_text_is_escaped_into_the_page(tmp_path, monkeypatch):
    """Card text is ASR and model output -- data this pipeline did not author, rendered into
    a page served by a root process. An episode whose dialogue happens to contain markup
    would otherwise execute in the reviewer's browser."""
    stem = str(tmp_path / "ep_xss")
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": 0.0, "end": 2.0, "text": "x"}], f)
    unresolved.record(stem, "repair_applied", "accepted", original_text="<script>alert(1)</script>", proposed_text="a & b")
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    page = review_server.render_page(stem)

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page and "a &amp; b" in page


def test_the_token_is_never_placed_in_a_url(tmp_path, monkeypatch):
    """A token in a query string lands in every proxy log, browser history and Referer
    header it passes. The page must carry it in a header instead."""
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    tok = review_server.resolve_token(str(tmp_path))

    page = review_server.render_page(stem)

    assert tok not in page, "the operator pastes the token; the page must never embed it"
    assert review_server.TOKEN_HEADER.lower() == "x-review-token"


def test_the_token_comparison_is_timing_safe():
    """A SOURCE assertion, and it is the weaker kind of test on purpose.

    `==` and `secrets.compare_digest` return the same answer for every input, so no
    behavioural test can tell them apart -- a mutation swapping one for the other passes the
    whole suite. The difference is only observable as a timing side channel, which is not
    something this suite can measure reliably. This token is the single thing between a LAN
    and a root-owned endpoint that rewrites subtitles, so the property is worth a guard that
    catches a silent revert, even though it pins the decision rather than the behaviour."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "review_server.py")).read()
    body = src[src.index("def authorised(") : src.index("def known_stems(")]

    assert "compare_digest" in body, "the token comparison must be constant-time"
    assert "== resolve_token" not in body and "resolve_token() ==" not in body


def test_a_show_with_an_ampersand_in_its_name_is_still_usable(tmp_path, monkeypatch):
    """html.escape is right for HTML TEXT and wrong for the JS and URL contexts.

    A stem is a real file path, and directory names legitimately contain `&`. Escaped into
    the page's `const STEM`, the value the browser posts back is `Tom &amp; Jerry`, which is
    not the stem `_resolve()` knows -- so every verdict on that show is refused as "unknown
    episode". The href has the same fault for a different reason: a raw `&` in a query value
    terminates the parameter.

    Not a security hole -- html.escape does neutralise `</script>` -- but a total functional
    failure for an ordinary filename, and silent apart from a refusal the reviewer cannot
    explain."""
    show = tmp_path / "Tom & Jerry (1940)"
    show.mkdir()
    stem = str(show / "ep01")
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": 0.0, "end": 2.0, "text": "x"}], f)
    unresolved.record(stem, "repair_applied", "accepted", original_text="x", proposed_text="y")
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    page = review_server.render_page(stem)
    embedded = json.loads(page.split("const STEM=")[1].split(";")[0])

    assert embedded == stem, "the page must post back the REAL stem, not an HTML-escaped one"
    assert review_server.handle_episode(embedded).get("error") is None, "and that value must resolve"


def test_an_angle_bracket_in_a_stem_is_escaped_for_the_script_block(tmp_path, monkeypatch):
    """A stem cannot contain `</script>` -- `/` is a path separator, so that exact sequence
    is not a legal filename, and the breakout risk from a stem is nil. `<` alone IS legal,
    and is escaped anyway: the rule "never emit a raw `<` inside a script block" is the one
    worth holding, because the next value interpolated there may not be a filename.

    The `</script>` case that IS reachable is card text, covered by
    test_episode_text_is_escaped_into_the_page."""
    stem = str(tmp_path / "a<b")
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([], f)

    page = review_server.render_page(stem)
    js = page.split("const STEM=")[1].split(";")[0]

    assert "\\u003c" in js, "a raw < must never be emitted inside a script block"
    assert json.loads(js) == stem, "and it must still decode to the real stem"


def test_the_index_link_url_encodes_the_stem(tmp_path, monkeypatch):
    """A raw `&` in a query VALUE terminates the parameter, so the link to an episode of
    "Tom & Jerry" would arrive at the server as a truncated stem and resolve to nothing.
    html.escape does not help -- `&amp;` is still an ampersand once the HTML is parsed.
    Caught by a mutation, not by design: the JS fix had a test and this one did not."""
    show = tmp_path / "Tom & Jerry (1940)"
    show.mkdir()
    stem = str(show / "ep01")
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": 0.0, "end": 2.0, "text": "x"}], f)
    unresolved.record(stem, "repair_applied", "accepted", original_text="x", proposed_text="y")
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    page = review_server.render_page()
    href = page.split('href="')[1].split('"')[0]

    assert "%26" in href, "the ampersand must be percent-encoded, not left to split the query"
    from urllib.parse import parse_qs, urlparse

    assert parse_qs(urlparse(href).query)["stem"][0] == stem, "and the link must round-trip to the real stem"


# --- the transport layer -----------------------------------------------------
# Driven directly, still without a socket: Handler is constructed unbound and given fake
# streams. The previous suite tested route() only, and the body-cap defect below lived
# entirely in the layer that gap left uncovered.


class _Wire:
    """A fake rfile/wfile pair, so do_POST can be driven with no network."""

    def __init__(self, body=b"", declared=None):
        import io

        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.headers = {"Content-Length": str(len(body) if declared is None else declared)}
        self.status: int | None = None

    def as_handler(self, path="/api/decide"):
        wire = self

        class _H(review_server.Handler):
            """A subclass rather than attribute assignment: BaseHTTPRequestHandler declares
            these, so patching them onto an instance is a type error and, more to the point,
            a subclass is what actually proves the real methods are the ones being driven."""

            def __init__(self):  # no socket, no server, no __init__ chain
                self.rfile, self.wfile, self.path = wire.rfile, wire.wfile, path
                self.headers = wire.headers  # type: ignore[assignment]

            def send_response(self, code, message=None):
                wire.status = code

            def send_header(self, keyword, value):
                pass

            def end_headers(self):
                pass

        return _H()


def test_a_negative_content_length_cannot_defeat_the_body_cap(tmp_path, monkeypatch):
    """`int("-1")` does not raise, so a declared length of -1 slips past `n > 1<<20`, and
    `rfile.read(-1)` reads to EOF rather than to the cap. The body is read BEFORE
    authorised() runs, so any unauthenticated caller on the LAN could stream until this root
    process ran out of memory -- while the docstring claimed the read was bounded."""
    monkeypatch.setattr(review_server, "known_stems", lambda: [])
    wire = _Wire(b'{"stem":"x"}' + b" " * 4096, declared=-1)

    wire.as_handler().do_POST()

    assert wire.status == 411, "a length that is absent, negative or unparseable must be refused"
    assert wire.rfile.tell() == 0, "and nothing may be read from the socket first"


def test_an_oversized_body_is_refused_without_being_read(tmp_path, monkeypatch):
    monkeypatch.setattr(review_server, "known_stems", lambda: [])
    wire = _Wire(b"x" * 32, declared=(1 << 20) + 1)

    wire.as_handler().do_POST()

    assert wire.status == 413
    assert wire.rfile.tell() == 0, "the refusal must come before the read, or the cap buys nothing"


def test_a_generated_token_is_stable_when_it_cannot_be_persisted(tmp_path, monkeypatch):
    """If persistence fails, resolve_token() is called fresh on every write request, so a
    new random token would be minted per request -- none matching the one printed at
    startup. Every write becomes 401 forever, including for the operator holding the logged
    token: a total, silent denial of the write API rather than a missing convenience."""
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    unwritable = str(tmp_path / "nope")
    monkeypatch.setattr(review_server, "TOKEN_DIR", unwritable)
    monkeypatch.setattr(review_server, "_GENERATED", None)

    def boom(*a, **k):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(review_server.os, "makedirs", boom)

    first = review_server.resolve_token(unwritable)
    second = review_server.resolve_token(unwritable)

    assert first and first == second, "the token must survive for the life of the process"
    assert review_server.authorised("POST", first) is True, "the token that was logged must still work"


def test_the_stem_walk_is_cached_so_an_unauthenticated_get_cannot_thrash_the_disk(tmp_path, monkeypatch):
    """GET routes are never gated, and every one of them resolved a stem by walking the
    whole media root. On a 20,000-episode library over CIFS that is a full recursive walk
    per unauthenticated request -- a denial of service that costs the caller one HTTP GET.

    Cached with a short TTL rather than forever: an episode appearing mid-session should
    still show up without a restart."""
    root = tmp_path / "lib"
    root.mkdir()
    (root / ("a" + review_server.CONF_SUFFIX)).write_text("[]")
    monkeypatch.setattr(review_server, "ROOTS", [str(root)])
    monkeypatch.setattr(review_server, "_STEMS_CACHE", None)
    walks = []
    real_walk = review_server.os.walk
    monkeypatch.setattr(review_server.os, "walk", lambda *a, **k: (walks.append(1), real_walk(*a, **k))[1])

    for _ in range(5):
        review_server.known_stems()

    assert len(walks) == 1, "five requests, one walk"


def test_the_stem_cache_expires(tmp_path, monkeypatch):
    """The counterpart: a cache that never expires means a newly generated episode is
    invisible to the reviewer until the container restarts."""
    root = tmp_path / "lib"
    root.mkdir()
    (root / ("a" + review_server.CONF_SUFFIX)).write_text("[]")
    monkeypatch.setattr(review_server, "ROOTS", [str(root)])
    monkeypatch.setattr(review_server, "_STEMS_CACHE", None)
    monkeypatch.setattr(review_server, "STEMS_TTL", 0.0)

    assert len(review_server.known_stems()) == 1
    (root / ("b" + review_server.CONF_SUFFIX)).write_text("[]")

    assert len(review_server.known_stems()) == 2, "a new episode must appear without a restart"


def test_the_token_never_lands_at_the_filesystem_root(monkeypatch):
    """os.path.dirname("/decisions") is "/", which is truthy, so an `or "/config"` fallback
    never fires and the credential would be written to /review_token."""
    assert review_server.token_dir_for("/config/decisions") == "/config"
    assert review_server.token_dir_for("/decisions") == "/config", "not the filesystem root"
    assert review_server.token_dir_for("decisions") == "/config"
    assert review_server.token_dir_for("/srv/dub/decisions") == "/srv/dub"


def test_a_symlinked_conf_outside_the_roots_is_not_in_the_allow_list(tmp_path, monkeypatch):
    """The media tree is deliberately group-writable, so anything with local write access
    could plant a symlinked conf.json whose stem then entered the allow-list -- and
    handle_apply would follow it out of the roots. Needs a pre-existing local capability, so
    it is a second line of defence rather than the first, but membership in known_stems() is
    documented as the boundary and should actually be one."""
    root = tmp_path / "lib"
    root.mkdir()
    secret = tmp_path / "elsewhere"
    secret.mkdir()
    (secret / ("evil" + review_server.CONF_SUFFIX)).write_text("[]")
    os.symlink(secret / ("evil" + review_server.CONF_SUFFIX), root / ("evil" + review_server.CONF_SUFFIX))
    (root / ("good" + review_server.CONF_SUFFIX)).write_text("[]")
    monkeypatch.setattr(review_server, "ROOTS", [str(root)])
    monkeypatch.setattr(review_server, "_STEMS_CACHE", None)

    found = review_server.known_stems()

    assert found == [str(root / "good")], "a symlink out of the roots is not an episode of this library"


def test_the_handler_has_a_socket_deadline():
    """Without one, an unauthenticated caller pins a worker thread forever.

    `BaseHTTPRequestHandler.timeout` is None by default, and
    `socketserver.StreamRequestHandler.setup()` only calls `connection.settimeout()` when it
    is not None -- so `rfile.read(n)` blocks with no deadline. The 1MB cap bounds MEMORY per
    request and nothing else: a client declaring a legal length and dripping one byte a
    minute holds a thread, before `authorised()` is ever reached, and `ThreadingHTTPServer`
    spawns those threads without a cap.

    This asserts the attribute because the attribute IS the mechanism -- setup() reads it
    off the class. It is not a source-text assertion standing in for behaviour."""
    import socketserver

    assert review_server.Handler.timeout is not None, "a None timeout means setup() never calls settimeout"
    assert 0 < review_server.Handler.timeout <= 120, "long enough for a real review POST, short enough to shed a drip"
    assert "settimeout" in __import__("inspect").getsource(socketserver.StreamRequestHandler.setup)


def test_an_offered_verdict_is_encoded_for_the_javascript_context(monkeypatch, tmp_path):
    """`html.escape` is not JavaScript escaping.

    Today `OFFERED` is a closed constant set, so nothing reachable exploits this -- the
    finding is latent, not live. It is fixed anyway because the renderer's contract is that
    it handles queue data, and the cost of being right here is one call. A quote in an
    offered value would otherwise close the JS string inside the onclick attribute."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    monkeypatch.setattr(review_server, "DEFAULT_OFFERED", ("x');alert(1);//",))
    monkeypatch.setattr(review_server, "OFFERED", {})

    page = review_server.render_page(stem)

    # Decoded the way a browser decodes an attribute value BEFORE the JS in it is parsed.
    # Asserting on the raw page is the vacuous version of this test: html.escape turns the
    # quote into &#x27;, which the HTML parser turns back into a quote, and the injection
    # fires anyway. The first draft of this test asserted exactly that and passed.
    import html as _html

    assert "onclick=" not in page, "no inline handler: the value must not reach a JS literal at all"
    # The payload appearing as attribute DATA and as button text is fine and expected -- both
    # are inert. What must hold is that it never lands inside the script block, where
    # attribute-entity decoding would hand it to the JS parser. Asserting it is absent from
    # the whole page would fail on the harmless copies and prove nothing about the JS.
    script = page[page.index("<script>") : page.index("</script>")]

    assert "alert(1)" not in _html.unescape(script), "the value must never reach the script block"
    assert 'data-v="' in page, "it travels as data, read back through dataset"


def test_decide_reports_a_failed_resolve_instead_of_claiming_success(tmp_path, monkeypatch):
    """The two writes are independent files and cannot be made atomic across them. What CAN
    be honest is the report: if the verdict is durable but the queue entry did not clear,
    saying `saved: true` tells the reviewer the line is settled when their queue will still
    show it. The gate itself is unaffected -- mux trusts the durable verdict, not the flag
    -- so this is a reporting fix, not a correctness one."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(review_server, "show_for", lambda p: "Show")
    monkeypatch.setattr(unresolved, "resolve", lambda *a, **k: False)

    res = review_server.handle_decide(stem, 0, "reject")

    assert res.get("saved") is True, "the verdict IS durable and must be reported as such"
    assert res.get("queue_cleared") is False, "but the queue entry did not clear, and that must not be hidden"
    assert "warning" in res


def test_concurrent_requests_are_bounded(monkeypatch):
    """[F-4]. The 30s deadline bounds how LONG one unauthenticated request holds a worker;
    it does not bound HOW MANY. `ThreadingHTTPServer` spawns a daemon thread per connection
    with no cap, so a LAN client can still open many at once -- each now dying after 30s
    instead of never, which turns an indefinite pin into a sustained churn.

    Refused promptly rather than queued: an unbounded queue is the same exhaustion with an
    extra step. Asserted without opening a socket, matching the rest of this file."""
    assert review_server.MAX_CONCURRENT > 0
    assert issubclass(review_server.BoundedHTTPServer, review_server.http.server.ThreadingHTTPServer)

    srv: Any = review_server.BoundedHTTPServer.__new__(review_server.BoundedHTTPServer)
    srv._slots = review_server.threading.Semaphore(1)
    handled, refused = [], []
    monkeypatch.setattr(
        review_server.http.server.ThreadingHTTPServer,
        "process_request",
        lambda self, req, addr: handled.append(addr),
    )
    srv.close_request = lambda req: refused.append(req)

    srv.process_request("r1", ("10.0.0.1", 1))  # takes the only slot, never released here
    srv.process_request("r2", ("10.0.0.2", 2))

    assert handled == [("10.0.0.1", 1)], "the first is served"
    assert refused == ["r2"], "the second is closed immediately, not queued behind it"


def test_the_slot_is_returned_after_a_request(monkeypatch):
    """A semaphore that is never released is a server that stops answering after N requests
    -- a worse outage than the one being prevented."""
    srv: Any = review_server.BoundedHTTPServer.__new__(review_server.BoundedHTTPServer)
    srv._slots = review_server.threading.Semaphore(1)
    srv.close_request = lambda req: None
    monkeypatch.setattr(review_server.http.server.ThreadingHTTPServer, "process_request", lambda self, req, addr: None)
    monkeypatch.setattr(review_server.http.server.ThreadingHTTPServer, "process_request_thread", lambda self, req, addr: None)

    # Through the REAL pair: process_request acquires, process_request_thread releases.
    # Calling only the release half never takes a slot, so the semaphore stays full and the
    # assertion below passes whether or not the release exists -- which is how the first
    # draft of this test let a "never release the slot" mutation through.
    for _ in range(3):
        srv.process_request("req", ("10.0.0.1", 1))
        srv.process_request_thread("req", ("10.0.0.1", 1))

    assert srv._slots.acquire(blocking=False), "the slot must come back, or the server dies after MAX_CONCURRENT requests"


def test_serve_uses_the_bounded_server(monkeypatch, tmp_path):
    """serve() constructing a plain ThreadingHTTPServer would leave the cap unreachable in
    production while every unit test above still passed."""
    monkeypatch.setenv("REVIEW_TOKEN", "t")
    built = {}

    class _Fake:
        def __init__(self, addr, handler):
            built["addr"], built["handler"] = addr, handler

        def serve_forever(self):
            built["served"] = True

    monkeypatch.setattr(review_server, "BoundedHTTPServer", _Fake)
    review_server.serve(port=1)

    assert built.get("served") is True, "serve() must construct BoundedHTTPServer, not the unbounded one"
    assert built["handler"] is review_server.Handler


def test_the_page_offers_a_way_to_apply_decisions_to_an_episode(tmp_path, monkeypatch):
    """Recording a verdict and APPLYING it are two different things for an episode that is
    already muxed: the verdict changes what the next repair run ships, and the write-back is
    what re-opens an episode that has already shipped. `/api/apply` existed and nothing in
    the page called it, so the write-back was reachable only by hand-crafting a POST.

    The button says what it does. It rewrites the subtitle and drops the stamp, which costs
    a re-mux of a multi-GB file -- not something to trigger by accident."""
    stem = _episode(tmp_path)
    monkeypatch.setattr(review_server, "known_stems", lambda: [stem])

    page = review_server.render_page(stem)

    assert 'id="apply"' in page, "an episode page needs a control that applies its decisions"
    assert "/api/apply" in page, "wired to the route, not just present"
    assert "re-mux" in page.lower(), "and it says what it costs before you press it"
