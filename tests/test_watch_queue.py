"""The watch gate. Its failure mode is not crashing -- it is returning a confident,
correctly-sorted, incomplete list, which is what each source does on its own."""

import pytest

import watch_queue as wq


def test_union_takes_the_newer_timestamp(monkeypatch):
    """One Pace is newer in WatchState (Jellyfin playback) than in Plex, by 40.0 days."""
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace": 1787280626})
    monkeypatch.setattr(wq, "from_plex", lambda s: {"One Pace": 1783822185})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace"])
    order, rep = wq.build(0, "/x")
    assert order == ["One Pace"] and rep["union"] == 1


def test_a_plex_only_show_survives(monkeypatch):
    """SPY x FAMILY is watched by another Plex account. WatchState imports one user, so it
    never sees it -- a WatchState-only queue would silently omit it."""
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace": 200})
    monkeypatch.setattr(wq, "from_plex", lambda s: {"SPY x FAMILY": 100})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace", "SPY x FAMILY (2022) {tvdb-405920}"])
    order, _ = wq.build(0, "/x")
    assert order == ["One Pace", "SPY x FAMILY (2022) {tvdb-405920}"]


def test_one_source_unreachable_refuses_to_write(monkeypatch):
    """A stale queue is safe. A queue narrowed by an outage is not."""

    def boom(s):
        raise wq.Unreachable("watchstate down")

    monkeypatch.setattr(wq, "from_watchstate", boom)
    monkeypatch.setattr(wq, "from_plex", lambda s: {"One Pace": 100})
    with pytest.raises(wq.Unreachable):
        wq.build(0, "/x")


def test_both_reachable_but_empty_also_refuses(monkeypatch):
    """'nothing watched' and 'cannot tell' are different facts."""
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {})
    monkeypatch.setattr(wq, "from_plex", lambda s: {})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace"])
    with pytest.raises(wq.Unreachable):
        wq.build(0, "/x")


def test_unreachable_out_file_is_left_untouched(monkeypatch, tmp_path, capsys):
    out = tmp_path / "anime_order.txt"
    out.write_text("One Pace\n")

    def boom(s):
        raise wq.Unreachable("plex down")

    monkeypatch.setattr(wq, "from_plex", boom)
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace": 100})
    assert wq.main(["--out", str(out)]) == 2
    assert out.read_text() == "One Pace\n"  # byte-identical


def test_zero_matched_shows_refuses_to_write_and_leaves_the_file_alone(monkeypatch, tmp_path, capsys):
    """A renamed library folder is real data on both sources that matches zero directories --
    a different fact from 'nothing watched' (empty sources, which build() itself refuses) and
    just as dangerous to write: an order file with zero shows idles the whole GPU sweep for
    RESCAN_INTERVAL with no log signal, while docker ps shows healthy."""
    out = tmp_path / "anime_order.txt"
    out.write_text("One Pace\n")
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace (renamed)": 100})
    monkeypatch.setattr(wq, "from_plex", lambda s: {})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace"])  # the old name -- nothing matches
    assert wq.main(["--out", str(out)]) == 2
    assert out.read_text() == "One Pace\n"  # byte-identical, not truncated to empty
    assert "REFUSING TO WRITE" in capsys.readouterr().err


def test_the_write_is_atomic_no_tmp_file_left_behind(monkeypatch, tmp_path):
    out = tmp_path / "order.txt"
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace": 100})
    monkeypatch.setattr(wq, "from_plex", lambda s: {"One Pace": 90})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace"])
    assert wq.main(["--out", str(out)]) == 0
    assert [p.name for p in tmp_path.iterdir()] == ["order.txt"]  # no order.txt.<x>.tmp survives


def test_title_matches_a_tvdb_suffixed_directory():
    dirs = ["SPY x FAMILY (2022) {tvdb-405920}", "One Pace"]
    order, misses = wq.match_dirs({"SPY x FAMILY": 5}, dirs)
    assert order == ["SPY x FAMILY (2022) {tvdb-405920}"] and misses == []


def test_html_escaped_plex_titles_match():
    """Plex returns `I&#39;m in Love with the Villainess`."""
    import html as _h

    dirs = ["I'm in Love with the Villainess (2023) {tvdb-1}"]
    order, misses = wq.match_dirs({_h.unescape("I&#39;m in Love with the Villainess"): 5}, dirs)
    assert order == dirs and misses == []


def test_an_unmatched_title_is_reported_not_dropped():
    """A library rename would otherwise shrink the queue invisibly."""
    order, misses = wq.match_dirs({"Renamed Show": 5}, ["One Pace"])
    assert order == [] and misses == ["Renamed Show"]


def test_ordering_is_most_recently_watched_first():
    dirs = ["A", "B", "C"]
    order, _ = wq.match_dirs({"A": 100, "B": 300, "C": 200}, dirs)
    assert order == ["B", "C", "A"]


