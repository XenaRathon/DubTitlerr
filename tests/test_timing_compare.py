"""Unit tests for tools/timing_compare.py (U2: T2-T6). Pure functions get full synthetic
coverage (pairing, RANSAC fit, overlap classification); the conf.json load/hardening (T3)
and CLI/walk scaffold (T2) are exercised hermetically (tmp_path, no ffmpeg); the real
subtitle-extraction/track-selection I/O (T4's select_reference_track/_sub_codec_map --
ffmpeg/ffprobe subprocess calls) has no real media available in this environment and is
PENDING manual verification on the server -- process_episode()'s orchestration logic
around it IS covered here by monkeypatching select_reference_track (same pattern
tests/test_common.py uses for extract_sub)."""
import json

import pytest

import tools.timing_compare as tc

# ============================================================================
# T2 -- CLI scaffold + walking
# ============================================================================

def test_build_arg_parser_defaults():
    a = tc.build_arg_parser().parse_args(["/some/show"])
    assert a.show_dir == ["/some/show"]
    assert a.tolerance == 0.30
    assert a.out == "timing-compare.report.json"
    assert a.vad == "webrtcvad"
    assert a.vad_aggressiveness == 2
    assert a.summary_only is False


def test_build_arg_parser_vad_choices_reject_bad_value():
    with pytest.raises(SystemExit):
        tc.build_arg_parser().parse_args(["/some/show", "--vad", "bogus"])
    with pytest.raises(SystemExit):
        tc.build_arg_parser().parse_args(["/some/show", "--vad-aggressiveness", "9"])


