"""The new workspace uses existing verdict semantics and never trusts client paths or indices alone."""

import http.client
import json
import threading
from pathlib import Path

import pytest

import decisions
import review_server as rs
import unresolved


@pytest.fixture
def episode(tmp_path, monkeypatch):
    show = tmp_path / "media" / "Test Show"
    season = show / "Season 01"
    season.mkdir(parents=True)
    stem = str(season / "Test Show - S01E01")
    Path(stem + ".mkv").write_bytes(b"fixture")
    Path(stem + rs.CONF_SUFFIX).write_text(
        json.dumps(
            [
                {"start": 3.0, "end": 5.0, "text": "We need a factory."},
            ]
        )
    )
    unresolved.record(stem, "repair_applied", "accepted", original_text="We need a factory.", proposed_text="We need a needle.")
    gloss = tmp_path / "glossaries"
    gloss.mkdir()
    (gloss / "Test Show.json").write_text('{"show":"Test Show"}')
    monkeypatch.setattr(rs, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    monkeypatch.setattr(decisions, "GLOSSARY_DIR", str(gloss))
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path / "decisions"))
    monkeypatch.setattr(rs, "show_for", lambda _: "Test Show")
    monkeypatch.setenv("REVIEW_TOKEN", "fixture-token")
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    return stem


def test_workspace_entries_have_stable_handles(episode):
    row = rs.handle_episode(episode)["entries"][0]
    assert isinstance(row.get("id"), str) and len(row["id"]) >= 16
    assert row["id"] == rs.handle_episode(episode)["entries"][0]["id"]


def test_workspace_stale_verdict_cannot_decide_replaced_row(episode):
    row = rs.handle_episode(episode)["entries"][0]
    stale_id = row.get("id", "old-entry")
    Path(unresolved.path_for(episode)).write_text(
        json.dumps(
            {
                "stage": "repair_applied",
                "reason": "accepted",
                "original_text": "Different original",
                "proposed_text": "Different proposal",
                "resolved": False,
            }
        )
        + "\n"
    )
    result = rs.handle_decide_batch(episode, [{"index": row["index"], "id": stale_id, "verdict": "accept"}])
    assert result["saved"] == 0
    assert "stale" in result["errors"][0]["error"]
    assert not decisions.load("Test Show", decisions.DECISIONS_DIR)


def test_workspace_correct_with_real_handle_keeps_existing_semantics(episode):
    row = rs.handle_episode(episode)["entries"][0]
    result = rs.handle_decide_batch(
        episode, [{"index": row["index"], "id": row.get("id"), "verdict": "correct", "text": "We need a factory."}]
    )
    assert result["saved"] == 1
    stored = decisions.load("Test Show", decisions.DECISIONS_DIR)
    assert decisions.lookup(stored, row["original_text"], row["proposed_text"])["verdict"] == "reject"


def test_workspace_document_is_inert_and_loads_only_local_assets(tmp_path, monkeypatch):
    # Production bundling is checked by npm build/browser tests; unit CI can run without Node.
    index = Path(__file__).resolve().parents[1] / "web" / "index.html"
    shell = index.read_text().replace("/src/main.ts", "/review/assets/app.js")
    (tmp_path / "index.html").write_text(shell)
    monkeypatch.setattr(rs, "UI_DIST", tmp_path)
    status, payload = rs.route("GET", "/review", {}, None)
    assert status == 200
    assert b"DubTitlerr" in payload
    assert b"fixture-token" not in payload
    assert b"/review/assets/" in payload


