"""wiki_scope against the real 'Plot of Naruto' wikitext (tests/fixtures/plot_of_naruto.wikitext), hosts, header variants.

No network: every request goes to an injected function."""

import os
import urllib.parse as up

import pytest

import wiki_scope

FIXTURE = open(os.path.join(os.path.dirname(__file__), "fixtures", "plot_of_naruto.wikitext"), encoding="utf-8").read()
WIKI = "https://naruto.fandom.com/api.php"


class FakeWiki:
    """Serves the index page from the fixture (or a given text), arc pages with a fixed link list, no redirects."""

    def __init__(self, index_text=FIXTURE, fail_redirects=False):
        self.index_text, self.fail_redirects = index_text, fail_redirects
        self.pages = []

    def __call__(self, url):
        if "redirects=1" in url:
            if self.fail_redirects:
                raise OSError("redirects down")
            return {"query": {"redirects": []}}
        page = up.unquote(url.split("page=")[1].split("&")[0])
        self.pages.append(page)
        if page == "Plot of Naruto":
            return {"parse": {"wikitext": {"*": self.index_text}}}
        return {"parse": {"wikitext": {"*": f"[[Naruto Uzumaki]] [[Sakura Haruno]] [[{page} Character]]"}}}

    def arc_pages(self):
        return [p for p in self.pages if p != "Plot of Naruto"]


def cfg(**extra):
    return {"rung": "arc_index", "wiki": WIKI, "index_page": "Plot of Naruto", **extra}


# ---- host allowlist: dot-anchored suffix --------------------------- ----


@pytest.mark.parametrize(
    "wiki",
    [
        "https://evilfandom.com/api.php",
        "https://fandom.com.evil.com/api.php",
        "https://xbulbapedia.bulbagarden.net/w/api.php",
        "https://bulbapedia.bulbagarden.net.evil.com/w/api.php",
        "http://naruto.fandom.com/api.php",
    ],
)
def test_a_lookalike_or_plain_http_host_is_rejected_before_any_request(wiki):
    def boom(url):
        raise AssertionError("no request may be made")

    res = wiki_scope.resolve_scope({"rung": "whole_wiki", "wiki": wiki}, http=boom)
    assert res.complete is False and res.titles == set() and ("disallowed" in res.notes[0] or "https" in res.notes[0])


@pytest.mark.parametrize(
    "wiki", ["https://naruto.fandom.com/api.php", "https://fandom.com/api.php", "https://bulbapedia.bulbagarden.net/w/api.php"]
)
def test_the_real_hosts_are_accepted(wiki):
    ok, _ = wiki_scope._validate_wiki_url(wiki)
    assert ok


def test_the_season_rung_redirect_failure_makes_the_result_incomplete():
    def http(url):
        if "redirects=1" in url:
            raise OSError("down")
        return {"parse": {"wikitext": {"*": "[[Pikachu]] [[Ash Ketchum]]"}, "links": [{"ns": 0, "*": "Pikachu"}]}}

    res = wiki_scope.resolve_scope(
        {"rung": "season_page", "wiki": "https://bulbapedia.bulbagarden.net/w/api.php"}, season=1, http=http
    )
    assert res.complete is False and "Pikachu" in res.titles and any("redirect" in n for n in res.notes)


# ---- the real Naruto table ----------------------------------------- ----


def test_part_one_episodes_1_to_19_select_only_the_prologue():
    wiki = FakeWiki()
    res = wiki_scope.resolve_scope(cfg(part="Part I"), season=1, episode_numbers=list(range(1, 20)), http=wiki)
    assert res.complete is True and wiki.arc_pages() == ["Prologue — Land of Waves"]
    assert {"Naruto Uzumaki", "Sakura Haruno"} <= res.titles


def test_part_one_episodes_20_to_67_select_the_chunin_exams_arc():
    wiki = FakeWiki()
    res = wiki_scope.resolve_scope(cfg(part="Part I"), season=1, episode_numbers=[20, 45, 67], http=wiki)
    assert res.complete is True and wiki.arc_pages() == ["Chūnin Exams (Arc)"]


def test_an_episode_beyond_the_last_row_is_incomplete():
    wiki = FakeWiki()
    res = wiki_scope.resolve_scope(cfg(part="Part I"), season=1, episode_numbers=[999], http=wiki)
    assert res.complete is False and res.titles == set() and wiki.arc_pages() == []


