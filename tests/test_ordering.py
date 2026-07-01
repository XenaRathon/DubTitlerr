"""Unit tests for ordering.py — watch-order season priority for the --root walk.

Lets a library run process the seasons a viewer is ABOUT to watch (>= a start season)
before the ones they've already seen, instead of a flat S01->S36 alphabetical grind.
Pure stdlib; paths are plain strings. Built with help of Claude (Anthropic)."""
import ordering as o

BASE = "/media/Anime Library/One Pace"


def paths(*specs):
    # spec "20:1" -> ".../Season 20/One Pace - S20E01 - t.mkv"
    out = []
    for s in specs:
        se, ep = s.split(":")
        out.append(f"{BASE}/Season {int(se):02d}/One Pace - S{int(se):02d}E{int(ep):02d} - t.mkv")
    return out


# --- season_ep parsing -------------------------------------------------------

def test_season_ep_parses_numeric():
    assert o.season_ep(paths("20:1")[0]) == (20, 1)
    assert o.season_ep(paths("1:10")[0]) == (1, 10)


def test_season_ep_unmatched_is_high_sentinel():
    s, e = o.season_ep("/media/Anime Library/One Pace/Specials/A Movie.mkv")
    assert s == o.NO_SEASON and e == 0


# --- order_files: start disabled = plain lexical -----------------------------

def test_order_start_zero_is_plain_sorted():
    files = paths("20:1", "1:2", "3:1")
    assert o.order_files(files, 0) == sorted(files)


# --- order_files: watch-order priority ---------------------------------------

def test_order_puts_start_season_and_after_first():
    files = paths("1:2", "18:1", "20:1", "21:5", "36:2")
    out = o.order_files(files, 20)
    # S20, S21, S36 (>= 20) come before S01, S18 (< 20)
    assert out == paths("20:1", "21:5", "36:2", "1:2", "18:1")


def test_order_within_group_is_season_then_episode_numeric():
    files = paths("21:10", "20:2", "20:10", "21:2")
    out = o.order_files(files, 20)
    assert out == paths("20:2", "20:10", "21:2", "21:10")


def test_order_low_group_also_ascending():
    files = paths("18:1", "2:1", "1:3")
    out = o.order_files(files, 20)
    assert out == paths("1:3", "2:1", "18:1")


def test_order_unmatched_files_sort_last_but_stable():
    weird = "/media/Anime Library/One Pace/poster-clip.mkv"
    files = paths("1:1", "20:1") + [weird]
    out = o.order_files(files, 20)
    assert out[-1] == weird
    assert out[:2] == paths("20:1", "1:1")


# --- read_start: config file + env fallback ----------------------------------

def test_read_start_from_file(tmp_path):
    f = tmp_path / "season_priority.txt"
    f.write_text("# watch positions\nOne Pace:20\nJoJo's Bizarre Adventure:3\n")
    assert o.read_start("One Pace", str(f)) == 20
    assert o.read_start("JoJo's Bizarre Adventure", str(f)) == 3


def test_read_start_unknown_show_is_zero(tmp_path):
    f = tmp_path / "season_priority.txt"
    f.write_text("One Pace:20\n")
    assert o.read_start("Cowboy Bebop", str(f)) == 0


def test_read_start_missing_file_is_zero(tmp_path):
    assert o.read_start("One Pace", str(tmp_path / "nope.txt")) == 0


def test_read_start_env_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("SEASON_START", "5")
    # no file -> env wins
    assert o.read_start("Anything", str(tmp_path / "nope.txt")) == 5


def test_read_start_file_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SEASON_START", "5")
    f = tmp_path / "season_priority.txt"
    f.write_text("One Pace:20\n")
    assert o.read_start("One Pace", str(f)) == 20
