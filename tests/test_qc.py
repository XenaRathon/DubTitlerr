import pytest

import qc


def test_quantiles_are_complete_even_when_events_truncate():
    r = qc.Recorder()
    for i in range(qc.MAX_EVENTS + 50):
        r.observe("displacement", i * 0.01)
        r.event(card_id=f"c{i}", effects=["displaced"], delta_start=i * 0.01)
    doc = r.build(show="S", episode="E1", stem="/x/E1")
    assert doc["events_truncated"] is True
    assert doc["events_retained"] == qc.MAX_EVENTS
    assert doc["event_count_total"] == qc.MAX_EVENTS + 50
    q = doc["quantiles"]["displacement"]
    assert q["max"] == pytest.approx(5.49)  # every observation counted
    assert q["p50"] < q["p90"] < q["p99"] <= q["max"]


def test_effects_is_a_list_not_an_enum():
    r = qc.Recorder()
    r.event(card_id="c0", effects=["shortened", "displaced"])
    ev = r.build(show="S", episode="E1", stem="/x/E1")["events"][0]
    assert ev["effects"] == ["shortened", "displaced"]


def test_counters_default_to_zero_and_increment():
    r = qc.Recorder()
    r.count("merged_backward", 3)
    c = r.build(show="S", episode="E1", stem="/x/E1")["counters"]
    assert c["merged_backward"] == 3
    assert c["stolen"] == 0  # declared, not absent


def test_write_returns_false_on_failure_and_never_raises():
    assert qc.write("/nonexistent-dir/x.json", {"a": 1}) is False


def test_priority_events_are_never_evicted_by_ordinary_ones():
    """A common event class must not crowd out a rare one that no counter can
    reconstruct -- measured: ~130 over_cps events per episode against a handful of
    correction-introduced layout exceptions."""
    r = qc.Recorder()
    for i in range(qc.MAX_EVENTS + 200):
        r.event(card_id=f"noise{i}", effects=["displaced"])
    r.event(priority=True, card_id="rare", reason="layout_exception")
    doc = r.build(show="S", episode="E1", stem="/x/E1")
    kinds = [e.get("reason") for e in doc["events"]]
    assert "layout_exception" in kinds
    assert doc["events_truncated"] is True
    assert doc["event_count_total"] == qc.MAX_EVENTS + 201


def test_priority_flag_is_not_stored_as_an_event_field():
    r = qc.Recorder()
    r.event(priority=True, card_id="c0", reason="layout_exception")
    assert r.build(show="S", episode="E", stem="x")["events"][0] == {"card_id": "c0", "reason": "layout_exception"}


def test_sidecar_is_written_world_readable_and_group_writable(tmp_path):
    """mkstemp gives 0600. This sidecar exists to be read library-wide by an aggregator
    that is not root, so 0600 would make it unreadable over the share -- and it must be
    GROUP-WRITABLE too, because the uid that regenerates the episode is not always the uid
    that created the sidecar. 0644 shipped for months and broke every non-root writer."""
    import stat

    p = tmp_path / "e.dubtitles.qc.json"
    assert qc.write(str(p), {"a": 1}) is True
    assert stat.S_IMODE(p.stat().st_mode) == 0o664


def test_qc_mode_matches_common(tmp_path):
    """qc.py is standalone by design and hardcodes its mode rather than importing common.
    This is the guard that stops the two drifting -- referenced by name in both files."""
    import stat

    import common

    p = tmp_path / "e.dubtitles.qc.json"
    assert qc.write(str(p), {"a": 1}) is True
    assert stat.S_IMODE(p.stat().st_mode) == common.SIDECAR_MODE


def test_plain_open_sidecars_are_group_writable(tmp_path):
    """common sets umask 002 at import so the sites that use a bare open(path, "w") --
    write_stamp, the .fail marker, crash/lastrun json, repair's outputs, mux.log -- come out
    group-writable without each one needing its own chmod."""
    import stat

    import common  # noqa: F401  (import applies the umask)

    p = tmp_path / "plain.json"
    with open(p, "w") as f:
        f.write("{}")
    assert stat.S_IMODE(p.stat().st_mode) & 0o060 == 0o060, "group rw expected under umask 002"


def test_duration_threshold_constants_exposed():
    assert qc.OVERLONG_DUR_FLOOR == 6.0
    assert qc.OVERLONG_BASE_DUR == 3.0
    assert qc.OVERLONG_WORD_FACTOR == 0.6
    assert qc.DRIP_MIN_CARDS == 3
    assert qc.DRIP_MIN_WORDS == 1
    assert qc.DRIP_MAX_WORDS == 2
    assert qc.DRIP_MAX_GAP == 1.0
    assert qc.DRIP_MIN_SPAN == 6.0


