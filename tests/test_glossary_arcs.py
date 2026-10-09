"""The arc-scoped wiki stage wired into the glossary pipeline: tagging (GLOSSARY_ARC_TAGS) and the verify gate (VERIFY_ARC_GATE).

Synthetic only; the wiki is a function, the show directory is a tmp tree."""

import json
import os
import subprocess

import pytest

import glossary_acquire as ga
import glossary_verify as gv

ARC_TITLES = {
    "Dressrosa": {"Donquixote Doflamingo", "Monkey D. Luffy", "Rebecca", "Kyros"},
    "Wano": {"Kouzuki Momonosuke", "Monkey D. Luffy", "Kaido"},
}


def make_show(tmp_path, seasons):
    """seasons: {dir name: <title> or None (no season.nfo) or "" (an nfo with no title)}."""
    show = tmp_path / "Show"
    for name, title in seasons.items():
        d = show / name
        d.mkdir(parents=True)
        (d / "Show - S01E01.mkv").write_bytes(b"")
        if title is not None:
            (d / "season.nfo").write_text(f"<season><title>{title}</title></season>" if title else "<season></season>")
    return show


def write_gloss(tmp_path, **extra):
    path = tmp_path / "Show.json"
    path.write_text(
        json.dumps(
            {
                "show": "Show",
                "wiki": "https://x.fandom.com/api.php",
                "names": ["Doflamingo", "Luffy", "Kaido", "Spandam"],
                "phrases": [],
                **extra,
            }
        )
    )
    return path


@pytest.fixture
def wiki(monkeypatch, tmp_path):
    """A fake wiki: fetch_arc_titles_checked answers from ARC_TITLES and counts the calls; the cache dir is private."""
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    calls = []

    def fetch(api, arc):
        calls.append(arc)
        return set(ARC_TITLES.get(arc, set())), True

    monkeypatch.setattr(gv, "fetch_arc_titles_checked", fetch)
    monkeypatch.setattr(gv, "redirect_targets", lambda api, titles: ({}, True))
    return calls


# ---- discovering the arcs ----------------------------------------------------------------------------------------------------


def test_the_distinct_arcs_come_from_each_seasons_nfo(tmp_path):
    show = make_show(
        tmp_path, {"Season 30": "Dressrosa", "Season 31": "Dressrosa", "Season 02": "Wano", "Season 05": None, "Season 07": ""}
    )
    assert gv.arcs_in_show(str(show)) == ["Dressrosa", "Wano"]


def test_a_show_without_season_nfos_has_no_arcs(tmp_path):
    assert gv.arcs_in_show(str(make_show(tmp_path, {"Season 01": None}))) == []
    assert gv.arcs_in_show(str(tmp_path / "missing")) == []


# ---- tagging ------------------------------------------------------------------------------------------------------------------


def test_tagging_persists_the_tags_and_the_arc_universe_fetching_each_arc_once(tmp_path, wiki):
    show = make_show(tmp_path, {"Season 30": "Dressrosa", "Season 31": "Dressrosa", "Season 02": "Wano"})
    path = write_gloss(tmp_path)
    rep = gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert sorted(wiki) == ["Dressrosa", "Wano"]  # one fetch per distinct arc, not per season
    assert saved["arc_tags"] == {"doflamingo": ["Dressrosa"], "luffy": ["Dressrosa", "Wano"], "kaido": ["Wano"]}
    assert saved["arc_titles"] == {arc: sorted(t) for arc, t in ARC_TITLES.items()}
    assert saved["names"] == ["Doflamingo", "Luffy", "Kaido", "Spandam"]  # the names stay show-wide and unchanged
    assert rep["arcs"] == 2 and rep["fetched"] == 2 and rep["names_tagged"] == 3 and rep["written"] is True


def test_tagging_is_idempotent_and_does_not_rewrite_an_unchanged_glossary(tmp_path, wiki, monkeypatch):
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    path = write_gloss(tmp_path)
    gv.tag_arcs(str(path), str(show))
    first = path.read_text()
    writes = []
    monkeypatch.setattr(ga, "_write_json", lambda *a: writes.append(a))
    rep = gv.tag_arcs(str(path), str(show))
    assert path.read_text() == first and writes == [] and rep["written"] is False


