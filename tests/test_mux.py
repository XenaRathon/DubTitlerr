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
    assert mux.MIN_FREE_GB >= 0
    assert mux.SIGNS_RE.search("Signs & Songs")


# --- T2: stamp helpers -------------------------------------------------------


def test_stamp_round_trip_and_validity(tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + mux.STAMP_SUFFIX))
    mux.write_stamp(sp, str(v))
    s = mux.read_stamp(sp)
    assert s["muxed"] is True and s["size"] == 100
    assert mux.stamp_valid(s, str(v))


def test_stamp_invalid_when_file_replaced(tmp_path):
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    sp = str(tmp_path / ("ep" + mux.STAMP_SUFFIX))
    mux.write_stamp(sp, str(v))
    v.write_bytes(b"y" * 250)  # replaced download -> size differs
    assert not mux.stamp_valid(mux.read_stamp(sp), str(v))


def test_stamp_missing_is_invalid():
    assert mux.read_stamp("/nope/none.done") is None
    assert not mux.stamp_valid(None, "/nope")


# --- T3: has_room ------------------------------------------------------------


def test_has_room_boundary():
    assert mux.has_room(10 * GB, 1 * GB)  # 10 > 1.1 + 5
    assert not mux.has_room(2 * GB, 1 * GB)  # 2 < 6.1


# --- T4: keep_sub ------------------------------------------------------------


def test_keep_sub_language():
    assert mux.keep_sub(subt(0, "eng"), mux.KEEP_LANGS)
    assert mux.keep_sub(subt(0, "jpn"), {"jpn"})
    assert not mux.keep_sub(subt(0, "fre"), mux.KEEP_LANGS)


def test_keep_sub_keeps_mul_and_signs_songs():
    assert mux.keep_sub(subt(0, "mul"), mux.KEEP_LANGS)
    assert mux.keep_sub(subt(0, "fre", "Signs & Songs"), mux.KEEP_LANGS)  # survives despite fre
    assert mux.keep_sub(subt(0, "", "Karaoke"), set())


# --- T5: build_cmd flags -----------------------------------------------------


def test_build_cmd_audio_and_sub_flags():
    info = {"tracks": [aud(0, "jpn", default=True), aud(1, "eng"), aud(2, "fre"), subt(3, "eng"), subt(4, "fre", "Signs")]}
    cmd, dropped = mux.build_cmd(info, "ep.mkv", "ep.ass", "out.mkv")
    assert "1:yes" in cmd  # eng audio default
    assert "0:no" in cmd  # jpn audio kept, not default
    assert any("audio:fre" in d for d in dropped)  # foreign dub dropped
    si = cmd.index("-s") + 1
    assert "4" in cmd[si].split(",")  # the fre 'Signs' sub kept (signs/songs survive)
    assert "0:yes" in cmd  # new Dubtitles track default


# --- C16: verify() duration check is the truncation canary --------------------


def _ok_info():
    return {
        "tracks": [
            {"id": 0, "type": "video", "properties": {}},
            aud(1, "eng"),
            subt(2, "eng", mux.TRACK_NAME),
        ]
    }


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
        "out.mkv": _info_with_fonts([_font()]),  # one font dropped by the remux
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
    assert mux.verify("orig.mkv", "out.mkv") == "ok"  # generic MIME warns, doesn't fail
    assert "Weird.ttf" in capsys.readouterr().out


# --- T6: sub_source selection ------------------------------------------------


def test_sub_source_prefers_ass_then_srt(tmp_path):
    stem = str(tmp_path / "ep")
    assert mux.sub_source(stem) is None
    (tmp_path / "ep.eng.dubtitles.srt").write_text("x")
    assert mux.sub_source(stem).endswith(".srt")
    (tmp_path / "ep.eng.dubtitles.ass").write_text("x")
    assert mux.sub_source(stem).endswith(".ass")  # .ass (signs) preferred over .srt


# --- strip-at-mux: an old "Dubtitles" track is replaced, never duplicated ------


