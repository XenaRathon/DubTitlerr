"""Phase 29: tests for the five one-line mutations Sol made that no existing test noticed. Each test here fails under its mutation
(checked by hand against the exact one-line change; see the commit message). The redirect cap (4th) is pinned in
test_redirect_error_evidence.py."""

import json
import os
from pathlib import Path

import pytest

import common
import glossary_acquire as ga
import mux
import repair
import unresolved

# ---- 1. REPAIR_OPENAI_URL keeps its query string (providers that need ?api-version=) -----------------------------------------


class _Sock:
    def settimeout(self, t):
        pass


class _Resp:
    status = 200

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "fixed line"}}]}).encode()


def _recording_conn(paths):
    class Conn:
        def __init__(self, *a, **k):
            self.sock = _Sock()

        def connect(self):
            pass

        def request(self, method, path, **kw):
            paths.append(path)

        def getresponse(self):
            return _Resp()

        def close(self):
            pass

    return Conn


def test_post_json_keeps_the_query_string_of_the_url(monkeypatch):
    paths = []
    monkeypatch.setattr(repair.http.client, "HTTPConnection", _recording_conn(paths))
    repair._post_json("http://127.0.0.1:1/v1?api-version=2026-01-01", {})
    repair._post_json("http://127.0.0.1:1/v1", {})
    assert paths == ["/v1?api-version=2026-01-01", "/v1"]


def test_a_configured_openai_url_with_a_query_reaches_the_request_and_is_accepted(monkeypatch):
    """The real path from REPAIR_OPENAI_URL: the endpoint check accepts a query, and llm_openai sends it."""
    paths = []
    url = "https://api.example.test/openai/deployments/d/chat/completions?api-version=2026-01-01"
    assert common.openai_endpoint_problem(url) in ("", None)
    monkeypatch.setattr(repair, "OPENAI_URL", url)
    monkeypatch.setattr(repair, "OPENAI_KEY_ENV", "TEST_REPAIR_KEY")
    monkeypatch.setenv("TEST_REPAIR_KEY", "sk-test-0123456789")  # gitleaks:allow -- test fixture, not a real credential
    monkeypatch.setenv("REPAIR_EXTRA_BODY", "")
    monkeypatch.setattr(repair.http.client, "HTTPSConnection", _recording_conn(paths))
    assert repair.llm_openai("P", None) == "fixed line"
    assert paths == ["/openai/deployments/d/chat/completions?api-version=2026-01-01"]


# ---- 2. one malformed queue line does not hide the records after it ------------------------------------------------------------


def test_items_continues_past_a_malformed_line(tmp_path):
    stem = str(tmp_path / "ep")
    Path(unresolved.path_for(stem)).write_text("not-json\n")
    unresolved.record(stem, "repair_applied", "accepted", original_text="line", proposed_text="changed")
    Path(unresolved.path_for(stem)).write_text(
        Path(unresolved.path_for(stem)).read_text() + "{broken\n" + json.dumps({"stage": "repair", "reason": "llm_empty"}) + "\n"
    )
    assert [e["reason"] for e in unresolved.items(stem)] == ["accepted", "llm_empty"]


# ---- 3. one unmeasurable duration refuses, in either direction -----------------------------------------------------------------


@pytest.mark.parametrize("orig_s,out_s", [(100.0, 0.0), (0.0, 100.0)])
def test_mux_refuses_when_only_one_duration_is_unmeasurable(monkeypatch, orig_s, out_s):
    info = {"tracks": [{"type": "video"}, {"type": "audio"}, {"type": "subtitles", "properties": {"track_name": mux.TRACK_NAME}}]}
    monkeypatch.setattr(mux, "identify", lambda p: info)
    monkeypatch.setattr(mux, "video_duration", lambda p: orig_s if p == "orig" else out_s)
    assert mux.verify("orig", "out") == "duration-unmeasurable"


# ---- 5. a saved answer applies only to the EXACT spelling the human saw ------------------------------------------------------


def test_a_saved_answer_is_skipped_when_the_canonical_differs_only_in_case(tmp_path, capsys):
    path = tmp_path / "g.json"
    path.write_text(
        json.dumps(
            {"show": "S", "names": ["Lufy"], "flagged": {"Lufy": {"reason": "respelling-needs-review", "canonical": "LUFFY"}}}
        )
    )
    Path(str(path) + ".review-pending").write_text(json.dumps({"answers": [["Lufy", True, "Luffy", "respelling-needs-review"]]}))
    ga._commit_answers(str(path), [])
    saved = json.loads(path.read_text())
    assert "hard_fixes" not in saved and saved["flagged"]["Lufy"]["canonical"] == "LUFFY"
    assert "proposal changed" in capsys.readouterr().out
    assert not os.path.exists(str(path) + ".review-pending")


def test_the_same_spelling_is_still_applied(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(
        json.dumps(
            {"show": "S", "names": ["Lufy"], "flagged": {"Lufy": {"reason": "respelling-needs-review", "canonical": "Luffy"}}}
        )
    )
    Path(str(path) + ".review-pending").write_text(json.dumps({"answers": [["Lufy", True, "Luffy", "respelling-needs-review"]]}))
    ga._commit_answers(str(path), [])
    assert json.loads(path.read_text())["hard_fixes"] == {"Lufy": "Luffy"}
