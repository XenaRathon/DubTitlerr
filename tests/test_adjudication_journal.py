"""The adjudication journal: durable per-result checkpoints (adjudication_journal.py)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import adjudication_journal as aj

ROOT = Path(__file__).resolve().parents[1]
RESULT = {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}
PROV = {"show": "S", "cands": "abc", "backend": "ollama", "model": "m", "prompt": "1"}


def make(tmp_path, clock=None, **kw):
    return aj.Journal(str(tmp_path / "j.jsonl"), "verify", **({"clock": clock} if clock else {}), **kw)


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def lines(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def test_a_recorded_result_is_reused_by_a_new_journal_object(tmp_path):
    j = make(tmp_path)
    assert j.record(aj.pick_key("Zoro"), PROV, RESULT)
    again = make(tmp_path)
    assert again.lookup(aj.pick_key("Zoro"), PROV) == RESULT
    assert again.lookup(aj.pick_key("Nami"), PROV) is None


def test_every_line_is_on_disk_before_record_returns(tmp_path):
    j = make(tmp_path)
    j.record("k1", PROV, RESULT)
    assert [e["key"] for e in lines(j.path)] == ["k1"]  # no flush, no close: it is already there
    j.record("k2", PROV, RESULT)
    assert [e["key"] for e in lines(j.path)] == ["k1", "k2"]


def test_a_changed_provenance_is_ignored_but_not_deleted(tmp_path):
    j = make(tmp_path)
    j.record("k", PROV, RESULT)
    for field, value in (("cands", "zzz"), ("model", "other"), ("prompt", "2"), ("show", "T"), ("backend", "decision")):
        assert make(tmp_path).lookup("k", {**PROV, field: value}) is None, field
    assert len(lines(j.path)) == 1 and make(tmp_path).lookup("k", PROV) == RESULT


def test_the_latest_line_for_a_key_wins(tmp_path):
    j = make(tmp_path)
    j.record("k", PROV, {**RESULT, "canonical": "Old"})
    j.record("k", PROV, {**RESULT, "canonical": "New"})
    assert make(tmp_path).lookup("k", PROV)["canonical"] == "New"


def test_unavailable_and_fallback_answers_are_never_journaled(tmp_path):
    j = make(tmp_path)
    assert not j.record("a", PROV, {**RESULT, "unavailable": True})
    assert not j.record("b", PROV, {**RESULT, "fallback": True})
    assert not j.record("c", PROV, None)
    assert not j.record("d", PROV, ["not", "a", "dict"])
    assert not os.path.exists(j.path)


def test_a_torn_last_line_is_skipped_and_the_next_append_starts_on_its_own_line(tmp_path, capsys):
    j = make(tmp_path)
    j.record("k1", PROV, RESULT)
    with open(j.path, "ab") as f:
        f.write(b'{"v": 1, "stage": "verify", "key": "k2", "pr')  # the process died mid-write
    again = make(tmp_path)
    assert again.skipped == 1 and again.lookup("k1", PROV) == RESULT and len(again) == 1
    assert again.record("k3", PROV, RESULT)
    final = make(tmp_path)
    assert final.lookup("k3", PROV) == RESULT and final.lookup("k1", PROV) == RESULT
    assert b'"pr\n{' in Path(final.path).read_bytes(), "the damaged bytes stay on their own line"


def test_garbage_lines_and_foreign_stages_are_skipped(tmp_path):
    p = tmp_path / "j.jsonl"
    good = {"v": 1, "stage": "verify", "key": "k", "prov": PROV, "result": RESULT, "at": 1.0}
    p.write_text(
        "not json\n"
        + json.dumps({**good, "stage": "acquire", "key": "x"})
        + "\n"
        + json.dumps({**good, "v": 99, "key": "y"})
        + "\n"
        + json.dumps([1, 2])
        + "\n"
        + json.dumps(good)
        + "\n"
    )
    j = aj.Journal(str(p), "verify")
    assert len(j) == 1 and j.skipped == 4 and j.lookup("k", PROV) == RESULT


def test_a_corrupt_or_unwritable_journal_never_raises(tmp_path, capsys):
    d = tmp_path / "isdir"
    d.mkdir()
    j = aj.Journal(str(d), "verify")  # a directory where the file should be
    assert j.lookup("k", PROV) is None
    assert j.record("k", PROV, RESULT) is False
    assert j.compact() == 0
    assert capsys.readouterr().out.count("continuing without it") == 1, "logged once"


def test_two_processes_appending_at_once_lose_nothing(tmp_path):
    path = str(tmp_path / "j.jsonl")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import adjudication_journal as aj\n"
        "j = aj.Journal(sys.argv[2], 'verify')\n"
        "for i in range(60):\n"
        "    assert j.record(f'{sys.argv[3]}-{i}', {'p': sys.argv[3]}, {'canonical': 'x' * 400, 'confidence': 'high'})\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, str(ROOT), path, tag]) for tag in ("a", "b", "c")]
    assert [p.wait(timeout=60) for p in procs] == [0, 0, 0]
    j = aj.Journal(path, "verify")
    assert j.skipped == 0 and len(j) == 180
    assert all(len(e["result"]["canonical"]) == 400 for e in lines(path)), "no interleaved or truncated line"


def test_compaction_keeps_the_latest_line_per_key_and_is_idempotent(tmp_path):
    clock = Clock()
    j = make(tmp_path, clock)
    j.record("k", PROV, {**RESULT, "canonical": "Old"})
    clock.now += 10
    j.record("k", PROV, {**RESULT, "canonical": "New"})
    j.record("other", PROV, RESULT)
    assert len(lines(j.path)) == 3
    assert j.compact() == 2
    first = Path(j.path).read_bytes()
    assert len(lines(j.path)) == 2 and make(tmp_path, clock).lookup("k", PROV)["canonical"] == "New"
    assert j.compact() == 2 and Path(j.path).read_bytes() == first


def test_compaction_drops_old_lines_and_foreign_versions(tmp_path):
    clock = Clock()
    j = make(tmp_path, clock)
    j.record("old", PROV, RESULT)
    clock.now += 31 * 86400
    j.record("new", PROV, RESULT)
    assert j.compact() == 1
    again = make(tmp_path, clock)
    assert again.lookup("old", PROV) is None and again.lookup("new", PROV) == RESULT


def test_compaction_leaves_no_temp_files_and_a_live_appender_is_not_lost(tmp_path):
    j = make(tmp_path)
    for i in range(5):
        j.record(f"k{i}", PROV, RESULT)
    j.compact()
    j.record("after", PROV, RESULT)
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".tmp") == []
    assert len(make(tmp_path)) == 6
