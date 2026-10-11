import urllib.parse

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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
    index_with_bad_row = NARUTO_INDEX_WIKITEXT.replace(
        "|}",
        """|-
| [[Unparseable Arc]]
| invalid_chapters
| not_an_episode_number
| Some text
|}""",
    )

    def fake_http(url):
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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
        if "action=query" in url and "redirects=1" in url:
            return {"query": {"redirects": []}}
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


# ---- Tests for task 5: items 1-6 --------------------------------------------

PLOT_WITH_CHAPTERS_FIRST = """{| class="wikitable"
! Manga chapters !! Arc !! Anime episodes !! Volumes
|-
| [[Chapter 1]]–8 || [[Prologue — Land of Waves|Land of Waves]] || 1–19 || 1–3
|-
| [[Chapter 34|34]]–115 || [[Chūnin Exam Arc|Chūnin Exams]] || 20–67 || 4–13
|-
| 116–138 || [[Konoha Crush]] || 68–80 || 13–15
|}
== Characters ==
{| class="wikitable"
! Character !! Debut !! Episodes
|-
| [[Naruto Uzumaki]] || 1 || 1–220
|}
"""

ARC_PAGES_FIXTURE = {
    "Prologue — Land of Waves": (
        "[[Zabuza Momochi]] fought [[Kakashi_Hatake#Abilities|Kakashi]] and [[haku]]; "
        "see [[Template:Infobox]] [[User:Admin]] [[Category:Arcs]]"
    ),
    "Chūnin Exam Arc": "[[Orochimaru]] [[Gaara]]",
    "Konoha Crush": "[[Hiruzen Sarutobi]]",
    "Naruto Uzumaki": "[[Every Character Ever]] [[Hinata Hyūga]]",
    "Chapter 1": "[[Manga Only Person]]",
}


def test_arc_index_empty_or_partial_evidence_complete_false():
    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    # 1. Prose only (no parseable arc rows)
    res_prose = wiki_scope.resolve_scope(
        cfg, None, [1], lambda url: {"parse": {"wikitext": {"*": "Naruto is a story about ninjas."}}}
    )
    assert res_prose.complete is False
    assert res_prose.titles == set()

    # 2. Episodes beyond table (500-520)
    def fake_plot(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        return {"parse": {"wikitext": {"*": ""}}}

    res_beyond = wiki_scope.resolve_scope(cfg, None, range(500, 521), fake_plot)
    assert res_beyond.complete is False
    assert res_beyond.titles == set()

    # 3. Partially uncovered episodes (e.g. 1-19 and 500)
    res_uncovered = wiki_scope.resolve_scope(cfg, None, [1, 500], fake_plot)
    assert res_uncovered.complete is False


def test_season_page_episode_list_page_failure_or_error_complete_false():
    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
        "episode_list_page": "List of episodes S{season:02d}",
    }
    # Failure (exception)
    def fake_fail(url):
        if "List%20of%20episodes" in url or "List_of_episodes" in url:
            raise OSError("network boom")
        return {"parse": {"links": [{"ns": 0, "*": "Ash Ketchum"}]}}

    res_fail = wiki_scope.resolve_scope(cfg, 1, None, fake_fail)
    assert res_fail.complete is False

    # Error response
    def fake_err(url):
        if "List%20of%20episodes" in url or "List_of_episodes" in url:
            return {"error": {"code": "missingtitle"}}
        return {"parse": {"links": [{"ns": 0, "*": "Ash Ketchum"}]}}

    res_err = wiki_scope.resolve_scope(cfg, 1, None, fake_err)
    assert res_err.complete is False


