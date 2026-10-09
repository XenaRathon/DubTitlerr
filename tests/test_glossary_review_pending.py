"""A human's --review answers survive a busy glossary: the final write waits (GLOSSARY_LOCK_WAIT_INTERACTIVE), and on timeout the
answers are saved to '<glossary>.json.review-pending' and applied at the start of the next --review. Synthetic data only."""

import json
import os
import subprocess
import sys
import threading

import pytest

import glossary_acquire as ga
import glossary_lock

RS = "respelling-needs-review"
LUFY_Y = ("Lufy", True, "Luffy", RS)
FLAGS = {
    "Lufy": {"reason": "respelling-needs-review", "canonical": "Luffy"},
    "Zorro": {"reason": "respelling-needs-review", "canonical": "Zoro"},
}


@pytest.fixture(autouse=True)
def waits(monkeypatch):
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "0.1")
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT_INTERACTIVE", "0.4")


def make(tmp_path, **extra):
    path = tmp_path / "S.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": [], "flagged": dict(FLAGS), **extra}))
    return path


def run_review(path, monkeypatch, *flags, answers=("y", "y")):
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(path.parent), "--review", "--apply", *flags])
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    ga.main()


def pending_file(path):
    return str(path) + ".review-pending"


class Holder:
    """Holds the glossary's lock from another thread (stage name 'nightly-verify') until released."""

    def __init__(self, path, stage="nightly-verify"):
        self.path, self.stage = str(path), stage
        self.held, self.release = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        with glossary_lock.locked(self.path, self.stage) as ok:
            assert ok
            self.held.set()
            self.release.wait(15)

    def __enter__(self):
        self.thread.start()
        assert self.held.wait(5)
        return self

    def __exit__(self, *a):
        self.release.set()
        self.thread.join(5)


def last_json(out):
    return json.loads([ln for ln in out.strip().splitlines() if ln.startswith("{")][-1])


# ---- the wait ----


def test_the_interactive_wait_defaults_to_ten_minutes_and_is_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("GLOSSARY_LOCK_WAIT_INTERACTIVE", raising=False)
    assert glossary_lock.interactive_wait_seconds() == 600
    for raw, expect in (("30", 30.0), ("0", 0.0), ("lots", 600), ("-5", 0.0)):
        monkeypatch.setenv("GLOSSARY_LOCK_WAIT_INTERACTIVE", raw)
        assert glossary_lock.interactive_wait_seconds() == expect, raw


def test_review_waits_for_the_holder_and_writes_when_it_lets_go(tmp_path, monkeypatch, capsys):
    path = make(tmp_path)
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT_INTERACTIVE", "10")
    holder = Holder(path)
    threading.Timer(0.6, holder.release.set).start()
    with holder:
        run_review(path, monkeypatch)
    out = capsys.readouterr().out
    assert "waiting for nightly-verify to finish" in out
    saved = json.loads(path.read_text())
    assert saved["hard_fixes"] == {"Lufy": "Luffy", "Zorro": "Zoro"} or saved["hard_fixes"].get("Lufy") == "Luffy"
    assert not os.path.exists(pending_file(path)) and last_json(out)["written"] is True


# ---- the answers survive a timeout ----


def hold_in_another_process(path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        f"import sys, time; sys.path.insert(0, {root!r}); import glossary_lock\n"
        f"with glossary_lock.locked({str(path)!r}, 'nightly-verify') as ok:\n"
        "    print('held' if ok else 'busy', flush=True); time.sleep(30)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_answers_are_saved_when_another_process_holds_the_lock_and_applied_by_the_next_review(tmp_path, monkeypatch, capsys):
    path = make(tmp_path)
    before = path.read_text()
    proc = hold_in_another_process(path)
    try:
        run_review(path, monkeypatch, answers=("y", "n"))
    finally:
        proc.kill()
        proc.wait()
    out = capsys.readouterr().out
    assert path.read_text() == before  # nothing was lost, nothing half-written
    doc = json.load(open(pending_file(path)))  # ONE json document
    assert sorted(map(tuple, doc["answers"])) == [LUFY_Y, ("Zorro", False, "Zoro", RS)]
    summary = last_json(out)
    assert summary["written"] is False and summary["pending"] == 2 and summary["saved"] == 2
    assert "waiting for nightly-verify to finish" in out and "review-pending" in out
    assert not os.path.exists(pending_file(path) + ".tmp")
    # the lock is free again: the next review applies the saved answers BEFORE listing anything
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("nothing is left to ask"))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    ga.main()
    saved = json.loads(path.read_text())
    assert saved["hard_fixes"] == {"Lufy": "Luffy"} and "Zorro" not in saved.get("hard_fixes", {})
    assert "flagged" not in saved or not saved["flagged"]
    assert not os.path.exists(pending_file(path))
    assert last_json(capsys.readouterr().out)["pending"] == 0


