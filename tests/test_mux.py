"""Unit tests for mux.py pure helpers (D1). mkvmerge/ffprobe calls are integration."""
import os

import mux


def sub(lang="", name=""):
    return {"type": "subtitles", "properties": {"language": lang, "track_name": name}}


# --- T1: scaffold / constants ------------------------------------------------

def aud(tid, lang, default=False):
    return {"id": tid, "type": "audio", "properties": {"language": lang, "default_track": default}}


def subt(tid, lang, name=""):
    return {"id": tid, "type": "subtitles", "properties": {"language": lang, "track_name": name}}


GB = 1 << 30


def test_constants_and_defaults():
    assert mux.STAMP_SUFFIX == ".dubtitles.done"
    assert mux.DELETE_BROKEN is False          # never delete seeding partners by default
    assert mux.MIN_FREE_GB >= 0
    assert mux.SIGNS_RE.search("Signs & Songs")


# --- T2: stamp helpers -------------------------------------------------------

def test_stamp_round_trip_and_validity(tmp_path):
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + mux.STAMP_SUFFIX))
    mux.write_stamp(sp, str(v))
    s = mux.read_stamp(sp)
    assert s["muxed"] is True and s["size"] == 100
    assert mux.stamp_valid(s, str(v))


def test_stamp_invalid_when_file_replaced(tmp_path):
    v = tmp_path / "ep.mkv"; v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + mux.STAMP_SUFFIX)); mux.write_stamp(sp, str(v))
    v.write_bytes(b"y" * 250)                  # replaced download -> size differs
    assert not mux.stamp_valid(mux.read_stamp(sp), str(v))


def test_stamp_missing_is_invalid():
    assert mux.read_stamp("/nope/none.done") is None
    assert not mux.stamp_valid(None, "/nope")


# --- T3: has_room ------------------------------------------------------------

def test_has_room_boundary():
    assert mux.has_room(10 * GB, 1 * GB)       # 10 > 1.1 + 5
    assert not mux.has_room(2 * GB, 1 * GB)    # 2 < 6.1


# --- T4: keep_sub ------------------------------------------------------------

def test_keep_sub_language():
    assert mux.keep_sub(subt(0, "eng"), mux.KEEP_LANGS)
    assert mux.keep_sub(subt(0, "jpn"), {"jpn"})
    assert not mux.keep_sub(subt(0, "fre"), mux.KEEP_LANGS)


def test_keep_sub_keeps_mul_and_signs_songs():
    assert mux.keep_sub(subt(0, "mul"), mux.KEEP_LANGS)
    assert mux.keep_sub(subt(0, "fre", "Signs & Songs"), mux.KEEP_LANGS)   # survives despite fre
    assert mux.keep_sub(subt(0, "", "Karaoke"), set())


# --- T5: build_cmd flags -----------------------------------------------------

def test_build_cmd_audio_and_sub_flags():
    info = {"tracks": [aud(0, "jpn", default=True), aud(1, "eng"), aud(2, "fre"),
                       subt(3, "eng"), subt(4, "fre", "Signs")]}
    cmd, dropped = mux.build_cmd(info, "ep.mkv", "ep.ass", "out.mkv")
    assert "1:yes" in cmd            # eng audio default
    assert "0:no" in cmd             # jpn audio kept, not default
    assert any("audio:fre" in d for d in dropped)     # foreign dub dropped
    si = cmd.index("-s") + 1
    assert "4" in cmd[si].split(",")  # the fre 'Signs' sub kept (signs/songs survive)
    assert "0:yes" in cmd            # new Dubtitles track default


# --- C16: verify() duration check is the truncation canary --------------------

def _ok_info():
    return {"tracks": [
        {"id": 0, "type": "video", "properties": {}},
        aud(1, "eng"),
        subt(2, "eng", mux.TRACK_NAME),
    ]}


def test_verify_duration_mismatch_catches_truncated_output(monkeypatch):
    monkeypatch.setattr(mux, "identify", lambda p: _ok_info())
    monkeypatch.setattr(mux, "duration", lambda p: 100.0 if p == "orig.mkv" else 10.0)  # truncated out
    assert mux.verify("orig.mkv", "out.mkv") == "duration-mismatch"


