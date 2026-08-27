"""Unit tests for mux.py pure helpers (D1). mkvmerge/ffprobe calls are integration."""

import os
import time

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


# --- [S-6] the pre-mux review gate -------------------------------------------
# A repair `accept_repair` ADMITTED is a change nothing checked the meaning of. For a show
# the operator has opted in, the episode waits for a human rather than shipping.


def _gated(tmp_path, monkeypatch, show="Gated Show", entries=1):
    """A muxable episode whose queue holds `entries` pending accepted repairs."""
    import unresolved

    v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
    stem = str(tmp_path / "ep")
    for i in range(entries):
        unresolved.record(stem, "repair_applied", "accepted", original_text=f"asr {i}", proposed_text=f"fix {i}")
    monkeypatch.setattr(mux, "show_for", lambda p: show)
    return v, stem


def test_a_gated_show_holds_an_episode_with_a_pending_accepted_repair(tmp_path, monkeypatch):
    """Three halves, and the last two are what stop this being vacuous: an UNLISTED show
    must mux exactly as today (the default for every install), and resolving the entry must
    release the episode -- otherwise a gate that simply never muxed anything would pass."""
    v, stem = _gated(tmp_path, monkeypatch)
    import unresolved

    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    assert mux.process(v, apply=False) == "held-for-review"

    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", [])
    assert mux.process(v, apply=False) == "plan", "an unlisted show behaves exactly as today"

    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    unresolved.resolve(stem, 0, accept=True)
    assert mux.process(v, apply=False) == "plan", "resolving the entry releases the episode"


def test_a_gate_holds_only_on_accepted_repairs_not_on_guard_rejections(tmp_path, monkeypatch):
    """A REJECTED repair means the ASR text shipped -- the safe outcome, and nothing a
    viewer sees that a human has not effectively approved by default. The unchecked change
    is the ACCEPTED one, which is the only thing worth stopping a release for."""
    import unresolved

    v = _muxable(tmp_path, monkeypatch, [aud(0, "eng"), subt(1, "eng", mux.TRACK_NAME)])
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "rejected_guard", original_text="asr", proposed_text="fix")
    monkeypatch.setattr(mux, "show_for", lambda p: "Gated Show")
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])

    assert mux.process(v, apply=False) == "plan"


def test_a_stale_hold_is_reported_loudly_and_is_still_not_released(tmp_path, monkeypatch, capsys):
    """The alert must never become a release.

    Written after the branch existed, so it is held by the mutation check rather than by a
    red run: making the stale path return False (an "auto-release after N days") passes the
    logging half and fails the second assertion. That is the whole point of the story --
    releasing unreviewed repairs on a timer is the failure this spec exists to prevent, and
    an alert that quietly releases is worse than none because it reads as supervision."""
    import unresolved

    v, stem = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    monkeypatch.setattr(mux, "REVIEW_GATE_STALE_DAYS", 7.0)
    old = time.time() - 30 * 86400
    os.utime(unresolved.path_for(stem), (old, old))

    verdict = mux.process(v, apply=False)
    out = capsys.readouterr().out

    assert "STALLED" in out and "30d" in out, "a backlog must be visible, not silent"
    assert "NOT released" in out
    assert verdict == "held-for-review", "the alert reports the stall; it does not end it"


def test_a_fresh_hold_is_silent(tmp_path, monkeypatch, capsys):
    """The counterpart: a hold inside the window is normal operation, not an incident.
    Without this, the STALLED line could fire on every held episode and mean nothing."""
    v, _ = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    monkeypatch.setattr(mux, "REVIEW_GATE_STALE_DAYS", 7.0)

    assert mux.process(v, apply=False) == "held-for-review"
    assert "STALLED" not in capsys.readouterr().out


def test_the_sweep_summary_carries_the_held_count(tmp_path, monkeypatch, capsys):
    """A backlog has to be countable from the sweep's own output, or a gated show silently
    stops producing episodes and nothing says why. process() returns a distinct status, so
    main()'s existing counts dict carries it with no new plumbing."""
    v, _ = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])

    mux.main([v])
    out = capsys.readouterr().out

    assert "held-for-review" in out and "SUMMARY" in out


def test_an_already_muxed_episode_reports_already_muxed_not_held(tmp_path, monkeypatch):
    """The gate sits AFTER the stamp check, and this is what says so.

    The plan sketched the reverse order. An episode that already shipped cannot be held
    back: reporting a hold for it would inflate the backlog with episodes no review can
    affect, and would hide "already-muxed" behind a status the operator is meant to act on.
    Added because a mutation that moved the gate above the stamp check passed the whole
    suite -- a design decision taken deliberately and pinned by nothing."""
    v, _ = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    mux.write_stamp(str(tmp_path / ("ep" + mux.STAMP_SUFFIX)), v)

    assert mux.process(v, apply=False) == "already-muxed"


def test_an_opted_in_operator_is_told_when_a_show_cannot_be_resolved(tmp_path, monkeypatch, capsys):
    """Listing a show whose glossary is missing or misnamed turns the gate OFF in silence.

    `show_for` returns "" when no glossary ancestor matches, "" is never in
    REVIEW_GATE_SHOWS, and the episode muxes exactly as if the operator had never opted in.
    They would believe unreviewed repairs were being held while every one of them shipped.
    Only fires when the operator HAS opted in, so an install with the gate off stays silent.
    Same failure class the sprint-005 review found in review_apply's sweep."""
    v, _ = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "show_for", lambda p: "")
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    monkeypatch.setattr(mux, "_warned_unresolved", set())

    assert mux.process(v, apply=False) == "plan", "it still muxes -- the gate genuinely is off"
    assert "cannot resolve a show" in capsys.readouterr().out.lower()