def test_a_second_timeout_adds_to_the_saved_answers(tmp_path, monkeypatch):
    path = make(tmp_path, flagged={**FLAGS, "Sanjy": {"reason": "respelling-needs-review", "canonical": "Sanji"}})
    with Holder(path):
        run_review(path, monkeypatch, answers=("y", "q"))
        first = json.load(open(pending_file(path)))
        assert [tuple(a) for a in first["answers"]] == [LUFY_Y]
        run_review(path, monkeypatch, answers=("n", "q"))  # still busy: the earlier answer is kept, not replaced
    doc = json.load(open(pending_file(path)))
    assert [a[0] for a in doc["answers"]][0] == "Lufy" and len(doc["answers"]) == 2


def test_pending_answers_are_applied_together_with_new_ones_when_the_lock_is_free(tmp_path, monkeypatch, capsys):
    path = make(tmp_path)
    json.dump({"answers": [list(LUFY_Y)]}, open(pending_file(path), "w"))
    answers = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    ga.main()
    saved = json.loads(path.read_text())
    assert saved["hard_fixes"] == {"Lufy": "Luffy", "Zorro": "Zoro"} and not os.path.exists(pending_file(path))
    assert last_json(capsys.readouterr().out)["pending"] == 0


def test_a_corrupt_pending_file_is_set_aside_not_trusted_or_deleted(tmp_path, monkeypatch, capsys):
    path = make(tmp_path)
    open(pending_file(path), "w").write("{not json")
    run_review(path, monkeypatch)
    assert os.path.exists(pending_file(path) + ".bad") and not os.path.exists(pending_file(path))
    assert "hard_fixes" in json.loads(path.read_text()) and "unreadable" in capsys.readouterr().out


def test_the_pending_count_comes_from_the_file_on_disk(tmp_path, monkeypatch, capsys):
    path = make(tmp_path)

    def answer(prompt=""):
        doc = json.load(open(path))
        doc["flagged"]["Brand New"] = "low-confidence"  # another stage flags a third term while the human answers
        path.write_text(json.dumps(doc))
        return "y"

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    ga.main()
    assert last_json(capsys.readouterr().out)["pending"] == 1


def test_a_dry_review_saves_nothing(tmp_path, monkeypatch):
    path = make(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review"])
    with Holder(path):
        ga.main()
    assert not os.path.exists(pending_file(path))


# ---- revert / prune wait too (nothing to save: they are idempotent) ----


def test_prune_and_revert_wait_for_the_interactive_window_then_report_not_written(tmp_path, monkeypatch, capsys):
    path = make(tmp_path, verified=["Aaa"], flagged={"Aaa": "no-match"})
    before = path.read_text()
    with Holder(path):
        base = ["glossary_acquire", str(path), str(tmp_path)]
        monkeypatch.setattr(sys, "argv", [*base, "--review", "--prune-no-match", "--apply"])
        ga.main()
        monkeypatch.setattr(sys, "argv", [*base, "--revert", "--apply"])
        ga.main()
    out = capsys.readouterr().out
    assert path.read_text() == before and out.count("waiting for nightly-verify to finish") == 2


def test_prune_waits_and_then_writes_when_released(tmp_path, monkeypatch, capsys):
    path = make(tmp_path, verified=["Aaa"], flagged={"Aaa": "no-match"})
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT_INTERACTIVE", "10")
    holder = Holder(path)
    threading.Timer(0.5, holder.release.set).start()
    with holder:
        monkeypatch.setattr(
            sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--prune-no-match", "--apply"]
        )
        ga.main()
    assert "flagged" not in json.loads(path.read_text()) and last_json(capsys.readouterr().out)["written"] is True


# ---- lock-module notes ----


def test_the_lock_documents_that_it_is_not_reentrant():
    doc = glossary_lock.__doc__.lower()
    assert "nest" in doc and "not reentrant" in doc


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_directory_runs_unlocked_and_says_so_once(tmp_path, capsys, monkeypatch):
    d = tmp_path / "ro"
    d.mkdir()
    path = d / "S.json"
    path.write_text("{}")
    d.chmod(0o500)
    monkeypatch.setattr(glossary_lock, "_WARNED_UNLOCKED", set())
    try:
        for _ in range(2):
            with glossary_lock.locked(str(path), "verify") as ok:
                assert ok is True
    finally:
        d.chmod(0o700)
    out = capsys.readouterr().out
    assert out.count("running unlocked") == 1 and "verify" in out


# ---- phase 23: a saved answer is replayed only for a term that is still flagged ----


def decided(path, **extra):
    """A glossary where Lufy was ALREADY accepted (a hard fix) by another session while the answer waited."""
    doc = {
        "show": "S",
        "names": ["Zoro"],
        "phrases": [],
        "hard_fixes": {"Lufy": "Luffy"},
        "acquired": {"Lufy": {"canonical": "Luffy", "reason": "human-approved", "run": "review"}},
        "flagged": {"Zorro": {"reason": "respelling-needs-review", "canonical": "Zoro"}},
        **extra,
    }
    path.write_text(json.dumps(doc))


@pytest.mark.parametrize("accept", [False, True])
def test_a_stale_saved_answer_cannot_undo_a_decision_made_meanwhile(tmp_path, monkeypatch, capsys, accept):
    path = tmp_path / "S.json"
    decided(path)
    json.dump({"answers": [["Lufy", accept, "Luffy", RS], ["Zorro", True, "Zoro", RS]]}, open(pending_file(path), "w"))
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("nothing is left to ask"))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    ga.main()
    saved = json.loads(path.read_text())
    assert saved["hard_fixes"] == {"Lufy": "Luffy", "Zorro": "Zoro"}  # the earlier fix survives; the still-flagged answer applies
    assert "Lufy" not in saved.get("known", []) and "Lufy" in saved["acquired"]
    assert "Lufy" in capsys.readouterr().out and not os.path.exists(pending_file(path))