def test_an_episode_in_a_gap_between_rows_is_incomplete():
    """Episode 101 is in no Part I row (Search for Tsunade ends at 100, Land of Tea starts at 102)."""
    res = wiki_scope.resolve_scope(cfg(part="Part I"), season=1, episode_numbers=[100, 101], http=FakeWiki())
    assert res.complete is False and any("101" in n for n in res.notes)


def test_the_part_two_table_uses_shippuden_numbers_plus_the_season_offset():
    """Part II rows restart at 1 (Shippuden numbering): season 2 episode 5 with an offset of 32 is absolute 37."""
    wiki = FakeWiki()
    res = wiki_scope.resolve_scope(cfg(part="Part II", season_offsets={"2": 32}), season=2, episode_numbers=[5], http=wiki)
    assert res.complete is True and wiki.arc_pages() == ["Tenchi Bridge Reconnaissance Mission"]


def test_without_a_part_the_overlapping_tables_are_ambiguous_not_merged():
    """Part I, Part II and the New Era tables all number from 1: merging them would pick arcs of four different series."""
    wiki = FakeWiki()
    res = wiki_scope.resolve_scope(cfg(), season=1, episode_numbers=[5], http=wiki)
    assert res.complete is False and res.titles == set() and wiki.arc_pages() == []
    assert any("part" in n.lower() for n in res.notes)


def test_a_season_to_part_map_chooses_the_table_per_season():
    wiki = FakeWiki()
    c = cfg(season_parts={"1": "Part I", "2": "Part II"})
    wiki_scope.resolve_scope(c, season=1, episode_numbers=[1], http=wiki)
    wiki_scope.resolve_scope(c, season=2, episode_numbers=[1], http=wiki)
    assert wiki.arc_pages() == ["Prologue — Land of Waves", "Kazekage Rescue Mission"]


def test_a_range_written_as_link_text_is_read():
    """New Era rows like `[[Steam Ninja Scrolls Arc|106-111]]` carry the episode range as the link's display text."""
    arcs, notes, _parts = wiki_scope._parse_arc_rows(FIXTURE, part="New Era: Part I")
    assert dict(arcs)["Konoha Shinden: Steam Ninja Scrolls"] == set(range(106, 112)) and not notes


def test_a_table_with_a_title_column_is_read_when_it_has_no_arc_column():
    """The Blank Period table is headed Title / Episodes / Summary."""
    arcs, _notes, _parts = wiki_scope._parse_arc_rows(FIXTURE, part="Blank Period")
    assert dict(arcs)["Shikamaru Hiden: A Cloud Drifting in Silent Darkness"] == set(range(489, 494))


def test_rows_whose_episodes_are_n_a_or_a_dash_are_skipped():
    arcs, _n, _p = wiki_scope._parse_arc_rows(FIXTURE, part="New Era: Part II")
    assert arcs == []  # every episode cell is N/A: the manga continuation has no anime episodes


# ---- episode / arc header variants and overrides ------------------- ----


def _table(header, cell):
    return f'{{| class="wikitable"\n|-\n! Arc Name\n! {header}\n|-\n| [[The Arc]]\n| {cell}\n|}}'


@pytest.mark.parametrize("header", ["Ep.", "Ep", "Eps", "Eps.", "Episodes", "Episode", "Anime"])
def test_the_episode_header_variants(header):
    arcs, _n, _p = wiki_scope._parse_arc_rows(_table(header, "1-3"))
    assert arcs == [("The Arc", {1, 2, 3})]


@pytest.mark.parametrize("header", ["Chapters", "Step", "Epic", "Reps"])
def test_other_headers_are_not_episode_columns(header):
    assert wiki_scope._parse_arc_rows(_table(header, "1-3"))[0] == []


@pytest.mark.parametrize(
    "cell,expected", [("1–19", set(range(1, 20))), ("1—3", {1, 2, 3}), ("1-3, 7, 9–10", {1, 2, 3, 7, 9, 10}), ("&ndash;", set())]
)
def test_dash_styles_and_comma_lists(cell, expected):
    arcs, _n, _p = wiki_scope._parse_arc_rows(_table("Episodes", cell))
    assert (arcs[0][1] if arcs else set()) == expected


def test_episode_column_and_arc_column_overrides():
    wt = '{| class="wikitable"\n|-\n! Saga\n! Aired\n|-\n| [[The Saga]]\n| 4-5\n|}'
    assert wiki_scope._parse_arc_rows(wt)[0] == []
    arcs, _n, _p = wiki_scope._parse_arc_rows(wt, arc_column="Saga", episode_column="Aired")
    assert arcs == [("The Saga", {4, 5})]
