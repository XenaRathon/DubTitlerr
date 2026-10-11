"""Phase 29 F12: `glossary_acquire --review` without --apply is read-only, including the saved answers file.

Sol's probe: a glossary flagged Raftel -> Ratel plus a saved answer [Raftel, true, Ratel, ...]. The dry run replayed the answer,
wrote hard_fixes, cleared the flag and deleted the pending file, then reported written:false."""

import json
import sys
from pathlib import Path

import glossary_acquire as ga

FLAGGED = {
    "show": "S",
    "names": ["Raftel"],
    "phrases": [],
    "flagged": {"Raftel": {"reason": "respelling-needs-review", "canonical": "Ratel"}},
}
ANSWERS = {"answers": [["Raftel", True, "Ratel", "respelling-needs-review"]]}


def setup(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(FLAGGED))
    Path(str(path) + ".review-pending").write_text(json.dumps(ANSWERS))
    return path


def run(monkeypatch, path, tmp_path, *flags, answer="q"):
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review", *flags])
    monkeypatch.setattr("builtins.input", lambda *a: answer)
    ga.main()


def test_a_dry_review_leaves_the_glossary_and_the_pending_file_alone_and_says_what_it_keeps(tmp_path, monkeypatch, capsys):
    path = setup(tmp_path)
    before = path.read_text()
    run(monkeypatch, path, tmp_path)
    out = capsys.readouterr().out
    assert path.read_text() == before
    assert json.loads(Path(str(path) + ".review-pending").read_text()) == ANSWERS
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["written"] is False and summary["saved"] == 1
    assert "1 saved answer" in out and "--apply" in out


def test_an_applying_review_still_replays_and_clears_the_saved_answers(tmp_path, monkeypatch, capsys):
    path = setup(tmp_path)
    run(monkeypatch, path, tmp_path, "--apply")
    saved = json.loads(path.read_text())
    assert saved["hard_fixes"] == {"Raftel": "Ratel"} and "flagged" not in saved
    assert not Path(str(path) + ".review-pending").exists()
    assert "saved" not in json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_a_dry_review_with_nothing_saved_reports_no_saved_key(tmp_path, monkeypatch, capsys):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(FLAGGED))
    run(monkeypatch, path, tmp_path)
    assert "saved" not in json.loads(capsys.readouterr().out.strip().splitlines()[-1])