def test_keep_sub_drops_our_own_old_dubtitles_track():
    """The name check must win over language/mul/signs -- our track is language=eng, so
    every other rule would keep it and the remux would end up with two Dubtitles tracks."""
    assert not mux.keep_sub(subt(0, "eng", mux.TRACK_NAME), mux.KEEP_LANGS)
    assert not mux.keep_sub(subt(0, "mul", mux.TRACK_NAME), mux.KEEP_LANGS)
    assert not mux.keep_sub(subt(0, "fre", mux.TRACK_NAME), mux.KEEP_LANGS)


def test_keep_sub_tolerates_null_properties():
    """mkvmerge can emit a track with no properties block; the new name check must not
    raise on it. ("" is in KEEP_LANGS by default, so an untagged sub is still kept.)"""
    assert mux.keep_sub({"type": "subtitles", "properties": None}, mux.KEEP_LANGS)
    assert not mux.keep_sub({"type": "subtitles", "properties": None}, {"eng"})


def test_build_cmd_drops_the_old_dubtitles_track_and_adds_one_fresh():
    """Drop-then-re-add in a single mkvmerge pass: the old track never survives into -s,
    it is reported in `dropped`, and the sidecar is appended as the one new Dubtitles."""
    info = {
        "tracks": [aud(0, "jpn", default=True), aud(1, "eng"), subt(2, "eng", "English (Fansub)"), subt(3, "eng", mux.TRACK_NAME)]
    }
    cmd, dropped = mux.build_cmd(info, "ep.mkv", "ep.ass", "out.mkv")
    kept_subs = cmd[cmd.index("-s") + 1].split(",")
    assert kept_subs == ["2"]  # fansub kept, old dubtitle gone
    assert any(mux.TRACK_NAME in d for d in dropped)  # and reported as dropped
    assert cmd[-1] == "ep.ass"  # the new track is still appended
    assert cmd.count(f"0:{mux.TRACK_NAME}") == 1  # exactly one Dubtitles track


def test_build_cmd_suppresses_all_source_subs_when_none_are_kept():
    """mkvmerge's -s is a WHITELIST and its default is copy-every-subtitle-track: with an
    empty keep list, omitting -s would copy the very track we just "dropped" and the file
    would end up with two Dubtitles tracks (verify() only checks presence, so it would
    pass and get stamped). -S is the explicit "no source subs" that makes the drop real.

    This is the mp4-origin shape: a dialogue-only episode whose ONLY subtitle track is our
    own previous dubtitle."""
    info = {"tracks": [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)]}
    cmd, dropped = mux.build_cmd(info, "ep.mkv", "ep.ass", "out.mkv")
    assert "-S" in cmd and "-s" not in cmd
    assert dropped == [f"sub:{mux.TRACK_NAME}(old)"]
    assert cmd.count(f"0:{mux.TRACK_NAME}") == 1  # exactly one Dubtitles track


def test_build_cmd_drops_every_duplicate_dubtitles_track():
    """A buggy past run could have left two; keep_sub drops any track with the name, so
    the result self-heals to exactly one (the new one)."""
    info = {"tracks": [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME), subt(2, "eng", mux.TRACK_NAME)]}
    cmd, dropped = mux.build_cmd(info, "ep.mkv", "ep.ass", "out.mkv")
    assert "-S" in cmd
    assert len([d for d in dropped if mux.TRACK_NAME in d]) == 2


def test_build_cmd_suppresses_source_subs_when_only_foreign_ones_exist():
    """Same hole, pre-existing shape: a file whose only subs are other-language dialogue
    reported them as dropped while mkvmerge silently copied them all."""
    info = {"tracks": [aud(0, "eng"), subt(1, "fre"), subt(2, "spa")]}
    cmd, dropped = mux.build_cmd(info, "ep.mkv", "ep.ass", "out.mkv")
    assert "-S" in cmd
    assert dropped == ["sub:fre", "sub:spa"]


# --- process() skip guard is stamp-only (no ffprobe "already-muxed" backstop) --


