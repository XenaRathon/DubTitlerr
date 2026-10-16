"""One advisory lock per glossary file (<glossary>.lock, flock): overlapping stages skip with a log line instead of losing each
other's updates. Real threads and a real second process; no network."""

import json
import os
import subprocess
import sys
import threading

import pytest

import glossary_acquire as ga
import glossary_lock
import glossary_verify as gv


def write(path, **extra):
    doc = {"show": "S", "names": ["Zoro"], "phrases": [], "wiki": "https://x.fandom.com/api.php", **extra}
    path.write_text(json.dumps(doc))
    return str(path)


@pytest.fixture(autouse=True)
def short_wait(monkeypatch):
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "0.2")
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT_INTERACTIVE", "0.2")


class Holder:
    """Holds a glossary's lock from another thread until released."""

    def __init__(self, path):
        self.path, self.held, self.release = path, threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        with glossary_lock.locked(self.path, "holder") as ok:
            assert ok
            self.held.set()
            self.release.wait(10)

    def __enter__(self):
        self.thread.start()
        assert self.held.wait(5)
        return self

    def __exit__(self, *a):
        self.release.set()
        self.thread.join(5)


# ---- the lock itself ----------------------------------------------- ----


def test_the_lock_file_sits_beside_the_glossary_and_is_not_a_glossary(tmp_path):
    import fnmatch

    import tools.glossary_bakeoff as gb

    path = write(tmp_path / "Show.json")
    with glossary_lock.locked(path, "t") as ok:
        assert ok and os.path.exists(path + ".lock")
    assert glossary_lock.lock_path(path) == path + ".lock"
    assert gb._glossary_files(str(tmp_path)) == ["Show.json"]  # discovery by .json suffix
    assert not fnmatch.fnmatch("Show.json.lock", "*.json")  # glossary_doctor's glob


def test_a_second_holder_in_the_same_process_is_refused_and_says_so(tmp_path, capsys):
    path = write(tmp_path / "S.json")
    with Holder(path):
        with glossary_lock.locked(path, "verify") as ok:
            assert ok is False
    assert "glossary busy: verify skipped" in capsys.readouterr().out


def test_a_second_process_is_refused_and_the_lock_is_free_again_afterwards(tmp_path):
    path = write(tmp_path / "S.json")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        f"import sys, time; sys.path.insert(0, {root!r}); import glossary_lock\n"
        f"with glossary_lock.locked({path!r}, 'other') as ok:\n"
        "    print('held' if ok else 'busy', flush=True); time.sleep(3)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        with glossary_lock.locked(path, "verify") as ok:
            assert ok is False
    finally:
        proc.kill()
        proc.wait()
    with glossary_lock.locked(path, "verify") as ok:  # the OS released it with the process
        assert ok is True


def test_the_lock_is_released_on_exit_even_after_an_exception(tmp_path):
    path = write(tmp_path / "S.json")
    with pytest.raises(RuntimeError):
        with glossary_lock.locked(path, "t"):
            raise RuntimeError("boom")
    with glossary_lock.locked(path, "t") as ok:
        assert ok is True


def test_a_short_wait_lets_a_just_finishing_holder_hand_over(tmp_path, monkeypatch):
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "3")
    path = write(tmp_path / "S.json")
    holder = Holder(path)
    holder.__enter__()
    threading.Timer(0.3, holder.release.set).start()
    with glossary_lock.locked(path, "verify") as ok:
        assert ok is True
    holder.thread.join(5)


def test_an_unlockable_location_does_not_block_the_stage(tmp_path):
    with glossary_lock.locked(str(tmp_path / "missing-dir" / "S.json"), "t") as ok:
        assert ok is True  # it could not write there either; the stage's own error handling applies


def test_the_wait_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("GLOSSARY_LOCK_WAIT", raising=False)
    assert glossary_lock.wait_seconds() == 5.0
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "0")
    assert glossary_lock.wait_seconds() == 0.0
    monkeypatch.setenv("GLOSSARY_LOCK_WAIT", "soon")
    assert glossary_lock.wait_seconds() == 5.0


# ---- every stage that writes a glossary takes it ------------------- ----


def test_verify_skips_when_the_glossary_is_busy(tmp_path, monkeypatch):
    path = write(tmp_path / "S.json")
    before = open(path).read()
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: pytest.fail("a busy stage does no work"))
    with Holder(path):
        rep = gv.verify(path)
    assert rep["note"] == "glossary busy: verify skipped" and open(path).read() == before


def test_tag_arcs_skips_when_the_glossary_is_busy(tmp_path):
    path = write(tmp_path / "S.json")
    with Holder(path):
        assert gv.tag_arcs(path, str(tmp_path))["note"] == "glossary busy: tag-arcs skipped"


def test_acquire_apply_skips_when_busy_but_a_dry_run_does_not(tmp_path, monkeypatch):
    path = write(tmp_path / "S.json")
    with Holder(path):
        assert ga.acquire(path, str(tmp_path), apply=True)["note"] == "glossary busy: acquire skipped"
        assert "busy" not in ga.acquire(path, str(tmp_path), apply=False).get("note", "")  # a dry run writes no glossary


def test_mine_glossary_skips_when_busy(tmp_path, monkeypatch, capsys):
    import mine_glossary

    monkeypatch.setattr(mine_glossary, "GLOSS_DIR", str(tmp_path))
    show = tmp_path / "Show"
    show.mkdir()
    path = write(tmp_path / "Show.json")
    before = open(path).read()
    monkeypatch.setattr(sys, "argv", ["mine_glossary.py", str(show)])
    with Holder(path):
        mine_glossary.main()
    assert "glossary busy: mine skipped" in capsys.readouterr().out and open(path).read() == before