def test_main_clamps_tolerance_out_of_range(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_process_episode(video, lang, tolerance, **kw):
        seen["tolerance"] = tolerance
        return {"video": video, "status": "no-conf"}

    (tmp_path / "Show" / "S01").mkdir(parents=True)
    (tmp_path / "Show" / "S01" / "ep.mkv").write_bytes(b"")
    monkeypatch.setattr(tc, "process_episode", fake_process_episode)
    tc.main(["Show", "--tolerance", "99"])
    assert seen["tolerance"] == tc.TOLERANCE_MAX

    tc.main(["Show", "--tolerance", "-5"])
    assert seen["tolerance"] == tc.TOLERANCE_MIN


def test_main_default_lang_matches_common_sub_langs_including_untagged(tmp_path, monkeypatch):
    """The blank token ("") must survive the --lang parse so untagged subtitle streams
    (language == "", as common.eng_sub_streams treats a stream with no <language> tag)
    are matched, exactly like common.SUB_LANGS does. Regression test for the bug where
    `if s.strip()` silently dropped "" from the default --lang set, making this tool
    stricter than the pipeline it reports on and wrongly marking untagged-only episodes
    as no-reference."""
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_process_episode(video, lang, tolerance, **kw):
        seen["lang"] = lang
        return {"video": video, "status": "no-conf"}

    (tmp_path / "Show" / "S01").mkdir(parents=True)
    (tmp_path / "Show" / "S01" / "ep.mkv").write_bytes(b"")
    monkeypatch.setattr(tc, "process_episode", fake_process_episode)

    tc.main(["Show"])
    assert "" in seen["lang"]
    assert seen["lang"] == tc.common.SUB_LANGS


def test_main_explicit_lang_keeps_blank_token_like_common_sub_langs(tmp_path, monkeypatch):
    """An explicit --lang string is parsed the same way common.SUB_LANGS parses its env
    var -- no `if s.strip()` filtering -- so a trailing/embedded blank token is kept."""
    monkeypatch.chdir(tmp_path)
    seen = {}

    def fake_process_episode(video, lang, tolerance, **kw):
        seen["lang"] = lang
        return {"video": video, "status": "no-conf"}

    (tmp_path / "Show" / "S01").mkdir(parents=True)
    (tmp_path / "Show" / "S01" / "ep.mkv").write_bytes(b"")
    monkeypatch.setattr(tc, "process_episode", fake_process_episode)

    tc.main(["Show", "--lang", "fre,fr,"])
    assert seen["lang"] == {"fre", "fr", ""}


def test_find_episodes_walks_and_prunes_extra_dirs_and_sorts(tmp_path):
    show = tmp_path / "Show A"
    (show / "S01").mkdir(parents=True)
    (show / "S01" / "b.mkv").write_bytes(b"")
    (show / "S01" / "a.mp4").write_bytes(b"")
    (show / "S01" / "notes.txt").write_bytes(b"")
    extra_dir_name = next(iter(tc.common.EXTRA_DIRS))
    (show / extra_dir_name).mkdir()
    (show / extra_dir_name / "junk.mkv").write_bytes(b"")

    found = tc.find_episodes([str(show)])
    assert found == sorted(found)
    assert str(show / "S01" / "a.mp4") in found
    assert str(show / "S01" / "b.mkv") in found
    assert not any(extra_dir_name in f for f in found)
    assert not any(f.endswith(".txt") for f in found)


def test_find_episodes_accepts_single_video_file(tmp_path):
    f = tmp_path / "solo.mkv"
    f.write_bytes(b"")
    assert tc.find_episodes([str(f)]) == [str(f)]


def test_find_episodes_skips_nonexistent_path(tmp_path, capsys):
    assert tc.find_episodes([str(tmp_path / "nope")]) == []


# ============================================================================
# T3 -- conf.json load + hardening
# ============================================================================

def test_load_conf_missing_file_is_no_conf(tmp_path):
    status, rows = tc.load_conf(str(tmp_path / "missing.dubtitles.conf.json"))
    assert (status, rows) == ("no-conf", [])


def test_load_conf_malformed_json_is_bad_conf(tmp_path):
    p = tmp_path / "bad.dubtitles.conf.json"
    p.write_text("{not valid json")
    assert tc.load_conf(str(p)) == ("bad-conf", [])


def test_load_conf_non_list_top_level_is_bad_conf(tmp_path):
    p = tmp_path / "bad2.dubtitles.conf.json"
    p.write_text(json.dumps({"oops": "not a list"}))
    assert tc.load_conf(str(p)) == ("bad-conf", [])


def test_load_conf_permission_error_is_bad_conf(tmp_path, monkeypatch):
    p = tmp_path / "perm.dubtitles.conf.json"
    p.write_text("[]")

    def raise_perm(*a, **kw):
        raise PermissionError("denied")

    monkeypatch.setattr("builtins.open", raise_perm)
    assert tc.load_conf(str(p)) == ("bad-conf", [])


def test_load_conf_drops_bad_rows_keeps_good_ones(tmp_path):
    rows = [
        {"start": 1.0, "end": 2.0, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "ok"},
        {"start": 5.0, "end": 5.0, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "start==end"},
        {"start": -1.0, "end": 2.0, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "negative start"},
        {"start": 3.0, "end": 2.0, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "start>end"},
        {"start": 6.0, "end": 7.0, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "ok2", "flag": "low_conf"},
    ]
    p = tmp_path / "ep.dubtitles.conf.json"
    p.write_text(json.dumps(rows))
    status, cleaned = tc.load_conf(str(p))
    assert status == "ok"
    assert [r["text"] for r in cleaned] == ["ok", "ok2"]


def test_load_conf_empty_list_is_ok_zero_rows(tmp_path):
    p = tmp_path / "empty.dubtitles.conf.json"
    p.write_text("[]")
    assert tc.load_conf(str(p)) == ("ok", [])


# ============================================================================
# T5 -- nearest_onset_pairs (pure)
# ============================================================================

def test_nearest_onset_pairs_basic():
    card_starts = [0.0, 10.0, 20.0]
    cue_starts = [0.2, 10.3, 25.0]
    pairs = tc.nearest_onset_pairs(card_starts, cue_starts, max_radius_s=5.0)
    assert [(ci, cj) for ci, cj, _d in pairs] == [(0, 0), (1, 1), (2, 2)]
    assert [d for _ci, _cj, d in pairs] == pytest.approx([0.2, 0.3, 5.0])


def test_nearest_onset_pairs_excludes_beyond_radius():
    card_starts = [0.0, 100.0]
    cue_starts = [0.1]
    pairs = tc.nearest_onset_pairs(card_starts, cue_starts, max_radius_s=5.0)
    assert pairs == [(0, 0, 0.1)]      # card 1 has no cue within radius -> omitted


def test_nearest_onset_pairs_tie_break_prefers_earlier_cue():
    # card at 10.0 is exactly 2.0s from cues at 8.0 and 12.0 -> tie -> earlier cue (idx 0)
    card_starts = [10.0]
    cue_starts = [8.0, 12.0]
    pairs = tc.nearest_onset_pairs(card_starts, cue_starts, max_radius_s=5.0)
    assert pairs == [(0, 0, -2.0)]


def test_nearest_onset_pairs_tie_break_lower_index_on_duplicate_cue_time():
    card_starts = [10.0]
    cue_starts = [9.0, 10.0, 10.0, 11.0]   # two cues share the same start time
    pairs = tc.nearest_onset_pairs(card_starts, cue_starts, max_radius_s=5.0)
    assert pairs == [(0, 1, 0.0)]           # exact match -> lower of the tied indices


def test_nearest_onset_pairs_empty_inputs():
    assert tc.nearest_onset_pairs([], [1.0, 2.0]) == []
    assert tc.nearest_onset_pairs([1.0, 2.0], []) == []


def test_resolve_pairs_glue():
    card_starts = [1.0, 5.0, 9.0]
    cue_starts = [1.2, 5.4]
    index_pairs = [(0, 0, 0.2), (2, 1, -3.6)]
    assert tc.resolve_pairs(card_starts, cue_starts, index_pairs) == [(1.0, 1.2), (9.0, 5.4)]


# ============================================================================
# T5 -- ransac_offset_drift (pure, synthetic)
# ============================================================================

def _pairs_from_model(card_starts, a, b, noise=None):
    """Build (card_start, cue_start) pairs implied by offset(t)=a+b*t, i.e.
    cue_start = card_start - (a + b*card_start), optionally jittered per-index."""
    out = []
    for i, ct in enumerate(card_starts):
        cue = ct - (a + b * ct)
        if noise:
            cue += noise[i % len(noise)]
        out.append((ct, cue))
    return out


def test_ransac_offset_drift_constant_offset_no_drift():
    card_starts = [float(i * 10) for i in range(20)]
    pairs = _pairs_from_model(card_starts, a=0.5, b=0.0)
    fit = tc.ransac_offset_drift(pairs)
    assert fit["matched_pairs_count"] == 20
    assert fit["inlier_count"] == 20
    assert fit["offset_a_s"] == pytest.approx(0.5, abs=1e-6)
    assert fit["drift_b"] == pytest.approx(0.0, abs=1e-6)
    assert fit["residual_median_s"] == pytest.approx(0.0, abs=1e-6)
    assert fit["look_for_drift"] is False


def test_ransac_offset_drift_pure_drift_recovers_slope():
    card_starts = [float(i * 20) for i in range(50)]   # 0..980
    pairs = _pairs_from_model(card_starts, a=0.2, b=0.004)   # slope over LOOK_FOR_DRIFT_SLOPE
    fit = tc.ransac_offset_drift(pairs)
    assert fit["inlier_count"] == 50
    assert fit["offset_a_s"] == pytest.approx(0.2, abs=1e-6)
    assert fit["drift_b"] == pytest.approx(0.004, abs=1e-6)
    assert fit["look_for_drift"] is True     # |drift_b| > 0.002


def test_ransac_offset_drift_rejects_outliers_and_recovers_true_line():
    card_starts = [float(i * 10) for i in range(30)]
    good = _pairs_from_model(card_starts, a=0.3, b=0.001)
    # outliers: cue_starts wildly off the true line (5s+ off), well outside the 0.30s band
    outliers = [(305.0, 250.0), (315.0, 400.0), (325.0, 260.0), (335.0, 410.0),
                (345.0, 270.0), (355.0, 420.0), (365.0, 280.0), (375.0, 430.0)]
    pairs = good + outliers
    fit = tc.ransac_offset_drift(pairs)
    assert fit["matched_pairs_count"] == 38
    assert fit["inlier_count"] == 30                 # exactly the good points, outliers rejected
    assert fit["offset_a_s"] == pytest.approx(0.3, abs=1e-6)
    assert fit["drift_b"] == pytest.approx(0.001, abs=1e-6)


def test_ransac_offset_drift_null_guard_offset_below_min_inliers():
    # 5 perfectly-consistent points: inlier_count=5 (< RANSAC_MIN_INLIERS=10) ->
    # offset/drift null, but residual stats ARE reported (inlier_count >= 2).
    card_starts = [0.0, 10.0, 20.0, 30.0, 40.0]
    pairs = _pairs_from_model(card_starts, a=0.4, b=0.0)
    fit = tc.ransac_offset_drift(pairs)
    assert fit["inlier_count"] == 5
    assert fit["offset_a_s"] is None
    assert fit["drift_b"] is None
    assert fit["residual_median_s"] is not None
    assert fit["residual_iqr_s"] is not None


def test_ransac_offset_drift_null_guard_residual_below_min_n():
    fit = tc.ransac_offset_drift([(0.0, -0.4)])   # a single pair: matched=1 < 2
    assert fit == {"offset_a_s": None, "drift_b": None, "matched_pairs_count": 1,
                    "inlier_count": 0, "residual_median_s": None, "residual_iqr_s": None,
                    "look_for_drift": False}


def test_ransac_offset_drift_empty_pairs():
    fit = tc.ransac_offset_drift([])
    assert fit["matched_pairs_count"] == 0
    assert fit["inlier_count"] == 0
    assert fit["offset_a_s"] is None


def test_ransac_offset_drift_look_for_drift_via_residual_iqr():
    # Loosen the inlier band so a genuinely scattered dataset is accepted as "inliers"
    # with residual IQR > 1.0s -- demonstrates the IQR half of the look_for_drift OR
    # fires on its own (whether or not the slope clause also happens to fire).
    card_starts = [float(i * 10) for i in range(20)]
    scatter = [0.0, 2.0, -2.0, 3.0, -3.0]
    pairs = _pairs_from_model(card_starts, a=0.0, b=0.0, noise=scatter)
    fit = tc.ransac_offset_drift(pairs, threshold_s=5.0)
    assert fit["inlier_count"] == 20
    assert fit["residual_iqr_s"] > tc.LOOK_FOR_DRIFT_IQR_S
    assert fit["look_for_drift"] is True


def test_ransac_offset_drift_large_n_random_sampling_is_deterministic():
    card_starts = [float(i * 5) for i in range(200)]   # > RANSAC_EXHAUSTIVE_CAP
    pairs = _pairs_from_model(card_starts, a=0.15, b=0.0015)
    fit1 = tc.ransac_offset_drift(pairs)
    fit2 = tc.ransac_offset_drift(pairs)
    assert fit1 == fit2                                 # fixed seed -> reproducible
    assert fit1["offset_a_s"] == pytest.approx(0.15, abs=0.05)
    assert fit1["drift_b"] == pytest.approx(0.0015, abs=0.001)


# ============================================================================
# T6 -- classify_overlap / align_card / classify_card (pure)
# ============================================================================

def test_classify_overlap_touching_boundary_is_not_overlap():
    # card ends exactly at the tolerance-loosened cue start -> intersection length 0
    assert tc.classify_overlap(5.0, 6.0, 6.3, 7.0, tolerance=0.3) is False


def test_classify_overlap_just_inside_boundary_is_overlap():
    assert tc.classify_overlap(5.0, 6.01, 6.3, 7.0, tolerance=0.3) is True


def test_classify_overlap_partial_overlap_zero_tolerance():
    assert tc.classify_overlap(5.0, 6.5, 6.0, 7.0, tolerance=0.0) is True


def test_classify_overlap_no_overlap_far_apart_zero_tolerance():
    assert tc.classify_overlap(1.0, 2.0, 5.0, 6.0, tolerance=0.0) is False


def test_classify_overlap_card_nested_inside_cue():
    assert tc.classify_overlap(6.1, 6.5, 6.0, 7.0, tolerance=0.0) is True


def test_classify_overlap_cue_nested_inside_card():
    assert tc.classify_overlap(5.0, 8.0, 6.0, 7.0, tolerance=0.0) is True


def test_classify_overlap_tolerance_bridges_a_real_gap():
    # without slack these do not overlap; the 0.3s tolerance on the cue's left edge closes it
    assert tc.classify_overlap(1.0, 2.0, 5.0, 6.0, tolerance=0.0) is False
    assert tc.classify_overlap(4.8, 5.0, 5.2, 6.0, tolerance=0.3) is True


def test_align_card_applies_offset_and_drift():
    fit = {"offset_a_s": 0.5, "drift_b": 0.0}
    aligned_start, aligned_end, low_conf = tc.align_card(10.0, 12.0, fit)
    assert aligned_start == pytest.approx(9.5)
    assert aligned_end == pytest.approx(11.5)
    assert low_conf is False


def test_align_card_no_offset_skips_alignment_and_flags_low_confidence():
    fit = {"offset_a_s": None, "drift_b": None}
    aligned_start, aligned_end, low_conf = tc.align_card(10.0, 12.0, fit)
    assert (aligned_start, aligned_end) == (10.0, 12.0)
    assert low_conf is True


def test_classify_card_on_cue_and_in_gap():
    cues = [(1.0, 2.0, "a"), (10.0, 11.0, "b")]
    assert tc.classify_card(1.5, 1.9, cues, tolerance=0.0) == "on-cue"
    assert tc.classify_card(5.0, 5.5, cues, tolerance=0.0) == "in-gap"
    assert tc.classify_card(4.8, 5.0, cues, tolerance=0.3) == "in-gap"   # 0.2s short of bridging


# ============================================================================
# process_episode() orchestration -- I/O deps (select_reference_track) monkeypatched,
# same hermetic pattern as tests/test_common.py. Real ffmpeg/ffprobe calls (select_
# reference_track's/_sub_codec_map's internals) are PENDING manual verification.
# ============================================================================

def test_process_episode_no_conf(tmp_path):
    video = tmp_path / "ep.mkv"
    video.write_bytes(b"")
    res = tc.process_episode(str(video), {"eng"}, tolerance=0.3)
    assert res == {"video": str(video), "status": "no-conf"}


def test_process_episode_bad_conf(tmp_path):
    video = tmp_path / "ep.mkv"
    video.write_bytes(b"")
    (tmp_path / "ep.dubtitles.conf.json").write_text("not json")
    res = tc.process_episode(str(video), {"eng"}, tolerance=0.3)
    assert res == {"video": str(video), "status": "bad-conf"}


def test_process_episode_no_reference(tmp_path, monkeypatch):
    video = tmp_path / "ep.mkv"
    video.write_bytes(b"")
    (tmp_path / "ep.dubtitles.conf.json").write_text(json.dumps(
        [{"start": 1.0, "end": 2.0, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "hi"}]))
    monkeypatch.setattr(tc, "select_reference_track", lambda video, lang: None)
    res = tc.process_episode(str(video), {"eng"}, tolerance=0.3)
    assert res == {"video": str(video), "status": "no-reference"}


def test_process_episode_empty_conf_is_analyzed_zero_cards(tmp_path, monkeypatch):
    video = tmp_path / "ep.mkv"
    video.write_bytes(b"")
    (tmp_path / "ep.dubtitles.conf.json").write_text("[]")
    ref_track = {"stream_index": 2, "codec": "ass", "cue_count": 100, "density_score": 0.9}
    monkeypatch.setattr(tc, "select_reference_track", lambda video, lang: (ref_track, []))
    res = tc.process_episode(str(video), {"eng"}, tolerance=0.3)
    assert res["status"] == "analyzed"
    assert res["cards"] == []
    assert res["reference_track"] == ref_track
    assert res["fit"]["matched_pairs_count"] == 0


def test_process_episode_analyzed_classifies_and_aligns_cards(tmp_path, monkeypatch):
    video = tmp_path / "ep.mkv"
    video.write_bytes(b"")
    rows = [{"start": 10.5, "end": 11.5, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "on cue"},
            {"start": 50.0, "end": 51.0, "avg_logprob": -0.1, "no_speech_prob": 0.05, "text": "in gap"}]
    (tmp_path / "ep.dubtitles.conf.json").write_text(json.dumps(rows))
    # cue at 10.5 (matches card 1 exactly); nothing near 50.0 -> card 2 stays in-gap
    ref_track = {"stream_index": 3, "codec": "ass", "cue_count": 1, "density_score": 1.0}
    cue_intervals = [(10.5, 11.5, "cue text")]
    monkeypatch.setattr(tc, "select_reference_track", lambda video, lang: (ref_track, cue_intervals))
    # T7 wiring: no real ffmpeg/ffprobe/webrtcvad in this test -- monkeypatch the I/O seam
    # exactly like select_reference_track above, same hermetic pattern.
    monkeypatch.setattr(tc, "select_audio_stream", lambda video: 1)
    extract_calls = []

    def fake_extract(video, audio_idx, start_s, end_s, out_wav):
        extract_calls.append((audio_idx, start_s, end_s))
        return True

    monkeypatch.setattr(tc, "extract_audio_window", fake_extract)
    monkeypatch.setattr(tc.vad, "vad_probe", lambda wav_path, aggressiveness, backend: True)

    res = tc.process_episode(str(video), {"eng"}, tolerance=0.3)
    assert res["status"] == "analyzed"
    assert res["cue_count"] == 1
    by_text = {c["text"]: c for c in res["cards"]}
    assert by_text["on cue"]["classification"] == "on-cue"
    assert by_text["in gap"]["classification"] == "in-gap"
    # only 1 nearest-onset pair total -> inlier_count < 10 -> low-confidence alignment
    assert by_text["on cue"]["low_confidence_alignment"] is True
    # T7: VAD only touches in-gap cards, and only ever probes the card's ORIGINAL
    # (un-aligned) [start, end] -- never aligned_start/aligned_end.
    assert "in_gap_vad_verdict" not in by_text["on cue"]
    assert by_text["in gap"]["in_gap_vad_verdict"] == "in_gap_speech"
    assert extract_calls == [(1, 50.0, 51.0)]


# ============================================================================
# T7 -- classify_in_gap_cards() orchestration (verdict mapping, on-cue cards untouched,
# no-audio-stream fallback). select_audio_stream/extract_audio_window themselves are real
# ffmpeg/ffprobe I/O -- PENDING manual verification on the server, same status as T4's
# select_reference_track/_sub_codec_map; monkeypatched here exactly like those.
# ============================================================================

def test_classify_in_gap_cards_no_in_gap_cards_is_noop(monkeypatch):
    called = []
    monkeypatch.setattr(tc, "select_audio_stream", lambda video: called.append(video) or 0)
    cards = [{"classification": "on-cue", "start": 1.0, "end": 2.0}]
    tc.classify_in_gap_cards("ep.mkv", cards)
    assert cards == [{"classification": "on-cue", "start": 1.0, "end": 2.0}]
    assert called == []          # no in-gap cards -> select_audio_stream never even called


def test_classify_in_gap_cards_no_audio_stream_all_error_no_extract_attempted(monkeypatch):
    monkeypatch.setattr(tc, "select_audio_stream", lambda video: None)
    extract_called = []
    monkeypatch.setattr(tc, "extract_audio_window", lambda *a: extract_called.append(a) or True)
    cards = [{"classification": "in-gap", "start": 1.0, "end": 2.0},
             {"classification": "in-gap", "start": 3.0, "end": 4.0}]
    tc.classify_in_gap_cards("ep.mkv", cards)
    assert all(c["in_gap_vad_verdict"] == "in_gap_vad_error" for c in cards)
    assert extract_called == []


def test_classify_in_gap_cards_extract_failure_is_vad_error_and_skips_probe(monkeypatch):
    monkeypatch.setattr(tc, "select_audio_stream", lambda video: 2)
    monkeypatch.setattr(tc, "extract_audio_window", lambda video, idx, s, e, out: False)
    probe_called = []
    monkeypatch.setattr(tc.vad, "vad_probe", lambda *a, **kw: probe_called.append((a, kw)) or True)
    cards = [{"classification": "in-gap", "start": 1.0, "end": 2.0}]
    tc.classify_in_gap_cards("ep.mkv", cards)
    assert cards[0]["in_gap_vad_verdict"] == "in_gap_vad_error"
    assert probe_called == []    # extraction failed -> never call vad_probe on a missing window


@pytest.mark.parametrize("verdict,expected", [
    (True, "in_gap_speech"),
    (False, "in_gap_silent"),
    (None, "in_gap_vad_error"),
])
def test_classify_in_gap_cards_verdict_mapping(monkeypatch, verdict, expected):
    monkeypatch.setattr(tc, "select_audio_stream", lambda video: 2)
    monkeypatch.setattr(tc, "extract_audio_window", lambda video, idx, s, e, out: True)
    monkeypatch.setattr(tc.vad, "vad_probe", lambda *a, **kw: verdict)
    cards = [{"classification": "in-gap", "start": 5.0, "end": 6.0}]
    tc.classify_in_gap_cards("ep.mkv", cards)
    assert cards[0]["in_gap_vad_verdict"] == expected


def test_classify_in_gap_cards_only_touches_in_gap_cards(monkeypatch):
    monkeypatch.setattr(tc, "select_audio_stream", lambda video: 2)
    monkeypatch.setattr(tc, "extract_audio_window", lambda video, idx, s, e, out: True)
    monkeypatch.setattr(tc.vad, "vad_probe", lambda *a, **kw: True)
    on_cue = {"classification": "on-cue", "start": 1.0, "end": 2.0}
    in_gap = {"classification": "in-gap", "start": 3.0, "end": 4.0}
    cards = [on_cue, in_gap]
    tc.classify_in_gap_cards("ep.mkv", cards)
    assert "in_gap_vad_verdict" not in on_cue
    assert in_gap["in_gap_vad_verdict"] == "in_gap_speech"


def test_classify_in_gap_cards_passes_original_unaligned_window(monkeypatch):
    """Regression guard for the spec-v3.md requirement that the VAD window is extracted at
    the card's ORIGINAL Whisper-timebase [start, end], never aligned_start/aligned_end."""
    monkeypatch.setattr(tc, "select_audio_stream", lambda video: 7)
    seen = []

    def fake_extract(video, idx, s, e, out):
        seen.append((s, e))
        return True

    monkeypatch.setattr(tc, "extract_audio_window", fake_extract)
    monkeypatch.setattr(tc.vad, "vad_probe", lambda *a, **kw: False)
    cards = [{"classification": "in-gap", "start": 12.34, "end": 13.5,
              "aligned_start": 99.0, "aligned_end": 100.0}]
    tc.classify_in_gap_cards("ep.mkv", cards)
    assert seen == [(12.34, 13.5)]