def _muxable(tmp_path, monkeypatch, tracks):
    """A video + sidecar on disk with mkvmerge -J stubbed, so process() can be driven
    in dry-run without media. Returns the video path."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    (tmp_path / ("ep" + mux.ASS_SUFFIX)).write_text("[Script Info]\n")
    monkeypatch.setattr(mux, "identify", lambda p: {"tracks": tracks})
    return str(v)


def test_process_remuxes_a_file_that_already_has_a_dubtitles_track(tmp_path, monkeypatch):
    """The old ffprobe backstop is gone: a Dubtitles track alone no longer counts as done,
    because re-muxing is now idempotent (drop old + add fresh). Without this, every
    regeneration would silently no-op on already-dubbed files."""
    v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
    assert mux.process(v, apply=False) == "plan"


def test_process_skips_on_a_current_version_stamp(tmp_path, monkeypatch):
    v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
    mux.write_stamp(str(tmp_path / ("ep" + mux.STAMP_SUFFIX)), v)
    assert mux.process(v, apply=False) == "already-muxed"


def test_process_remuxes_a_file_whose_stamp_is_from_an_older_pipeline_version(tmp_path, monkeypatch):
    """A version bump is the regeneration trigger: the v1 stamp still matches
    size+mtime, but its version is behind, so the file is re-muxed in place."""
    import common

    v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
    mux.write_stamp(str(tmp_path / ("ep" + mux.STAMP_SUFFIX)), v)
    monkeypatch.setattr(common, "TEXT_VERSION", common.TEXT_VERSION + 1)
    assert mux.process(v, apply=False) == "plan"


def test_process_still_no_ops_without_a_sidecar(tmp_path, monkeypatch):
    """mux never touches a file that has no new subtitle to embed -- this is what makes
    "old track dropped" impossible to happen independently of "new track added"."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    monkeypatch.setattr(mux, "identify", lambda p: {"tracks": [aud(0, "eng")]})
    assert mux.process(str(v), apply=False) == "no-sub"


# --- a failed stamp write must be loud ----------------------------------------


def test_process_reports_a_failed_stamp_write_and_keeps_the_sidecar(tmp_path, monkeypatch, capsys):
    """With the ffprobe backstop retired, the stamp is the only record that a file is
    done. If writing it fails (read-only/full branch, EIO) the remux has ALREADY happened,
    so the next sweep would silently redo the whole multi-GB mkvmerge -- forever, in a
    container that sweeps continuously. Keep the sidecar so the retry can still succeed,
    but surface it as its own status instead of a bare "muxed" line."""
    v = tmp_path / "ep.mkv"
    v.write_bytes(b"x" * 100)
    sidecar = tmp_path / ("ep" + mux.ASS_SUFFIX)
    sidecar.write_text("[Script Info]\n")
    monkeypatch.setattr(mux, "identify", lambda p: {"tracks": [aud(0, "eng")]})
    monkeypatch.setattr(mux, "verify", lambda orig, out: "ok")
    monkeypatch.setattr(mux.subprocess, "run", lambda cmd, **kw: open(cmd[cmd.index("-o") + 1], "wb").write(b"muxed"))

    def boom(path, video, **_kw):
        raise OSError("read-only file system")

    monkeypatch.setattr(mux, "write_stamp", boom)

    assert mux.process(str(v), apply=True) == "stamp-write-failed"
    assert sidecar.exists()  # kept, so the next sweep can retry
    assert "stamp" in capsys.readouterr().out.lower()


# --- verify(): compare the VIDEO track, not the container ---------------------
#
# Matroska's container duration is the LONGEST track. Releases routinely ship a foreign
# subtitle that runs past the end of the video -- e.g. JUJUTSU KAISEN S02E04 carries a
# Polish fansub track ending at 24:12.74 while the video ends at 23:54.85. mux correctly
# drops that track (not a keep language), so the remux's container duration falls by ~19s
# and the old container-vs-container check failed with DUR_TOL=2 even though video and
# audio were untouched. That bricked every such release: assembled sidecars, mux rejected
# on every sweep, 25 days of retries on one episode alone.


def test_parse_duration_tag_handles_matroska_hhmmss():
    assert abs(mux._parse_duration("00:23:54.849708333") - 1434.849) < 0.01
    assert abs(mux._parse_duration("01:02:03.5") - 3723.5) < 0.01


