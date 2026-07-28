"""Unit tests for the one-time stamp migration (scripts/migrate_write_v1_stamps.py).

Context: the strip-at-mux change made the version-aware .dubtitles.done stamp the ONLY
"already muxed" guard -- the ffprobe "has a Dubtitles track" backstop that generate.py
and mux.py used to fall back on is gone. A file muxed before stamps existed (or one
whose stamp was lost) therefore reads as STALE and would be fully re-transcribed and
re-muxed on the next sweep. This script closes that gap before deploy by writing the
grandfather stamp for exactly those files. No media is touched; hermetic here (ffprobe
stubbed, tmp_path only).
"""
import json
import os
import types

import common
import scripts.migrate_write_v1_stamps as mig


def _stub_ffprobe(monkeypatch, titles):
    """ffprobe answers with one subtitle stream per entry in `titles` (None = untagged)."""
    streams = [{"index": i, "tags": ({} if t is None else {"title": t})}
               for i, t in enumerate(titles)]

    def run(cmd, **kw):
        return types.SimpleNamespace(stdout=json.dumps({"streams": streams}), returncode=0)

    monkeypatch.setattr(mig.subprocess, "run", run)


def _video(tmp_path, name="ep.mkv"):
    v = tmp_path / name
    v.write_bytes(b"x" * 100)
    return str(v)


def _stamp_path(video):
    return video.rsplit(".", 1)[0] + common.STAMP_SUFFIX


# --- detection ----------------------------------------------------------------

def test_has_dubtitles_track_detects_our_track(monkeypatch, tmp_path):
    _stub_ffprobe(monkeypatch, ["English (Fansub)", common.TRACK_NAME])
    assert mig.has_dubtitles_track(_video(tmp_path))


def test_has_dubtitles_track_false_without_our_track(monkeypatch, tmp_path):
    _stub_ffprobe(monkeypatch, ["English (Fansub)", None])
    assert not mig.has_dubtitles_track(_video(tmp_path))


# A probe failure must NOT read as "no Dubtitles track". Collapsing the two would file
# every unreadable/corrupt file under `no-dubtitles` -- "the normal pipeline owns it" --
# so a run over a partly-broken library would report zero errors and look clean while
# silently skipping the files that most need looking at.

def test_has_dubtitles_track_none_when_ffprobe_cannot_run(monkeypatch, tmp_path):
    def boom(cmd, **kw):
        raise OSError("ffprobe not found")

    monkeypatch.setattr(mig.subprocess, "run", boom)
    assert mig.has_dubtitles_track(_video(tmp_path)) is None


def test_has_dubtitles_track_none_when_ffprobe_times_out(monkeypatch, tmp_path):
    def slow(cmd, **kw):
        raise mig.subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(mig.subprocess, "run", slow)
    assert mig.has_dubtitles_track(_video(tmp_path)) is None


def test_has_dubtitles_track_none_on_nonzero_exit(monkeypatch, tmp_path):
    """ffprobe exits nonzero on an unreadable/truncated file and prints nothing to stdout;
    parsing that as an empty stream list is what made a broken file look sub-less."""
    monkeypatch.setattr(mig.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(stdout="", returncode=1))
    assert mig.has_dubtitles_track(_video(tmp_path)) is None


def test_has_dubtitles_track_none_on_unparseable_output(monkeypatch, tmp_path):
    monkeypatch.setattr(mig.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(stdout="not json", returncode=0))
    assert mig.has_dubtitles_track(_video(tmp_path)) is None


def test_process_reports_probe_failure_separately_and_writes_nothing(monkeypatch, tmp_path):
    v = _video(tmp_path)
    monkeypatch.setattr(mig.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(stdout="", returncode=1))
    assert mig.process(v, apply=True) == "probe-failed"
    assert common.read_stamp(_stamp_path(v)) is None    # never stamp what we couldn't read


# --- dry-run is the default ---------------------------------------------------

def test_dry_run_reports_the_migration_without_writing(monkeypatch, tmp_path):
    v = _video(tmp_path)
    _stub_ffprobe(monkeypatch, [common.TRACK_NAME])
    assert mig.process(v, apply=False) == "plan"
    assert common.read_stamp(_stamp_path(v)) is None


