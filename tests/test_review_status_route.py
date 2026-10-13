"""GET /api/status through route(): auth, the cache-warming 503, and that query params reach the handler.

The handler itself is covered by its own tests; this pins the registration in review_server.route()."""

import time

import pytest

import review_server

TWO_STEMS = ["Show A/Season 1/Show A - S01E01", "Show B/Season 2/Show B - S02E03"]


@pytest.fixture
def tok(tmp_path, monkeypatch):
    monkeypatch.delenv("REVIEW_TOKEN", raising=False)
    monkeypatch.delenv("REVIEW_AUTH", raising=False)
    monkeypatch.setattr(review_server, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(review_server, "_GENERATED", None)  # keep the generated token from leaking into other tests
    return review_server.resolve_token(str(tmp_path))


@pytest.fixture
def stems(tmp_path, monkeypatch):
    """A filled cache of two fake stems; no sidecars exist, so every episode reads as just transcribed."""
    paths = [str(tmp_path / s) for s in TWO_STEMS]
    monkeypatch.setattr(review_server, "_STEMS_CACHE", (time.monotonic() + 600, paths, time.monotonic()))
    return paths


def test_status_requires_the_token(tok, stems):
    assert review_server.route("GET", "/api/status", {}, None)[0] == 401
    assert review_server.route("GET", "/api/status", {}, "nope")[0] == 401
    assert review_server.route("GET", "/api/status", {}, tok)[0] == 200


def test_status_is_not_an_open_route():
    assert not any(route == "/api/status" for _method, route in review_server.OPEN_ROUTES)
    assert set(review_server.OPEN_ROUTES) == {("GET", "/healthz"), ("GET", "/api/auth-mode"), ("POST", "/api/login")}


def test_an_empty_cache_is_503_cache_warming(tok, monkeypatch):
    monkeypatch.setattr(review_server, "_STEMS_CACHE", None)
    assert review_server.route("GET", "/api/status", {}, tok) == (503, {"error": "cache warming"})


def test_a_filled_cache_lists_both_episodes_with_show_season_episode(tok, stems):
    status, payload = review_server.route("GET", "/api/status", {}, tok)

    assert status == 200
    assert [(e["show"], e["season"], e["episode"]) for e in payload["episodes"]] == [
        ("Show A", "Season 1", "Show A - S01E01"),
        ("Show B", "Season 2", "Show B - S02E03"),
    ]
    assert [e["stem"] for e in payload["episodes"]] == stems
    assert payload["header"]["total"] == 2 and payload["header"]["page"] == 1


def test_the_show_filter_reaches_the_handler(tok, stems):
    _, payload = review_server.route("GET", "/api/status", {"show": "Show B"}, tok)
    assert [e["show"] for e in payload["episodes"]] == ["Show B"]
    assert payload["header"]["total"] == 1

    _, none = review_server.route("GET", "/api/status", {"show": "Nope"}, tok)
    assert none["episodes"] == [] and none["header"]["total"] == 0


def test_page_and_limit_reach_the_handler(tok, stems):
    _, first = review_server.route("GET", "/api/status", {"page": "1", "limit": "1"}, tok)
    _, second = review_server.route("GET", "/api/status", {"page": "2", "limit": "1"}, tok)

    assert [e["show"] for e in first["episodes"]] == ["Show A"]
    assert [e["show"] for e in second["episodes"]] == ["Show B"]
    assert (first["header"]["limit"], first["header"]["pages"], second["header"]["page"]) == (1, 2, 2)


def test_cache_age_comes_from_the_walk_start_stored_in_the_cache(tok, stems, monkeypatch):
    monkeypatch.setattr(review_server, "_STEMS_CACHE", (time.monotonic() + 600, stems, time.monotonic() - 42))
    _, payload = review_server.route("GET", "/api/status", {}, tok)
    assert 41 <= payload["header"]["cache_age_s"] <= 44


def test_route_passes_one_snapshot_the_queue_reader_and_a_monotonic_now(tok, stems, monkeypatch):
    seen = {}

    def spy(method, path, body, **kw):
        seen.update(kw, method=method, path=path)
        return 200, {}

    snapshot = review_server._STEMS_CACHE
    monkeypatch.setattr(review_server.review_status, "handle", spy)
    before = time.monotonic()
    review_server.route("GET", "/api/status", {}, tok)

    assert set(seen) == {"method", "path", "stems_cache", "open_entries", "now"}
    assert seen["stems_cache"] is snapshot, "one snapshot of the cache tuple, never two separate loads"
    assert seen["open_entries"] is review_server.open_entries
    assert before <= seen["now"] <= time.monotonic()


def test_an_expired_cache_does_not_trigger_a_walk_for_status(tok, stems, monkeypatch):
    monkeypatch.setattr(review_server, "_STEMS_CACHE", (time.monotonic() - 1, stems, time.monotonic() - 5))

    def no_walk(*a, **k):
        raise AssertionError("status must never walk the media tree")

    monkeypatch.setattr(review_server.os, "walk", no_walk)
    assert review_server.route("GET", "/api/status", {}, tok)[0] == 200


def test_the_fill_time_global_is_gone():
    assert not hasattr(review_server, "_STEMS_FILLED")


def test_known_stems_stores_the_walk_start_not_the_walk_end(tmp_path, monkeypatch):
    media = tmp_path / "media" / "Show" / "Season 1"
    media.mkdir(parents=True)
    (media / "ep.dubtitles.conf.json").write_text("[]")
    monkeypatch.setattr(review_server, "ROOTS", [str(tmp_path / "media")])
    monkeypatch.setattr(review_server, "_STEMS_CACHE", None)
    ticks = iter([100.0])  # the first call is the walk start; every later one is "after a 30 s walk"

    monkeypatch.setattr(review_server.time, "monotonic", lambda: next(ticks, 130.0))
    review_server.known_stems()

    expiry, stems_, filled_at = review_server._STEMS_CACHE
    assert filled_at == 100.0, "walk START, so cache_age_s covers the walk's own duration"
    assert expiry > 130.0
    assert stems_ == [str(media / "ep")]
