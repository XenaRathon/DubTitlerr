"""Sonarr/Radarr webhook receiver (specs/arr-webhooks): mapping, auth, show resolve, dedup, dispatch.

Pure helpers with injected inputs (environ dicts, fake create/list_requests); no server needed.
Fixtures under tests/fixtures/webhooks/ are hand-written, not captured."""

import copy
import datetime
import json
import os
import re
import secrets

import pytest

import review_requests as rr
import review_webhooks as wh

TOKEN = "hook-token-fixture"
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "webhooks")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def env(**overrides):
    base = {"WEBHOOK_TOKEN": TOKEN}
    base.update(overrides)
    return base


def headers(token=TOKEN):
    return {"X-Webhook-Token": token} if token is not None else {}


def dumped(payload):
    return json.dumps(payload, sort_keys=True, default=str)


def clean(payload):
    assert TOKEN not in dumped(payload), "the token never appears in any returned payload"


class Queue:
    """Stand-in for review_requests.create / list_requests."""

    def __init__(self, existing=None):
        self.existing = list(existing or [])
        self.created = []
        self.next_id = "new-id-1"
        self.conflict = None

    def list_requests(self):
        return copy.deepcopy(self.existing)

    def create(self, body, anime_root=None, now=None):
        self.created.append(body)
        if self.conflict is not None:
            return 409, {"error": "identical request already pending", "existing_id": self.conflict}
        return 201, {"id": self.next_id, "status": "pending"}


def entry(req_id, show, remote, created_at, status="pending"):
    return {
        "id": req_id,
        "show": show,
        "status": status,
        "created_at": created_at,
        "webhook": {"source": "sonarr", "event": "Download", "remote_path": remote},
    }


def iso(now, delta_seconds):
    return datetime.datetime.fromtimestamp(now - delta_seconds, tz=datetime.timezone.utc).isoformat()


# ---- path mappings ---------------------------------------------------------------------------------------------------

def test_parse_mappings_splits_pairs_and_sorts_longest_first():
    assert wh.parse_mappings("/tv=/anime;/movies=/films") == [("/movies", "/films"), ("/tv", "/anime")]
    assert wh.parse_mappings("")[0:] == []
    assert wh.parse_mappings(None) == []


def test_parse_mappings_skips_entries_with_extra_separators_or_empties():
    assert wh.parse_mappings("a=b=c;d=e") == [("d", "e")]
    assert wh.parse_mappings("x;=y;z=;=;ok=/fine") == [("ok", "/fine")]


def test_map_path_longest_prefix_wins_on_component_boundary():
    mappings = wh.parse_mappings("/tv/One Pace=/anime/One Pace;/tv=/anime")
    assert wh.map_path("/tv/One Pace/Season 31/x.mkv", mappings) == "/anime/One Pace/Season 31/x.mkv"
    assert wh.map_path("/tv/Other/x.mkv", mappings) == "/anime/Other/x.mkv"
    assert wh.map_path("/tv2/x.mkv", mappings) == "/tv2/x.mkv"
    assert wh.map_path("/tv", mappings) == "/anime"


# ---- token check --------------------------------------------------------------------------------------------------------

def test_token_ok_missing_wrong_and_unset():
    assert wh.check_token(TOKEN, env()) is None
    assert wh.check_token(None, env()) == (401, {"error": "a token is required"})
    assert wh.check_token("", env()) == (401, {"error": "a token is required"})
    assert wh.check_token("nope", env()) == (403, {"error": "wrong token"})
    assert wh.check_token(TOKEN, {}) == (404, {"error": "no such route"})
    assert wh.check_token("anything", {"WEBHOOK_TOKEN": ""})[0] == 404


def test_token_comparison_is_constant_time_on_str(monkeypatch):
    calls = []
    real = secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(wh.secrets, "compare_digest", spy)
    assert wh.check_token(TOKEN, env()) is None
    assert wh.check_token("wrong", env())[0] == 403
    assert [type(a) for a, _ in calls] == [str, str]


def test_test_event_still_needs_the_token():
    q = Queue()
    status, payload = wh.handle(
        "POST", "/api/webhook/sonarr", load("sonarr_test.json"), {},
        env(), create=q.create, list_requests=q.list_requests,
    )
    assert (status, payload) == (401, {"error": "a token is required"})
    assert q.created == []