def test_the_unresolved_warning_is_not_repeated_per_episode(tmp_path, monkeypatch, capsys):
    """A whole season of a misconfigured show would otherwise print one line per episode
    every sweep, which is how a real warning becomes background noise."""
    v, _ = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "show_for", lambda p: "")
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    monkeypatch.setattr(mux, "_warned_unresolved", set())

    mux.process(v, apply=False)
    capsys.readouterr()
    mux.process(v, apply=False)

    assert "cannot resolve a show" not in capsys.readouterr().out.lower()


def test_a_listed_show_that_never_matches_anything_is_reported(tmp_path, monkeypatch, capsys):
    """REVIEW_GATE_SHOWS must carry the DIRECTORY BASENAME, not the show's common name.

    decisions.show_for resolves to the directory basename on purpose -- "Cowboy Bebop (1998)
    {tvdb-76885}", not gloss["show"] == "Cowboy Bebop" -- and that distinction already cost
    one design bug in sprint 002. An operator naturally writes the display name. show_for
    then returns a NON-empty string that simply is not in the list, so the earlier
    "cannot resolve a show" warning does not fire, every episode ships unreviewed, and the
    operator believes the gate is holding them."""
    v, _ = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "show_for", lambda p: "Cowboy Bebop (1998) {tvdb-76885}")
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Cowboy Bebop"])

    mux.main([v])
    out = capsys.readouterr().out

    assert "never matched" in out.lower(), "a gate that matches nothing must say so"
    assert "Cowboy Bebop (1998) {tvdb-76885}" in out, "and name what it DID see, so the fix is obvious"


def test_a_queued_line_that_already_has_a_verdict_does_not_hold_the_episode(tmp_path, monkeypatch):
    """`unresolved.resolve()` and `decisions.record()` are two independent write paths.

    The one that stops repair re-queueing a line is the DECISION (repair.py consults the
    store); the one the queue's own --review CLI writes is the RESOLVED flag. If the gate
    trusted only the flag, a line settled by a verdict -- recorded by hand, by a future
    sync, or by a server whose resolve() write failed -- would hold the episode forever
    while the pipeline itself considered it decided. The verdict is the authority."""
    import decisions as dec

    v, stem = _gated(tmp_path, monkeypatch)
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    assert mux.process(v, apply=False) == "held-for-review"

    store = dec.record({}, "asr 0", "fix 0", "accept")
    monkeypatch.setattr(mux, "decisions_for", lambda p: (store, "Gated Show"))

    assert mux.process(v, apply=False) == "plan", "a decided line is settled however it was settled"


def _conf(stem, texts):
    """The episode's current conf.json -- the ASR text of each card."""
    import json as _j

    with open(stem + ".dubtitles.conf.json", "w") as f:
        _j.dump([{"start": i * 2.0, "end": i * 2.0 + 2.0, "text": t} for i, t in enumerate(texts)], f)


def test_an_entry_orphaned_by_a_version_bump_does_not_hold_the_episode(tmp_path, monkeypatch):
    """The queue is NOT in generate.SIDECAR_SUFFIXES, so park_stale_sidecars leaves it in
    place across a TRANSCRIBE_VERSION/TEXT_VERSION bump. After a re-transcription its
    entries can describe text that no longer appears anywhere in the episode. Nothing will
    ever re-queue those lines, so nothing will ever resolve them, and with the gate on they
    hold the episode forever.

    Owner's decision 2026-08-27: keep the history (it is the record of what a human already
    judged, and the input to the later accept_repair tightening) and have the gate ignore
    the orphans. The second half is what stops this passing on a gate that never holds."""
    v, stem = _gated(tmp_path, monkeypatch, entries=0)
    import unresolved

    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    unresolved.record(stem, "repair_applied", "accepted", original_text="a line from the OLD transcript", proposed_text="x")
    _conf(stem, ["a line the current transcript actually has"])
    assert mux.process(v, apply=False) == "plan", "an orphan must not hold the episode"

    unresolved.record(
        stem, "repair_applied", "accepted", original_text="a line the current transcript actually has", proposed_text="y"
    )
    assert mux.process(v, apply=False) == "held-for-review", "a live entry still holds it"


def test_matching_a_live_entry_ignores_case_and_whitespace(tmp_path, monkeypatch):
    """Normalised with decisions.key, the same function the store keys on. A raw string
    compare would orphan a live entry over a doubled space and release it silently."""
    v, stem = _gated(tmp_path, monkeypatch, entries=0)
    import unresolved

    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])
    unresolved.record(stem, "repair_applied", "accepted", original_text="  I saw   SPONDUM ", proposed_text="z")
    _conf(stem, ["I saw spondum"])

    assert mux.process(v, apply=False) == "held-for-review"


def test_an_unreadable_conf_json_holds_everything(tmp_path, monkeypatch):
    """Fails CLOSED. Without conf.json the gate cannot tell an orphan from a live entry, and
    the alternative to holding is releasing unreviewed repairs -- the failure this whole
    spec exists to prevent. A sidecar present with no conf.json is an anomaly, and the
    STALLED alert is what surfaces it."""
    v, _ = _gated(tmp_path, monkeypatch)  # queue written, no conf.json at all
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["Gated Show"])

    assert mux.process(v, apply=False) == "held-for-review"
