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
    assert q["max"] == pytest.approx(5.49)       # every observation counted
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
    assert c["stolen"] == 0                      # declared, not absent


def test_write_returns_false_on_failure_and_never_raises():
    assert qc.write("/nonexistent-dir/x.json", {"a": 1}) is False
