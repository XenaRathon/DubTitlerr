import builtins
import json
import math
import os
import threading
import time

import common
import decisions
import review_server
import review_status


def _create_episode(tmp_path, show="ShowA", season="Season 1", ep="E01"):
    ep_dir = tmp_path / show / season
    ep_dir.mkdir(parents=True, exist_ok=True)
    stem = str(ep_dir / f"{show} - {ep}")
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": 0.0, "end": 1.0, "text": "Hello world"}], f)
    return stem


def test_status_requires_auth():
    """Unauthenticated GET /api/status returns 401 and is not in OPEN_ROUTES."""
    assert ("GET", "/api/status") not in review_server.OPEN_ROUTES
    status, payload = review_server.route("GET", "/api/status", {}, None)
    assert status == 401
    assert payload == {"error": "login required"}


def test_status_registered(tmp_path):
    """review_status exposes handle(method, path, body, ...) returning (status, payload)."""
    assert hasattr(review_status, "handle")
    assert hasattr(review_status, "handle_status")
    stem = _create_episode(tmp_path)
    now = 100.0
    stems_cache = (200.0, [stem], 95.0)
    status, payload = review_status.handle("GET", "/api/status", {}, stems_cache=stems_cache, now=now)
    assert status == 200
    assert "header" in payload
    assert "episodes" in payload
    assert len(payload["episodes"]) == 1
    assert payload["header"]["cache_age_s"] == 5.0


def test_status_zero_walks(tmp_path, monkeypatch):
    """T2: GET /api/status performs zero filesystem tree walks even with expired cache."""
    stem = _create_episode(tmp_path)

    def forbid_walk(*args, **kwargs):
        raise RuntimeError("os.walk forbidden")

    monkeypatch.setattr(os, "walk", forbid_walk)
    expired_cache = (time.monotonic() - 1.0, [stem], time.monotonic() - 10.0)
    status, payload = review_status.handle("GET", "/api/status", {}, stems_cache=expired_cache, now=time.monotonic())
    assert status == 200
    assert len(payload["episodes"]) == 1


def test_status_stages(tmp_path, monkeypatch):
    """Stage classification covers failed, stale (M3/T5), pending-review, muxed, repaired, transcribed."""
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(tmp_path / "decisions"))

    # 1. Failed via .dubtitles.fail
    s_failed = _create_episode(tmp_path, "One Pace", "S01", "E01")
    (tmp_path / "One Pace" / "S01" / "One Pace - E01.dubtitles.fail").write_text("crash")

    # 2. Failed via stages.json
    s_failed_stage = _create_episode(tmp_path, "One Pace", "S01", "E02")
    with open(s_failed_stage + ".dubtitles.stages.json", "w") as f:
        json.dump({"repair": {"outcome": "backend-unreachable", "at": 100.0}}, f)

    # 3a. Stale via both tiers behind
    s_stale_both = _create_episode(tmp_path, "One Pace", "S01", "E03a")
    with open(s_stale_both + ".dubtitles.done", "w") as f:
        json.dump(
            {
                "size": 1000,
                "mtime": 100.0,
                "muxed": True,
                "version": 1,
                "text_version": 1,
                "transcribe_version": 1,
            },
            f,
        )

    # 3b. Stale via transcribe_version behind only (M3/T5)
    s_stale_transcribe = _create_episode(tmp_path, "One Pace", "S01", "E03b")
    with open(s_stale_transcribe + ".dubtitles.done", "w") as f:
        json.dump(
            {
                "size": 1000,
                "mtime": 100.0,
                "muxed": True,
                "text_version": common.TEXT_VERSION,
                "transcribe_version": 1,
            },
            f,
        )

    # 3c. Stale via no version keys (M3/T5 grandfather version)
    s_stale_no_version = _create_episode(tmp_path, "One Pace", "S01", "E03c")
    with open(s_stale_no_version + ".dubtitles.done", "w") as f:
        json.dump(
            {
                "size": 1000,
                "mtime": 100.0,
                "muxed": True,
            },
            f,
        )

    # 4. Pending review via open_entries
    s_pending = _create_episode(tmp_path, "One Pace", "S01", "E04")

    # 5. Muxed via current version in both tiers and muxed=True
    s_muxed = _create_episode(tmp_path, "One Pace", "S01", "E05")
    with open(s_muxed + ".dubtitles.done", "w") as f:
        json.dump(
            {
                "size": 2000,
                "mtime": 200.0,
                "muxed": True,
                "text_version": common.TEXT_VERSION,
                "transcribe_version": common.TRANSCRIBE_VERSION,
            },
            f,
        )
    with open(s_muxed + ".dubtitles.stages.json", "w") as f:
        json.dump({"mux": {"outcome": "ok", "at": 200.0}}, f)

    # 6. Repaired via repair-summary.json
    s_repaired = _create_episode(tmp_path, "One Pace", "S01", "E06")
    with open(s_repaired + ".dubtitles.repair-summary.json", "w") as f:
        json.dump({"model": "qwen3-4b-instruct", "repaired_lines": 5}, f)

    # 7. Transcribed (only conf.json exists)
    s_transcribed = _create_episode(tmp_path, "One Pace", "S01", "E07")

    stems = [
        s_failed,
        s_failed_stage,
        s_stale_both,
        s_stale_transcribe,
        s_stale_no_version,
        s_pending,
        s_muxed,
        s_repaired,
        s_transcribed,
    ]

    def fake_open_entries(stem):
        if stem == s_pending:
            return [{"stage": "repair_applied", "original_text": "Hello world"}]
        return []

    stems_cache = (300.0, stems, 100.0)
    status, payload = review_status.handle(
        "GET", "/api/status", {"limit": 50}, stems_cache=stems_cache, open_entries=fake_open_entries, now=110.0
    )
    assert status == 200
    by_stem = {ep["stem"]: ep for ep in payload["episodes"]}

    assert by_stem[s_failed]["stage"] == "failed"
    assert by_stem[s_failed]["last_outcome"] == "crashed"

    assert by_stem[s_failed_stage]["stage"] == "failed"
    assert by_stem[s_failed_stage]["last_outcome"] == "backend-unreachable"

    assert by_stem[s_stale_both]["stage"] == "stale"
    assert by_stem[s_stale_both]["text_version"] == 1

    assert by_stem[s_stale_transcribe]["stage"] == "stale"
    assert by_stem[s_stale_transcribe]["text_version"] == common.TEXT_VERSION

    assert by_stem[s_stale_no_version]["stage"] == "stale"

    assert by_stem[s_pending]["stage"] == "pending-review"
    assert by_stem[s_pending]["pending_review_count"] == 1

    assert by_stem[s_muxed]["stage"] == "muxed"
    assert by_stem[s_muxed]["last_outcome"] == "ok"
    assert by_stem[s_muxed]["text_version"] == common.TEXT_VERSION

    assert by_stem[s_repaired]["stage"] == "repaired"
    assert by_stem[s_repaired]["repair_model"] == "qwen3-4b-instruct"

    assert by_stem[s_transcribed]["stage"] == "transcribed"