def test_parse_duration_tag_rejects_junk():
    for bad in ("", None, "N/A", "abc"):
        assert mux._parse_duration(bad) is None


def test_video_duration_prefers_the_stream_over_the_container(monkeypatch):
    """The container figure is exactly the one that lies when an over-long sub is dropped."""
    monkeypatch.setattr(mux, "_ffprobe_video", lambda p: {"duration": "1434.849"})
    assert abs(mux.video_duration("x.mkv") - 1434.849) < 0.01


def test_video_duration_falls_back_to_the_duration_tag(monkeypatch):
    """Matroska usually leaves stream=duration as N/A and carries a DURATION tag instead."""
    monkeypatch.setattr(mux, "_ffprobe_video", lambda p: {"duration": "N/A", "tags": {"DURATION": "00:23:54.849708333"}})
    assert abs(mux.video_duration("x.mkv") - 1434.849) < 0.01


def test_verify_passes_when_only_a_dropped_subtitle_shortened_the_container(monkeypatch):
    """The real JUJUTSU KAISEN case: container 1453.88 -> 1434.95 (delta 18.9s, way over
    DUR_TOL) but the video track is unchanged. This must pass."""
    monkeypatch.setattr(mux, "identify", lambda p: _ok_info())
    monkeypatch.setattr(mux, "video_duration", lambda p: 1434.849 if p == "orig.mkv" else 1434.850)
    assert mux.verify("orig.mkv", "out.mkv") == "ok"


def test_verify_still_catches_a_genuinely_truncated_remux(monkeypatch):
    """The check exists as a truncation canary -- it has to keep working."""
    monkeypatch.setattr(mux, "identify", lambda p: _ok_info())
    monkeypatch.setattr(mux, "video_duration", lambda p: 1434.8 if p == "orig.mkv" else 900.0)
    assert mux.verify("orig.mkv", "out.mkv") == "duration-mismatch"


# --- 2026-08-22: dead destructive knob, removed ---------------------------------------


def test_delete_broken_hardlinks_is_not_a_silent_noop():
    """DELETE_BROKEN_HARDLINKS was read into mux.DELETE_BROKEN at import and never consumed:
    partners() had no caller either. An operator could set DELETE_BROKEN_HARDLINKS=1, get no
    error, and believe broken seeding hardlinks were being reaped -- a destructive safety
    control that did nothing. Both removed 2026-08-22 (adversarial review).

    This test pins the removal. If the feature is ever wanted, it must be WIRED into
    process() with an integration test proving the setting changes the filesystem result --
    not merely read back into a module global."""
    assert not hasattr(mux, "DELETE_BROKEN"), "dead destructive knob reintroduced without being wired to anything"
    assert not hasattr(mux, "partners"), "partners() reintroduced; it had no caller -- wire it or leave it out"


# --- stage-execution record (2026-08-22) ----------------------------------------------


def test_stages_ran_reads_the_sidecars_still_on_disk(tmp_path):
    """mux stamps AFTER the other stages, while their sidecars are still present. That is
    the one moment the pipeline can say what actually ran."""
    stem = str(tmp_path / "ep")
    open(stem + ".dubtitles.repair-summary.json", "w").write("{}")
    with open(stem + ".dubtitles.qc.json", "w") as f:
        f.write('{"counters": {"restore_runs_sent": 12}}')
    got = mux._stages_ran(stem, stem + ".eng.dubtitles.ass")
    assert got["repair"] is True
    assert got["signs_merge"] is True  # muxed from .ass -> signs were merged
    assert got["punctuation"] is True


def test_stages_ran_omits_what_it_cannot_determine(tmp_path):
    """'did not run' and 'cannot tell' are DIFFERENT claims. With no qc sidecar the
    punctuation key is omitted, never guessed False -- the tri-state lesson from
    tools/vad.py, which returns None rather than a confident wrong answer."""
    stem = str(tmp_path / "ep")
    got = mux._stages_ran(stem, stem + ".eng.dubtitles.srt")
    assert got["repair"] is False  # summary absent: repair demonstrably did not run
    assert got["signs_merge"] is False  # muxed from .srt
    assert "punctuation" not in got  # unknowable -> omitted