# --- what it writes -----------------------------------------------------------

def test_apply_writes_a_grandfather_version_stamp(monkeypatch, tmp_path):
    v = _video(tmp_path)
    _stub_ffprobe(monkeypatch, [common.TRACK_NAME])
    assert mig.process(v, apply=True) == "stamped"
    stamp = common.read_stamp(_stamp_path(v))
    assert stamp["muxed"] is True
    assert stamp["version"] == common.GRANDFATHER_VERSION


def test_written_stamp_makes_the_file_read_as_done(monkeypatch, tmp_path):
    """The whole point: after migration, generate/mux skip the file instead of
    regenerating it.

    Pinned to the migration-era pipeline version. The migration ran while
    PIPELINE_VERSION == GRANDFATHER_VERSION, which is what made its stamps current; a
    later deliberate bump is *supposed* to make them read as stale again, and the next
    test covers exactly that."""
    v = _video(tmp_path)
    _stub_ffprobe(monkeypatch, [common.TRACK_NAME])
    monkeypatch.setattr(common, "PIPELINE_VERSION", common.GRANDFATHER_VERSION)
    mig.process(v, apply=True)
    assert common.stamp_valid(common.read_stamp(_stamp_path(v)), v)


def test_stamp_is_grandfather_version_even_after_a_pipeline_version_bump(monkeypatch, tmp_path):
    """Migration records what actually produced the file (pre-versioning output = v1), so
    running it after a deliberate bump must NOT falsely mark old output as current."""
    v = _video(tmp_path)
    _stub_ffprobe(monkeypatch, [common.TRACK_NAME])
    monkeypatch.setattr(common, "PIPELINE_VERSION", common.GRANDFATHER_VERSION + 1)
    mig.process(v, apply=True)
    stamp = common.read_stamp(_stamp_path(v))
    assert stamp["version"] == common.GRANDFATHER_VERSION
    assert not common.stamp_valid(stamp, v)      # still stale under the bumped version


# --- what it leaves alone -----------------------------------------------------

def test_skips_a_file_with_no_dubtitles_track(monkeypatch, tmp_path):
    v = _video(tmp_path)
    _stub_ffprobe(monkeypatch, ["English (Fansub)"])
    assert mig.process(v, apply=True) == "no-dubtitles"
    assert common.read_stamp(_stamp_path(v)) is None


def test_never_overwrites_an_existing_stamp(monkeypatch, tmp_path):
    """Idempotent, and it must not undo an operator's version bump: any existing stamp
    (current OR deliberately stale) is left exactly as it is."""
    v = _video(tmp_path)
    common.write_stamp(_stamp_path(v), v)
    before = common.read_stamp(_stamp_path(v))
    _stub_ffprobe(monkeypatch, [common.TRACK_NAME])
    assert mig.process(v, apply=True) == "has-stamp"
    assert common.read_stamp(_stamp_path(v)) == before


def test_rerunning_after_a_migration_is_a_no_op(monkeypatch, tmp_path):
    v = _video(tmp_path)
    _stub_ffprobe(monkeypatch, [common.TRACK_NAME])
    assert mig.process(v, apply=True) == "stamped"
    assert mig.process(v, apply=True) == "has-stamp"


# --- walking ------------------------------------------------------------------

def test_walk_collects_videos_and_prunes_extras_dirs(tmp_path):
    (tmp_path / "Season 01").mkdir()
    (tmp_path / "Season 01" / "ep1.mkv").write_bytes(b"x")
    (tmp_path / "Season 01" / "ep2.mp4").write_bytes(b"x")
    (tmp_path / "Season 01" / "notes.txt").write_text("x")
    (tmp_path / "Featurettes").mkdir()
    (tmp_path / "Featurettes" / "extra.mkv").write_bytes(b"x")

    found = sorted(os.path.basename(p) for p in mig.walk([str(tmp_path)]))
    assert found == ["ep1.mkv", "ep2.mp4"]
