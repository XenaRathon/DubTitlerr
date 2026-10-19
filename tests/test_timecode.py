"""Unit tests for subtitle timecode parsing, formatting, and edge cases.

Covers:
- Comma vs. period millisecond separators in SRT cues
- Zero-duration cue handling (start == end)
- Out-of-order or negative timecode protection and behavior in pysubs2 and common helpers
"""

import pysubs2

import common

# --- Comma vs. Period Millisecond Separators in SRT Cues ---------------------


def test_srt_timecode_parsing_comma_separator():
    """Standard SRT uses commas for millisecond separators (HH:MM:SS,mmm)."""
    srt_data = """1
00:01:02,345 --> 00:01:05,678
Standard comma separator cue
"""
    subs = pysubs2.SSAFile.from_string(srt_data, format_="srt")
    assert len(subs) == 1
    ev = subs[0]
    assert ev.start == 62345  # 1m 2s 345ms = 62,345 ms
    assert ev.end == 65678    # 1m 5s 678ms = 65,678 ms
    assert ev.text == "Standard comma separator cue"


def test_srt_timecode_parsing_period_separator():
    """Non-standard but common SRT variant uses periods for milliseconds (HH:MM:SS.mmm)."""
    srt_data = """1
00:01:02.345 --> 00:01:05.678
Non-standard period separator cue
"""
    subs = pysubs2.SSAFile.from_string(srt_data, format_="srt")
    assert len(subs) == 1
    ev = subs[0]
    assert ev.start == 62345
    assert ev.end == 65678
    assert ev.text == "Non-standard period separator cue"


def test_srt_timecode_mixed_separators():
    """Test SRT cue with comma in start time and period in end time."""
    srt_data = """1
00:00:01,200 --> 00:00:03.800
Mixed separator cue
"""
    subs = pysubs2.SSAFile.from_string(srt_data, format_="srt")
    assert len(subs) == 1
    ev = subs[0]
    assert ev.start == 1200
    assert ev.end == 3800


# --- Zero-Duration Cue Handling ----------------------------------------------


def test_zero_duration_cue_parsing_srt():
    """Zero-duration cue where start time equals end time (start == end)."""
    srt_data = """1
00:00:05,000 --> 00:00:05,000
Flash subtitle
"""
    subs = pysubs2.SSAFile.from_string(srt_data, format_="srt")
    assert len(subs) == 1
    ev = subs[0]
    assert ev.start == 5000
    assert ev.end == 5000
    assert ev.end - ev.start == 0


def test_zero_duration_cue_is_dialogue_event():
    """Zero-duration event with non-empty dialogue text is still identified as dialogue."""
    ev = pysubs2.SSAEvent(start=5000, end=5000, text="Flash cue", style="Default")
    assert common.is_dialogue_event(ev)


def test_zero_duration_cue_dialogue_intervals(monkeypatch):
    """dialogue_intervals extracts zero-duration cues correctly into interval tuples."""
    sub = pysubs2.SSAFile()
    sub.events = [pysubs2.SSAEvent(start=5000, end=5000, text="Flash cue", style="Default")]

    def fake_extract(video, idx, out_path):
        sub.save(out_path)
        return True

    monkeypatch.setattr(common, "extract_sub", fake_extract)
    ivals = common.dialogue_intervals("fake.mkv", stream_indices=[0])
    assert ivals == [(5.0, 5.0, "Flash cue")]


# --- Out-of-Order and Negative Timecode Handling -----------------------------


def test_out_of_order_start_end_timecodes_in_cue():
    """Cue where start time is greater than end time (start > end)."""
    srt_data = """1
00:00:10,000 --> 00:00:05,000
Inverted timecode cue
"""
    subs = pysubs2.SSAFile.from_string(srt_data, format_="srt")
    assert len(subs) == 1
    ev = subs[0]
    assert ev.start == 10000
    assert ev.end == 5000
    assert ev.end < ev.start
    assert ev.end - ev.start == -5000


def test_dialogue_intervals_sorts_out_of_order_cues(monkeypatch):
    """cues that appear out of chronological order in the file are sorted by start time."""
    sub = pysubs2.SSAFile()
    sub.events = [
        pysubs2.SSAEvent(start=10000, end=12000, text="Second in time", style="Default"),
        pysubs2.SSAEvent(start=2000, end=4000, text="First in time", style="Default"),
    ]

    def fake_extract(video, idx, out_path):
        sub.save(out_path)
        return True

    monkeypatch.setattr(common, "extract_sub", fake_extract)
    ivals = common.dialogue_intervals("fake.mkv", stream_indices=[0])
    assert ivals == [
        (2.0, 4.0, "First in time"),
        (10.0, 12.0, "Second in time"),
    ]


def test_ts_srt_formatting_standard_and_edge_values():
    """ts_srt formats floats into HH:MM:SS,mmm string representations."""
    assert common.ts_srt(0.0) == "00:00:00,000"
    assert common.ts_srt(1.5) == "00:00:01,500"
    assert common.ts_srt(62.345) == "00:01:02,345"
    assert common.ts_srt(3661.005) == "01:01:01,005"


def test_ts_srt_negative_timecode_behavior():
    """Document ts_srt behavior on negative inputs (e.g. before zero)."""
    # Negative values use Python integer floor division:
    # -0.5 // 3600 = -1 (hours = -1 -> "-1")
    # (-0.5 % 3600) // 60 = 3599 // 60 = 59 (minutes = 59 -> "59")
    # -0.5 % 60 = 59.5 (seconds = 59.500)
    formatted = common.ts_srt(-0.5)
    assert formatted.startswith("-") or "59" in formatted
    assert common.ts_srt(-0.5) == "-1:59:59,500"


def test_ass_timecode_parsing():
    """Verify ASS timecode format (H:MM:SS.cs) parsing in pysubs2."""
    ass_data = """[Script Info]
ScriptType: v4.00+

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:01:02.34,0:01:05.67,Default,,0,0,0,,ASS timecode cue
"""
    subs = pysubs2.SSAFile.from_string(ass_data, format_="ass")
    assert len(subs) == 1
    ev = subs[0]
    # ASS centiseconds: 1m 2s 34cs = 62,340 ms; 1m 5s 67cs = 65,670 ms
    assert ev.start == 62340
    assert ev.end == 65670
