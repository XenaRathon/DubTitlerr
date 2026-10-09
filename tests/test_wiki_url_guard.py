"""Wiki fetches only ever speak https (http only with WIKI_ALLOW_HTTP=1, for tests): a glossary's `wiki` value or an override
must not reach urlopen as file://, ftp:// or javascript:. No network: urlopen is a stub."""

import io
import json
import urllib.request

import pytest

import glossary_verify as gv


@pytest.fixture
def urlopen(monkeypatch):
    calls = []

    class Resp(io.BytesIO):
        def __init__(self, url):
            super().__init__(json.dumps({"query": {}}).encode())
            self._url = url

        def geturl(self):
            return self._url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        calls.append(req.full_url)
        return Resp(req.full_url)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.delenv("WIKI_ALLOW_HTTP", raising=False)
    return calls


BAD = [
    "file:///etc/passwd",
    "FILE:///etc/passwd",
    "File:///etc/passwd",
    "ftp://x.fandom.com/api.php",
    "javascript:alert(1)",
    "data:text/plain,{}",
    "//x.fandom.com/api.php",
    "https://user:pw@x.fandom.com/api.php",
    "https://x.fandom.com@evil.example/api.php",
    "https:///api.php",
    "",
    "x.fandom.com/api.php",
]


@pytest.mark.parametrize("url", BAD)
def test_a_bad_url_never_reaches_urlopen(urlopen, url):
    with pytest.raises(ValueError):
        gv._http_json(url)
    assert urlopen == []


def test_http_is_refused_without_the_test_switch_and_allowed_with_it(urlopen, monkeypatch):
    with pytest.raises(ValueError):
        gv._http_json("http://x.fandom.com/api.php?action=query")
    assert urlopen == []
    monkeypatch.setenv("WIKI_ALLOW_HTTP", "1")
    assert gv._http_json("http://127.0.0.1:1/api.php?x=1") == {"query": {}}
    assert urlopen == ["http://127.0.0.1:1/api.php?x=1"]


def test_https_in_any_case_is_fine(urlopen):
    assert gv._http_json("HTTPS://x.fandom.com/api.php?x=1") == {"query": {}}
    assert gv._http_json("https://x.fandom.com/api.php?x=1") == {"query": {}}
    assert len(urlopen) == 2


def test_a_redirect_to_a_scheme_that_is_not_allowed_is_refused(urlopen, monkeypatch):
    class Redirected(io.BytesIO):
        def geturl(self):
            return "ftp://elsewhere.example/api.php"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: Redirected(b"{}"))
    with pytest.raises(ValueError):
        gv._http_json("https://x.fandom.com/api.php")


@pytest.mark.parametrize("url", BAD)
def test_normalize_api_rejects_what_is_not_http_or_https(url):
    assert gv.normalize_api(url) is None


def test_normalize_api_still_reduces_good_urls():
    assert gv.normalize_api("https://onepiece.fandom.com/wiki/Spandam") == "https://onepiece.fandom.com/api.php"
    assert gv.normalize_api("HTTPS://onepiece.fandom.com/wiki/Spandam") == "https://onepiece.fandom.com/api.php"
    assert gv.normalize_api("http://127.0.0.1:8000/anything") == "http://127.0.0.1:8000/api.php"


@pytest.mark.parametrize("override", ["file:///etc/passwd", "ftp://x/api.php", "javascript:1", "FILE:///x"])
def test_resolve_wiki_returns_none_for_a_bad_override_and_asks_nothing(urlopen, override):
    assert gv.resolve_wiki("Show", override) is None
    assert urlopen == []


def test_callers_that_swallow_fetch_errors_degrade_to_empty(urlopen, monkeypatch, tmp_path):
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path))
    assert gv.fetch_titles("file:///etc/passwd", "ShowX") == []
    assert gv.arc_page_links_checked("file:///etc/passwd", "Arc") == (set(), False)


def test_a_glossary_with_a_file_wiki_is_not_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "wiki": "file:///etc/passwd"}))
    rep = gv.verify(str(path))
    assert "wiki unresolved" in rep["note"]
