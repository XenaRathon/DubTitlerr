"""wiki_scope wired into tag_arcs: shows without season.nfo arc names get a stored spelling universe.

The wiki is an injected function behind glossary_verify._http_json; the library is a tmp tree of SxxExx files."""

import json
import os
import urllib.parse as up

import pytest

import glossary_acquire as ga  # noqa: F401  (the glossary save helper lives here)
import glossary_verify as gv

NARUTO = "https://naruto.fandom.com/api.php"
FIXTURE = open(os.path.join(os.path.dirname(__file__), "fixtures", "plot_of_naruto.wikitext"), encoding="utf-8").read()


class Wiki:
    """Plot of Naruto from the real fixture, arc pages with fixed links, allpages for whole-wiki, no redirects."""

    def __init__(self):
        self.urls, self.fail = [], False
        self.allpages = ["Naruto Uzumaki", "Sakura Haruno", "Konoha", "Main Page", "Chapter 1"]

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("wiki down")
        if "redirects=1" in url:
            return {"query": {"redirects": []}}
        if "list=allpages" in url:
            return {"query": {"allpages": [{"title": t} for t in self.allpages]}}
        page = up.unquote(url.split("page=")[1].split("&")[0])
        if page == "Plot of Naruto":
            return {"parse": {"wikitext": {"*": FIXTURE}}}
        return {"parse": {"wikitext": {"*": f"[[Naruto Uzumaki]] [[Sakura Haruno]] [[Hero of {page}]]"}}}

    def pages(self):
        decoded = [up.unquote(u.split("page=")[1].split("&")[0]) for u in self.urls if "page=" in u]
        return [p for p in decoded if p != "Plot of Naruto"]


def library(tmp_path, seasons, nfo=None):
    """seasons: {season number: [episode numbers]}; nfo: {season number: arc title}."""
    show = tmp_path / "Naruto"
    for s, eps in seasons.items():
        d = show / f"Season {s:02d}"
        d.mkdir(parents=True)
        for e in eps:
            (d / f"Naruto - S{s:02d}E{e:02d} - Title.mkv").write_bytes(b"")
        if nfo and s in nfo:
            (d / "season.nfo").write_text(f"<season><title>{nfo[s]}</title></season>")
    return show


def gloss(tmp_path, scope, **extra):
    path = tmp_path / "Naruto.json"
    path.write_text(
        json.dumps({"show": "Naruto", "names": ["Naruto Uzumaki", "Konoha"], "phrases": [], "wiki_scope": scope, **extra})
    )
    return path


@pytest.fixture
def wiki(monkeypatch, tmp_path):
    w = Wiki()
    monkeypatch.setattr(gv, "_http_json", w)
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("ARC_MIN_TITLES", "1")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: pytest.fail("a scope needs no season.nfo arc lookup"))
    return w


ARC_INDEX = {"rung": "arc_index", "wiki": NARUTO, "index_page": "Plot of Naruto", "part": "Part I"}


def test_each_season_gets_its_own_namespaced_scope(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2, 3], 2: [20, 21]})
    path = gloss(tmp_path, ARC_INDEX)
    rep = gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert set(saved["arc_titles"]) == {"scope:arc_index:1", "scope:arc_index:2"}
    assert sorted(wiki.pages()) == ["Chūnin Exams (Arc)", "Prologue — Land of Waves"]
    assert "Hero of Prologue — Land of Waves" in saved["arc_titles"]["scope:arc_index:1"]
    assert saved["arc_coverage"]["scope:arc_index:1"] == {
        "titles": len(saved["arc_titles"]["scope:arc_index:1"]),
        "kind": "scope",
        "rung": "arc_index",
        "complete": True,
        "redirects": True,
    }  # fmt: skip
    assert "arc_titles_missing" not in saved and rep["scopes"] == 2 and rep["scope_fetched"] == 2


def test_an_incomplete_scope_stores_nothing_and_is_missing(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2], 2: [999]})  # episode 999 is in no row
    path = gloss(tmp_path, ARC_INDEX)
    rep = gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert set(saved["arc_titles"]) == {"scope:arc_index:1"} and saved["arc_titles_missing"] == ["scope:arc_index:2"]
    assert rep["scope_incomplete"] == 1


def test_a_wiki_failure_changes_nothing_but_the_missing_record(tmp_path, wiki):
    wiki.fail = True
    show = library(tmp_path, {1: [1]})
    path = gloss(tmp_path, ARC_INDEX)
    before = json.loads(path.read_text())
    gv.tag_arcs(str(path), str(show))
    assert json.loads(path.read_text()) == {**before, "arc_titles_missing": ["scope:arc_index:1"]}


