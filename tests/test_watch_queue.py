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
    monkeypatch.setattr(wq, "library_dirs",
                        lambda r: ["One Pace", "SPY x FAMILY (2022) {tvdb-405920}"])
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
    assert out.read_text() == "One Pace\n"          # byte-identical


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
    dirs = ["TRIGUN STAMPEDE (2023) {tvdb-421378}",
            "I'm in Love With the Villainess (2023) {tvdb-428350}",
            "MARRIAGETOXIN (2026) {tvdb-468734}"]
    titles = {"Trigun Stampede": 3, "I'm in Love with the Villainess": 2,
              "Marriage Toxin": 1}
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
    dirs = ["I'm in Love With the Villainess (2023) {tvdb-428350}",
            "The Dark History of the Reincarnated Villainess (2025) {tvdb-446238}"]
    order, misses = wq.match_dirs({"I'm in Love with the Villainess": 1}, dirs)
    assert order == [dirs[0]] and misses == []