def test_overlong_card_flags_four_real_one_pace_examples():
    cards = [
        {"start": 10.0, "end": 32.9, "text": "I want to be."},
        {"start": 40.0, "end": 50.6, "text": "Meow!"},
        {"start": 60.0, "end": 66.9, "text": "My eyes are"},
        {"start": 70.0, "end": 76.4, "text": "mom what do you"},
    ]
    flags = qc.detect_duration_flags(cards)
    assert len(flags) == 4

    f0 = flags[0]
    assert f0 == {
        "start": 10.0,
        "end": 32.9,
        "duration": 22.9,
        "words": 4,
        "text": "I want to be.",
        "reason": "overlong",
    }

    f1 = flags[1]
    assert f1 == {
        "start": 40.0,
        "end": 50.6,
        "duration": 10.6,
        "words": 1,
        "text": "Meow!",
        "reason": "overlong",
    }

    f2 = flags[2]
    assert f2 == {
        "start": 60.0,
        "end": 66.9,
        "duration": 6.9,
        "words": 3,
        "text": "My eyes are",
        "reason": "overlong",
    }

    f3 = flags[3]
    assert f3 == {
        "start": 70.0,
        "end": 76.4,
        "duration": 6.4,
        "words": 4,
        "text": "mom what do you",
        "reason": "overlong",
    }


def test_normal_cards_must_not_be_flagged():
    cards = [
        # 12 words shown 6.5s: duration > 6.0, but 12 * 0.6 = 7.2 > 6.5 -> not flagged
        {"start": 0.0, "end": 6.5, "text": "This is a normal subtitle card with twelve words that reads totally fine."},
        # Short card: duration <= 6.0 -> not flagged
        {"start": 10.0, "end": 12.5, "text": "Four words right here."},
    ]
    flags = qc.detect_duration_flags(cards)
    assert flags == []


def test_drip_chain_flagged():
    # 3 consecutive cards each holding 1-2 words, gaps < 1.0 s, span > 6.0 s
    cards = [
        {"start": 10.0, "end": 12.5, "text": "I am"},
        {"start": 12.9, "end": 15.0, "text": "going"},
        {"start": 15.5, "end": 17.5, "text": "home."},
    ]
    flags = qc.detect_duration_flags(cards)
    assert len(flags) == 1
    assert flags[0] == {
        "start": 10.0,
        "end": 17.5,
        "duration": 7.5,
        "words": 4,
        "text": "I am going home.",
        "reason": "drip_chain",
    }


def test_real_pause_case_must_not_be_drip_chain():
    # 3 cards each holding 1-2 words, but gap between card 1 and 2 is 1.5s (>= 1.0s)
    cards = [
        {"start": 10.0, "end": 12.5, "text": "Wait."},
        {"start": 14.0, "end": 16.0, "text": "Who is"},
        {"start": 16.4, "end": 18.0, "text": "there?"},
    ]
    flags = qc.detect_duration_flags(cards)
    # Neither card 1 alone nor cards 2+3 (2 cards < 3, span 4.0 <= 6.0) qualifies as a drip chain.
    # Also individual cards durations are <= 2.5s (not overlong).
    assert flags == []


def test_detector_does_not_change_any_card():
    import copy

    cards = [
        {"start": 10.0, "end": 32.9, "text": "I want to be.\nSome wrap"},
        {"start": 40.0, "end": 42.0, "text": "Meow!"},
    ]
    orig = copy.deepcopy(cards)
    qc.detect_duration_flags(cards)
    assert cards == orig


def test_qc_sidecar_output_includes_duration_flags():
    r = qc.Recorder()
    cards = [
        {"start": 1.0, "end": 23.9, "text": "I want to be."},
    ]
    r.record_duration_flags(cards)
    doc = r.build(show="One Pace", episode="E13", stem="/x/E13")
    assert "duration_flags" in doc
    assert doc["duration_flags"] == [
        {
            "start": 1.0,
            "end": 23.9,
            "duration": 22.9,
            "words": 4,
            "text": "I want to be.",
            "reason": "overlong",
        }
    ]


def test_generate_record_qc_wires_duration_flags():
    import sys
    import types

    if "faster_whisper" not in sys.modules:
        fake = types.ModuleType("faster_whisper")

        class _UnusedWhisperModel:
            def __init__(self, *a, **kw):
                raise AssertionError("WhisperModel must never be instantiated by these tests")

        fake.WhisperModel = _UnusedWhisperModel
        sys.modules["faster_whisper"] = fake

    import generate

    r = qc.Recorder()
    cards = [
        {"start": 0.0, "end": 10.6, "text": "Meow!", "source_start": 0.0, "source_end": 10.6},
    ]
    generate._record_qc(r, cards)
    doc = r.build(show="One Pace", episode="E13", stem="/x/E13")
    assert doc["duration_flags"] == [
        {
            "start": 0.0,
            "end": 10.6,
            "duration": 10.6,
            "words": 1,
            "text": "Meow!",
            "reason": "overlong",
        }
    ]