def test_the_cli_exits_zero_when_busy(tmp_path, monkeypatch):
    path = write(tmp_path / "S.json")
    monkeypatch.setattr(sys, "argv", ["glossary_verify", path])
    with Holder(path):
        with pytest.raises(SystemExit) as e:
            gv.main()
    assert e.value.code == 0


def test_two_overlapping_verify_runs_do_not_lose_the_first_ones_updates(tmp_path, monkeypatch):
    """A (slow, mid-adjudication) and a second run on the same glossary: the second is skipped, A's result is written."""
    path = write(tmp_path / "S.json", names=["Zoro", "Slow"])
    monkeypatch.setattr(gv, "resolve_wiki", lambda show, override=None: "https://x.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda api, show: ["Roronoa Zoro"])
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    started, release = threading.Event(), threading.Event()

    def adjudicate(term, cands, show):
        started.set()
        release.wait(10)
        return {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": ""}

    monkeypatch.setattr(gv, "adjudicate", adjudicate)
    results = {}
    a = threading.Thread(target=lambda: results.setdefault("a", gv.verify(path)))
    a.start()
    assert started.wait(5)
    second = gv.verify(path)
    release.set()
    a.join(10)
    assert second["note"] == "glossary busy: verify skipped"
    saved = json.load(open(path))
    assert "Roronoa Zoro" in saved["phrases"] + saved["names"] and saved["verified"]


def test_review_writes_its_decisions_onto_the_fresh_file(tmp_path, monkeypatch):
    """The walk can take minutes; a pass that finished meanwhile must not be overwritten by the reviewer's stale copy."""
    path = tmp_path / "S.json"
    write(path, flagged={"Resp": {"reason": "respelling-needs-review", "canonical": "Respelled"}})
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--apply"])

    def answer(prompt=""):
        doc = json.load(open(path))  # another stage lands while the human is thinking
        doc["verified"] = ["Added Meanwhile"]
        path.write_text(json.dumps(doc))
        return "y"

    monkeypatch.setattr("builtins.input", answer)
    ga.main()
    saved = json.load(open(path))
    # A same-token-count respelling that a human approves is a deterministic correction (a hard fix), not an additive name.
    assert saved["verified"] == ["Added Meanwhile"] and saved["hard_fixes"] == {"Resp": "Respelled"}
    assert "Resp" not in saved.get("flagged", {})


# ---- E: a no-match that carries a candidate is a decision; F: --prun ----


def test_a_no_match_with_a_canonical_is_listed_among_the_decisions():
    g = {"flagged": {"Aaa": "no-match", "Bbb": {"reason": "no-match", "canonical": "Delta"}, "Ccc": {"reason": "no-match"}}}
    decisions, no_match = ga.review_groups(g)
    assert [i["term"] for i in decisions] == ["Bbb"]  # a candidate to accept or reject
    assert sorted(i["term"] for i in no_match) == ["Aaa", "Ccc"]


def prunable():
    return {
        "verified": ["Aaa", "Bbb", "Ccc", "Low"],
        "flagged": {
            "Aaa": "no-match",
            "Bbb": {"reason": "no-match"},
            "Ccc": {"reason": "no-match", "canonical": "Delta"},
            "Low": "low-confidence",
            "Unverified": "no-match",
        },
    }


def test_prune_removes_only_candidate_less_no_matches_of_verified_terms():
    pruned, n = ga.prune_no_match(prunable())
    assert n == 2 and set(pruned["flagged"]) == {"Ccc", "Low", "Unverified"}
    assert pruned["verified"] == prunable()["verified"]


def test_pruning_everything_drops_the_flagged_key():
    pruned, n = ga.prune_no_match({"verified": ["A"], "flagged": {"A": "no-match"}})
    assert n == 1 and "flagged" not in pruned


def _prune(tmp_path, monkeypatch, *flags):
    path = tmp_path / "S.json"
    path.write_text(json.dumps(prunable()))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--prune-no-match", *flags])
    ga.main()
    return path


def test_prune_is_a_dry_run_without_apply(tmp_path, monkeypatch, capsys):
    path = tmp_path / "S.json"
    before = json.dumps(prunable())
    path.write_text(before)
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--prune-no-match"])
    ga.main()
    assert path.read_text() == before and '"pruned": 2' in capsys.readouterr().out


def test_prune_with_apply_writes_atomically_and_prints_the_count(tmp_path, monkeypatch, capsys):
    path = _prune(tmp_path, monkeypatch, "--apply")
    assert set(json.loads(path.read_text())["flagged"]) == {"Ccc", "Low", "Unverified"}
    assert not (tmp_path / "S.json.tmp").exists() and '"pruned": 2' in capsys.readouterr().out


def test_prune_does_nothing_while_the_glossary_is_busy(tmp_path, monkeypatch):
    path = tmp_path / "S.json"
    path.write_text(json.dumps(prunable()))
    before = path.read_text()
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", "--prune-no-match", "--apply"])
    with Holder(str(path)):
        ga.main()
    assert path.read_text() == before


def test_the_default_review_does_not_prune(tmp_path, monkeypatch):
    """GUARD: without the flag --review leaves stored no-matches alone."""
    path = tmp_path / "S.json"
    path.write_text(json.dumps(prunable()))
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review"])
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    ga.main()
    assert json.loads(path.read_text()) == prunable()
