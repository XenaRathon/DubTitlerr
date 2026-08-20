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
    assert r.build(show="S", episode="E", stem="x")["events"][0] == {
        "card_id": "c0", "reason": "layout_exception"}