def test_verify_ok_when_duration_within_tolerance(monkeypatch):
    monkeypatch.setattr(mux, "identify", lambda p: _ok_info())
    monkeypatch.setattr(mux, "duration", lambda p: 100.0)
    assert mux.verify("orig.mkv", "out.mkv") == "ok"


# --- D2: font-attachment audit -------------------------------------------------

def _font(name="Arial.ttf", ctype="application/x-truetype-font"):
    return {"content_type": ctype, "file_name": name}


def _info_with_fonts(fonts=None):
    d = _ok_info()
    if fonts is not None:
        d["attachments"] = fonts
    return d


def test_verify_font_count_mismatch_is_non_ok(monkeypatch):
    infos = {
        "orig.mkv": _info_with_fonts([_font(), _font(name="Comic.ttf")]),
        "out.mkv": _info_with_fonts([_font()]),   # one font dropped by the remux
    }
    monkeypatch.setattr(mux, "identify", lambda p: infos[p])
    monkeypatch.setattr(mux, "duration", lambda p: 100.0)
    assert mux.verify("orig.mkv", "out.mkv") == "font-count-mismatch"


def test_verify_ok_when_font_counts_equal_nonzero(monkeypatch):
    infos = {
        "orig.mkv": _info_with_fonts([_font(), _font(name="Comic.ttf")]),
        "out.mkv": _info_with_fonts([_font(), _font(name="Comic.ttf")]),
    }
    monkeypatch.setattr(mux, "identify", lambda p: infos[p])
    monkeypatch.setattr(mux, "duration", lambda p: 100.0)
    assert mux.verify("orig.mkv", "out.mkv") == "ok"


def test_verify_ok_when_no_fonts_either_side(monkeypatch):
    # "attachments" key absent entirely on both sides -- .get(..., []) must treat
    # this as 0 == 0, not KeyError, and still return "ok".
    infos = {
        "orig.mkv": _info_with_fonts(None),
        "out.mkv": _info_with_fonts(None),
    }
    monkeypatch.setattr(mux, "identify", lambda p: infos[p])
    monkeypatch.setattr(mux, "duration", lambda p: 100.0)
    assert mux.verify("orig.mkv", "out.mkv") == "ok"


def test_verify_warns_on_generic_font_mime_but_still_ok(monkeypatch, capsys):
    infos = {
        "orig.mkv": _info_with_fonts([_font(name="Weird.ttf", ctype="application/octet-stream")]),
        "out.mkv": _info_with_fonts([_font(name="Weird.ttf", ctype="application/octet-stream")]),
    }
    monkeypatch.setattr(mux, "identify", lambda p: infos[p])
    monkeypatch.setattr(mux, "duration", lambda p: 100.0)
    assert mux.verify("orig.mkv", "out.mkv") == "ok"   # generic MIME warns, doesn't fail
    assert "Weird.ttf" in capsys.readouterr().out


# --- T6: sub_source selection ------------------------------------------------

# --- C3: partners() inode cache -----------------------------------------------

def test_partners_cached_by_inode(tmp_path):
    a = tmp_path / "a.mkv"; a.write_bytes(b"x" * 10)
    b = tmp_path / "b.mkv"
    os.link(str(a), str(b))
    mux._partners_cache.clear()
    orig_hl_roots = mux.HL_ROOTS
    mux.HL_ROOTS = [str(tmp_path)]
    try:
        first = mux.partners(str(a))
        assert str(b) in first
        mux.HL_ROOTS = ["/nonexistent-root-xyz"]      # a fresh (uncached) walk would find nothing here
        second = mux.partners(str(a))
        assert second == first                        # cache hit: HL_ROOTS change had no effect
        assert (os.stat(str(a)).st_ino, os.stat(str(a)).st_dev) in mux._partners_cache
    finally:
        mux.HL_ROOTS = orig_hl_roots


def test_sub_source_prefers_ass_then_srt(tmp_path):
    stem = str(tmp_path / "ep")
    assert mux.sub_source(stem) is None
    (tmp_path / "ep.eng.dubtitles.srt").write_text("x")
    assert mux.sub_source(stem).endswith(".srt")
    (tmp_path / "ep.eng.dubtitles.ass").write_text("x")
    assert mux.sub_source(stem).endswith(".ass")   # .ass (signs) preferred over .srt