def test_tagging_is_additive_and_keeps_other_tags_and_titles(tmp_path, wiki):
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    path = write_gloss(tmp_path, arc_tags={"spandam": ["Enies Lobby"]}, arc_titles={"Enies Lobby": ["Spandam"]})
    gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert saved["arc_tags"]["spandam"] == ["Enies Lobby"] and saved["arc_titles"]["Enies Lobby"] == ["Spandam"]
    assert saved["arc_tags"]["doflamingo"] == ["Dressrosa"]


def test_the_second_run_is_served_from_the_disk_cache(tmp_path, wiki, monkeypatch):
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    gv.tag_arcs(str(write_gloss(tmp_path)), str(show))
    assert wiki == ["Dressrosa"]
    wiki.clear()
    rep = gv.tag_arcs(str(write_gloss(tmp_path)), str(show))  # a fresh glossary: the tags must come back without the network
    assert wiki == [] and rep["cached"] == 1 and rep["fetched"] == 0 and rep["names_tagged"] == 2


def test_a_stale_cache_entry_is_refetched(tmp_path, wiki, monkeypatch):
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    gv.tag_arcs(str(write_gloss(tmp_path)), str(show))
    wiki.clear()
    monkeypatch.setattr(gv, "WIKI_TTL", -1)
    gv.tag_arcs(str(write_gloss(tmp_path)), str(show))
    assert wiki == ["Dressrosa"]


def test_an_empty_arc_changes_nothing_and_is_not_cached(tmp_path, wiki, capsys):
    """[S-7]: Gaimon is a character, not an arc; a network failure looks the same. Neither may touch the glossary."""
    show = make_show(tmp_path, {"Season 01": "Gaimon"})
    path = write_gloss(tmp_path)
    before = json.loads(path.read_text())
    rep = gv.tag_arcs(str(path), str(show))
    assert rep["empty"] == 1
    assert json.loads(path.read_text()) == {**before, "arc_titles_missing": ["Gaimon"]}  # no tags, no titles; only the record
    assert "Gaimon" in capsys.readouterr().out
    assert not os.path.exists(os.path.join(gv.CACHE_DIR, "Show_arcs.json"))  # only positive results are cached
    wiki.clear()
    gv.tag_arcs(str(path), str(show))
    assert wiki == ["Gaimon"]  # asked again next time


def test_one_empty_arc_does_not_clear_what_another_established(tmp_path, wiki):
    show = make_show(tmp_path, {"Season 30": "Dressrosa", "Season 01": "Gaimon"})
    path = write_gloss(tmp_path)
    gv.tag_arcs(str(path), str(show))
    assert json.loads(path.read_text())["arc_tags"]["doflamingo"] == ["Dressrosa"]


def test_an_unreachable_wiki_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: None)
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    path = write_gloss(tmp_path)
    before = path.read_text()
    assert "wiki unresolved" in gv.tag_arcs(str(path), str(show))["note"] and path.read_text() == before


def test_a_show_without_arcs_changes_nothing(tmp_path, wiki):
    path = write_gloss(tmp_path)
    before = path.read_text()
    rep = gv.tag_arcs(str(path), str(make_show(tmp_path, {"Season 01": None})))
    assert rep["note"] == "no arcs" and path.read_text() == before and wiki == []


def test_a_failed_write_leaves_the_glossary_intact(tmp_path, wiki, monkeypatch):
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    path = write_gloss(tmp_path)
    before = path.read_text()

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(ga, "_write_json", boom)
    assert gv.tag_arcs(str(path), str(show))["note"].startswith("write-failed") and path.read_text() == before


