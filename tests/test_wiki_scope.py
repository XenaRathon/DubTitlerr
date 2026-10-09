"""Unit tests for wiki_scope.py pure core (all HTTP mocked via injected http function)."""

import wiki_scope

NARUTO_INDEX_WIKITEXT = """
{| class="wikitable sortable"
|-
! Arc Name
! Chapters
! Episodes
! Summary
|-
| [[Prologue — Land of Waves]]
| 1-33
| 1-19
| Team 7 is sent on a mission to the [[Land of Waves]].
|-
| [[Chūnin Exams (Arc)|Chūnin Exams]]
| 34-115
| 20-67
| Team 7 participates in the [[Chūnin Exams]].
|-
| [[Konoha Crush (Arc)|Konoha Crush]]
| 116-138
| 68-80
| The village is invaded by [[Orochimaru]].
|}
"""

LAND_OF_WAVES_WIKITEXT = """
== Plot ==
[[Naruto Uzumaki]] and [[Kakashi Hatake]] fight [[Zabuza Momochi]] and [[Haku]].
[[Demon Brothers]] also appear.
"""

CHUNIN_EXAMS_WIKITEXT = """
== Plot ==
[[Gaara]] fights [[Rock Lee]]. [[Orochimaru]] attacks [[Sasuke Uchiha]].
[[Neji Hyūga]] and [[Hinata Hyūga]] battle.
"""

POKEMON_S01_LINKS = [
    {"ns": 0, "*": "Ash Ketchum"},
    {"ns": 0, "*": "Pikachu (Pokémon)"},
    {"ns": 0, "*": "Brock (anime)"},
    {"ns": 0, "*": "Ash's Bulbasaur"},
    {"ns": 0, "*": "EP001"},
    {"ns": 0, "*": "EP002"},
    {"ns": 14, "*": "Category:Original series episodes"},
]


# ---- Test: empty or missing cfg ---------------------------------------------


def test_empty_or_missing_cfg_returns_rung_none_and_not_complete():
    for empty_cfg in [None, {}, {"rung": ""}, {"rung": "unknown_rung"}]:
        res = wiki_scope.resolve_scope(empty_cfg, season=1, episode_numbers=[1], http=lambda url: {})
        assert res.rung == "none"
        assert res.complete is False
        assert res.titles == set()
        assert len(res.notes) >= 1


# ---- Test Rung 1: arc_index (Naruto shape) ----------------------------------


def test_arc_index_naruto_shape():
    def fake_http(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": NARUTO_INDEX_WIKITEXT}}}
        if "Prologue" in url:
            return {"parse": {"wikitext": {"*": LAND_OF_WAVES_WIKITEXT}}}
        if "Ch%C5%ABnin" in url or "Chunin" in url:
            return {"parse": {"wikitext": {"*": CHUNIN_EXAMS_WIKITEXT}}}
        raise AssertionError(f"unexpected url: {url}")

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    # Request episode 5 (Land of Waves only)
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=[5], http=fake_http)
    assert res.rung == "arc_index"
    assert res.complete is True
    assert "Zabuza Momochi" in res.titles
    assert "Haku" in res.titles
    assert "Gaara" not in res.titles  # Chunin Exams not included


def test_arc_index_unparseable_row_reported_in_notes():
    index_with_bad_row = NARUTO_INDEX_WIKITEXT + """
|-
| [[Unparseable Arc]]
| invalid_chapters
| not_an_episode_number
| Some text
"""

    def fake_http(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": index_with_bad_row}}}
        return {"parse": {"wikitext": {"*": LAND_OF_WAVES_WIKITEXT}}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=[1], http=fake_http)
    assert res.complete is True
    assert any("unparseable" in n.lower() for n in res.notes)
    assert "Zabuza Momochi" in res.titles


def test_arc_index_overlapping_two_seasons():
    """Chunin Exams (eps 20-67) overlaps Season 1 (1-57) and Season 2 (58-100)."""
    calls = []

    def fake_http(url):
        calls.append(url)
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": NARUTO_INDEX_WIKITEXT}}}
        if "Ch%C5%ABnin" in url or "Chunin" in url:
            return {"parse": {"wikitext": {"*": CHUNIN_EXAMS_WIKITEXT}}}
        if "Prologue" in url:
            return {"parse": {"wikitext": {"*": LAND_OF_WAVES_WIKITEXT}}}
        raise AssertionError(f"unexpected url: {url}")

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    # Season 1 request including ep 25 -> Chunin Exams
    res1 = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=[25], http=fake_http)
    assert "Gaara" in res1.titles
    assert res1.complete is True

    # Season 2 request including ep 60 -> Chunin Exams too!
    res2 = wiki_scope.resolve_scope(cfg, season=2, episode_numbers=[60], http=fake_http)
    assert "Gaara" in res2.titles
    assert res2.complete is True


