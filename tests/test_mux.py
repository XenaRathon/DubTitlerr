"""Unit tests for mux.py pure helpers (D1). mkvmerge/ffprobe calls are integration."""
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


# --- T6: sub_source selection ------------------------------------------------

def test_sub_source_prefers_ass_then_srt(tmp_path):
    stem = str(tmp_path / "ep")
    assert mux.sub_source(stem) is None
    (tmp_path / "ep.eng.dubtitles.srt").write_text("x")
    assert mux.sub_source(stem).endswith(".srt")
    (tmp_path / "ep.eng.dubtitles.ass").write_text("x")
    assert mux.sub_source(stem).endswith(".ass")   # .ass (signs) preferred over .srt
