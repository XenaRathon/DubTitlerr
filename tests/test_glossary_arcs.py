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
    """A fake wiki: fetch_arc_titles answers from ARC_TITLES and counts the calls; the cache dir is private."""
    monkeypatch.setattr(gv, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    calls = []

    def fetch(api, arc):
        calls.append(arc)
        return set(ARC_TITLES.get(arc, set()))

    monkeypatch.setattr(gv, "fetch_arc_titles", fetch)
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
    before = path.read_text()
    rep = gv.tag_arcs(str(path), str(show))
    assert path.read_text() == before and rep["written"] is False and rep["empty"] == 1
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