def test_record_decision_leaves_an_unflagged_term_alone():
    g = {
        "hard_fixes": {"Lufy": "Luffy"},
        "acquired": {"Lufy": {"canonical": "Luffy"}},
        "known": ["Other"],
        "flagged": {"X": "no-match"},
    }
    for accept in (True, False):
        assert ga.record_decision(g, "Lufy", accept=accept) == g
    assert ga.record_decision(g, "Never Seen", accept=False) == g


def test_record_decision_still_decides_a_flagged_term():
    g = {"flagged": {"X": "no-match"}}
    out = ga.record_decision(g, "X", accept=False)
    assert out["known"] == ["X"] and "flagged" not in out


# ---- the pending file is read-modify-written under its own lock ----


def test_concurrent_reviewers_never_drop_each_others_saved_answers(tmp_path):
    path = tmp_path / "S.json"
    path.write_text("{}")
    n = 25
    barrier = threading.Barrier(n)

    def save(i):
        barrier.wait()
        ga._append_pending(str(path), [[f"T{i}", True]])

    threads = [threading.Thread(target=save, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(a[0] for a in json.load(open(pending_file(path)))["answers"]) == sorted(f"T{i}" for i in range(n))


def test_appending_waits_while_another_writer_holds_the_pending_lock(tmp_path):
    path = tmp_path / "S.json"
    path.write_text("{}")
    done = threading.Event()
    with ga._pending_lock(str(path)):
        t = threading.Thread(target=lambda: (ga._append_pending(str(path), [["A", True]]), done.set()))
        t.start()
        assert not done.wait(0.4)  # blocked behind the lock holder
    assert done.wait(5)
    t.join(5)


def test_the_pending_lock_file_is_not_a_glossary(tmp_path):
    path = tmp_path / "S.json"
    path.write_text("{}")
    ga._append_pending(str(path), [["A", True]])
    assert not any(n.endswith(".json") and n != "S.json" for n in os.listdir(tmp_path))


# ---- answers are on disk BEFORE the wait, so a kill while waiting loses nothing ----


def test_a_review_killed_while_waiting_leaves_its_answers_on_disk_and_the_next_review_applies_them(tmp_path):
    import signal

    path = make(tmp_path)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        f"import sys; sys.path.insert(0, {root!r}); import glossary_acquire as ga\n"
        "rs = 'respelling-needs-review'\n"
        f"ga._commit_answers({str(path)!r}, [['Lufy', True, 'Luffy', rs], ['Zorro', False, 'Zoro', rs]])\n"
    )
    env = {**os.environ, "GLOSSARY_LOCK_WAIT_INTERACTIVE": "60"}
    with Holder(path):
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=env)
        try:
            assert "waiting for nightly-verify" in proc.stdout.readline()
            assert sorted(map(tuple, json.load(open(pending_file(path)))["answers"])) == [LUFY_Y, ("Zorro", False, "Zoro", RS)]
            proc.send_signal(signal.SIGKILL)  # no chance to clean up or save anything
        finally:
            proc.kill()
            proc.wait()
    assert "hard_fixes" not in json.loads(path.read_text())
    ga._commit_answers(str(path), [])
    saved = json.loads(path.read_text())
    assert saved["hard_fixes"] == {"Lufy": "Luffy"} and "Zorro" in saved["known"]
    assert not os.path.exists(pending_file(path))


