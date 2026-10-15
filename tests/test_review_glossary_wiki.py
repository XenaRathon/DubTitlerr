"""The per-show wiki override on the glossary editor backend: GET/POST /api/glossary "wiki" and POST
/api/glossary/wiki-test. GLOSSARY_DIR is always a tmp_path; _http_json is always mocked (no network)."""

import hashlib
import json

import pytest

import decisions
import glossary_verify
import review_auth
import review_glossary
import review_server as rs

SHOW = "Yu-Gi-Oh"
RAW = {
    "show": SHOW,
    "initial_prompt": "This is Yu-Gi-Oh.",
    "names": ["Yugi"],
    "phrases": [],
    "hard_fixes": {},
    "verified": {"Yugi": {"source": "wiki"}},
    "flagged": [{"term": "Yugi", "why": "alt"}],
    "_curated": True,
}


@pytest.fixture
def gdir(tmp_path, monkeypatch):
    d = tmp_path / "glossaries"
    d.mkdir()
    monkeypatch.setattr(decisions, "GLOSSARY_DIR", str(d))
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "0")
    return d


def _put(gdir, data=None):
    p = gdir / f"{SHOW}.json"
    p.write_text(json.dumps(RAW if data is None else data, indent=2) + "\n")
    return p


def _post(p, **kw):
    body = {"show": SHOW, "expected_version": hashlib.sha256(p.read_bytes()).hexdigest()}
    body.update(kw)
    return review_glossary.handle("POST", "/api/glossary", body, role="admin")


def test_get_includes_wiki_or_empty(gdir):
    _put(gdir)
    assert review_glossary.handle("GET", "/api/glossary", {"show": SHOW})[1]["wiki"] == ""
    _put(gdir, {**RAW, "wiki": "https://yugioh.fandom.com"})
    assert review_glossary.handle("GET", "/api/glossary", {"show": SHOW})[1]["wiki"] == "https://yugioh.fandom.com"


def test_wiki_only_post_sets_trimmed_value_as_typed_and_keeps_other_keys(gdir):
    p = _put(gdir)
    status, payload = _post(p, wiki="  https://yugioh.fandom.com/wiki/Main  ")
    assert status == 200 and payload["ok"] is True
    disk = json.loads(p.read_text())
    assert disk["wiki"] == "https://yugioh.fandom.com/wiki/Main"
    assert {k: v for k, v in disk.items() if k != "wiki"} == RAW
    assert payload["version"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert list(gdir.glob("*.bak-*"))


def test_empty_wiki_removes_the_key(gdir):
    p = _put(gdir, {**RAW, "wiki": "https://yugioh.fandom.com"})
    assert _post(p, wiki="")[0] == 200
    assert "wiki" not in json.loads(p.read_text())


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "yugioh", "https://user:pw@x.com", "x" * 301, "https://a.com/​"])
def test_invalid_wiki_is_400_and_file_unchanged(gdir, bad):
    p = _put(gdir)
    before = p.read_bytes()
    status, payload = _post(p, wiki=bad)
    assert status == 400 and payload["error"]
    assert p.read_bytes() == before
    assert not list(gdir.glob("*.bak-*"))


def test_non_string_wiki_is_400(gdir):
    p = _put(gdir)
    assert _post(p, wiki=5)[0] == 400


def test_stale_version_refused_for_wiki_write(gdir):
    p = _put(gdir)
    before = p.read_bytes()
    status, _ = _post(p, wiki="https://yugioh.fandom.com", expected_version="0" * 64)
    assert status == 409 and p.read_bytes() == before


def test_wiki_edit_is_logged_like_term_edits(gdir, monkeypatch):
    p = _put(gdir)
    lines = []
    monkeypatch.setattr(review_glossary, "log", lines.append)
    _post(p, wiki="https://yugioh.fandom.com")
    assert any("glossary edit:" in s and "key=wiki" in s and "https://yugioh.fandom.com" in s for s in lines)


def test_term_op_still_needs_op_and_key_without_wiki(gdir):
    p = _put(gdir)
    assert _post(p)[0] == 400  # neither a term op nor a wiki field