def test_audio_is_authenticated_before_extraction(episode, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unauthenticated request reached audio extraction")

    monkeypatch.setattr(rs, "preview_audio", forbidden, raising=False)
    status, _ = rs.route("GET", "/api/audio", {"stem": episode, "index": "0"}, None)
    assert status == 401


def test_audio_unknown_episode_is_refused(episode):
    status, _ = rs.route("GET", "/api/audio", {"stem": "/etc/passwd", "index": "0"}, "fixture-token")
    assert status == 404


def test_static_workspace_http_and_path_allowlist(tmp_path, monkeypatch):
    # A build is not needed to test serving semantics or path containment.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><title>DubTitlerr</title><script src="/review/assets/app.js"></script>')
    (dist / "assets/app.js").write_text("console.log('local asset')")
    monkeypatch.setattr(rs, "UI_DIST", dist)
    srv = rs.BoundedHTTPServer(("127.0.0.1", 0), rs.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        for path, expected, mime in [
            ("/review", 200, "text/html"),
            ("/review/assets/app.js", 200, "text/javascript"),
            ("/review/assets/../../review_token", 404, "application/json"),
        ]:
            conn = http.client.HTTPConnection(*srv.server_address, timeout=3)
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            assert response.status == expected
            assert response.getheader("Content-Type").startswith(mime)
            assert response.getheader("Cache-Control") == "no-store"
            if path == "/review":
                assert "default-src 'self'" in response.getheader("Content-Security-Policy")
            conn.close()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_workspace_already_resolved_row_is_refused_as_stale(episode):
    """A row resolved out of band (the --review CLI, another tab's queue write) with NO verdict in the store: the id still matches
    and undecided() still passes, so only the `resolved` clause of the stale check stops a second tab's verdict."""
    row = rs.handle_episode(episode)["entries"][0]
    assert unresolved.resolve(episode, row["index"], accept=False, note="resolved elsewhere")
    assert not decisions.load("Test Show", decisions.DECISIONS_DIR)
    result = rs.handle_decide_batch(episode, [{"index": row["index"], "id": row["id"], "verdict": "accept"}])
    assert result["saved"] == 0
    assert "stale" in result["errors"][0]["error"]
    assert not decisions.load("Test Show", decisions.DECISIONS_DIR), "no verdict was written for a row nobody could still decide"


# ---- API consistency (the documented shapes are the real ones) ----------------------------------------------------------------


def test_a_save_with_nothing_to_save_has_the_documented_shape(episode):
    """saved, errors, queue_cleared and show are always on a batch response, even one where every item is refused."""
    res = rs.handle_decide_batch(episode, [{"index": 99, "verdict": "accept"}])
    assert set(res) == {"saved", "errors", "queue_cleared", "show"}
    assert res["saved"] == 0 and res["queue_cleared"] is False and res["show"] == "Test Show"
    assert rs.handle_decide_batch(episode, [])["saved"] == 0


def test_shared_errors_are_keyed_by_id_everywhere(episode, monkeypatch):
    stem2 = episode.replace("S01E01", "S01E02")
    Path(stem2 + rs.CONF_SUFFIX).write_text(json.dumps([{"start": 3.0, "end": 5.0, "text": "We need a factory."}]))
    unresolved.record(stem2, "repair_applied", "accepted", original_text="We need a factory.", proposed_text="We need a needle.")
    monkeypatch.setattr(rs, "_STEMS_CACHE", None)
    monkeypatch.setattr(rs, "_QUEUE_CACHE", {})
    sid = rs.handle_shared()["pairs"][0]["id"]
    monkeypatch.setattr(decisions, "save", lambda *a, **k: False)
    res = rs.handle_shared_decide([{"id": sid, "verdict": "accept"}])
    assert res["saved"] == 0
    assert all("id" in e and "pair" not in e for e in res["errors"]), res["errors"]
    assert "could not be saved" in res["errors"][0]["error"]


@pytest.mark.parametrize(
    "params", [{}, {"index": "x"}, {"index": "-1"}, {"index": "0", "occurrence": "x"}, {"index": "0", "occurrence": "-2"}]
)
def test_audio_names_a_bad_parameter_as_a_parameter_problem(episode, params):
    status, payload = rs.route("GET", "/api/audio", {"stem": episode, **params}, "fixture-token")
    assert status == 400 and payload["error"].startswith("invalid parameter"), payload


def test_audio_still_says_no_playable_card_for_a_card_problem(episode):
    row = rs.handle_episode(episode)["entries"][0]
    params = {"stem": episode, "index": "0", "id": row["id"], "occurrence": "5"}
    status, payload = rs.route("GET", "/api/audio", params, "fixture-token")
    assert status == 400 and "no playable card" in payload["error"]
