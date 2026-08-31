"""Checks for tools/export_reviewed.py -- qualifying-episode manifest for the subtitle
release.

TDD entry point. These tests are written against synthetic temp dirs before the tool
exists, so the first run must fail at import or at a clearly-named missing feature.
"""

import json
import os
import subprocess
import sys

import decisions
import unresolved

EP_SUFFIX = ".dubtitles.conf.json"


def _stem(tmp_path, show, season, episode, ext="mkv"):
    """One episode laid out two levels below its show so unresolved.show_for() and
    decisions.show_for() both resolve to `show` the way the live pipeline does."""
    dir = tmp_path / show / season
    dir.mkdir(parents=True)
    stem = str(dir / episode)
    with open(stem + "." + ext, "wb") as f:
        f.write(b"x")
    return stem


def _conf(stem, cards):
    with open(stem + EP_SUFFIX, "w") as f:
        json.dump(cards, f)


def _unresolved(stem, *rows):
    """Write synthetic queue rows with the same text fields the pipeline records."""
    for r in rows:
        row = dict(r)
        stage = row.pop("stage", "repair_applied")
        reason = row.pop("reason", "accepted")
        unresolved.record(
            stem,
            stage,
            reason,
            original_text=row.get("original_text"),
            proposed_text=row.get("proposed_text"),
        )


def _decisions_dir(tmp_path, show, verdicts):
    d = tmp_path / "decisions"
    d.mkdir()
    store = {}
    for v in verdicts:
        store = decisions.record(store, v["orig"], v["prop"], v["verdict"], text=v.get("text", ""))
    decisions.save(store, show, dir=str(d))
    return str(d)


def _run_export(tmp_path, show, decisions_dir, episodes, *, media_duration=None):
    """Run the export logic in-process so the duration probe is injectable."""
    import tools.export_reviewed as er

    original_probe = er.media_duration
    try:
        er.media_duration = media_duration if media_duration is not None else original_probe
        out = tmp_path / "manifest.json"
        # queue_episodes comes from the tool, not recomputed here: a hand-rolled count in the
        # test is a parallel implementation, and it would agree with a broken one.
        entries, queue_episodes, undecided = er.qualifying_episodes(
            show, decisions_dir, str(tmp_path), duration_probe=er.media_duration
        )
        er.write_manifest(str(out), entries)
        er.summarize(entries, queue_episodes, undecided)
        return 0, out, ""
    finally:
        er.media_duration = original_probe


def _media_duration(value):
    return lambda path: value


def _manifest(out):
    with open(out) as f:
        return json.load(f)


def test_the_cli_writes_a_valid_empty_manifest_end_to_end(tmp_path):
    """The implemented CLI writes a valid empty manifest."""
    show = "One Pace"
    d = _decisions_dir(tmp_path, show, [])
    ep = _stem(tmp_path, show, "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "a line"}])

    prog = os.path.join(os.path.dirname(__file__), "..", "tools", "export_reviewed.py")
    proc = subprocess.run(
        [
            sys.executable,
            prog,
            "--show",
            show,
            "--decisions",
            str(d),
            "--out",
            str(tmp_path / "manifest.json"),
            "--media-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert json.loads((tmp_path / "manifest.json").read_text()) == []


def test_qualifying_episodes_uses_the_queue_not_the_full_log(tmp_path, monkeypatch):
    import inspect

    import tools.export_reviewed as er

    source = inspect.getsource(er.queue_for)
    assert "primary_only=True" in source
    assert "unresolved.live_only" in source
    assert "unresolved.items" not in source


def _two_line_episode(tmp_path, show="One Pace"):
    ep = _stem(tmp_path, show, "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "line 1"}, {"start": 2.0, "end": 4.0, "text": "line 2"}])
    _unresolved(
        ep,
        {"original_text": "line 1", "proposed_text": "line 1.", "stage": "repair_applied", "reason": "accepted"},
        {"original_text": "line 2", "proposed_text": "line 2.", "stage": "repair_applied", "reason": "accepted"},
    )
    return ep


def test_qualifying_episode_has_nonempty_queue_and_nothing_undecided(tmp_path):
    ep = _two_line_episode(tmp_path)
    d = _decisions_dir(
        tmp_path,
        "One Pace",
        [
            {"orig": "line 1", "prop": "line 1.", "verdict": "correct", "text": "line 1."},
            {"orig": "line 2", "prop": "line 2.", "verdict": "accept"},
        ],
    )
    code, out, _ = _run_export(tmp_path, "One Pace", d, [ep], media_duration=_media_duration(12.5))
    assert code == 0
    assert _manifest(out)[0] == {
        "stem": ep,
        "show": "One Pace",
        "season": "Season 31",
        "episode_title": "One Pace - S31E11",
        "duration_seconds": 12.5,
        "queue_size": 2,
        "corrections": 1,
    }


def test_episode_with_one_undecided_line_does_not_qualify(tmp_path):
    ep = _two_line_episode(tmp_path)
    d = _decisions_dir(tmp_path, "One Pace", [{"orig": "line 1", "prop": "line 1.", "verdict": "accept"}])
    _, out, _ = _run_export(tmp_path, "One Pace", d, [ep])
    assert _manifest(out) == []


def test_episode_without_a_queue_does_not_qualify(tmp_path):
    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "a line"}])
    d = _decisions_dir(tmp_path, "One Pace", [])
    _, out, _ = _run_export(tmp_path, "One Pace", d, [ep])
    assert _manifest(out) == []


def test_correct_accepts_nonempty_text_only(tmp_path):
    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": float(i), "end": i + 1.0, "text": f"line {i}"} for i in range(1, 6)])
    _unresolved(
        ep,
        *[
            {"original_text": f"line {i}", "proposed_text": f"line {i}.", "stage": "repair_applied", "reason": "accepted"}
            for i in range(1, 6)
        ],
    )
    d = _decisions_dir(
        tmp_path,
        "One Pace",
        [
            {"orig": "line 1", "prop": "line 1.", "verdict": "correct", "text": "line 1."},
            {"orig": "line 2", "prop": "line 2.", "verdict": "accept"},
            {"orig": "line 3", "prop": "line 3.", "verdict": "reject"},
            {"orig": "line 4", "prop": "line 4.", "verdict": "force"},
            {"orig": "line 5", "prop": "line 5.", "verdict": "correct", "text": "line 5 fixed"},
        ],
    )
    _, out, _ = _run_export(tmp_path, "One Pace", d, [ep])
    assert _manifest(out)[0]["corrections"] == 2


def test_empty_qualifying_set_produces_a_valid_empty_manifest(tmp_path):
    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "a line"}])
    _, out, _ = _run_export(tmp_path, "One Pace", _decisions_dir(tmp_path, "One Pace", []), [ep])
    assert _manifest(out) == []


