import os
import sys
import types

import pytest


def _stub_faster_whisper():
    if "faster_whisper" in sys.modules:
        return
    fake = types.ModuleType("faster_whisper")

    class _UnusedWhisperModel:
        def __init__(self, *a, **kw):
            raise AssertionError("WhisperModel must never be instantiated by these tests")

    fake.WhisperModel = _UnusedWhisperModel
    sys.modules["faster_whisper"] = fake


_stub_faster_whisper()
import generate  # noqa: E402
import ordering  # noqa: E402


def _create_episodes(tmp_path, count=54):
    files = []
    for i in range(1, count + 1):
        f = tmp_path / f"Show Name - S01E{i:02d}.mkv"
        f.write_text("fake video content")
        files.append(str(f))
    return files


def test_generate_only_re_filters_matching_files(tmp_path, monkeypatch, capsys):
    _create_episodes(tmp_path, 54)
    monkeypatch.setenv("GENERATE_ONLY_RE", r"S01E(0[1-9]|1[0-9]|2[0-7])\b")
    monkeypatch.setattr(sys, "argv", ["generate.py", "--root", str(tmp_path)])

    ordered_files = []
    orig_order = ordering.order_files

    def fake_order(files, start):
        ordered_files.extend(files)
        return orig_order(files, start)

    monkeypatch.setattr(ordering, "order_files", fake_order)
    monkeypatch.setattr(generate, "load_glossary", lambda: None)
    monkeypatch.setattr(generate, "build_lastrun", lambda *a, **k: {})
    # Pretend all files are already done so model is not loaded
    monkeypatch.setattr(generate, "stamp_valid", lambda stamp, v: True)

    generate.main()

    assert len(ordered_files) == 27
    for f in ordered_files:
        assert any(f"S01E{i:02d}" in f for i in range(1, 28))
        assert not any(f"S01E{i:02d}" in f for i in range(28, 55))

    out = capsys.readouterr().out
    assert "GENERATE_ONLY_RE: kept 27 of 54 files" in out


def test_generate_only_re_unset_and_empty_keeps_all(tmp_path, monkeypatch, capsys):
    _create_episodes(tmp_path, 10)
    monkeypatch.delenv("GENERATE_ONLY_RE", raising=False)
    monkeypatch.setattr(sys, "argv", ["generate.py", "--root", str(tmp_path)])

    ordered_files = []

    def fake_order(files, start):
        ordered_files.extend(files)
        return files

    monkeypatch.setattr(ordering, "order_files", fake_order)
    monkeypatch.setattr(generate, "load_glossary", lambda: None)
    monkeypatch.setattr(generate, "build_lastrun", lambda *a, **k: {})
    monkeypatch.setattr(generate, "stamp_valid", lambda stamp, v: True)

    generate.main()
    assert len(ordered_files) == 10
    out = capsys.readouterr().out
    assert "GENERATE_ONLY_RE" not in out

    # Test empty string as well
    ordered_files.clear()
    monkeypatch.setenv("GENERATE_ONLY_RE", "")
    generate.main()
    assert len(ordered_files) == 10
    out = capsys.readouterr().out
    assert "GENERATE_ONLY_RE" not in out


def test_generate_only_re_invalid_fails_closed(tmp_path, monkeypatch, capsys):
    _create_episodes(tmp_path, 5)
    monkeypatch.setenv("GENERATE_ONLY_RE", "[unclosed-bracket")
    monkeypatch.setattr(sys, "argv", ["generate.py", "--root", str(tmp_path)])

    monkeypatch.setattr(
        ordering, "order_files", lambda *a: pytest.fail("ordering.order_files must not be reached on invalid regex")
    )
    monkeypatch.setattr(generate, "load_glossary", lambda: pytest.fail("load_glossary must not be reached on invalid regex"))
    monkeypatch.setattr(generate, "process", lambda v: pytest.fail("process must not be reached on invalid regex"))

    with pytest.raises(SystemExit) as exc_info:
        generate.main()

    assert exc_info.value.code != 0
    out = capsys.readouterr().out
    assert "invalid GENERATE_ONLY_RE regex" in out


def test_generate_only_re_explicit_args_unfiltered(tmp_path, monkeypatch, capsys):
    eps = _create_episodes(tmp_path, 4)
    # Even with GENERATE_ONLY_RE set, explicit args are NOT filtered
    monkeypatch.setenv("GENERATE_ONLY_RE", r"S01E01")
    monkeypatch.setattr(sys, "argv", ["generate.py", eps[0], eps[1], eps[2]])

    monkeypatch.setattr(generate, "load_glossary", lambda: None)
    monkeypatch.setattr(generate, "build_lastrun", lambda *a, **k: {})
    monkeypatch.setattr(generate, "stamp_valid", lambda stamp, v: True)

    generate.main()

    out = capsys.readouterr().out
    assert "files=3" in out
    assert "GENERATE_ONLY_RE:" not in out


def test_generate_only_re_digimon_names_with_brackets_and_spaces(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "[Fansub Group] Digimon Adventure (2020) - S01E05 [1080p][x264].mkv"
    f2 = tmp_path / "[Fansub Group] Digimon Adventure (2020) - S01E35 [1080p][x264].mkv"
    f3 = tmp_path / "[Other] Digimon Adventure - 01 [720p].mkv"
    f1.write_text("video")
    f2.write_text("video")
    f3.write_text("video")

    monkeypatch.setenv("GENERATE_ONLY_RE", r"S01E(0[1-9]|1[0-9]|2[0-7])\b")
    monkeypatch.setattr(sys, "argv", ["generate.py", "--root", str(tmp_path)])

    ordered_files = []

    def fake_order(files, start):
        ordered_files.extend(files)
        return files

    monkeypatch.setattr(ordering, "order_files", fake_order)
    monkeypatch.setattr(generate, "load_glossary", lambda: None)
    monkeypatch.setattr(generate, "build_lastrun", lambda *a, **k: {})
    monkeypatch.setattr(generate, "stamp_valid", lambda stamp, v: True)

    generate.main()

    assert len(ordered_files) == 1
    assert os.path.basename(ordered_files[0]) == "[Fansub Group] Digimon Adventure (2020) - S01E05 [1080p][x264].mkv"
    out = capsys.readouterr().out
    assert "GENERATE_ONLY_RE: kept 1 of 3 files" in out
