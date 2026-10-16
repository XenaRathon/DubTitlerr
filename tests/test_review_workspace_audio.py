"""Security/resource invariants for short audio evidence, using disposable media only."""

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import review_server as rs
import unresolved


@pytest.fixture
def clip(tmp_path, monkeypatch):
    stem = str(tmp_path / "episode")
    Path(stem + ".mkv").write_bytes(b"fixture")
    Path(stem + rs.CONF_SUFFIX).write_text(json.dumps([{"text": "Hello.", "start": 3.0, "end": 200.0}]))
    unresolved.record(stem, "repair_applied", "accepted", original_text="Hello.", proposed_text="Hello!")
    row = unresolved.items(stem)[0]
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path)])
    monkeypatch.setattr(rs, "_resolve", lambda value: stem if value == stem else None)
    monkeypatch.setattr(rs, "_AUDIO_SLOTS", threading.BoundedSemaphore(2))
    return {"stem": stem, "index": "0", "id": rs.entry_id(row)}


def test_clip_limits_duration_and_selects_non_commentary_english_track(clip, monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[0] == "ffprobe":
            return SimpleNamespace(
                stdout=json.dumps(
                    {
                        "streams": [
                            {"index": 0, "codec_type": "audio", "tags": {"language": "jpn"}},
                            {"index": 1, "codec_type": "audio", "tags": {"language": "eng", "title": "Commentary"}},
                            {"index": 2, "codec_type": "audio", "tags": {"language": "eng", "title": "English dub"}},
                        ]
                    }
                ).encode()
            )
        return SimpleNamespace(stdout=b"RIFF" + bytes(80))

    monkeypatch.setattr(rs.subprocess, "run", run)
    status, data = rs.preview_audio({**clip, "start": "999999", "duration": "99999"})
    assert status == 200 and data.startswith(b"RIFF")
    cmd, kwargs = calls[1]
    assert cmd[cmd.index("-map") + 1] == "0:2"
    assert cmd[cmd.index("-ss") + 1] == "1.5"
    assert float(cmd[cmd.index("-t") + 1]) == 20
    assert kwargs["timeout"] == 30 and kwargs["stdin"] == subprocess.DEVNULL
    assert "-ac" in cmd and "16000" in cmd


@pytest.mark.parametrize("bounds", [(float("nan"), 5), (3, float("inf")), (-2, 4), (5, 3)])
def test_unusable_cue_bounds_do_not_run_extraction(clip, monkeypatch, bounds):
    Path(clip["stem"] + rs.CONF_SUFFIX).write_text(json.dumps([{"text": "Hello.", "start": bounds[0], "end": bounds[1]}]))
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **kw: pytest.fail("invalid cue reached ffmpeg"))
    assert rs.preview_audio(clip)[0] == 400


def test_stale_question_is_not_played(clip, monkeypatch):
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **kw: pytest.fail("stale question reached ffmpeg"))
    assert rs.preview_audio({**clip, "id": "stale"})[0] == 409


def test_symlinked_media_outside_library_is_not_read(clip, tmp_path, monkeypatch):
    external = tmp_path.parent / (tmp_path.name + "-external")
    external.write_bytes(b"outside")
    video = Path(clip["stem"] + ".mkv")
    video.unlink()
    video.symlink_to(external)
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **kw: pytest.fail("outside media reached ffmpeg"))
    try:
        assert rs.preview_audio(clip)[0] == 404
    finally:
        external.unlink()


def test_audio_busy_is_visible_and_does_not_start_another_process(clip, monkeypatch):
    assert rs._AUDIO_SLOTS.acquire(False)
    assert rs._AUDIO_SLOTS.acquire(False)
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **kw: pytest.fail("third extraction started"))
    assert rs.preview_audio(clip)[0] == 429


def test_extraction_timeout_releases_the_slot(clip, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 10)

    monkeypatch.setattr(rs.subprocess, "run", timeout)
    assert rs.preview_audio(clip)[0] == 502
    assert rs._AUDIO_SLOTS.acquire(False)
    assert rs._AUDIO_SLOTS.acquire(False)


def test_absent_english_track_is_not_silently_replaced_with_japanese(clip, monkeypatch):
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=b'{"streams":[]}'))
    status, error = rs.preview_audio(clip)
    assert status == 422 and "English" in error["error"]