def test_arc_page_failure_or_error_keeps_complete_false():
    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    # Arc page fetch raises exception
    def fake_fail(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        if "Prologue" in url:
            raise OSError("arc fetch failed")
        return {"parse": {"wikitext": {"*": ""}}}

    res_fail = wiki_scope.resolve_scope(cfg, None, [5], fake_fail)
    assert res_fail.complete is False

    # Arc page returns error response
    def fake_err(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        if "Prologue" in url:
            return {"error": {"code": "missingtitle"}}
        return {"parse": {"wikitext": {"*": ""}}}

    res_err = wiki_scope.resolve_scope(cfg, None, [5], fake_err)
    assert res_err.complete is False


def test_whole_wiki_page_cap_sets_complete_false():
    def fake_allpages(url):
        return {
            "query": {"allpages": [{"title": "Page"}]},
            "continue": {"apcontinue": "TOKEN"},
        }
    cfg = {"rung": "whole_wiki", "wiki": "https://naruto.fandom.com/api.php"}
    res = wiki_scope.resolve_scope(cfg, None, None, fake_allpages)
    assert res.complete is False
    assert any("exceeded 10-page limit" in n for n in res.notes)


def test_arc_index_parser_chapter_column_first_and_skips_character_tables():
    def fake_http(url):
        if "redirects=1" in url:  # nothing redirects (an API error here would now be incomplete evidence)
            return {"query": {"redirects": []}}
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        for name, wt in ARC_PAGES_FIXTURE.items():
            if urllib.parse.quote(name) in url or name in url:
                return {"parse": {"wikitext": {"*": wt}}}
        return {"error": {"code": "missingtitle"}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    res = wiki_scope.resolve_scope(cfg, None, range(1, 20), fake_http)
    assert res.complete is True
    # Must pick Land of Waves, not Chapter 1
    assert "Manga Only Person" not in res.titles
    assert "Zabuza Momochi" in res.titles
    # Character table must be skipped
    assert "Every Character Ever" not in res.titles
    assert "Hinata Hyūga" not in res.titles


def test_bad_config_or_input_returns_result_without_raising():
    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    # season_offsets bad values
    res1 = wiki_scope.resolve_scope({**cfg, "season_offsets": {"2": "nineteen"}}, 2, [1], lambda u: {})
    assert res1.complete is False
    assert res1.rung == "arc_index"
    assert len(res1.notes) >= 1

    res2 = wiki_scope.resolve_scope({**cfg, "season_offsets": {"2": None}}, 2, [1], lambda u: {})
    assert res2.complete is False
    assert res2.rung == "arc_index"

    # episode_numbers bad values
    res3 = wiki_scope.resolve_scope(cfg, None, ["x"], lambda u: {})
    assert res3.complete is False
    assert res3.rung == "arc_index"


def test_arc_page_normalised_links_and_non_ns0_dropped():
    def fake_http(url):
        if "redirects=1" in url:  # the redirect step: nothing redirects (an API error here would now be incomplete evidence)
            return {"query": {"redirects": []}}
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        if "Prologue" in url:
            return {"parse": {"wikitext": {"*": ARC_PAGES_FIXTURE["Prologue — Land of Waves"]}}}
        return {"error": {"code": "missingtitle"}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    res = wiki_scope.resolve_scope(cfg, None, range(1, 20), fake_http)
    assert res.complete is True
    # Normalized links
    assert "Kakashi Hatake" in res.titles
    assert "Haku" in res.titles
    # Non-ns0 namespaces dropped
    assert "Template:Infobox" not in res.titles
    assert "User:Admin" not in res.titles
    assert "Category:Arcs" not in res.titles


def test_redirect_resolution_for_arc_and_season_rungs():
    # Arc rung redirect resolution
    def fake_arc(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        if "Prologue" in url:
            return {"parse": {"wikitext": {"*": "[[Zabuza]] fought [[Kakashi Hatake]]"}}}
        if "action=query" in url and "redirects=1" in url:
            return {
                "query": {
                    "redirects": [{"from": "Zabuza", "to": "Zabuza Momochi"}]
                }
            }
        return {"error": {"code": "missingtitle"}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    res = wiki_scope.resolve_scope(cfg, None, [1], fake_arc)
    assert "Zabuza Momochi" in res.titles

    # Season rung redirect resolution
    def fake_season(url):
        if "page=S01" in url:
            return {"parse": {"links": [{"ns": 0, "*": "Ash"}, {"ns": 0, "*": "Pikachu"}]}}
        if "action=query" in url and "redirects=1" in url:
            return {
                "query": {
                    "redirects": [{"from": "Ash", "to": "Ash Ketchum"}]
                }
            }
        return {"error": {"code": "missingtitle"}}

    scfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
    }
    sres = wiki_scope.resolve_scope(scfg, 1, None, fake_season)
    assert "Ash Ketchum" in sres.titles


def test_redirect_resolution_failure_sets_complete_false():
    def fake_fail_redir(url):
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        if "Prologue" in url:
            return {"parse": {"wikitext": {"*": "[[Zabuza Momochi]]"}}}
        if "action=query" in url and "redirects=1" in url:
            raise OSError("redirects network error")
        return {"error": {"code": "missingtitle"}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    res = wiki_scope.resolve_scope(cfg, None, [1], fake_fail_redir)
    assert res.complete is False


def test_host_safety_rejects_insecure_or_disallowed_hosts(monkeypatch):
    # Insecure scheme http://
    res_http = wiki_scope.resolve_scope(
        {"rung": "arc_index", "wiki": "http://naruto.fandom.com/api.php"}, 1, [1], lambda u: {}
    )
    assert res_http.rung == "none"
    assert res_http.complete is False

    # Disallowed host
    res_bad = wiki_scope.resolve_scope(
        {"rung": "arc_index", "wiki": "https://169.254.169.254/latest"}, 1, [1], lambda u: {}
    )
    assert res_bad.rung == "none"
    assert res_bad.complete is False

    # Allowed via WIKI_HOST_ALLOW
    monkeypatch.setenv("WIKI_HOST_ALLOW", "custom.wiki.org,another.org")
    calls = []
    def fake_custom(url):
        calls.append(url)
        return {"error": {"code": "missingtitle"}}
    res_allow = wiki_scope.resolve_scope(
        {"rung": "arc_index", "wiki": "https://custom.wiki.org/api.php", "index_page": "Index"}, 1, [1], fake_custom
    )
    assert res_allow.rung == "arc_index"


def test_season_page_plain_replace_instead_of_str_format():
    calls = []
    def fake(url):
        calls.append(url)
        return {"parse": {"links": []}}

    scfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "{season.__class__.__mro__}",
    }
    # Should not raise AttributeError/KeyError from str.format evaluating __class__
    wiki_scope.resolve_scope(scfg, 1, None, fake)
    assert len(calls) == 1
    assert urllib.parse.quote("{season.__class__.__mro__}") in calls[0]


def test_default_deny_list_additions():
    links = [
        {"ns": 0, "*": "Ash Ketchum"},
        {"ns": 0, "*": "List of Pokémon episodes"},
        {"ns": 0, "*": "Sakura (disambiguation)"},
        {"ns": 0, "*": "Season 1"},
        {"ns": 0, "*": "Series 2"},
    ]
    def fake(url):
        return {"parse": {"links": links}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
    }
    res = wiki_scope.resolve_scope(cfg, 1, None, fake)
    assert "Ash Ketchum" in res.titles
    assert "List of Pokémon episodes" not in res.titles
    assert "Sakura (disambiguation)" not in res.titles
    assert "Season 1" not in res.titles
    assert "Series 2" not in res.titles


def test_season_page_drops_non_ns0_links():
    links = [
        {"ns": 0, "*": "Ash Ketchum"},
        {"ns": 10, "*": "Template:Season"},
        {"ns": 14, "*": "Category:Anime"},
    ]
    def fake(url):
        return {"parse": {"links": links}}

    cfg = {
        "rung": "season_page",
        "wiki": "https://bulbapedia.bulbagarden.net/w/api.php",
        "season_page": "S{season:02d}",
    }
    res = wiki_scope.resolve_scope(cfg, 1, None, fake)
    assert "Ash Ketchum" in res.titles
    assert "Template:Season" not in res.titles
    assert "Category:Anime" not in res.titles


def test_range_last_episode_included():
    def fake_http(url):
        if "redirects=1" in url:  # the redirect step: nothing redirects (an API error here would now be incomplete evidence)
            return {"query": {"redirects": []}}
        if "Plot" in url:
            return {"parse": {"wikitext": {"*": PLOT_WITH_CHAPTERS_FIRST}}}
        if "Prologue" in url:
            return {"parse": {"wikitext": {"*": "[[Zabuza Momochi]]"}}}
        return {"error": {"code": "missingtitle"}}

    cfg = {
        "rung": "arc_index",
        "wiki": "https://naruto.fandom.com/api.php",
        "index_page": "Plot of Naruto",
    }
    # Episode 19 is the LAST episode of Land of Waves (1-19)
    res = wiki_scope.resolve_scope(cfg, None, [19], fake_http)
    assert res.complete is True
    assert "Zabuza Momochi" in res.titles