def test_status_cost_bound(tmp_path, monkeypatch):
    """T1/H3: File reads per stem <= 5, and only slice stems are touched."""
    stems = [_create_episode(tmp_path, "ShowA", "S01", f"E{i:02d}") for i in range(10)]
    for s in stems:
        with open(s + ".dubtitles.done", "w") as f:
            json.dump({"muxed": True, "text_version": common.TEXT_VERSION, "transcribe_version": common.TRANSCRIBE_VERSION}, f)
        with open(s + ".dubtitles.stages.json", "w") as f:
            json.dump({"mux": {"outcome": "ok"}}, f)
        with open(s + ".dubtitles.repair-summary.json", "w") as f:
            json.dump({"model": "test-m"}, f)

    orig_open = builtins.open
    orig_exists = os.path.exists
    orig_getmtime = os.path.getmtime
    orig_stat = os.stat

    touches = {}

    def track(path):
        p = str(path)
        for s in stems:
            if s in p:
                touches[s] = touches.get(s, 0) + 1

    def wrapped_open(path, *args, **kwargs):
        track(path)
        return orig_open(path, *args, **kwargs)

    def wrapped_exists(path, *args, **kwargs):
        track(path)
        return orig_exists(path, *args, **kwargs)

    def wrapped_getmtime(path, *args, **kwargs):
        track(path)
        return orig_getmtime(path, *args, **kwargs)

    def wrapped_stat(path, *args, **kwargs):
        track(path)
        return orig_stat(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", wrapped_open)
    monkeypatch.setattr(os.path, "exists", wrapped_exists)
    monkeypatch.setattr(os.path, "getmtime", wrapped_getmtime)
    monkeypatch.setattr(os, "stat", wrapped_stat)

    # Request page 1 with limit 2 -> only stems[0] and stems[1] should be touched
    stems_cache = (100.0, stems, 50.0)
    status, payload = review_status.handle(
        "GET", "/api/status", {"page": 1, "limit": 2}, stems_cache=stems_cache, open_entries=lambda s: [], now=60.0
    )
    assert status == 200
    assert len(payload["episodes"]) == 2
    assert payload["header"]["total"] == 10

    # Assert stems outside the page slice were NOT touched
    for s in stems[2:]:
        assert touches.get(s, 0) == 0, f"Stem {s} outside page slice was touched {touches.get(s)} times"

    # Assert stems on the page slice had <= 5 filesystem touches
    for s in stems[:2]:
        assert touches.get(s, 0) <= 5, f"Stem {s} exceeded budget with {touches.get(s)} touches"


def test_status_malformed_sidecars(tmp_path):
    """T4/H2/M4: Corrupt shapes, nulls, and NaNs fall back safely and produce valid JSON."""
    stem = _create_episode(tmp_path)
    (tmp_path / "ShowA" / "Season 1" / f"{os.path.basename(stem)}.dubtitles.done").write_text("{broken json")
    # Wrong shapes in stages.json: non-dict values and NaN
    with open(tmp_path / "ShowA" / "Season 1" / f"{os.path.basename(stem)}.dubtitles.stages.json", "w") as f:
        json.dump({"repair": "ok", "extra": None, "list": [1], "mux": {"outcome": "ok", "at": "NaN"}}, f)
    (tmp_path / "ShowA" / "Season 1" / f"{os.path.basename(stem)}.dubtitles.repair-summary.json").write_text("[1, 2, 3]")

    stems_cache = (100.0, [stem], 50.0)
    status, payload = review_status.handle("GET", "/api/status", {}, stems_cache=stems_cache, open_entries=lambda s: [], now=60.0)
    assert status == 200
    ep = payload["episodes"][0]
    assert ep["text_version"] is None
    assert ep["repair_model"] is None
    assert ep["last_outcome"] in ("ok", "unknown")

    # M4: Assert payload serialises strictly without NaN / Infinity
    serialized = json.dumps(payload, allow_nan=False)
    assert "NaN" not in serialized
    assert "Infinity" not in serialized


def test_status_cache_age_and_heartbeat(tmp_path, monkeypatch):
    """L1/M5: None cache returns 503; empty list returns 200 total 0; cache_age_s is now - filled_at."""
    # Stems cache None returns 503 cache warming
    assert review_status.handle("GET", "/api/status", {}, stems_cache=None, now=10.0)[0] == 503

    # L1: Empty library list returns 200 with total 0
    empty_cache = (100.0, [], 50.0)
    st_empty, pay_empty = review_status.handle("GET", "/api/status", {}, stems_cache=empty_cache, now=60.0)
    assert st_empty == 200
    assert pay_empty["header"]["total"] == 0
    assert pay_empty["episodes"] == []

    # M5: cache_age_s = now - filled_at
    stem = _create_episode(tmp_path)
    stems_cache = (100.0, [stem], 50.0)
    st, pay = review_status.handle("GET", "/api/status", {}, stems_cache=stems_cache, now=64.2)
    assert st == 200
    assert math.isclose(pay["header"]["cache_age_s"], 14.2, abs_tol=0.1)

    # When now is None or filled_at is None, cache_age_s is None
    st2, pay2 = review_status.handle("GET", "/api/status", {}, stems_cache=stems_cache, now=None)
    assert pay2["header"]["cache_age_s"] is None

    # Heartbeat file present with NaN/Infinity check (M4)
    hb_file = tmp_path / "heartbeat.json"
    monkeypatch.setattr(common, "HEARTBEAT_PATH", str(hb_file))
    common.heartbeat(last_sweep_end=1726058400.0, current_show="One Pace")
    status, payload = review_status.handle("GET", "/api/status", {}, stems_cache=stems_cache, now=60.0)
    assert status == 200
    hdr = payload["header"]
    assert hdr["last_sweep_end"] == 1726058400.0
    assert hdr["current_show"] == "One Pace"
    assert hdr["builder_heartbeat_age_s"] is not None

    # Missing heartbeat
    hb_file.unlink()
    status, payload = review_status.handle("GET", "/api/status", {}, stems_cache=stems_cache, now=60.0)
    assert status == 200
    assert payload["header"]["last_sweep_end"] is None
    assert payload["header"]["current_show"] is None
    assert payload["header"]["builder_heartbeat_age_s"] is None


def test_status_filtering_and_pagination(tmp_path):
    """Filters by show and paginates with page and limit."""
    stems_a = [_create_episode(tmp_path, "ShowA", "S01", f"E{i:02d}") for i in range(5)]
    stems_b = [_create_episode(tmp_path, "ShowB", "S01", f"E{i:02d}") for i in range(3)]
    all_stems = stems_a + stems_b
    stems_cache = (100.0, all_stems, 50.0)

    # Filter by ShowB
    status, payload = review_status.handle(
        "GET", "/api/status", {"show": "ShowB"}, stems_cache=stems_cache, open_entries=lambda s: [], now=60.0
    )
    assert status == 200
    assert payload["header"]["total"] == 3
    assert len(payload["episodes"]) == 3
    assert all(ep["show"] == "ShowB" for ep in payload["episodes"])

    # Pagination: page 2, limit 2
    status, payload = review_status.handle(
        "GET", "/api/status", {"page": 2, "limit": 2}, stems_cache=(100.0, stems_a, 50.0), open_entries=lambda s: [], now=60.0
    )
    assert status == 200
    assert payload["header"]["total"] == 5
    assert payload["header"]["page"] == 2
    assert payload["header"]["limit"] == 2
    assert payload["header"]["pages"] == 3
    assert len(payload["episodes"]) == 2
    assert payload["episodes"][0]["episode"] == "ShowA - E02"

    # Page out of bounds
    status, payload = review_status.handle(
        "GET", "/api/status", {"page": 99, "limit": 2}, stems_cache=(100.0, stems_a, 50.0), open_entries=lambda s: [], now=60.0
    )
    assert status == 200
    assert payload["header"]["total"] == 5
    assert payload["header"]["pages"] == 3
    assert payload["episodes"] == []


def test_status_concurrency_with_warm_thread(tmp_path):
    """T3: Swap stems_cache concurrently while calling handle(); verify no exception."""
    stems1 = [_create_episode(tmp_path, "ShowA", "S01", f"E{i:02d}") for i in range(3)]
    stems2 = [_create_episode(tmp_path, "ShowB", "S01", f"E{i:02d}") for i in range(3)]

    holder = {"cache": (200.0, stems1, 100.0)}
    stop_event = threading.Event()

    def swapper():
        flip = False
        while not stop_event.is_set():
            flip = not flip
            holder["cache"] = (300.0, stems2 if flip else stems1, 150.0 if flip else 100.0)
            time.sleep(0.001)

    t = threading.Thread(target=swapper, daemon=True)
    t.start()
    try:
        for _ in range(50):
            st, pay = review_status.handle(
                "GET", "/api/status", {}, stems_cache=holder["cache"], open_entries=lambda s: [], now=160.0
            )
            assert st == 200
            assert pay["header"]["total"] == 3
            # cache_age_s is 160 - 150 (10) or 160 - 100 (60)
            assert pay["header"]["cache_age_s"] in (10.0, 60.0)
    finally:
        stop_event.set()
        t.join(timeout=1.0)


def test_status_decisions_show_for(tmp_path, monkeypatch):
    """M2: Uses decisions.show_for(stem) to look up decisions store even with non-standard layouts."""
    # Deep layout: ShowA/Season 1/Part A/ShowA - E01
    ep_dir = tmp_path / "media" / "ShowA" / "Season 1" / "Part A"
    ep_dir.mkdir(parents=True, exist_ok=True)
    stem = str(ep_dir / "ShowA - E01")
    with open(stem + ".dubtitles.conf.json", "w") as f:
        json.dump([{"start": 0.0, "end": 1.0, "text": "Hello world"}], f)

    # Decisions directory
    dec_dir = tmp_path / "decisions"
    dec_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(decisions, "DECISIONS_DIR", str(dec_dir))

    # decisions.show_for resolves to "ShowA"
    monkeypatch.setattr(decisions, "show_for", lambda s: "ShowA")

    # Record a decision for ShowA that settles "Hello world"
    store = {}
    decisions.record(store, "Hello world", "Hello proposal", "reject")
    decisions.save(store, "ShowA", str(dec_dir))

    # open_entries returns the line
    def fake_open(s):
        return [{"stage": "repair_applied", "original_text": "Hello world", "proposed_text": "Hello proposal"}]

    stems_cache = (100.0, [stem], 50.0)
    st, pay = review_status.handle("GET", "/api/status", {}, stems_cache=stems_cache, open_entries=fake_open, now=60.0)
    assert st == 200
    # Because the line is decided in ShowA's store, pending_review_count must be 0!
    assert pay["episodes"][0]["pending_review_count"] == 0


def test_status_stages_file_with_a_non_dict_stage_value_is_just_an_unknown_stage(tmp_path):
    """A stages file {"repair": "ok"} (a string, not a stage record) must not raise: the episode reads as a plain
    transcribed one whose outcome is unknown, never failed, and the response is still strict JSON."""
    stem = _create_episode(tmp_path)
    with open(stem + ".dubtitles.stages.json", "w") as f:
        json.dump({"repair": "ok"}, f)

    status, payload = review_status.handle(
        "GET", "/api/status", {}, stems_cache=(100.0, [stem], 50.0), open_entries=lambda s: [], now=60.0
    )

    assert status == 200
    ep = payload["episodes"][0]
    assert (ep["stage"], ep["last_outcome"]) == ("transcribed", "unknown")
    json.dumps(payload, allow_nan=False)
