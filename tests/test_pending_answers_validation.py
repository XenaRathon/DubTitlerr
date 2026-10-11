"""Phase 29 F14: saved review answers are validated, never coerced.

Sol's probes: a row ["Raftel", "false", ...] became bool("false") == True and wrote a human-approved hard fix; a row [] raised an
uncaught IndexError instead of being set aside as .bad."""

import json
import sys
from pathlib import Path

import pytest

import glossary_acquire as ga

FLAGGED = {
    "show": "S",
    "names": ["Raftel"],
    "flagged": {"Raftel": {"reason": "respelling-needs-review", "canonical": "Ratel"}},
}

BAD_DOCS = [
    {"answers": [["Raftel", "false", "Ratel", "respelling-needs-review"]]},  # a string is not a JSON boolean
    {"answers": [["Raftel", 1, "Ratel", "respelling-needs-review"]]},  # nor is a number
    {"answers": [["Raftel", None, "Ratel", "respelling-needs-review"]]},
    {"answers": [[]]},
    {"answers": [["Raftel"]]},
    {"answers": [["Raftel", True, "Ratel", "respelling-needs-review", "extra"]]},
    {"answers": [[7, True, "Ratel", "respelling-needs-review"]]},
    {"answers": [["Raftel", True, ["Ratel"], "respelling-needs-review"]]},
    {"answers": ["Raftel"]},
    {"answers": {"Raftel": True}},
    {"answers": None},
    {"nothing": []},
    [["Raftel", True]],
    "text",
]


def pending(tmp_path, doc):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(FLAGGED))
    p = Path(str(path) + ".review-pending")
    p.write_text(json.dumps(doc))
    return path, p


@pytest.mark.parametrize("doc", BAD_DOCS)
def test_a_malformed_document_is_set_aside_and_counts_as_empty(tmp_path, doc):
    path, p = pending(tmp_path, doc)
    assert ga._read_pending(str(path)) == []
    assert not p.exists() and json.loads(Path(str(p) + ".bad").read_text()) == doc, "kept verbatim as .bad, never trusted"


@pytest.mark.parametrize("doc", BAD_DOCS[:4])
def test_a_malformed_row_is_never_replayed(tmp_path, doc):
    path, _ = pending(tmp_path, doc)
    before = json.loads(path.read_text())
    assert ga._commit_answers(str(path), []) in (True, False)
    assert json.loads(path.read_text()) == before, "no hard fix, no cleared flag"


def test_valid_rows_still_load_including_the_older_two_element_format(tmp_path):
    doc = {"answers": [["Raftel", True, "Ratel", "respelling-needs-review"], ["Old", False]]}
    path, p = pending(tmp_path, doc)
    assert ga._read_pending(str(path)) == [["Raftel", True, "Ratel", "respelling-needs-review"], ["Old", False]]
    assert p.exists()


def test_a_read_only_review_does_not_rename_a_bad_file(tmp_path, monkeypatch):
    path, p = pending(tmp_path, {"answers": [[]]})
    monkeypatch.setattr(sys, "argv", ["glossary_acquire", str(path), str(tmp_path), "--review"])
    monkeypatch.setattr("builtins.input", lambda *a: "q")
    ga.main()
    assert p.exists() and not Path(str(p) + ".bad").exists()