def test_wiki_and_term_op_together_apply_both(gdir):
    p = _put(gdir)
    assert _post(p, wiki="https://yugioh.fandom.com", op="add", key="names", term="Kaiba")[0] == 200
    disk = json.loads(p.read_text())
    assert disk["wiki"] == "https://yugioh.fandom.com" and disk["names"] == ["Yugi", "Kaiba"]


def test_wiki_test_ok(monkeypatch):
    seen = []

    def fake(url):
        seen.append(url)
        return {"query": {"general": {"sitename": "Yu-Gi-Oh! Wiki"}}}

    monkeypatch.setattr(glossary_verify, "_http_json", fake)
    status, payload = review_glossary.wiki_test({"url": "https://yugioh.fandom.com/wiki/Main"})
    assert (status, payload) == (200, {"ok": True, "api": "https://yugioh.fandom.com/api.php", "sitename": "Yu-Gi-Oh! Wiki"})
    assert seen == ["https://yugioh.fandom.com/api.php?action=query&meta=siteinfo&format=json"]


def test_wiki_test_failure_is_200_ok_false(monkeypatch):
    def boom(url):
        raise OSError("connection refused")

    monkeypatch.setattr(glossary_verify, "_http_json", boom)
    status, payload = review_glossary.wiki_test({"url": "https://nope.example"})
    assert status == 200 and payload["ok"] is False and payload["api"] == "https://nope.example/api.php"
    assert "connection refused" in payload["error"]


def test_wiki_test_without_siteinfo_is_ok_false(monkeypatch):
    monkeypatch.setattr(glossary_verify, "_http_json", lambda url: {"error": {"code": "x"}})
    status, payload = review_glossary.wiki_test({"url": "https://nope.example"})
    assert status == 200 and payload["ok"] is False and payload["error"]


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "yugioh", "", None, 5])
def test_wiki_test_invalid_url_is_400(monkeypatch, bad):
    monkeypatch.setattr(glossary_verify, "_http_json", lambda url: pytest.fail("must not fetch"))
    assert review_glossary.wiki_test({"url": bad})[0] == 400


def test_wiki_test_route_is_admin_json_only(tmp_path, monkeypatch):
    assert ("POST", "/api/glossary/wiki-test") in rs._JSON_REQUIRED
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    review_auth.create_user("alice", "user", "user-password-10ch")
    sid = review_auth.sessions().create("alice", False)
    headers = {"Cookie": f"dubtitlerr_session={sid}", "X-DubTitlerr-Request": "1"}
    monkeypatch.setattr(glossary_verify, "_http_json", lambda url: pytest.fail("a user must not trigger a fetch"))
    status, payload, _ = rs.route_full("POST", "/api/glossary/wiki-test", {"url": "https://a.com"}, None, headers=headers)
    assert (status, payload) == (403, {"error": "admin only"})


def test_user_role_wiki_write_is_403_and_file_unchanged(gdir):
    p = _put(gdir)
    before = p.read_bytes()
    body = {"show": SHOW, "expected_version": hashlib.sha256(before).hexdigest(), "wiki": "https://yugioh.fandom.com"}
    status, payload = review_glossary.handle("POST", "/api/glossary", body, role="user")
    assert status == 403 and payload == {"error": "admin only"}
    assert p.read_bytes() == before and not list(gdir.glob("*.bak-*"))
    # the default is the closed one
    assert review_glossary.handle("POST", "/api/glossary", body)[0] == 403


def test_user_role_term_edit_still_works(gdir):
    p = _put(gdir)
    body = {
        "show": SHOW,
        "expected_version": hashlib.sha256(p.read_bytes()).hexdigest(),
        "op": "add",
        "key": "names",
        "term": "Kaiba",
    }
    assert review_glossary.handle("POST", "/api/glossary", body, role="user")[0] == 200