def test_the_soft_stop_is_honoured_between_arcs(tmp_path, wiki, monkeypatch):
    show = make_show(tmp_path, {"Season 30": "Dressrosa", "Season 02": "Wano"})
    monkeypatch.setattr(gv, "stop_requested", lambda: True)
    path = write_gloss(tmp_path)
    before = path.read_text()
    assert gv.tag_arcs(str(path), str(show))["note"] == "stopped" and wiki == [] and path.read_text() == before


# ---- the entry points --------------------


def test_the_cli_flag_runs_tagging_only(tmp_path, wiki, monkeypatch, capsys):
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    path = write_gloss(tmp_path)
    monkeypatch.setattr(gv, "verify", lambda *a, **k: pytest.fail("--tag-arcs must not verify"))
    monkeypatch.setattr("sys.argv", ["glossary_verify", str(path), "--tag-arcs", str(show)])
    with pytest.raises(SystemExit) as e:
        gv.main()
    assert e.value.code == 0 and json.loads(path.read_text())["arc_tags"]["doflamingo"] == ["Dressrosa"]
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["names_tagged"] == 2


def test_gen_loop_runs_the_tagging_step_only_behind_the_flag_and_before_verify():
    text = open(os.path.join(os.path.dirname(__file__), "..", "gen_loop.sh")).read()
    assert subprocess.run(["bash", "-n", os.path.join(os.path.dirname(__file__), "..", "gen_loop.sh")]).returncode == 0
    step = text.index('"${GLOSSARY_ARC_TAGS:-0}" = "1"')
    assert step < text.index("#### VERIFY") and "--tag-arcs" in text[step : step + 900]
    assert text.count("GLOSSARY_ARC_TAGS") == text[: text.index("#### GENERATE")].count("GLOSSARY_ARC_TAGS")


# ---- the verify gate --------------------


def high(canon):
    return {"canonical": canon, "confidence": "high", "dub_note": ""}


def gated_gloss(**extra):
    return {
        "show": "Show",
        "names": ["Government", "Momonosuke"],
        "phrases": [],
        "arc_titles": {"Wano": ["Kouzuki Momonosuke", "Kaido"]},
        **extra,
    }


RESULTS = {"Government": high("World Government"), "Momonosuke": high("Kouzuki Momonosuke")}


def test_by_default_both_generic_and_arc_expansions_are_written():
    """GUARD (passes on the old code): the gate is opt-in."""
    new = gv.apply_results(gated_gloss(), RESULTS)
    assert "World Government" in new["phrases"] and "Kouzuki Momonosuke" in new["phrases"] and "flagged" not in new