def test_a_replay_after_a_kill_between_the_write_and_the_delete_is_harmless(tmp_path):
    path = make(tmp_path)
    assert ga._commit_answers(str(path), [list(LUFY_Y)])
    once = path.read_text()
    json.dump({"answers": [list(LUFY_Y)]}, open(pending_file(path), "w"))  # the delete never happened
    assert ga._commit_answers(str(path), [])
    assert json.loads(path.read_text()) == json.loads(once)


# ---- phase 25: an answer applies only to the proposal the human saw ----


def reflagged(path, canonical, reason):
    """Lufy was reverted and flagged again by a later verify with a DIFFERENT proposal."""
    doc = json.loads(path.read_text())
    doc["flagged"]["Lufy"] = {"reason": reason, "canonical": canonical}
    path.write_text(json.dumps(doc))


def replay(path, tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "q")  # a still-flagged term may be offered again; quit at once
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])
    ga.main()
    return json.loads(path.read_text())


def test_a_saved_yes_is_not_applied_to_a_proposal_that_changed(tmp_path, monkeypatch, capsys):
    path = make(tmp_path)
    reflagged(path, "Lufy Bandits", "common-word")
    json.dump({"answers": [list(LUFY_Y)]}, open(pending_file(path), "w"))
    saved = replay(path, tmp_path, monkeypatch)
    assert "Lufy Bandits" not in saved.get("phrases", []) + saved.get("names", []) and "hard_fixes" not in saved
    assert saved["flagged"]["Lufy"] == {"reason": "common-word", "canonical": "Lufy Bandits"}  # still waiting for a human
    out = capsys.readouterr().out
    assert "Lufy" in out and "proposal changed" in out and not os.path.exists(pending_file(path))


def test_a_saved_no_is_not_applied_to_a_proposal_that_changed(tmp_path, monkeypatch):
    path = make(tmp_path)
    reflagged(path, "Lufy Bandits", "common-word")
    json.dump({"answers": [["Lufy", False, "Luffy", RS]]}, open(pending_file(path), "w"))
    saved = replay(path, tmp_path, monkeypatch)
    assert "Lufy" not in saved.get("known", []) and "Lufy" in saved["flagged"]


def test_an_unchanged_canonical_still_applies_even_if_the_reason_moved(tmp_path, monkeypatch):
    path = make(tmp_path)
    reflagged(path, "Luffy", "low-confidence")  # same proposal, different bookkeeping reason
    json.dump({"answers": [list(LUFY_Y)]}, open(pending_file(path), "w"))
    saved = replay(path, tmp_path, monkeypatch)
    assert saved["hard_fixes"] == {"Lufy": "Luffy"} and "Lufy" not in saved.get("flagged", {})


def test_an_old_format_entry_is_unverifiable_and_skipped(tmp_path, monkeypatch, capsys):
    path = make(tmp_path)
    json.dump({"answers": [["Lufy", True], ["Zorro", True, "Zoro", RS]]}, open(pending_file(path), "w"))
    saved = replay(path, tmp_path, monkeypatch)
    assert "hard_fixes" in saved and saved["hard_fixes"] == {"Zorro": "Zoro"} and "Lufy" in saved["flagged"]
    assert "older format" in capsys.readouterr().out


def test_new_answers_are_saved_with_the_canonical_and_the_reason(tmp_path, monkeypatch):
    path = make(tmp_path)
    with Holder(path):
        run_review(path, monkeypatch, answers=("y", "y"))
    saved = sorted(map(tuple, json.load(open(pending_file(path)))["answers"]))
    assert saved == [LUFY_Y, ("Zorro", True, "Zoro", RS)]


def test_a_no_candidate_answer_matches_on_the_empty_canonical(tmp_path, monkeypatch):
    path = make(tmp_path, flagged={"Aaa": "no-match"})
    json.dump({"answers": [["Aaa", False, "", "no-match"]]}, open(pending_file(path), "w"))
    saved = replay(path, tmp_path, monkeypatch)
    assert saved["known"] == ["Aaa"] and "flagged" not in saved