@pytest.mark.parametrize(
    "bad",
    [
        "https://localhost/",
        "https://LOCALHOST",
        "https://127.0.0.1/",
        "https://10.0.0.5/",
        "https://192.168.1.1/",
        "https://172.16.0.1/",
        "https://169.254.169.254/latest",
        "https://0.0.0.0/",
        "https://224.0.0.1/",
        "https://240.0.0.1/",
        "https://[::1]/",
        "https://[fe80::1]/",
        "https://[fc00::1]/",
        "https://[::ffff:127.0.0.1]/",
    ],
)
def test_internal_hosts_are_refused_everywhere(gdir, monkeypatch, bad):
    assert glossary_verify._wiki_url_problem(bad, ("https", "http"))
    assert glossary_verify.normalize_api(bad) is None
    p = _put(gdir)
    assert _post(p, wiki=bad)[0] == 400
    monkeypatch.setattr(glossary_verify, "_http_json", lambda url: pytest.fail("must not fetch"))
    assert review_glossary.wiki_test({"url": bad})[0] == 400


def test_public_hosts_still_pass():
    for ok in ("https://yugioh.fandom.com", "https://1.1.1.1/", "https://[2606:4700::1111]/", "https://localhost.example.com"):
        assert glossary_verify._wiki_url_problem(ok) == "", ok


def test_redirect_to_loopback_is_refused():
    h = glossary_verify._GuardedRedirect()
    with pytest.raises(ValueError):
        h.redirect_request(None, None, 302, "Found", {}, "https://127.0.0.1/api.php")


def test_http_wiki_needs_the_env_flag(gdir, monkeypatch):
    p = _put(gdir)
    monkeypatch.delenv("WIKI_ALLOW_HTTP", raising=False)
    status, _ = _post(p, wiki="http://yugioh.example.com")
    assert status == 400 and "wiki" not in json.loads(p.read_text())
    monkeypatch.setenv("WIKI_ALLOW_HTTP", "1")
    assert _post(p, wiki="http://yugioh.example.com")[0] == 200


def test_audit_line_names_the_operator(gdir, monkeypatch):
    p = _put(gdir)
    lines = []
    monkeypatch.setattr(review_glossary, "log", lines.append)
    body = {"show": SHOW, "expected_version": hashlib.sha256(p.read_bytes()).hexdigest(), "wiki": "https://a.example.com"}
    review_glossary.handle("POST", "/api/glossary", body, operator="session:alice", role="admin")
    assert any("operator=session:alice" in s and "key=wiki" in s for s in lines)


def test_route_passes_the_session_identity_and_role(gdir, tmp_path, monkeypatch):
    p = _put(gdir)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(review_auth, "SCRYPT_N", 2**4)
    review_auth.create_user("alice", "user", "user-password-10ch")
    review_auth.create_user("root", "admin", "admin-password-10ch")
    lines = []
    monkeypatch.setattr(review_glossary, "log", lines.append)
    ver = hashlib.sha256(p.read_bytes()).hexdigest()
    for name, expect in (("alice", 403), ("root", 200)):
        sid = review_auth.sessions().create(name, False)
        headers = {"Cookie": f"dubtitlerr_session={sid}", "X-DubTitlerr-Request": "1"}
        body = {"show": SHOW, "expected_version": ver, "wiki": "https://a.example.com"}
        assert rs.route_full("POST", "/api/glossary", body, None, headers=headers)[0] == expect
    assert any("operator=session:root" in s for s in lines)


@pytest.mark.parametrize(
    "bad",
    [
        "https://2130706433",
        "https://127.1",
        "https://0177.0.0.1",
        "https://0x7f000001",
        "https://100.64.0.1",
        "https://[::ffff:100.64.0.1]",
        "https://[::ffff:7f00:1]",
    ],
)
def test_legacy_ipv4_forms_and_cgnat_are_refused(bad):
    assert glossary_verify._wiki_url_problem(bad, ("https", "http")), bad


def test_real_hostnames_with_digits_still_pass():
    for ok in ("https://yugioh.fandom.com", "https://3dsmax.fandom.com", "https://0x.example.com", "https://8.8.8.8"):
        assert glossary_verify._wiki_url_problem(ok) == "", ok


def test_refusal_text_says_https(gdir):
    p = _put(gdir)
    err = _post(p, wiki="yugioh")[1]["error"]
    assert "https" in err and "WIKI_ALLOW_HTTP" in err
