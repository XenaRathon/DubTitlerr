"""Phase 1 of the glossary-stage bake-off: `tools/glossary_bakeoff.py build-set`.

Everything here runs on small synthetic fixtures built in tmp_path -- the real glossary snapshot is
git-excluded and must never be copied into a test. The acceptance criterion is (a): the candidate
list in items.jsonl is exactly what the PRODUCTION `glossary_verify.candidates` returns."""

import json
import re
import time

import pytest

import acquire_cache
import glossary_verify as gv
import tools.glossary_bakeoff as gb

ALPHA = {
    "show": "Alpha Show",
    "_curated": True,
    "names": ["Zoro", "Luffy", "Nami", "Sanji", "Chopper"],
    "phrases": ["Straw Hat Pirates"],
    "verified": ["Nami"],
    "flagged": {"Luffy": "no-match", "Chopper": {"reason": "respelling-needs-review", "canonical": "Chopperman"}},
    "hard_fixes": {"zorro": "Zoro"},
}
ALPHA_TITLES = ["Roronoa Zoro", "Zoro", "Monkey D. Luffy", "Luffy", "Nami", "Straw Hat Pirates", "Chopperman", "Unrelated Title"]
BETA = {"show": "Beta Show", "names": ["Kaido", "qqqzzz"], "phrases": []}  # not curated
BETA_TITLES = ["Kaidou", "Kaido"]


def _put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def _wiki(wiki_dir, show, titles):
    cache = {"api": "https://x/api.php", "fetched_at": 1, "titles": titles}
    _put(wiki_dir / (re.sub(r"[^A-Za-z0-9]+", "_", show) + ".json"), cache)


@pytest.fixture
def data(tmp_path):
    g, w = tmp_path / "glossaries", tmp_path / "wiki_cache"
    _put(g / "Alpha Show.json", ALPHA)
    _put(g / "Alpha Show.lastrun.json", {"junk": True})  # ignored
    _put(g / "Alpha Show.acquire-cache.json", {"Zoroo": {"Zoro": {"same_entity": True, "confidence": "high"}}, "Bad": "notadict"})
    _put(g / "Beta Show.json", BETA)
    _put(g / "Gamma Show.json", {"show": "Gamma Show", "names": ["Foo"], "phrases": []})  # no wiki cache
    _put(g / "Delta Show.json", "{ this is not json")  # malformed
    _put(g / "Epsilon Show.json", {"show": "Epsilon Show", "names": ["Bar"], "phrases": []})
    _wiki(w, "Alpha Show", ALPHA_TITLES)
    _wiki(w, "Beta Show", BETA_TITLES)
    _wiki(w, "Epsilon Show", [])  # empty titles
    return g, w


def _build(tmp_path, g, w, *extra, name="items.jsonl"):
    out = tmp_path / name
    code = gb.main(["build-set", "--glossaries", str(g), "--wiki-cache", str(w), "--out", str(out), *extra])
    items = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()] if out.exists() else []
    return code, items, out


def _verify(items, show, term):
    return next(i for i in items if i["stage"] == "verify" and i["show"] == show and i["term"] == term)


def test_candidate_lists_equal_the_production_function(tmp_path, data, capsys):
    g, w = data
    code, items, _ = _build(tmp_path, g, w)
    assert code == 0
    checked = 0
    for show, titles in (("Alpha Show", ALPHA_TITLES), ("Beta Show", BETA_TITLES)):
        for it in (i for i in items if i["stage"] == "verify" and i["show"] == show):
            assert [c["title"] for c in it["candidates"]] == gv.candidates(it["term"], titles)
            assert all(0.62 <= c["score"] <= 1 for c in it["candidates"])
            assert [c["score"] for c in it["candidates"]] == sorted((c["score"] for c in it["candidates"]), reverse=True)
            checked += 1
    assert checked == 8  # 6 Alpha terms + 2 Beta terms


