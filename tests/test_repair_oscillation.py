"""Phase 28 F8: an A -> B -> A proposal sequence leaves the LATEST unreviewed proposal as the only active review question.

Sol's probe: unchanged original, successive model proposals X, Y, X with no human decision between runs. Run 2 retired X as
superseded by Y; run 3 found X among the queue's history, so it neither reopened X nor retired Y: the SRT held X while the only
pending question was Y, and an accept on Y released the review gate for a line nobody had reviewed."""

import test_repair as tr

import decisions
import mux
import repair
import unresolved

ORIG = "the old line"
X, Y = "the new line", "the good line"


def _run(tmp_path, monkeypatch, replies):
    stem, conf_path = tr._one_target(tmp_path, "ep_osc", text=ORIG)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_osc.mkv"))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: ({}, "Show"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: tr.gl())
    it = iter(replies)
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: next(it))
    for _ in replies:
        repair.process(conf_path)
    return stem


def _applied(stem):
    return [e for e in unresolved.items(stem) if e["stage"] == "repair_applied"]


def test_a_returning_proposal_reopens_its_superseded_entry_and_retires_the_other(tmp_path, monkeypatch):
    stem = _run(tmp_path, monkeypatch, [X, Y, X])
    entries = _applied(stem)
    open_now = [e for e in entries if not e.get("resolved")]
    assert [e["proposed_text"] for e in open_now] == [X], "the proposal in the SRT is the only open question"
    y = next(e for e in entries if e["proposed_text"] == Y)
    assert y["resolved"] is True and y["note"].startswith("superseded"), "Y is retired, kept for the audit trail"
    assert len(entries) == 2, "X's entry was reopened, not duplicated"
    assert X in open(stem + repair.SRT_SUFFIX).read()


def test_an_accept_on_the_retired_proposal_does_not_release_the_hold(tmp_path, monkeypatch):
    stem = _run(tmp_path, monkeypatch, [X, Y, X])
    store = decisions.record({}, ORIG, Y, "accept")  # a stale tab approves Y, which is NOT what is in the SRT
    monkeypatch.setattr(mux, "REVIEW_GATE_SHOWS", ["S"])
    monkeypatch.setattr(mux, "show_for", lambda _: "S")
    monkeypatch.setattr(mux, "decisions_for", lambda _: (store, "S"))
    assert mux.held_for_review(stem) is True


def test_an_identical_rerun_still_queues_nothing_new(tmp_path, monkeypatch):
    stem = _run(tmp_path, monkeypatch, [X, X, X])
    assert len(_applied(stem)) == 1


def test_a_settled_pair_is_not_reopened(tmp_path, monkeypatch):
    """A pair a human resolved (not merely superseded) stays settled."""
    stem = _run(tmp_path, monkeypatch, [X])
    unresolved.resolve(stem, 0, accept=True, note="")
    it = iter([X])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: next(it))
    repair.process(stem + repair.CONF_SUFFIX)
    (entry,) = _applied(stem)
    assert entry["resolved"] is True