def test_the_second_run_is_served_from_the_cache_and_writes_nothing(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, ARC_INDEX)
    gv.tag_arcs(str(path), str(show))
    first, calls = path.read_text(), len(wiki.urls)
    rep = gv.tag_arcs(str(path), str(show))
    assert len(wiki.urls) == calls and rep["scope_cached"] == 1 and rep["written"] is False and path.read_text() == first


def test_changing_the_scope_config_refetches(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, ARC_INDEX)
    gv.tag_arcs(str(path), str(show))
    calls = len(wiki.urls)
    path = gloss(tmp_path, {**ARC_INDEX, "deny": ["Hero"]})
    gv.tag_arcs(str(path), str(show))
    assert len(wiki.urls) > calls
    assert not [t for t in json.loads(path.read_text())["arc_titles"]["scope:arc_index:1"] if t.startswith("Hero")]  # replaced


def test_a_whole_wiki_scope_is_one_key_and_tags_no_names(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, {"rung": "whole_wiki", "wiki": NARUTO})
    gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert set(saved["arc_titles"]) == {"scope:whole_wiki:all"}
    assert set(saved["arc_titles"]["scope:whole_wiki:all"]) == {
        "Naruto Uzumaki",
        "Sakura Haruno",
        "Konoha",
    }  # structural pages denied
    assert "arc_tags" not in saved and saved["arc_coverage"]["scope:whole_wiki:all"]["rung"] == "whole_wiki"


def test_a_scope_season_tags_names_only_under_the_name_arc_for_returns(tmp_path, wiki):
    """repair weights by glossary.arc_for(video): a season with a season.nfo title gets the tags, one without gets none."""
    show = library(tmp_path, {1: [1, 2], 2: [20, 21]}, nfo={1: "Land of Waves"})
    path = gloss(tmp_path, ARC_INDEX, arc_waived=["Land of Waves"])  # the arc lookup itself is not what is tested
    gv.tag_arcs(str(path), str(show))
    tags = json.loads(path.read_text())["arc_tags"]
    assert tags == {"naruto uzumaki": ["Land of Waves"]}  # season 2 has no season.nfo: untagged


def test_files_without_a_season_episode_tag_give_no_scopes(tmp_path, wiki):
    show = tmp_path / "Naruto"
    show.mkdir()
    (show / "Episode one.mkv").write_bytes(b"")
    path = gloss(tmp_path, ARC_INDEX)
    before = path.read_text()
    rep = gv.tag_arcs(str(path), str(show))
    assert rep["note"] == "no arcs" and path.read_text() == before  # debt: needs SxxExx in the file names


def test_a_bad_scope_block_is_ignored_with_a_log_and_never_raises(tmp_path, wiki, capsys, monkeypatch):
    monkeypatch.setattr(gv, "_config_logged", set())
    show = library(tmp_path, {1: [1]})
    path = tmp_path / "Naruto.json"
    path.write_text(json.dumps({"show": "Naruto", "names": [], "wiki_scope": "arc_index"}))
    assert gv.tag_arcs(str(path), str(show))["note"] == "no arcs"
    assert "wiki_scope must be" in capsys.readouterr().out


def test_a_disallowed_wiki_host_stores_nothing(tmp_path, wiki):
    show = library(tmp_path, {1: [1]})
    path = gloss(tmp_path, {**ARC_INDEX, "wiki": "https://evilfandom.com/api.php"})
    rep = gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert "arc_titles" not in saved and saved["arc_titles_missing"] == ["scope:arc_index:1"] and rep["scope_incomplete"] == 1
    assert wiki.urls == []


def test_the_soft_stop_leaves_the_scopes_unwritten(tmp_path, wiki, monkeypatch):
    monkeypatch.setattr(gv, "stop_requested", lambda: True)
    show = library(tmp_path, {1: [1]})
    path = gloss(tmp_path, ARC_INDEX)
    before = path.read_text()
    assert gv.tag_arcs(str(path), str(show))["note"] == "stopped" and path.read_text() == before


def test_a_scope_no_longer_expected_is_marked_stale(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, ARC_INDEX, arc_titles={"scope:arc_index:7": ["Old"]})
    gv.tag_arcs(str(path), str(show))
    assert json.loads(path.read_text())["arc_coverage"]["scope:arc_index:7"] == {"titles": 1, "stale": True}