# ---- show resolution ------------------------------------------------------------------------------------------------------

def test_resolve_show_returns_the_first_component(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(os.path.join(root, "One Pace"))
    assert wh.resolve_show(os.path.join(root, "One Pace", "Season 31", "x.mkv"), root) == "One Pace"


def test_resolve_show_rejects_traversal_and_root_itself(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(root)
    assert wh.resolve_show(os.path.join(root, "..", "evil", "x.mkv"), root) is None
    assert wh.resolve_show("/elsewhere/Show/x.mkv", root) is None
    assert wh.resolve_show(root, root) is None
    assert wh.resolve_show("", root) is None


def test_resolve_show_rejects_symlink_escape(tmp_path):
    root = str(tmp_path / "anime")
    outside = str(tmp_path / "outside")
    os.makedirs(root)
    os.makedirs(os.path.join(outside, "Show"))
    os.symlink(outside, os.path.join(root, "link"))
    assert wh.resolve_show(os.path.join(root, "link", "Show", "x.mkv"), root) is None


# ---- episode parsing ---------------------------------------------------------------------------------------------------------

def test_episodes_from_plural_files():
    season, episodes = wh.episodes_from_payload(load("sonarr_download.json"))
    assert (season, episodes) == (31, [5])


def test_episodes_from_singular_file_with_multi_episode_name():
    season, episodes = wh.episodes_from_payload(load("sonarr_upgrade.json"))
    assert (season, episodes) == (1, [1, 2])


def test_derive_generate_only_re_matches_fixture_filenames():
    rx = re.compile(rr.derive_generate_only_re("Show Name", 1, wh._episode_re([5], 1)))
    assert rx.search("Show Name - S01E05 - Title.mkv") is not None
    assert rx.search("Show Name - S02E05 - Title.mkv") is None, "season token still scopes"
    assert rx.search("Show Name - S01E50 - Title.mkv") is None, "episode 5 must not match 50"
    multi = re.compile(rr.derive_generate_only_re("Show Name", 1, wh._episode_re([1, 2], 1)))
    assert multi.search("Show Name - S01E01E02 - Title.mkv") is not None
    assert multi.search("Show Name - S01E01 - Title.mkv") is not None
    assert multi.search("Show Name - S01E02 - Title.mkv") is not None
    assert multi.search("Show Name - S01E10 - Title.mkv") is None


def test_episodes_fallback_to_episode_numbers_then_show_only():
    payload = {
        "episodeFiles": [{"relativePath": "Season 31/finale.mkv", "path": "/tv/One Pace/Season 31/finale.mkv"}],
        "episodes": [{"seasonNumber": 31, "episodeNumber": 7}],
    }
    assert wh.episodes_from_payload(payload) == (31, [7])
    assert wh.episodes_from_payload({"episodes": []}) == (None, [])
    assert wh.episodes_from_payload({}) == (None, [])


# ---- build_request ---------------------------------------------------------

def test_sonarr_download_enqueues_with_season_and_regex(tmp_path):
    root = str(tmp_path / "anime")
    action, body = wh.build_request(
        "sonarr", load("sonarr_download.json"),
        env(REMOTE_PATH_MAPPINGS=f"/tv={root}"), root,
    )
    assert action == "enqueue"
    assert body["show"] == "One Pace"
    assert body["season"] == 31
    assert body["episode_re"] == "(?:[Ee]0*(?:5))(?!\\d)", "episode_re holds only the E-anchored episode part"
    assert body["webhook"] == {
        "source": "sonarr",
        "event": "Download",
        "remote_path": "/tv/One Pace/Season 31/One Pace - S31E05.mkv",
    }
    clean(body)


def test_sonarr_upgrade_multi_episode_joins_branches(tmp_path):
    root = str(tmp_path / "anime")
    action, body = wh.build_request(
        "sonarr", load("sonarr_upgrade.json"),
        env(REMOTE_PATH_MAPPINGS=f"/tv={root}"), root,
    )
    assert action == "enqueue"
    assert body["show"] == "Frieren"
    assert body["episode_re"] == "(?:[Ee]0*(?:1|2))(?!\\d)"


def test_rename_health_unknown_are_ignored_and_test_answers(tmp_path):
    root = str(tmp_path / "anime")
    e = env(REMOTE_PATH_MAPPINGS=f"/tv={root}")
    assert wh.build_request("sonarr", load("sonarr_rename.json"), e, root)[0] == "ignored"
    assert wh.build_request("sonarr", load("sonarr_health.json"), e, root)[0] == "ignored"
    assert wh.build_request("sonarr", {"eventType": "SomethingNew"}, e, root)[0] == "ignored"
    action, message = wh.build_request("sonarr", load("sonarr_test.json"), e, root)
    assert (action, message) == ("test", "webhook works, nothing enqueued")


def test_unmapped_path_outside_root_is_ignored(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(root)
    payload = load("sonarr_download.json")
    payload["series"]["path"] = "/unmapped/One Pace"
    action, reason = wh.build_request("sonarr", payload, env(), root)
    assert action == "ignored"
    assert isinstance(reason, str) and reason


def test_radarr_download_enqueues_movies_with_null_season(tmp_path):
    root = str(tmp_path / "anime")
    action, body = wh.build_request(
        "radarr", load("radarr_download.json"),
        env(REMOTE_PATH_MAPPINGS=f"/movies={root}"), root,
    )
    assert action == "enqueue"
    assert body["show"] == "Akira (1988)"
    assert body["season"] is None and body["episode_re"] is None


def test_radarr_outside_root_and_other_events_are_ignored(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(root)
    action, _ = wh.build_request("radarr", load("radarr_download.json"), env(), root)
    assert action == "ignored"
    e = env(REMOTE_PATH_MAPPINGS=f"/movies={root}")
    assert wh.build_request("radarr", {"eventType": "Rename", "movie": {"folderPath": "/movies/X"}}, e, root)[0] == "ignored"
    assert wh.build_request("radarr", load("radarr_test.json"), e, root) == ("test", "webhook works, nothing enqueued")


# ---- handle dispatch --------------------------------------------------------

def _hooked(tmp_path, show="One Pace"):
    root = str(tmp_path / "anime")
    os.makedirs(os.path.join(root, show), exist_ok=True)
    e = env(REMOTE_PATH_MAPPINGS=f"/tv={root};/movies={root}")
    return root, e


def test_handle_sonarr_download_enqueues_and_returns_id(tmp_path):
    root, e = _hooked(tmp_path)
    q = Queue()
    status, payload = wh.handle(
        "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=1700000000.0,
    )
    assert (status, payload) == (200, {"ok": True, "id": "new-id-1", "hint": "anime"})
    assert len(q.created) == 1 and q.created[0]["show"] == "One Pace"
    clean(payload)


def test_handle_isupgrade_download_and_upgrade_enqueue(tmp_path):
    root, e = _hooked(tmp_path, "Frieren")
    q = Queue()
    upgrade = load("sonarr_download.json")
    upgrade["isUpgrade"] = True
    for payload in (upgrade, load("sonarr_upgrade.json")):
        status, payload_out = wh.handle(
            "POST", "/api/webhook/sonarr", payload, headers(),
            e, create=q.create, list_requests=q.list_requests, anime_root=root, now=1700000000.0,
        )
        assert status == 200 and payload_out["ok"] is True
    assert len(q.created) == 2


def test_handle_test_rename_health_shapes(tmp_path):
    root, e = _hooked(tmp_path)
    q = Queue()
    kw = {"headers": headers(), "environ": e, "create": q.create,
          "list_requests": q.list_requests, "anime_root": root}
    assert wh.handle("POST", "/api/webhook/sonarr", load("sonarr_test.json"), **kw) == (
        200, {"ok": True, "message": "webhook works, nothing enqueued"})
    status, payload = wh.handle("POST", "/api/webhook/sonarr", load("sonarr_rename.json"), **kw)
    assert status == 200 and payload["ignored"] is True and isinstance(payload["reason"], str)
    status, payload = wh.handle("POST", "/api/webhook/sonarr", load("sonarr_health.json"), **kw)
    assert status == 200 and payload["ignored"] is True
    assert wh.handle("POST", "/api/webhook/radarr", load("radarr_test.json"), **kw) == (
        200, {"ok": True, "message": "webhook works, nothing enqueued"})
    assert q.created == []


def test_handle_query_token_fallback_and_wrong_route(tmp_path):
    root, e = _hooked(tmp_path)
    q = Queue()
    kw = {"environ": e, "create": q.create, "list_requests": q.list_requests, "anime_root": root}
    status, _ = wh.handle(
        "POST", "/api/webhook/sonarr?token=" + TOKEN, load("sonarr_test.json"), {}, **kw)
    assert status == 200
    assert wh.handle("POST", "/api/webhook/sonarr", load("sonarr_test.json"), headers("nope"), **kw)[0] == 403
    assert wh.handle("GET", "/api/webhook/sonarr", load("sonarr_test.json"), headers(), **kw)[0] == 404
    assert wh.handle("POST", "/api/nope", {}, headers(), **kw) == (404, {"error": "no such route"})


def test_handle_unset_token_hides_both_routes(tmp_path):
    root = str(tmp_path / "anime")
    q = Queue()
    for route in ("sonarr", "radarr"):
        status, payload = wh.handle(
            "POST", f"/api/webhook/{route}", load("sonarr_test.json"), headers("whatever"),
            {}, create=q.create, list_requests=q.list_requests, anime_root=root)
        assert (status, payload) == (404, {"error": "no such route"})
        clean(payload)


def test_handle_body_cap_and_bad_json(tmp_path):
    root, e = _hooked(tmp_path)
    q = Queue()
    kw = {"headers": headers(), "environ": e, "create": q.create,
          "list_requests": q.list_requests, "anime_root": root}
    big = b'{"eventType": "Download", "pad": "' + b"x" * (256 * 1024) + b'"}'
    assert wh.handle("POST", "/api/webhook/sonarr", big, **kw)[0] == 413
    assert wh.handle("POST", "/api/webhook/sonarr", None, **kw) == (400, {"error": "invalid JSON"})
    assert wh.handle("POST", "/api/webhook/sonarr", b"not json", **kw) == (400, {"error": "invalid JSON"})


def test_handle_dedup_window_boundary(tmp_path):
    root, e = _hooked(tmp_path)
    now = 1700000000.0
    remote = "/tv/One Pace/Season 31/One Pace - S31E05.mkv"
    for delta, hits in ((23 * 3600 + 59 * 60, True), (24 * 3600 + 60, False)):
        q = Queue([entry("old-id", "One Pace", remote, iso(now, delta))])
        status, payload = wh.handle(
            "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
            e, create=q.create, list_requests=q.list_requests, anime_root=root, now=now)
        assert (status, payload) == (
            200, {"ok": True, "id": "old-id" if hits else "new-id-1", "hint": "anime"})
        assert len(q.created) == (0 if hits else 1)
        clean(payload)


def test_handle_failed_entries_do_not_block_but_done_ones_do(tmp_path):
    root, e = _hooked(tmp_path)
    now = 1700000000.0
    remote = "/tv/One Pace/Season 31/One Pace - S31E05.mkv"
    q = Queue([entry("failed-id", "One Pace", remote, iso(now, 3600), status="failed")])
    status, payload = wh.handle(
        "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=now)
    assert payload == {"ok": True, "id": "new-id-1", "hint": "anime"}
    q = Queue([entry("done-id", "One Pace", remote, iso(now, 3600), status="done")])
    status, payload = wh.handle(
        "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=now)
    assert payload == {"ok": True, "id": "done-id", "hint": "anime"}
    assert q.created == []


def test_handle_queue_conflict_returns_existing_id(tmp_path):
    root, e = _hooked(tmp_path)
    q = Queue()
    q.conflict = "pending-id"
    status, payload = wh.handle(
        "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=1700000000.0)
    assert (status, payload) == (200, {"ok": True, "id": "pending-id", "hint": "anime"})


# ---- fix round: windows paths, trailing slashes, future stamps, real queue, specials -------------------------------

def test_map_path_normalizes_windows_separators():
    mappings = wh.parse_mappings("C:/Anime=/anime")
    assert wh.map_path("C:\\Anime\\Show\\file.mkv", mappings) == "/anime/Show/file.mkv"
    unc = wh.parse_mappings("//server/share=/anime")
    assert wh.map_path("\\\\server\\share\\Show\\f.mkv", unc) == "/anime/Show/f.mkv"


def test_resolve_show_normalizes_windows_separators(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(os.path.join(root, "Show"))
    assert wh.resolve_show(root.replace("/", "\\") + "\\Show\\f.mkv", root) == "Show"
    assert wh.resolve_show("C:\\Anime\\Show\\f.mkv", "C:\\Anime") == "Show"


def test_parse_mappings_strips_trailing_slashes():
    assert wh.parse_mappings("/tv/=/anime/") == [("/tv", "/anime")]
    assert wh.parse_mappings("/=/anime") == []
    assert wh.map_path("/tv/Show", wh.parse_mappings("/tv/=/anime/")) == "/anime/Show"


def test_handle_future_dated_entries_do_not_block(tmp_path):
    root, e = _hooked(tmp_path)
    now = 1700000000.0
    remote = "/tv/One Pace/Season 31/One Pace - S31E05.mkv"
    q = Queue([entry("future-id", "One Pace", remote, iso(now, -3600))])
    status, payload = wh.handle(
        "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=now)
    assert (status, payload) == (200, {"ok": True, "id": "new-id-1", "hint": "anime"})
    assert len(q.created) == 1


def test_real_create_writes_a_matching_generate_only_re(tmp_path):
    root = str(tmp_path / "anime")
    rdir = str(tmp_path / "requests")
    os.makedirs(os.path.join(root, "One Pace"))
    action, body = wh.build_request(
        "sonarr", load("sonarr_download.json"),
        env(REMOTE_PATH_MAPPINGS=f"/tv={root}"), root)
    assert action == "enqueue"
    status, result = rr.create(body, anime_root=root, requests_dir=rdir, now=1700000000.0)
    assert status == 201
    with open(os.path.join(rdir, result["id"] + ".json"), encoding="utf-8") as f:
        doc = json.load(f)
    rx = re.compile(doc["generate_only_re"])
    assert rx.search("One Pace - S31E05 - Title.mkv") is not None
    assert rx.search("One Pace - S31E50 - Title.mkv") is None


def test_season_zero_specials_become_season_none_with_episode_regex(tmp_path):
    with pytest.raises(rr.Refused):
        rr.validate({"show": "Specials Show", "season": 0, "episode_re": "0*5(?!\\d)"})
    root = str(tmp_path / "anime")
    os.makedirs(os.path.join(root, "Specials Show"))
    payload = {
        "eventType": "Download",
        "series": {"title": "Specials Show", "path": "/tv/Specials Show"},
        "episodeFiles": [{"relativePath": "Specials/Specials Show - S00E05.mkv",
                          "path": "/tv/Specials Show/Specials/Specials Show - S00E05.mkv"}],
        "episodes": [{"seasonNumber": 0, "episodeNumber": 5}],
    }
    action, body = wh.build_request(
        "sonarr", payload, env(REMOTE_PATH_MAPPINGS=f"/tv={root}"), root)
    assert action == "enqueue"
    assert body["season"] is None and body["episode_re"] == "(?:[Ss]0*0[Ee]0*(?:5))(?!\\d)"
    rr.validate(body, root)


# ---- second fix round: E-anchored episode regex, Refused mapping, long-list fallback -------------------------------

def test_episode_two_scoping_with_real_derive():
    rx = re.compile(rr.derive_generate_only_re("Show", 1, wh._episode_re([2], 1)))
    assert rx.search("Show - S01E02.mkv") is not None
    assert rx.search("Show - S01E02E03.mkv") is not None
    assert rx.search("Show - S01E12.mkv") is None, "E2 must not match E12"
    assert rx.search("Show - S01E22 x265.mkv") is None, "E2 must not match E22"
    assert rx.search("Show - S02E02.mkv") is None, "season token still scopes"


def test_special_requires_s00_with_real_derive():
    rx = re.compile(rr.derive_generate_only_re("Show", None, wh._episode_re([5], None)))
    assert rx.search("Show - S00E05.mkv") is not None
    assert rx.search("Show - S01E05.mkv") is None, "a special must not match S01"
    assert rx.search("Show - S03E15 1080p.mkv") is None


def test_multi_episode_matches_both_with_real_derive():
    rx = re.compile(rr.derive_generate_only_re("Show", 1, wh._episode_re([1, 2], 1)))
    assert rx.search("Show - S01E01.mkv") is not None
    assert rx.search("Show - S01E02.mkv") is not None
    assert rx.search("Show - S01E01E02.mkv") is not None


def test_refused_becomes_200_ignored_not_4xx(tmp_path):
    root = str(tmp_path / "anime")
    e = env(REMOTE_PATH_MAPPINGS=f"/tv={root}")

    class Boom:
        def __call__(self, body, anime_root=None, now=None):
            raise rr.Refused(400, "show directory not found: One Pace")

    for refusal in (
        "show directory not found: One Pace",
        "invalid show name: path traversal characters not permitted",
        "episode_re exceeds max length of 200 characters",
    ):

        class BoomWithText:
            def __call__(self, body, anime_root=None, now=None, _text=refusal):
                raise rr.Refused(400, _text)

        status, payload = wh.handle(
            "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
            e, create=BoomWithText(), list_requests=lambda: [], anime_root=root, now=1700000000.0)
        assert (status, payload) == (200, {"ok": True, "ignored": True, "reason": refusal})
        assert TOKEN not in json.dumps(payload)


def test_real_create_missing_show_dir_is_ignored(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(root)
    e = env(REMOTE_PATH_MAPPINGS=f"/tv={root}")
    status, payload = wh.handle(
        "POST", "/api/webhook/sonarr", load("sonarr_download.json"), headers(),
        e, create=rr.create, list_requests=lambda: [], anime_root=root, now=1700000000.0)
    assert status == 200 and payload["ignored"] is True
    assert "show directory not found" in payload["reason"]


def _absolute_pack(first, last, season=3):
    numbers = list(range(first, last + 1))
    return {
        "eventType": "Download",
        "series": {"title": "One Pace", "path": "/tv/One Pace"},
        "episodeFiles": [
            {"relativePath": f"One Pace - {n}.mkv", "path": f"/tv/One Pace/One Pace - {n}.mkv"}
            for n in numbers
        ],
        "episodes": [{"seasonNumber": season, "episodeNumber": n} for n in numbers],
    }


def test_thirty_absolute_episodes_keep_the_full_regex(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(os.path.join(root, "One Pace"))
    action, body = wh.build_request(
        "sonarr", _absolute_pack(1071, 1100),
        env(REMOTE_PATH_MAPPINGS=f"/tv={root}"), root)
    assert action == "enqueue"
    assert body["season"] == 3 and body["episode_re"] is not None
    assert len(body["episode_re"]) <= 200
    rr.validate(body, root)


def test_long_episode_list_falls_back_to_season_only(tmp_path):
    root = str(tmp_path / "anime")
    os.makedirs(os.path.join(root, "One Pace"))
    action, body = wh.build_request(
        "sonarr", _absolute_pack(1001, 1060),
        env(REMOTE_PATH_MAPPINGS=f"/tv={root}"), root)
    assert action == "enqueue"
    assert body["season"] == 3 and body["episode_re"] is None
    rr.validate(body, root)


# ---- newer payloads: v5/v6 extras, unknown fields, anime hint ---------------------------------------------------------

def _mapped(tmp_path, show):
    root = str(tmp_path / "anime")
    os.makedirs(os.path.join(root, show), exist_ok=True)
    return root, env(REMOTE_PATH_MAPPINGS=f"/tv={root};/movies={root}")


def test_v5_download_enqueues_exactly_like_v4(tmp_path):
    root = str(tmp_path / "anime")
    e = env(REMOTE_PATH_MAPPINGS=f"/tv={root}")
    assert wh.build_request("sonarr", load("sonarr_v5_download.json"), e, root) == \
        wh.build_request("sonarr", load("sonarr_download.json"), e, root)


def test_v5_upgrade_enqueues_exactly_like_v4(tmp_path):
    root = str(tmp_path / "anime")
    e = env(REMOTE_PATH_MAPPINGS=f"/tv={root}")
    assert wh.build_request("sonarr", load("sonarr_v5_upgrade.json"), e, root) == \
        wh.build_request("sonarr", load("sonarr_upgrade.json"), e, root)


def test_v6_radarr_enqueues_exactly_like_v5(tmp_path):
    root = str(tmp_path / "anime")
    e = env(REMOTE_PATH_MAPPINGS=f"/movies={root}")
    assert wh.build_request("radarr", load("radarr_v6_download.json"), e, root) == \
        wh.build_request("radarr", load("radarr_download.json"), e, root)


def test_unknown_extra_fields_never_break_parsing(tmp_path):
    root, e = _mapped(tmp_path, "One Pace")
    payload = load("sonarr_v5_download.json")
    payload["futureTopLevel"] = {"nested": [1, 2, {"deep": None}]}
    payload["series"]["futureSeriesField"] = ["x"]
    payload["episodeFiles"][0]["futureFileField"] = {"a": 1}
    payload["release"]["futureReleaseField"] = 42
    q = Queue()
    status, out = wh.handle(
        "POST", "/api/webhook/sonarr", payload, headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=1700000000.0)
    assert (status, out) == (200, {"ok": True, "id": "new-id-1", "hint": "anime"})
    assert q.created[0]["show"] == "One Pace"
    clean(out)


def test_unknown_event_type_is_ignored(tmp_path):
    root, e = _mapped(tmp_path, "One Pace")
    q = Queue()
    payload = load("sonarr_v5_download.json")
    payload["eventType"] = "SeriesAdd"
    status, out = wh.handle(
        "POST", "/api/webhook/sonarr", payload, headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=1700000000.0)
    assert status == 200 and out["ignored"] is True
    assert q.created == []


def test_string_or_null_id_lists_do_not_crash(tmp_path):
    root = str(tmp_path / "anime")
    e = env(REMOTE_PATH_MAPPINGS=f"/tv={root}")
    for ids in ({"malIds": "20", "aniListIds": None}, {"malIds": None, "aniListIds": "21"}, {}):
        payload = load("sonarr_v5_download.json")
        payload["series"] = {k: v for k, v in payload["series"].items()
                             if k not in ("malIds", "aniListIds", "type")}
        payload["series"].update(ids)
        action, body = wh.build_request("sonarr", payload, e, root)
        assert action == "enqueue" and body["show"] == "One Pace"


def test_is_anime_hint():
    assert wh.is_anime_hint(load("sonarr_download.json")) is True
    assert wh.is_anime_hint(load("sonarr_v5_download.json")) is True
    assert wh.is_anime_hint({"series": {"title": "X", "malIds": [20]}}) is True
    assert wh.is_anime_hint({"series": {"title": "X", "aniListIds": [21]}}) is True
    assert wh.is_anime_hint({"series": {"title": "X", "type": "standard"}}) is False
    assert wh.is_anime_hint({"series": {"title": "X", "malIds": [], "aniListIds": []}}) is False
    assert wh.is_anime_hint({"series": {"title": "X", "malIds": "20"}}) is False
    assert wh.is_anime_hint({"series": {"title": "X", "malIds": None}}) is False
    assert wh.is_anime_hint({"series": {"title": "X"}}) is False
    assert wh.is_anime_hint({"movie": {"title": "Y"}}) is False
    assert wh.is_anime_hint({}) is False
    assert wh.is_anime_hint(None) is False


def _standard_download(show="Some Show"):
    return {
        "eventType": "Download",
        "series": {"title": show, "path": f"/tv/{show}", "type": "standard"},
        "episodeFiles": [{
            "relativePath": "Season 01/Some Show - S01E03.mkv",
            "path": f"/tv/{show}/Season 01/Some Show - S01E03.mkv",
        }],
        "episodes": [{"seasonNumber": 1, "episodeNumber": 3}],
    }


def test_hint_is_informational_only_never_a_filter(tmp_path):
    root, e = _mapped(tmp_path, "Some Show")
    q = Queue()
    status, out = wh.handle(
        "POST", "/api/webhook/sonarr", _standard_download(), headers(),
        e, create=q.create, list_requests=q.list_requests, anime_root=root, now=1700000000.0)
    assert (status, out) == (200, {"ok": True, "id": "new-id-1"})
    assert "hint" not in out, "non-anime payloads carry no hint"
    assert len(q.created) == 1, "path confinement stays the only gate"
    clean(out)
