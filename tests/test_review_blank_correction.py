"""Phase 28 F3: a blank correction is refused by name, stays pending and is never counted as saved.

Sol's probe: `correct` with text "" (or whitespace) made decisions.record drop the verdict silently, yet the handler counted it as
saved and resolved the queue entry as accepted, which released an opted-in review hold with no stored human verdict."""

import json

import pytest

import decisions
import mux
import review_server as rs
import unresolved

ORIG, PROP = "the old line", "the wrong line"


@pytest.fixture
def ep(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep")
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"text": ORIG}], f)
    unresolved.record(stem, "repair_applied", "accepted", original_text=ORIG, proposed_text=PROP)
    monkeypatch.setattr(rs, "_resolve", lambda _: stem)
    monkeypatch.setattr(rs, "show_for", lambda _: "S")
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["S"])
    monkeypatch.setattr(mux, "show_for", lambda _: "S")
    monkeypatch.setattr(mux, "decisions_for", lambda _: (decisions.load("S", str(tmp_path)), "S"))
    return stem, tmp_path


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_a_blank_correction_is_refused_by_name_and_stays_pending(ep, text):
    stem, d = ep
    res = rs.handle_decide_batch(stem, [{"index": 0, "verdict": "correct", "text": text}])
    assert res["saved"] == 0 and res["errors"][0]["index"] == 0 and "text" in res["errors"][0]["error"]
    assert decisions.load("S", str(d)).get("decisions", []) == []
    (entry,) = unresolved.items(stem)
    assert entry["resolved"] is False
    assert mux.held_for_review(stem) is True, "no human verdict exists, so the hold stays"


def test_the_single_verdict_path_reports_the_error(ep):
    stem, _ = ep
    assert "text" in rs.handle_decide(stem, 0, "correct", text=" ")["error"]


def test_a_good_verdict_beside_a_blank_one_still_lands(ep, tmp_path):
    stem, d = ep
    unresolved.record(stem, "repair_applied", "accepted", original_text="b old", proposed_text="b new")
    res = rs.handle_decide_batch(
        stem,
        [{"index": 0, "verdict": "correct", "text": ""}, {"index": 1, "verdict": "accept"}],
    )
    assert res["saved"] == 1 and len(res["errors"]) == 1
    open_now = [e["original_text"] for e in unresolved.items(stem) if not e["resolved"]]
    assert open_now == [ORIG]


def test_a_correction_that_restores_the_original_is_stored_as_a_rejection(ep):
    """record() turns it into a reject; the queue entry must say rejected, not accepted."""
    stem, d = ep
    res = rs.handle_decide_batch(stem, [{"index": 0, "verdict": "correct", "text": ORIG}])
    assert res["saved"] == 1 and not res["errors"]
    assert decisions.lookup(decisions.load("S", str(d)), ORIG, PROP)["verdict"] == "reject"
    assert unresolved.items(stem)[0]["accepted"] is False


def test_the_shared_path_refuses_a_blank_correction_too(tmp_path, monkeypatch):
    for name in ("e01", "e02"):
        stem = str(tmp_path / name)
        with open(stem + ".dubtitles.conf.json", "w") as f:
            json.dump([{"text": ORIG}], f)
        unresolved.record(stem, "repair_applied", "accepted", original_text=ORIG, proposed_text=PROP)
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path)])
    monkeypatch.setattr(rs, "_STEMS_CACHE", (0.0, []))
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path))
    monkeypatch.setattr(rs, "show_for", lambda _: "S")
    sid = rs.handle_shared()["pairs"][0]["id"]
    res = rs.handle_shared_decide([{"id": sid, "verdict": "correct", "text": "  "}])
    assert res["saved"] == 0 and "text" in res["errors"][0]["error"]
    assert decisions.load("S", str(tmp_path)).get("decisions", []) == []
    assert rs.handle_shared()["pairs"], "the pair is still on the page"


def test_both_pages_stop_a_correct_verdict_with_no_text_before_posting(ep, monkeypatch):
    stem, d = ep
    monkeypatch.setattr(rs, "ROOTS", [str(d)])  # render_shared walks the library; keep its stem cache out of other tests
    monkeypatch.setattr(rs, "_STEMS_CACHE", (0.0, []))
    assert "A correction needs text" in rs.render_page(stem)
    assert "A correction needs text" in rs.render_shared()


@pytest.mark.parametrize("text", ["​", "‌‍", "﻿", "⁠", " ​   ", "­", "‎"])
def test_invisible_characters_count_as_blank(ep, text):
    """Zero-width and other format characters (Unicode Cf), no-break/line spaces and controls look empty on a card."""
    stem, d = ep
    res = rs.handle_decide_batch(stem, [{"index": 0, "verdict": "correct", "text": text}])
    assert res["saved"] == 0 and "text" in res["errors"][0]["error"]
    assert decisions.load("S", str(d)).get("decisions", []) == []
    assert decisions.is_blank(text)


def test_decisions_record_drops_an_invisible_correction_too(tmp_path):
    store = decisions.record({}, ORIG, PROP, "correct", text="​﻿")
    assert decisions.lookup(store, ORIG, PROP) is None
    assert not decisions.is_blank("a") and not decisions.is_blank("?!") and not decisions.is_blank("café​")
