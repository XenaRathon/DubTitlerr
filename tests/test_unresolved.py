"""Per-stage unresolved queue -- the missing human rung of the deterministic -> LLM -> human
ladder for the subtitle path (glossary_acquire already has one; repair/punctuation did not)."""
import json
import os
import stat

import pytest

import unresolved


def test_records_per_stage_and_survives_reread(tmp_path):
    stem = str(tmp_path / "ep")
    assert unresolved.record(stem, "repair", "no_reference", original_text="Gum -gum!",
                             source_start=1.0, source_end=1.4, avg_logprob=-0.79) is True
    assert unresolved.record(stem, "punctuation", "llm_empty",
                             original_text="who are you") is True
    got = unresolved.items(stem)
    assert [e["stage"] for e in got] == ["repair", "punctuation"]
    assert got[0]["reason"] == "no_reference"
    assert got[0]["original_text"] == "Gum -gum!"
    assert got[0]["source_start"] == 1.0


def test_rejected_guard_keeps_the_model_proposal(tmp_path):
    """repair.py currently increments `rejected` and DISCARDS what the model proposed. The
    proposal is the whole evidence a human needs to judge whether the guard was right."""
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "rejected_guard",
                      original_text="catch Hirohoshi",
                      proposed_text="catch Crocodile", avg_logprob=-1.2)
    e = unresolved.items(stem)[0]
    assert e["original_text"] == "catch Hirohoshi"
    assert e["proposed_text"] == "catch Crocodile"


def test_never_raises_and_never_blocks_an_episode(tmp_path):
    """Same contract as qc.write: this is observability. It must not fail an episode that
    otherwise generated correctly."""
    assert unresolved.record("/nonexistent/dir/ep", "repair", "no_reference") is False
    assert unresolved.items("/nonexistent/dir/ep") == []


def test_sidecar_is_group_writable(tmp_path):
    """A non-root writer must be able to append later -- see common.SIDECAR_MODE."""
    import common
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference")
    mode = stat.S_IMODE(os.stat(stem + unresolved.SUFFIX).st_mode)
    assert mode == common.SIDECAR_MODE


def test_append_is_o1_and_readable_at_every_step(tmp_path):
    """JSONL: one entry per line, appended. The array version re-read and re-wrote the whole
    file per card -- O(n^2) I/O on a path that fires ~86x per episode, one CIFS round-trip
    each. The file must still parse after every append."""
    stem = str(tmp_path / "ep")
    for i in range(5):
        unresolved.record(stem, "repair", "no_reference", original_text=f"line {i}")
        assert len(unresolved.items(stem)) == i + 1


def test_torn_final_line_costs_only_that_entry(tmp_path):
    """The one failure an append can produce. Everything before it must survive."""
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference", original_text="intact")
    with open(stem + unresolved.SUFFIX, "a") as f:
        f.write('{"stage": "repair", "reas')          # torn mid-write
    got = unresolved.items(stem)
    assert len(got) == 1 and got[0]["original_text"] == "intact"


def test_resolve_marks_without_deleting_evidence(tmp_path):
    """A reviewed entry keeps its evidence -- the queue is the audit trail, not a worklist
    that shrinks. Mirrors glossary_acquire.record_decision."""
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference", original_text="Gum -gum!")
    assert unresolved.resolve(stem, 0, accept=True, note="fansub missing, text is fine") is True
    e = unresolved.items(stem)[0]
    assert e["resolved"] is True
    assert e["note"] == "fansub missing, text is fine"
    assert e["original_text"] == "Gum -gum!"
    assert unresolved.pending(stem) == []


def test_pending_is_what_review_shows(tmp_path):
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "no_reference", original_text="a")
    unresolved.record(stem, "punctuation", "llm_empty", original_text="b")
    unresolved.resolve(stem, 0, accept=True)
    assert [e["original_text"] for e in unresolved.pending(stem)] == ["b"]


def test_repair_llm_empty_is_a_declared_reason(tmp_path):
    """A repair call that times out returns "" -- it fails accept_repair, but the
    `if new and ...` guard is falsy so nothing was incremented and nothing recorded. That
    is the silent-fallback class this module exists to remove, and it survived inside the
    fix for it until an end-to-end run against a dead endpoint exposed it."""
    assert "llm_empty" in unresolved.REASONS["repair"]
    stem = str(tmp_path / "ep")
    unresolved.record(stem, "repair", "llm_empty", original_text="garbled line",
                      reference="the fansub line", avg_logprob=-1.4)
    e = unresolved.items(stem)[0]
    assert e["reason"] == "llm_empty" and e["reference"] == "the fansub line"
