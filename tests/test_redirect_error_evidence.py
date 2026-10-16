"""Phase 29 F10: a MediaWiki API error is never complete redirect evidence.

Sol's probe: the redirect query answered {"error": {"code": "ratelimited"}} with HTTP 200 and no `query` object. redirect_targets
read the missing list as an empty (valid) result, so the scope stayed complete, tag_arcs wrote {"complete": true, "redirects":
true} and cached the title set, and the arc gate turned on over it."""

import json

import glossary_verify as gv
import wiki_scope

CFG = {"rung": "season_page", "wiki": "https://example.fandom.com/api.php"}


def fake_http(redirect_reply):
    def fake(url):
        if "action=parse" in url:
            return {"parse": {"links": [{"ns": 0, "*": "Alias Name"}], "wikitext": {"*": ""}}}
        return redirect_reply

    return fake


ERROR = {"error": {"code": "ratelimited", "info": "try later"}}


def test_an_error_reply_leaves_redirect_resolution_incomplete(monkeypatch):
    monkeypatch.setattr(gv, "_http_json", lambda url: ERROR)
    assert gv.redirect_targets("https://x/api.php", {"A", "B"}) == ({}, False)
    for odd in ({"error": "x", "query": {"redirects": []}}, {"query": None}, {"query": []}, [], "oops", None):
        monkeypatch.setattr(gv, "_http_json", lambda url, odd=odd: odd)
        assert gv.redirect_targets("https://x/api.php", {"A"}) == ({}, False), odd


def test_a_valid_reply_with_no_redirects_is_still_complete(monkeypatch):
    monkeypatch.setattr(gv, "_http_json", lambda url: {"batchcomplete": "", "query": {"pages": {"1": {"title": "A"}}}})
    assert gv.redirect_targets("https://x/api.php", {"A"}) == ({}, True)
    monkeypatch.setattr(gv, "_http_json", lambda url: {"query": {"redirects": [{"from": "Kirito", "to": "Kirigaya Kazuto"}]}})
    assert gv.redirect_targets("https://x/api.php", {"Kirito"}) == ({"Kirito": "Kirigaya Kazuto"}, True)


def test_wiki_scope_is_incomplete_when_the_redirect_step_errors():
    res = wiki_scope.resolve_scope(CFG, 1, [1], http=fake_http(ERROR))
    assert res.complete is False and any("redirect" in n for n in res.notes)


def test_an_incomplete_scope_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "_http_json", fake_http(ERROR))
    titles, how = gv.fetch_scope_cached(CFG, {"key": "scope:season_page:1", "season": 1, "episodes": [1]}, "S")
    assert how == "incomplete" and titles == set()
    assert not list((tmp_path / "cache").glob("*")), "nothing cached from an incomplete scope"


def test_tag_arcs_does_not_claim_whole_redirect_coverage(tmp_path, monkeypatch):
    video = tmp_path / "S01E01.mkv"
    video.write_bytes(b"fake media metadata input")
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Alias"], "phrases": [], "wiki_scope": CFG}))
    monkeypatch.setenv("ARC_MIN_TITLES", "1")
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "_http_json", fake_http(ERROR))
    gv.tag_arcs(str(path), str(tmp_path))
    saved = json.loads(path.read_text())
    cov = saved.get("arc_coverage", {}).get("scope:season_page:1")
    assert cov is None or (cov.get("complete") is not True and cov.get("redirects") is not True)
    assert gv.arc_universe(saved) is None, "the arc gate does not turn on over incomplete evidence"


def test_clipped_redirect_evidence_is_incomplete(monkeypatch):
    """Sol's mutation witness (redirect-cap-claims-complete): more titles than the chunk cap reads cannot be reported complete."""
    monkeypatch.setattr(gv, "REDIRECT_MAX_CHUNKS", 1)
    monkeypatch.setattr(gv, "_http_json", lambda url: {"query": {"redirects": []}})
    assert gv.redirect_targets("https://x/api.php", {f"Name {n}" for n in range(51)})[1] is False
    assert gv.redirect_targets("https://x/api.php", {f"Name {n}" for n in range(50)})[1] is True