def test_a_pinned_show_leads_even_if_long_unwatched(monkeypatch):
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"Trigun": 900})
    monkeypatch.setattr(wq, "from_plex", lambda s: {})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["Trigun", "One Pace"])
    order, _ = wq.build(0, "/x", pins=["One Pace"])
    assert order[0] == "One Pace"


def test_a_pin_resolves_through_the_same_matching_as_a_watched_title(monkeypatch):
    """R-6. A pin names a SHOW, not a directory: the operator writes `--pin Trigun Stampede`
    while the directory is `TRIGUN STAMPEDE (2023) {tvdb-421378}`. Inserting the raw string
    queued a path that does not exist and left the real one unpinned."""
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace": 900})
    monkeypatch.setattr(wq, "from_plex", lambda s: {})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace", "TRIGUN STAMPEDE (2023) {tvdb-421378}"])
    order, rep = wq.build(0, "/x", pins=["Trigun Stampede"])
    assert order[0] == "TRIGUN STAMPEDE (2023) {tvdb-421378}"
    assert rep["bad_pins"] == []


def test_an_invalid_pin_cannot_manufacture_a_queue_out_of_zero_matches(monkeypatch, tmp_path):
    """R-6, the reason this matters. The library was renamed, so no watched title matches
    anything -- exactly the state the zero-match refusal exists for. A stale `--pin` was
    inserted unvalidated, `order` came back non-empty, and main() happily overwrote a good
    order file with one nonexistent directory. gen_loop.sh then skipped it every pass."""
    out = tmp_path / "order.txt"
    out.write_text("One Pace\n")
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace (renamed)": 900})
    monkeypatch.setattr(wq, "from_plex", lambda s: {})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace"])

    order, rep = wq.build(0, "/x", pins=["One Pace (renamed)"])
    assert order == [], "a pin that names no library directory must not pad the queue"
    assert rep["bad_pins"] == ["One Pace (renamed)"], "and it must be reported, not swallowed"

    assert wq.main(["--out", str(out), "--root", "/x", "--pin", "One Pace (renamed)"]) == 2
    assert out.read_text() == "One Pace\n", "the previous order file must survive the refusal"


def test_dry_run_writes_nothing(monkeypatch, tmp_path):
    out = tmp_path / "order.txt"
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace": 100})
    monkeypatch.setattr(wq, "from_plex", lambda s: {"One Pace": 90})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace"])
    assert wq.main(["--out", str(out), "--dry-run"]) == 0
    assert not out.exists()


def test_a_queued_show_is_never_narrowed(monkeypatch, tmp_path):
    """The gate writes SHOW directories, never episode or season paths. Regenerating only
    already-watched episodes helps nobody."""
    out = tmp_path / "order.txt"
    monkeypatch.setattr(wq, "from_watchstate", lambda s: {"One Pace": 100})
    monkeypatch.setattr(wq, "from_plex", lambda s: {"One Pace": 90})
    monkeypatch.setattr(wq, "library_dirs", lambda r: ["One Pace"])
    wq.main(["--out", str(out)])
    assert out.read_text().strip().splitlines() == ["One Pace"]


def test_case_and_spacing_differences_still_match():
    """All three are real 2026-08-21 cases that exact matching dropped silently."""
    dirs = [
        "TRIGUN STAMPEDE (2023) {tvdb-421378}",
        "I'm in Love With the Villainess (2023) {tvdb-428350}",
        "MARRIAGETOXIN (2026) {tvdb-468734}",
    ]
    titles = {"Trigun Stampede": 3, "I'm in Love with the Villainess": 2, "Marriage Toxin": 1}
    order, misses = wq.match_dirs(titles, dirs)
    assert misses == []
    assert order == dirs[:1] + [dirs[1]] + [dirs[2]]


def test_an_ambiguous_fold_is_reported_not_guessed():
    """Two directories that fold together must not silently claim a title. Both differ
    from the title before the fold tier, so neither wins on an earlier tier."""
    dirs = ["TRIGUN STAMPEDE (2023) {tvdb-1}", "Trigun-Stampede (2023) {tvdb-2}"]
    order, misses = wq.match_dirs({"Trigun Stampede": 1}, dirs)
    assert order == [] and misses == ["Trigun Stampede"]


def test_an_exact_clean_match_beats_an_ambiguous_fold():
    """Ambiguity downstream must not poison a title that already matched cleanly."""
    dirs = ["Trigun Stampede (2023) {tvdb-1}", "TRIGUN STAMPEDE (2023) {tvdb-2}"]
    order, misses = wq.match_dirs({"Trigun Stampede": 1}, dirs)
    assert order == ["Trigun Stampede (2023) {tvdb-1}"] and misses == []