def test_a_term_with_no_candidates_is_kept_as_a_no_call_control(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    it = _verify(items, "Beta Show", "qqqzzz")
    assert it["candidates"] == [] and it["no_call"] is True and it["gold"] is None
    assert _verify(items, "Beta Show", "Kaido")["no_call"] is False


def test_items_say_where_the_term_came_from(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    luffy = _verify(items, "Alpha Show", "Luffy")
    assert luffy["list"] == "names" and luffy["flagged"] == "no-match" and luffy["verified"] is False
    assert _verify(items, "Alpha Show", "Nami")["verified"] is True  # a verify --force would still send it
    assert _verify(items, "Alpha Show", "Straw Hat Pirates")["list"] == "phrases"
    assert _verify(items, "Alpha Show", "Chopper")["flagged"]["reason"] == "respelling-needs-review"


def test_curated_show_gold_only_when_the_canonical_is_a_candidate(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    zoro = _verify(items, "Alpha Show", "Zoro")
    assert zoro["gold"] == "Zoro" and zoro["gold_source"] == "curated"  # the exact term wins over "Roronoa Zoro"
    luffy = _verify(items, "Alpha Show", "Luffy")
    assert luffy["gold"] == "Luffy"  # "Monkey D. Luffy" is not a curated name
    sanji = _verify(items, "Alpha Show", "Sanji")
    assert sanji["candidates"] == [] and sanji["gold"] is None  # no candidate at all
    chopper = _verify(items, "Alpha Show", "Chopper")
    assert [c["title"] for c in chopper["candidates"]] == ["Chopperman"]
    assert chopper["gold"] is None  # candidates exist but none is a curated canonical
    assert "gold_source" not in chopper


def test_a_non_curated_show_never_gets_gold(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    beta = [i for i in items if i["stage"] == "verify" and i["show"] == "Beta Show"]
    assert beta and all(i["gold"] is None and "gold_source" not in i for i in beta)


def test_acquire_pairs_carry_the_historical_verdict_and_no_quotes(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    pairs = [i for i in items if i["stage"] == "acquire"]
    assert len(pairs) == 1  # the malformed pair entry is skipped
    p = pairs[0]
    assert (p["show"], p["variant"], p["canonical"]) == ("Alpha Show", "Zoroo", "Zoro")
    assert p["historical"] == acquire_cache.escalation_for(acquire_cache.load(str(g / "Alpha Show.json")), "Zoroo", "Zoro")
    assert p["historical"] == {"same_entity": True, "confidence": "high"} and p["quotes"] is None


def test_a_rerun_is_byte_identical(tmp_path, data):
    g, w = data
    _, _, first = _build(tmp_path, g, w, name="a.jsonl")
    _, _, second = _build(tmp_path, g, w, name="b.jsonl")
    assert first.read_bytes() == second.read_bytes() and first.read_bytes()
    assert first.read_bytes().endswith(b"\n")


def test_unicode_is_written_unescaped(tmp_path):
    g, w = tmp_path / "g", tmp_path / "w"
    _put(g / "Uni.json", {"show": "Uni", "names": ["Ōtsutsuki"], "phrases": []})
    _wiki(w, "Uni", ["Ōtsutsuki Clan"])
    _, items, out = _build(tmp_path, g, w)
    assert "Ōtsutsuki" in out.read_text(encoding="utf-8") and items[0]["candidates"]


def test_malformed_and_empty_inputs_are_reported_and_skipped(tmp_path, data, capsys):
    g, w = data
    code, items, _ = _build(tmp_path, g, w)
    out = capsys.readouterr().out
    assert code == 0
    assert "Delta Show" in out and "malformed" in out
    assert "Epsilon Show" in out and "empty" in out
    assert not [i for i in items if i["show"] in ("Delta Show", "Epsilon Show")]


def test_a_show_with_no_wiki_cache_makes_no_verify_items_and_is_listed(tmp_path, data, capsys):
    g, w = data
    _, items, _ = _build(tmp_path, g, w)
    out = capsys.readouterr().out
    assert not [i for i in items if i["show"] == "Gamma Show"]
    assert "Gamma Show" in out and "no wiki cache" in out


def test_show_filter_keeps_only_matching_shows(tmp_path, data):
    g, w = data
    _, items, _ = _build(tmp_path, g, w, "--show", "beta")
    assert items and {i["show"] for i in items} == {"Beta Show"}
    _, items, _ = _build(tmp_path, g, w, "--show", "beta", "alpha", name="two.jsonl")
    assert {i["show"] for i in items} == {"Alpha Show", "Beta Show"}


def test_the_summary_has_per_show_counts_and_totals(tmp_path, data, capsys):
    g, w = data
    _build(tmp_path, g, w)
    out = capsys.readouterr().out
    alpha = next(line for line in out.splitlines() if line.startswith("Alpha Show"))
    assert "6" in alpha and "5" in alpha  # 6 verify items, 5 with candidates
    assert "TOTAL" in out and "skipped" in out.lower()


def test_building_the_set_makes_no_network_call(tmp_path, data, monkeypatch):
    import http.client
    import socket
    import urllib.request

    def no_net(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(urllib.request, "urlopen", no_net)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", no_net)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(gv, "_http_json", no_net)
    g, w = data
    code, items, _ = _build(tmp_path, g, w)
    assert code == 0 and items


def test_the_cache_file_mapping_is_the_one_fetch_titles_reads(tmp_path, monkeypatch):
    """fetch_titles has no separate mapping function, so the filename rule is mirrored; prove it by letting the
    production reader find the file the mirrored path points at."""
    show = "Weird Show (2020) {tvdb-1}"
    w = tmp_path / "w"
    w.mkdir()
    path = gb.wiki_cache_path(str(w), show)
    _put(type(w)(path), {"api": "https://x/api.php", "fetched_at": time.time(), "titles": ["T1", "T2"]})
    monkeypatch.setattr(gv, "CACHE_DIR", str(w))
    monkeypatch.setattr(gv, "_http_json", lambda url: pytest.fail("must read the cache"))
    assert gv.fetch_titles("https://x/api.php", show) == ["T1", "T2"]


def test_unknown_flags_and_missing_directories_exit_2(tmp_path, data):
    g, w = data
    with pytest.raises(SystemExit) as e:
        gb.main(["build-set", "--glossaries", str(g), "--wiki-cache", str(w), "--out", str(tmp_path / "o"), "--bogus"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        gb.main(["build-set", "--glossaries", str(tmp_path / "nope"), "--wiki-cache", str(w), "--out", str(tmp_path / "o")])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        gb.main([])  # a subcommand is required
    assert e.value.code == 2