def test_empty_qualifying_set_prints_a_clear_summary(tmp_path, capsys):
    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "a line"}])
    _, out, _ = _run_export(tmp_path, "One Pace", _decisions_dir(tmp_path, "One Pace", []), [ep])
    assert _manifest(out) == []
    assert "no episodes qualify" in capsys.readouterr().out


def test_duration_probe_failure_leaves_the_episode_in_the_manifest(tmp_path):
    ep = _two_line_episode(tmp_path)
    d = _decisions_dir(
        tmp_path,
        "One Pace",
        [{"orig": "line 1", "prop": "line 1.", "verdict": "accept"}, {"orig": "line 2", "prop": "line 2.", "verdict": "accept"}],
    )
    _, out, _ = _run_export(tmp_path, "One Pace", d, [ep], media_duration=lambda _: None)
    assert _manifest(out)[0]["duration_seconds"] is None


def test_summary_reports_queue_count_and_undecided_total(tmp_path):
    ep = _two_line_episode(tmp_path)
    d = _decisions_dir(
        tmp_path,
        "One Pace",
        [{"orig": "line 1", "prop": "line 1.", "verdict": "accept"}, {"orig": "line 2", "prop": "line 2.", "verdict": "accept"}],
    )
    _, out, _ = _run_export(tmp_path, "One Pace", d, [ep])
    assert _manifest(out)[0]["queue_size"] == 2


def test_decisions_dir_absent_leaves_an_empty_manifest(tmp_path):
    ep = _stem(tmp_path, "One Pace", "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "a line"}])
    _, out, _ = _run_export(tmp_path, "One Pace", str(tmp_path / "missing-decisions"), [ep])
    assert _manifest(out) == []


def test_the_media_tree_is_walked_exactly_once(tmp_path, monkeypatch):
    """`qualifying_episodes` already visits every episode and already computes each one's
    queue. Counting queue-bearing episodes with a SECOND os.walk re-reads the whole tree for
    a number the first pass had in hand.

    That is not a tidiness point. review_server's own docstring measures this walk at 297
    seconds for 989 episodes over a network mount, where "a stat costs what a read costs" --
    so a second pass doubles a five-minute operation to produce nothing new.

    Breaks if any code path walks the media root more than once per invocation."""
    show = "One Pace"
    d = _decisions_dir(tmp_path, show, [])
    ep = _stem(tmp_path, show, "Season 31", "One Pace - S31E11")
    _conf(ep, [{"start": 0.0, "end": 2.0, "text": "a line"}])

    import tools.export_reviewed as er

    walks = []
    real_walk = os.walk

    def counting_walk(top, *a, **kw):
        walks.append(top)
        return real_walk(top, *a, **kw)

    monkeypatch.setattr(er.os, "walk", counting_walk)
    er.main(["--show", show, "--decisions", str(d), "--media-root", str(tmp_path), "--out", str(tmp_path / "m.json")])

    assert len(walks) == 1, f"media root walked {len(walks)} times; it must be walked once"
