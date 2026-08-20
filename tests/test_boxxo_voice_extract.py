"""Unit tests for boxxo_voice_extract.py's pure logic: SDH speaker-tag parsing and the
Storms/Tindle season-episode validity window. No ffmpeg/pysubs2 I/O — those paths
(sdh_track_index, cut_clip, process_episode) need real media and aren't covered here.
"""
import boxxo_voice_extract as bve


def test_parse_season_episode():
    assert bve.parse_season_episode("Show - S01E05 - Title [WEBDL].mkv") == (1, 5)
    assert bve.parse_season_episode("Show - S02E08 - Title.mkv") == (2, 8)
    assert bve.parse_season_episode("no season episode marker.mkv") is None


def test_is_storms_episode():
    assert bve.is_storms_episode(1, 1) is True
    assert bve.is_storms_episode(1, 12) is True
    assert bve.is_storms_episode(2, 7) is False       # Tindle
    assert bve.is_storms_episode(2, 8) is True        # Storms returns
    assert bve.is_storms_episode(2, 20) is True
    assert bve.is_storms_episode(3, 1) is True
    assert bve.is_storms_episode(4, 1) is False        # unlisted season -> excluded, not assumed


def test_single_speaker_two_line_card():
    # "[BOXXO]\NHello there." — tag on line 1, continuation on line 2, no dash.
    segs = bve.extract_speaker_segments("[BOXXO]\nHello there.", 10.0, 12.0)
    assert segs == [{"speaker": "BOXXO", "text": "Hello there.", "start": 10.0, "end": 12.0, "audio_safe": True}]


def test_single_speaker_missing_opening_bracket():
    # Real CR captioning typo seen in the wild: "PROTAGONIST] ..." with no leading "[".
    segs = bve.extract_speaker_segments("PROTAGONIST] I just thought\nof a way to beat them!", 5.0, 7.0)
    assert segs == [{"speaker": "PROTAGONIST", "text": "I just thought of a way to beat them!",
                      "start": 5.0, "end": 7.0, "audio_safe": True}]


def test_shared_card_two_speakers_only_target_kept():
    # "-Someone help me, please!\N-[BOXXO] Hello there!" — first line is another
    # character (untagged continuation), second is Boxxo. Not audio_safe: both share
    # one event timespan.
    segs = bve.extract_speaker_segments("-Someone help me, please!\n-[BOXXO] Hello there!", 45.0, 48.0)
    assert segs == [{"speaker": "BOXXO", "text": "Hello there!", "start": 45.0, "end": 48.0, "audio_safe": False}]


def test_non_target_speaker_dropped():
    segs = bve.extract_speaker_segments("[MUNAMI]\nThat's not fair!", 1.0, 2.0)
    assert segs == []


def test_sound_effect_cue_not_mistaken_for_speaker():
    # Lowercase bracket = SDH sound cue, not a speaker tag -- must never match as one.
    segs = bve.extract_speaker_segments("[gasps]", 1.0, 2.0)
    assert segs == []


def test_shared_card_both_lines_untagged_yields_nothing():
    segs = bve.extract_speaker_segments("-Line one\n-Line two", 1.0, 2.0)
    assert segs == []