def test_fold_does_not_collide_distinct_villainess_shows():
    dirs = [
        "I'm in Love With the Villainess (2023) {tvdb-428350}",
        "The Dark History of the Reincarnated Villainess (2025) {tvdb-446238}",
    ]
    order, misses = wq.match_dirs({"I'm in Love with the Villainess": 1}, dirs)
    assert order == [dirs[0]] and misses == []


JOJO = ["JoJo's Bizarre Adventure (1993) {tvdb-83950}", "JoJo's Bizarre Adventure (2012) {tvdb-262954}"]


def test_an_ambiguous_clean_title_is_reported_not_guessed():
    """2026-09-25, live: Plex and WatchState both report the 2012 series as the bare
    "JoJo's Bizarre Adventure". Both directories clean to that, and the clean tier's
    setdefault() silently handed every play to the alphabetically-first (1993) OVA."""
    order, misses = wq.match_dirs({"JoJo's Bizarre Adventure": 1}, JOJO)
    assert order == [] and misses == ["JoJo's Bizarre Adventure"]


def test_a_tvdb_tagged_title_resolves_to_that_directory_even_when_the_name_is_shared():
    order, misses = wq.match_dirs({"JoJo's Bizarre Adventure {tvdb-262954}": 1}, JOJO)
    assert order == [JOJO[1]] and misses == []


def test_a_title_with_a_year_resolves_to_that_year():
    """Jellyfin-sourced WatchState rows carry "JoJo's Bizarre Adventure (2012)"."""
    order, misses = wq.match_dirs({"JoJo's Bizarre Adventure (2012)": 1}, JOJO)
    assert order == [JOJO[1]] and misses == []


def test_an_unknown_tvdb_id_falls_back_to_the_title():
    """A show whose id matches no directory still resolves by name when that is unambiguous."""
    order, misses = wq.match_dirs({"One Pace {tvdb-999}": 1}, ["One Pace"])
    assert order == ["One Pace"] and misses == []


def test_watchstate_tags_each_title_with_its_parent_tvdb(monkeypatch):
    import json

    rows = [
        {"type": "episode", "watched": 1, "updated": 500, "title": "JoJo's Bizarre Adventure", "parent": {"guid_tvdb": "262954"}},
        {"type": "episode", "watched": 1, "updated": 400, "title": "One Pace", "parent": {}},
    ]
    monkeypatch.setattr(wq, "WATCHSTATE_URL", "http://ws")
    monkeypatch.setattr(wq, "WATCHSTATE_API_KEY", "k")
    monkeypatch.setattr(wq, "_get", lambda url, headers=None: json.dumps({"history": rows, "paging": {"last_page": 1}}).encode())
    assert wq.from_watchstate(0) == {"JoJo's Bizarre Adventure {tvdb-262954}": 500, "One Pace": 400}


def test_plex_tags_each_title_with_its_show_tvdb(monkeypatch):
    """Plex history rows carry only grandparentTitle; the show's tvdb id is on its metadata."""
    history = (
        '<MediaContainer><Video grandparentTitle="JoJo&#39;s Bizarre Adventure" '
        'grandparentKey="/library/metadata/7" viewedAt="500"/>'
        '<Video grandparentTitle="One Pace" grandparentKey="/library/metadata/8" viewedAt="400"/></MediaContainer>'
    )
    shows = {
        "7": '<MediaContainer><Directory><Guid id="imdb://tt1"/><Guid id="tvdb://262954"/></Directory></MediaContainer>',
        "8": "<MediaContainer><Directory></Directory></MediaContainer>",
    }

    def fake_get(url, headers=None):
        if "/status/sessions/history/all" in url:
            return history.encode()
        return shows[url.split("/library/metadata/")[1].split("?")[0]].encode()

    monkeypatch.setattr(wq, "PLEX_URL", "http://plex")
    monkeypatch.setattr(wq, "PLEX_TOKEN", "t")
    monkeypatch.setattr(wq, "_get", fake_get)
    assert wq.from_plex(0) == {"JoJo's Bizarre Adventure {tvdb-262954}": 500, "One Pace": 400}


def test_a_failed_plex_show_lookup_keeps_the_bare_title(monkeypatch):
    """The id is an enrichment: its lookup failing must not turn a readable source unreachable."""
    history = (
        '<MediaContainer><Video grandparentTitle="One Pace" '
        'grandparentKey="/library/metadata/8" viewedAt="400"/></MediaContainer>'
    )

    def fake_get(url, headers=None):
        if "/status/sessions/history/all" in url:
            return history.encode()
        raise wq.Unreachable("metadata down")

    monkeypatch.setattr(wq, "PLEX_URL", "http://plex")
    monkeypatch.setattr(wq, "PLEX_TOKEN", "t")
    monkeypatch.setattr(wq, "_get", fake_get)
    assert wq.from_plex(0) == {"One Pace": 400}