def test_a_show_without_a_scope_block_has_the_old_report_and_store(tmp_path, monkeypatch):
    """GUARD (passes on the old code): no wiki_scope key, no scope keys in the report or the glossary."""
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_arc_titles_checked", lambda api, arc: ({"Kaido"}, True))
    monkeypatch.setattr(gv, "redirect_targets", lambda api, titles: ({}, True))
    monkeypatch.setenv("ARC_MIN_TITLES", "1")
    show = library(tmp_path, {1: [1]}, nfo={1: "Wano"})
    path = tmp_path / "Naruto.json"
    path.write_text(json.dumps({"show": "Naruto", "names": ["Kaido"], "phrases": []}))
    rep = gv.tag_arcs(str(path), str(show))
    assert not [k for k in rep if k.startswith("scope")] and not [
        k for k in json.loads(path.read_text())["arc_titles"] if k.startswith("scope")
    ]


# ---- the gate reads the union -----------------------------------------------------------------------------


def test_the_universe_unions_arc_and_scope_titles(tmp_path, wiki, monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, ARC_INDEX)
    gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    saved["arc_titles"]["Wano"] = ["Kaido"]
    saved["arc_coverage"]["Wano"] = {"titles": 1, "redirects": True}
    universe = gv.arc_universe(saved)
    assert universe is not None and {"kaido", "hero of prologue — land of waves"} <= universe


def test_a_whole_wiki_scope_alone_is_a_logged_no_op(tmp_path, wiki, monkeypatch, capsys):
    """A whole-wiki universe contains every page verify could propose, so it would pass everything: the gate stays off."""
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setattr(gv, "_gate_noop_logged", False)
    path = gloss(tmp_path, {"rung": "whole_wiki", "wiki": NARUTO})
    gv.tag_arcs(str(path), str(library(tmp_path, {1: [1]})))
    assert gv.arc_universe(json.loads(path.read_text())) is None
    assert "whole-wiki" in capsys.readouterr().out


def test_a_whole_wiki_scope_never_widens_the_arc_universe(tmp_path, wiki, monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = {
        "arc_titles": {"Wano": ["Kaido"], "scope:whole_wiki:all": ["Naruto Uzumaki", "Konoha"]},
        "arc_coverage": {
            "Wano": {"titles": 1, "redirects": True},
            "scope:whole_wiki:all": {"titles": 2, "kind": "scope", "rung": "whole_wiki", "complete": True, "redirects": True},
        },
    }
    assert gv.arc_universe(g) == {"kaido"}


def test_a_missing_scope_key_keeps_the_gate_off(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = {
        "arc_titles": {"scope:arc_index:1": ["A"]},
        "arc_coverage": {
            "scope:arc_index:1": {"titles": 1, "kind": "scope", "rung": "arc_index", "complete": True, "redirects": True}
        },
        "arc_titles_missing": ["scope:arc_index:2"],
    }
    assert gv.arc_universe(g) is None


# =====================================================================================
# Phase 15: review fixes
# =====================================================================================


def add_episode(show, season, episode):
    d = show / f"Season {season:02d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"Naruto - S{season:02d}E{episode:02d} - Title.mkv").write_bytes(b"")


def test_a_missing_wiki_scope_module_is_an_incomplete_scope_not_a_crash(tmp_path, wiki, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "wiki_scope", None)  # `import wiki_scope` now raises ImportError
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, ARC_INDEX)
    rep = gv.tag_arcs(str(path), str(show))
    assert rep["scope_incomplete"] == 1 and json.loads(path.read_text())["arc_titles_missing"] == ["scope:arc_index:1"]


def test_an_incomplete_refetch_of_a_stored_scope_turns_the_gate_off(tmp_path, wiki, monkeypatch):
    """Season 1 was stored whole; a new episode changes the digest and the refetch fails. The old titles may not contain the
    new episode's arc, so the stored scope must stop counting as evidence until a pass completes it."""
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, ARC_INDEX)
    gv.tag_arcs(str(path), str(show))
    assert gv.arc_universe(json.loads(path.read_text())) is not None
    add_episode(show, 1, 3)
    wiki.fail = True
    gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert saved["arc_titles"]["scope:arc_index:1"] and saved["arc_titles_missing"] == ["scope:arc_index:1"]  # kept, but missing
    monkeypatch.setattr(gv, "_gate_noop_logged", False)
    assert gv.arc_universe(saved) is None
    wiki.fail = False
    gv.tag_arcs(str(path), str(show))  # a complete pass lifts it
    assert "arc_titles_missing" not in json.loads(path.read_text())