def test_arc_index_season_offsets_mapping():
    """season_offsets maps season-relative episodes to absolute episode numbers."""
    def fake_http(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": NARUTO_INDEX_WIKITEXT}}}
        if "Ch%C5%ABnin" in url or "Chunin" in url:
            return {"parse": {"wikitext": {"*": CHUNIN_EXAMS_WIKITEXT}}}
        if "Konoha" in url:
            return {"parse": {"wikitext": {"*": "== Plot ==\n[[Hiruzen Sarutobi]] fights [[Orochimaru]]."}}}
        raise AssertionError(f"unexpected url: {url}")

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
        "season_offsets": {"1": 0, "2": 57},
    }
    # Season 2, episode 11 relative -> absolute 57 + 11 = 68 -> Konoha Crush Arc (eps 68-80)
    res = wiki_scope.resolve_scope(cfg, season=2, episode_numbers=[11], http=fake_http)
    assert res.complete is True
    assert "Hiruzen Sarutobi" in res.titles
    assert "Zabuza Momochi" not in res.titles


# ---- Test Rung 2: season_page (Pokemon shape) -------------------------------


def test_season_page_pokemon_shape():
    def fake_http(url):
        assert "page=S01" in url
        return {"parse": {"links": POKEMON_S01_LINKS}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert res.rung == "season_page"
    assert res.complete is True
    assert "Ash Ketchum" in res.titles
    assert "Pikachu (Pokémon)" in res.titles
    assert "Brock (anime)" in res.titles
    # Default season deny drops ^EP\d+ and ^Category:
    assert "EP001" not in res.titles
    assert "EP002" not in res.titles
    assert "Category:Original series episodes" not in res.titles


def test_season_page_custom_deny_regex():
    def fake_http(url):
        return {"parse": {"links": POKEMON_S01_LINKS}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
        "deny": [r"^Ash's\s+"],
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert "Ash Ketchum" in res.titles
    assert "Ash's Bulbasaur" not in res.titles  # dropped by custom deny


# ---- Test Rung 3: whole_wiki (Chainsmoker Cat / Marriagetoxin shape) ---------


def test_whole_wiki_chainsmoker_shape():
    pages = [
        {"title": "Ai Gatsubo"},
        {"title": "Aruko Sakai"},
        {"title": "Chapter 1"},
        {"title": "Chapter 2"},
        {"title": "Volume 1"},
        {"title": "Main Page"},
        {"title": "Chainsmoker Cat Wiki"},
    ]

    def fake_http(url):
        assert "list=allpages" in url
        return {"query": {"allpages": pages}}

    cfg = {
        "rung": "whole_wiki",
        "wiki": "https://chainsmoker-cat.fandom.com/api.php",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert res.rung == "whole_wiki"
    assert res.complete is True
    assert "Ai Gatsubo" in res.titles
    assert "Aruko Sakai" in res.titles
    # Default structural deny drops chapters, volumes, Main Page, Wiki
    assert "Chapter 1" not in res.titles
    assert "Chapter 2" not in res.titles
    assert "Volume 1" not in res.titles
    assert "Main Page" not in res.titles
    assert "Chainsmoker Cat Wiki" not in res.titles


def test_whole_wiki_continuation_followed():
    """Mutation check: ignoring continue must fail this test."""
    calls = []

    def fake_http(url):
        calls.append(url)
        if "apcontinue" not in url:
            return {
                "query": {"allpages": [{"title": "Character One"}]},
                "continue": {"apcontinue": "TOKEN_PAGE_2"},
            }
        else:
            assert "TOKEN_PAGE_2" in url
            return {
                "query": {"allpages": [{"title": "Character Two"}]},
            }

    cfg = {
        "rung": "whole_wiki",
        "wiki": "https://example.fandom.com/api.php",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert len(calls) == 2
    assert res.complete is True
    assert "Character One" in res.titles
    assert "Character Two" in res.titles  # Must be present because continuation was followed!


# ---- Test: Failure handling (complete is False) -----------------------------


def test_failure_on_http_sets_complete_false():
    def boom(url):
        raise OSError("network error")

    for rung in ["arc_index", "season_page", "whole_wiki"]:
        cfg = {"rung": rung, "wiki": "https://x.fandom.com/api.php", "season_page": "S{season:02d}"}
        res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=[1], http=boom)
        assert res.complete is False
        assert len(res.notes) >= 1


def test_normalize_title():
    assert wiki_scope.normalize_title("Spike_Spiegel#Trivia") == "Spike Spiegel"
    assert wiki_scope.normalize_title("  deidara  ") == "Deidara"
    assert wiki_scope.normalize_title("Monkey_D._Luffy") == "Monkey D. Luffy"
    assert wiki_scope.normalize_title("") == ""


def test_arc_index_multiple_comma_separated_ranges():
    """Itachi Pursuit Mission covers eps 113-118, 121-126."""
    wt = """
{| class="wikitable sortable"
|-
! Arc Name
! Chapters
! Episodes
! Summary
|-
| [[Itachi Pursuit Mission]]
| 343-367
| 113-118, 121-126
| Pursuit.
|}
"""
    def fake_http(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": wt}}}
        return {"parse": {"wikitext": {"*": "== Plot ==\n[[Itachi Uchiha]] appears."}}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    # Episode 115 matches first range
    res1 = wiki_scope.resolve_scope(cfg, season=6, episode_numbers=[115], http=fake_http)
    assert "Itachi Uchiha" in res1.titles

    # Episode 120 (Kakashi Gaiden) does NOT match
    res_gap = wiki_scope.resolve_scope(cfg, season=6, episode_numbers=[120], http=fake_http)
    assert "Itachi Uchiha" not in res_gap.titles

    # Episode 125 matches second range
    res2 = wiki_scope.resolve_scope(cfg, season=6, episode_numbers=[125], http=fake_http)
    assert "Itachi Uchiha" in res2.titles


# ---- Tests: Leak 1 (SMW property links containing '::') ---------------------


def test_arc_index_drops_smw_double_colon_properties():
    smw_wt = """== Plot ==
[[Kakashi Hatake]] fights [[Zabuza Momochi]].
[[Anime Arc number::1]]
[[Anime::Boruto]]
[[Arc number::1]]
[[Anime::Naruto: Shippūden]]
"""
    def fake_http(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": NARUTO_INDEX_WIKITEXT}}}
        return {"parse": {"wikitext": {"*": smw_wt}}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=[5], http=fake_http)
    assert "Kakashi Hatake" in res.titles
    assert "Zabuza Momochi" in res.titles
    assert "Anime Arc number::1" not in res.titles
    assert "Anime::Boruto" not in res.titles
    assert "Arc number::1" not in res.titles
    assert "Anime::Naruto: Shippūden" not in res.titles


def test_season_page_drops_smw_double_colon_properties():
    links = [
        {"ns": 0, "*": "Ash Ketchum"},
        {"ns": 0, "*": "Anime::Boruto"},
        {"ns": 0, "*": "Arc number::1"},
    ]
    def fake_http(url):
        return {"parse": {"links": links}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert "Ash Ketchum" in res.titles
    assert "Anime::Boruto" not in res.titles
    assert "Arc number::1" not in res.titles


# ---- Tests: Leak 2 (EP code suffix and episode-list table extraction) -------


def test_season_page_drops_titles_ending_with_ep_code():
    links = [
        {"ns": 0, "*": "Ash Ketchum"},
        {"ns": 0, "*": "Anthony (EP029)"},
        {"ns": 0, "*": "A.J. (EP009)"},
    ]
    def fake_http(url):
        return {"parse": {"links": links}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert "Ash Ketchum" in res.titles
    assert "Anthony (EP029)" not in res.titles
    assert "A.J. (EP009)" not in res.titles


def test_season_page_drops_titles_from_episode_table_cells():
    table_wt = """== Episodes ==
{| class="roundy"
|-
! Epicode !! Episode Title !! Number
|-
| [[EP001]] || ''Pokémon - I Choose You!'' || 1
|-
| [[Holiday Hi-Jynx|*]] || ''Holiday Hi-Jynx'' || 62
|-
| [[Snow Way Out!|*]] || ''Snow Way Out!'' || 63
|}
"""
    links = [
        {"ns": 0, "*": "Ash Ketchum"},
        {"ns": 0, "*": "Holiday Hi-Jynx"},
        {"ns": 0, "*": "Snow Way Out!"},
        {"ns": 0, "*": "Pikachu (Pokémon)"},
    ]
    def fake_http(url):
        return {"parse": {"links": links, "wikitext": {"*": table_wt}}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert "Ash Ketchum" in res.titles
    assert "Pikachu (Pokémon)" in res.titles
    assert "Holiday Hi-Jynx" not in res.titles
    assert "Snow Way Out!" not in res.titles


def test_season_page_with_explicit_episode_list_page_cfg():
    ep_wt = """== List of Episodes ==
{| class="wikitable"
|-
! # !! Title !! Air Date
|-
| 1 || [[The First Adventure]] || 2020-01-01
|-
| 2 || [[The Second Adventure]] || 2020-01-08
|}
"""
    season_links = [
        {"ns": 0, "*": "Main Hero"},
        {"ns": 0, "*": "The First Adventure"},
        {"ns": 0, "*": "Sidekick"},
    ]
    def fake_http(url):
        if "Episode_List_S01" in url:
            return {"parse": {"wikitext": {"*": ep_wt}}}
        return {"parse": {"links": season_links}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://example.fandom.com/api.php",
        "season_page": "Season_{season:02d}",
        "episode_list_page": "Episode_List_S{season:02d}",
    }
    res = wiki_scope.resolve_scope(cfg, season=1, episode_numbers=None, http=fake_http)
    assert "Main Hero" in res.titles
    assert "Sidekick" in res.titles
    assert "The First Adventure" not in res.titles