def test_the_gate_blocks_a_generic_expansion_and_allows_one_in_an_arc_page(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    new = gv.apply_results(gated_gloss(), RESULTS)
    assert new["flagged"] == {"Government": {"reason": "not-in-arc-pages", "canonical": "World Government"}}
    assert "World Government" not in new["names"] + new["phrases"] and new["names"] == ["Government", "Momonosuke"]
    assert "Kouzuki Momonosuke" in new["phrases"]


def test_the_arc_universe_is_the_union_of_every_arcs_titles_compared_casefolded(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = gated_gloss(arc_titles={"Wano": ["Kaido"], "Dressrosa": ["kouzuki momonosuke"]})
    new = gv.apply_results(g, {"Momonosuke": high("Kouzuki Momonosuke")})
    assert "Kouzuki Momonosuke" in new["phrases"] and "flagged" not in new


def test_a_blocked_pick_is_reviewable_like_a_respelling_flag(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    new = gv.apply_results(gated_gloss(), RESULTS)
    item = [i for i in ga.review_items(new) if i["term"] == "Government"][0]
    assert item["reason"] == "not-in-arc-pages" and item["canonical"] == "World Government"


@pytest.mark.parametrize("extra", [{"arc_titles": {}}, {"arc_titles": None}])
def test_without_an_arc_universe_the_gate_is_a_no_op_and_says_so_once(monkeypatch, capsys, extra):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setattr(gv, "_gate_noop_logged", False)
    g = gated_gloss(**extra)
    a, b = gv.apply_results(g, RESULTS), gv.apply_results(g, RESULTS)
    assert "World Government" in a["phrases"] and "flagged" not in a and a == b
    assert capsys.readouterr().out.count("VERIFY_ARC_GATE is on but this glossary has no arc titles") == 1


def test_a_glossary_with_no_arc_titles_key_at_all_is_a_no_op_too(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = gated_gloss()
    del g["arc_titles"]
    assert "World Government" in gv.apply_results(g, RESULTS)["phrases"]


def test_the_gate_applies_only_to_writes_not_to_respelling_flags_or_low_confidence(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    g = gated_gloss()
    new = gv.apply_results(
        g,
        {
            "Government": {"canonical": "Governmint", "confidence": "high"},
            "Momonosuke": {"canonical": "Kaido", "confidence": "low"},
        },
    )
    assert (
        new["flagged"]["Government"]["reason"] == "respelling-needs-review" and new["flagged"]["Momonosuke"] == "low-confidence"
    )


def _verify_run(tmp_path, monkeypatch, gloss):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(gloss))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["World Government", "Kouzuki Momonosuke"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "adjudicate", lambda term, cands, show: RESULTS[term])
    return gv.verify(str(path))


def test_the_report_counts_what_the_gate_blocked_and_applied_excludes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    rep = _verify_run(tmp_path, monkeypatch, {**gated_gloss(), "wiki": "https://x.fandom.com/api.php"})
    assert rep["applied"] == 1 and rep["escalated"] == 1 and rep["arc_gate"] == {"blocked": 1, "universe": 2}


def test_without_the_gate_the_report_has_no_arc_gate_key(tmp_path, monkeypatch):
    """GUARD: default report shape."""
    monkeypatch.delenv("VERIFY_ARC_GATE", raising=False)
    rep = _verify_run(tmp_path, monkeypatch, {**gated_gloss(), "wiki": "https://x.fandom.com/api.php"})
    assert "arc_gate" not in rep and rep["applied"] == 2


# ---- the whole-word guard's two-letter minimum (VERIFY_WRITE_WHOLE_WORD=1 only) -----------------------------------------------


@pytest.mark.parametrize("term", ["D", "3", "d."])
def test_a_term_with_fewer_than_two_letters_is_flagged_under_the_whole_word_guard(monkeypatch, term):
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    monkeypatch.setattr(ga, "is_expansion", lambda t, c: True)
    new = gv.apply_results({"show": "S", "names": [term], "phrases": [], "hard_fixes": {}}, {term: high(f"Monkey {term}. Luffy")})
    assert new["flagged"][term]["reason"] == "respelling-needs-review" and new["names"] == [term] and new["phrases"] == []


def test_two_letters_are_enough_and_the_default_is_unchanged(monkeypatch):
    monkeypatch.setattr(ga, "is_expansion", lambda t, c: True)
    g = {"show": "S", "names": ["Jo", "D"], "phrases": [], "hard_fixes": {}}
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "1")
    assert "Jo March" in gv.apply_results(g, {"Jo": high("Jo March")})["phrases"]
    monkeypatch.delenv("VERIFY_WRITE_WHOLE_WORD")  # GUARD: off by default, a one-letter term is written as before
    assert "Monkey D. Luffy" in gv.apply_results(g, {"D": high("Monkey D. Luffy")})["phrases"]


# =====================================================================================
# Phase 10: normalised arc links, redirects, complete-only storage, coverage
# =====================================================================================

WIKITEXT = (
    "[[Monkey_D._Luffy|Luffy]] [[Kaido]] [[whitebeard|the Emperor]] [[Ace]] [[Trafalgar Law#Wano|Law]] "
    "[[Category:Pirates]] [[File:a.png]] [[wikipedia:Foo]] [[#Plot]] [[Chapter 12]] [[Episode 5]]"
)


def test_arc_links_are_normalised_for_the_arc_stage():
    got = gv._extract_links(WIKITEXT, normalise=True)
    assert got == {"Monkey D. Luffy", "Kaido", "Whitebeard", "Ace", "Trafalgar Law"}


def test_the_episode_plot_links_keep_their_old_filter_so_acquire_is_byte_identical():
    """GUARD (passes on the old code): the per-episode candidate path is not touched by the arc stage's normalisation."""
    assert gv._extract_links(WIKITEXT) == {"Monkey_D._Luffy", "Kaido", "Ace"}
    assert gv.plot_section_links("==Plot==\n" + WIKITEXT) == {"Monkey_D._Luffy", "Kaido", "Ace"}


class RawWiki:
    """A fake MediaWiki behind gv._http_json: arc page wikitext, category search/members, redirects, with switchable failures."""

    def __init__(self, text=WIKITEXT, categories=None, members=None, redirects=None):
        self.text, self.categories, self.members = text, categories or [], members or {}
        self.redirects = redirects or {}
        self.fail = set()  # "parse" | "search" | "members" | "redirects"
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        for kind, marker in (
            ("parse", "action=parse"),
            ("search", "list=search"),
            ("members", "list=categorymembers"),
            ("redirects", "redirects=1"),
        ):
            if marker in url:
                if kind in self.fail:
                    raise OSError(f"{kind} down")
                return getattr(self, "_" + kind)(url)
        raise AssertionError(url)

    def _parse(self, url):
        if self.text is None:
            return {"error": {"code": "missingtitle"}}
        return {"parse": {"wikitext": {"*": self.text}}}

    def _search(self, url):
        return {"query": {"search": [{"title": c} for c in self.categories]}}

    def _members(self, url):
        import urllib.parse as up

        cat = up.unquote(url.split("cmtitle=")[1].split("&")[0])
        return {"query": {"categorymembers": [{"title": t} for t in self.members.get(cat, [])]}}

    def _redirects(self, url):
        import urllib.parse as up

        titles = up.unquote(url.split("titles=")[1]).split("|")
        return {"query": {"redirects": [{"from": t, "to": self.redirects[t]} for t in titles if t in self.redirects]}}


@pytest.fixture
def raw(monkeypatch, tmp_path):
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    wiki = RawWiki(categories=["Category:Wano Residents"], members={"Category:Wano Residents": ["Kaido", "Kouzuki Momonosuke"]})
    monkeypatch.setattr(gv, "_http_json", wiki)
    return wiki


def test_the_normalised_links_reach_the_stored_universe(tmp_path, raw):
    show = make_show(tmp_path, {"Season 35": "Wano"})
    path = write_gloss(tmp_path)
    gv.tag_arcs(str(path), str(show))
    stored = json.loads(path.read_text())["arc_titles"]["Wano"]
    assert {"Monkey D. Luffy", "Whitebeard", "Trafalgar Law", "Kouzuki Momonosuke"} <= set(stored)


def test_a_redirect_target_is_stored_beside_the_link(tmp_path, raw):
    raw.redirects = {"Ace": "Portgas D. Ace", "Whitebeard": "Edward Newgate"}
    show = make_show(tmp_path, {"Season 35": "Wano"})
    path = write_gloss(tmp_path)
    gv.tag_arcs(str(path), str(show))
    stored = set(json.loads(path.read_text())["arc_titles"]["Wano"])
    assert {"Ace", "Portgas D. Ace", "Whitebeard", "Edward Newgate"} <= stored  # both the link and where it points


def test_redirects_are_resolved_once_per_arc_in_bounded_chunks(tmp_path, raw):
    raw.text = " ".join(f"[[Person {k}]]" for k in range(120))
    show = make_show(tmp_path, {"Season 35": "Wano"})
    gv.tag_arcs(str(write_gloss(tmp_path)), str(show))
    chunks = [u for u in raw.urls if "redirects=1" in u]
    assert 1 <= len(chunks) <= 4  # 122 titles at 50 per call, once per arc
    raw.urls.clear()
    gv.tag_arcs(str(write_gloss(tmp_path)), str(show))
    assert not [u for u in raw.urls if "redirects=1" in u]  # served from the cache


def test_a_failed_redirect_step_keeps_the_plain_links_and_is_not_cached(tmp_path, raw):
    raw.fail = {"redirects"}
    show = make_show(tmp_path, {"Season 35": "Wano"})
    path = write_gloss(tmp_path)
    rep = gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert {"Ace", "Kaido", "Monkey D. Luffy"} <= set(saved["arc_titles"]["Wano"]) and rep["fetched"] == 1
    assert saved["arc_coverage"]["Wano"]["redirects"] is False
    raw.fail = set()
    raw.redirects = {"Ace": "Portgas D. Ace"}
    gv.tag_arcs(str(path), str(show))  # not cached, so the next pass resolves them
    assert "Portgas D. Ace" in json.loads(path.read_text())["arc_titles"]["Wano"]


# ---- complete results only ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("failing", ["parse", "search", "members"])
def test_a_partial_fetch_is_neither_cached_nor_stored(tmp_path, raw, failing, capsys):
    raw.fail = {failing}
    show = make_show(tmp_path, {"Season 35": "Wano"})
    path = write_gloss(tmp_path)
    before = json.loads(path.read_text())
    rep = gv.tag_arcs(str(path), str(show))
    assert rep["partial"] == 1 and rep["fetched"] == 0
    assert json.loads(path.read_text()) == {**before, "arc_titles_missing": ["Wano"]}  # nothing from the partial fetch stored
    assert not os.path.exists(os.path.join(gv.CACHE_DIR, "Show_arcs.json"))
    assert "partial" in capsys.readouterr().out


def test_a_category_listing_that_hits_the_page_cap_is_incomplete(tmp_path, raw, monkeypatch):
    raw._members = lambda url: {"query": {"categorymembers": [{"title": "Kaido"}]}, "continue": {"cmcontinue": "MORE"}}
    titles, complete = gv.fetch_arc_titles_checked("https://x.fandom.com/api.php", "Wano")
    assert "Kaido" in titles and complete is False


def test_a_missing_arc_page_is_a_complete_empty_result_for_the_page_not_a_failure(raw):
    raw.text, raw.categories = None, []  # "Gaimon Arc" does not exist and no category matches: [S-7], nothing to store
    assert gv.fetch_arc_titles_checked("https://x.fandom.com/api.php", "Gaimon") == (set(), True)
    assert gv.fetch_arc_titles("https://x.fandom.com/api.php", "Gaimon") == set()


def test_a_complete_fetch_reports_complete(raw):
    titles, complete = gv.fetch_arc_titles_checked("https://x.fandom.com/api.php", "Wano")
    assert complete is True and "Kouzuki Momonosuke" in titles


# ---- coverage -------------------------------------------- -----


def test_the_glossary_records_which_arcs_have_titles_and_which_do_not(tmp_path, raw, monkeypatch):
    show = make_show(tmp_path, {"Season 35": "Wano", "Season 01": "Gaimon"})

    def wiki(url):
        import urllib.parse as up

        page = up.unquote(url.split("page=")[1].split("&")[0]) if "action=parse" in url else ""
        if "action=parse" in url and not page.startswith("Wano"):
            return {"error": {"code": "missingtitle"}}  # "Gaimon Arc" does not exist
        if "list=search" in url and "Wano" not in up.unquote(url):
            return {"query": {"search": []}}
        return raw(url)

    monkeypatch.setattr(gv, "_http_json", wiki)
    path = write_gloss(tmp_path)
    gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert saved["arc_titles_missing"] == ["Gaimon"] and set(saved["arc_coverage"]) == {"Wano"}
    assert saved["arc_coverage"]["Wano"] == {"titles": len(saved["arc_titles"]["Wano"]), "redirects": True}


def test_the_gate_is_a_logged_no_op_while_any_arc_has_no_titles(monkeypatch, capsys):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    monkeypatch.setattr(gv, "_gate_noop_logged", False)
    g = gated_gloss(arc_titles_missing=["Marineford"])
    new = gv.apply_results(g, RESULTS)
    assert "World Government" in new["phrases"] and "flagged" not in new  # nothing blocked on partial evidence
    assert "Marineford" in capsys.readouterr().out


def test_the_gate_applies_once_every_arc_is_covered(monkeypatch):
    monkeypatch.setenv("VERIFY_ARC_GATE", "1")
    new = gv.apply_results(gated_gloss(arc_titles_missing=[]), RESULTS)
    assert new["flagged"]["Government"]["reason"] == "not-in-arc-pages"


def test_a_later_pass_that_covers_the_arc_clears_the_missing_list(tmp_path, raw):
    show = make_show(tmp_path, {"Season 35": "Wano"})
    path = write_gloss(tmp_path)
    raw.fail = {"parse"}
    gv.tag_arcs(str(path), str(show))
    assert json.loads(path.read_text())["arc_titles_missing"] == ["Wano"]
    raw.fail = set()
    gv.tag_arcs(str(path), str(show))
    saved = json.loads(path.read_text())
    assert "arc_titles_missing" not in saved and "Wano" in saved["arc_titles"]


def test_a_stopped_pass_writes_nothing_including_coverage(tmp_path, raw, monkeypatch):
    monkeypatch.setattr(gv, "stop_requested", lambda: True)
    path = write_gloss(tmp_path)
    before = path.read_text()
    gv.tag_arcs(str(path), str(make_show(tmp_path, {"Season 35": "Wano"})))
    assert path.read_text() == before


# ---- nits ------------------------------------------------ -----


def test_stored_titles_are_unioned_across_passes_not_replaced(tmp_path, wiki, monkeypatch):
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    path = write_gloss(tmp_path)
    gv.tag_arcs(str(path), str(show))
    first = set(json.loads(path.read_text())["arc_titles"]["Dressrosa"])
    monkeypatch.setattr(gv, "WIKI_TTL", -1)
    monkeypatch.setattr(gv, "fetch_arc_titles_checked", lambda api, arc: ({"Pica"}, True))
    monkeypatch.setattr(gv, "redirect_targets", lambda api, titles: ({}, True))
    gv.tag_arcs(str(path), str(show))
    assert set(json.loads(path.read_text())["arc_titles"]["Dressrosa"]) == first | {"Pica"}


def test_gen_loop_continues_when_arc_tagging_fails():
    import re

    text = open(os.path.join(os.path.dirname(__file__), "..", "gen_loop.sh")).read()
    step = text[text.index('"${GLOSSARY_ARC_TAGS:-0}" = "1"') :]
    step = step[: step.index("\n\t\tfi\n")]
    assert re.search(r'--tag-arcs "\$ANIME/\$show" </dev/null 2>&1 \|\|\s*\n\s*echo "  arc tagging skipped \(continuing\)"', step)
    assert "exit 1" not in step and "set -e" not in step


def test_tag_arcs_exits_nonzero_for_a_failure_only_under_verify_refuse_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: None)
    show = make_show(tmp_path, {"Season 30": "Dressrosa"})
    path = write_gloss(tmp_path)
    monkeypatch.setattr("sys.argv", ["glossary_verify", str(path), "--tag-arcs", str(show)])
    monkeypatch.delenv("VERIFY_REFUSE_EXIT", raising=False)
    with pytest.raises(SystemExit) as e:
        gv.main()
    assert e.value.code == 0  # the note field is the signal, as before
    monkeypatch.setenv("VERIFY_REFUSE_EXIT", "1")
    with pytest.raises(SystemExit) as e:
        gv.main()
    assert e.value.code not in (0, None) and "wiki unresolved" in capsys.readouterr().out.strip().splitlines()[-1]


def test_a_tag_arcs_pass_with_an_empty_arc_is_not_a_failure_exit(tmp_path, wiki, monkeypatch):
    monkeypatch.setenv("VERIFY_REFUSE_EXIT", "1")
    show = make_show(tmp_path, {"Season 01": "Gaimon"})
    monkeypatch.setattr("sys.argv", ["glossary_verify", str(write_gloss(tmp_path)), "--tag-arcs", str(show)])
    with pytest.raises(SystemExit) as e:
        gv.main()
    assert e.value.code == 0