def test_a_result_that_is_incomplete_but_has_titles_is_neither_stored_nor_cached(tmp_path, wiki):
    """One of two arc pages fails: resolve_scope returns the other arc's titles with complete=False."""
    real = wiki.__call__

    def flaky(url):
        if "Ch%C5%ABnin" in url or "Chūnin" in url:
            raise OSError("arc page down")
        return real(url)

    gv._http_json = flaky  # restored by the wiki fixture's monkeypatch
    show = library(tmp_path, {1: [1, 30]})  # Prologue (1-19) and Chunin Exams (20-67)
    path = gloss(tmp_path, ARC_INDEX)
    rep = gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert "arc_titles" not in saved and rep["scope_incomplete"] == 1
    assert not os.path.exists(os.path.join(gv.CACHE_DIR, "Naruto_arcs.json"))


def test_a_new_episode_changes_the_cache_key_and_refetches(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2]})
    path = gloss(tmp_path, ARC_INDEX)
    gv.tag_arcs(str(path), str(show))
    calls = len(wiki.urls)
    add_episode(show, 1, 3)
    assert gv.tag_arcs(str(path), str(show))["scope_fetched"] == 1 and len(wiki.urls) > calls


def test_a_stored_scope_is_replaced_not_unioned(tmp_path, wiki):
    show = library(tmp_path, {1: [1, 2]})
    old_cov = {"titles": 1, "kind": "scope", "rung": "arc_index", "complete": True, "redirects": True}
    path = gloss(
        tmp_path, ARC_INDEX, arc_titles={"scope:arc_index:1": ["Gone Title"]}, arc_coverage={"scope:arc_index:1": old_cov}
    )
    gv.tag_arcs(str(path), str(show))
    assert "Gone Title" not in json.loads(path.read_text())["arc_titles"]["scope:arc_index:1"]


def test_a_small_whole_wiki_scope_is_not_tiny(tmp_path, wiki, monkeypatch):
    monkeypatch.setenv("ARC_MIN_TITLES", "10")
    wiki.allpages = ["Naruto Uzumaki", "Konoha"]
    show = library(tmp_path, {1: [1]})
    path = gloss(tmp_path, {"rung": "whole_wiki", "wiki": NARUTO})
    rep = gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert rep["tiny"] == 0 and "arc_titles_missing" not in saved and saved["arc_titles"]["scope:whole_wiki:all"]


def test_season_zero_specials_get_no_scope_unless_the_config_names_them(tmp_path, wiki):
    show = library(tmp_path, {0: [1], 1: [1, 2]})
    cfg = dict(ARC_INDEX)
    assert [s["key"] for s in gv.scopes_in_show(cfg, str(show))] == ["scope:arc_index:1"]
    cfg["season_offsets"] = {"0": 0}
    assert [s["key"] for s in gv.scopes_in_show(cfg, str(show))] == ["scope:arc_index:0", "scope:arc_index:1"]
    cfg = {**ARC_INDEX, "season_parts": {"0": "Part I"}}
    assert "scope:arc_index:0" in [s["key"] for s in gv.scopes_in_show(cfg, str(show))]


def test_an_incomplete_whole_wiki_scope_does_not_turn_the_gate_off_for_the_arcs(tmp_path, wiki, monkeypatch):
    """The whole-wiki titles are never in the universe, so their absence cannot make the evidence partial."""
    wiki.fail = True
    show = library(tmp_path, {1: [1]})
    path = gloss(tmp_path, {"rung": "whole_wiki", "wiki": NARUTO})
    gv.tag_arcs(str(path), str(show))
    assert "arc_titles_missing" not in json.loads(path.read_text())


@pytest.mark.parametrize("name", ["Naruto - S01E01E02 - x.mkv", "Naruto - S01E01-E02 - x.mkv", "Naruto - S01E01-E02-E03 - x.mkv"])
def test_a_multi_episode_file_counts_every_episode(tmp_path, name):
    show = tmp_path / "Naruto" / "Season 01"
    show.mkdir(parents=True)
    (show / name).write_bytes(b"")
    (scope,) = gv.scopes_in_show(ARC_INDEX, str(tmp_path / "Naruto"))
    assert scope["episodes"][:2] == [1, 2]


def test_a_small_whole_wiki_scope_does_not_trip_the_floor_in_the_universe(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setenv("ARC_MIN_TITLES", "10")
    g = {
        "arc_titles": {"Wano": ["Kaido"] * 12, "scope:whole_wiki:all": ["Naruto Uzumaki", "Konoha"]},
        "arc_coverage": {
            "Wano": {"titles": 12, "redirects": True},
            "scope:whole_wiki:all": {"titles": 2, "kind": "scope", "rung": "whole_wiki", "complete": True, "redirects": True},
        },
    }
    assert gv.arc_universe(g) == {"kaido"}
