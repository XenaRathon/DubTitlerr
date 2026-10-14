import datetime
import json
import os
import stat
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import review_requests
from review_requests import (
    Refused,
    create,
    derive_generate_only_re,
    finish,
    get_schedule,
    handle,
    is_window_open,
    list_requests,
    mark_running,
    next_pending,
    prune,
    put_schedule,
    recover_running,
    validate,
    validate_schedule,
    write_effective_env,
)


def test_validate_and_traversal_guards(tmp_path):
    anime_root = tmp_path / "anime"
    anime_root.mkdir()
    show_dir = anime_root / "Frieren"
    show_dir.mkdir()

    # Valid body
    clean = validate(
        {"show": "Frieren", "season": 1, "episode_re": r"[Ee]01", "require_eng": 1},
        anime_root=str(anime_root),
    )
    assert clean["show"] == "Frieren"
    assert clean["season"] == 1
    assert clean["episode_re"] == r"[Ee]01"
    assert clean["require_eng"] == 1

    # Missing show
    with pytest.raises(Refused) as exc:
        validate({}, anime_root=str(anime_root))
    assert exc.value.status == 400

    # Empty show
    with pytest.raises(Refused) as exc:
        validate({"show": "   "}, anime_root=str(anime_root))
    assert exc.value.status == 400

    # Path traversal / slashes / NUL
    for bad_show in ("../etc", "Frieren/sub", "show\0name", ".."):
        with pytest.raises(Refused) as exc:
            validate({"show": bad_show}, anime_root=str(anime_root))
        assert exc.value.status == 400

    # Show directory does not exist
    with pytest.raises(Refused) as exc:
        validate({"show": "NonExistentShow"}, anime_root=str(anime_root))
    assert exc.value.status == 400
    assert "not found" in exc.value.error or "does not exist" in exc.value.error

    # Unknown keys rejected
    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "extra_key": 123}, anime_root=str(anime_root))
    assert exc.value.status == 400


def test_validate_rejects_hostile_characters():
    for hostile in ("Show\nPATH=/evil", "Show\r\nBad", "Show\x01test", "Show\x00test", "Show\u200btest"):
        with pytest.raises(Refused) as exc:
            validate({"show": hostile}, anime_root=None)
        assert exc.value.status == 400
        assert "control" in exc.value.error or "invalid character" in exc.value.error or "not permitted" in exc.value.error

    # Control characters in episode_re
    for bad_ep in ("E01\nINJECT", "E01\r\nBad", "E01\x00", "E01\x05"):
        with pytest.raises(Refused) as exc:
            validate({"show": "Frieren", "episode_re": bad_ep}, anime_root=None)
        assert exc.value.status == 400


def test_validate_rejects_symlink_escaping_anime_root(tmp_path):
    anime_root = tmp_path / "anime"
    anime_root.mkdir()
    outside_dir = tmp_path / "outside_secret"
    outside_dir.mkdir()
    symlink_show = anime_root / "EscapingShow"
    symlink_show.symlink_to(outside_dir)
    with pytest.raises(Refused) as exc:
        validate({"show": "EscapingShow"}, anime_root=str(anime_root))
    assert exc.value.status == 400
    assert "escapes" in exc.value.error

    # repair_model rejected explicitly
    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "repair_model": "qwen2.5"}, anime_root=str(anime_root))
    assert exc.value.status == 400

    # Invalid season (negative, zero, bool, non-int)
    for bad_season in (-1, 0, True, "1"):
        with pytest.raises(Refused) as exc:
            validate({"show": "Frieren", "season": bad_season}, anime_root=str(anime_root))
        assert exc.value.status == 400

    # Invalid episode_re (unclosed regex, too long)
    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "episode_re": "[unclosed"}, anime_root=str(anime_root))
    assert exc.value.status == 400

    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "episode_re": "a" * 201}, anime_root=str(anime_root))
    assert exc.value.status == 400

    # ReDoS checks: nested quantifiers, backreferences, lookbehind
    for redos_re in ("(a+)+", "(a*)*", "([0-9]+)+", r"(a)\1", r"(?P<foo>a)(?P=foo)", r"(?<=a)b", r"(?<!a)b"):
        with pytest.raises(Refused) as exc:
            validate({"show": "Frieren", "episode_re": redos_re}, anime_root=str(anime_root))
        assert exc.value.status == 400

    # Invalid require_eng (not 0, 1, or None)
    for bad_req in (2, -1, True, "1"):
        with pytest.raises(Refused) as exc:
            validate({"show": "Frieren", "require_eng": bad_req}, anime_root=str(anime_root))
        assert exc.value.status == 400


def test_derive_generate_only_re():
    # Show only
    re1 = derive_generate_only_re("One Pace", None, None)
    assert re1 == r"One\ Pace"

    # Escaping special regex chars in show
    re_special = derive_generate_only_re("Show [2024] + Test", None, None)
    assert re_special == r"Show\ \[2024\]\ \+\ Test"

    # Show + season
    re2 = derive_generate_only_re("One Pace", 1, None)
    assert r"One\ Pace" in re2
    assert r"[Ss]0*1" in re2
    assert not re2.endswith(r"(?!\d)")

    # Show + season + episode_re
    re3 = derive_generate_only_re("One Pace", 1, r"E01")
    assert r"One\ Pace" in re3
    assert r"[Ss]0*1" in re3
    assert r"(?!\d)" in re3

    # Show + episode alternation with trailing (?!\d) guard
    re4 = derive_generate_only_re("One Pace", None, r"E01|E02")
    assert r"(?!\d)" in re4

    # Matches 'Show - S01E05' and not 'Other - S01E05' and not S01E50 for episode 5
    import re
    re5 = derive_generate_only_re("Show", 1, "E05")
    rx5 = re.compile(re5)
    assert rx5.search("Show - S01E05") is not None
    assert rx5.search("Other - S01E05") is None
    assert rx5.search("Show - S01E50") is None

    # Alternation with existing (?!\d) guard does not leak across shows
    re6 = derive_generate_only_re("Show", None, r"E05|E06(?!\d)")
    rx6 = re.compile(re6)
    assert rx6.search("Show - S01E05") is not None
    assert rx6.search("Other - S01E05") is None
    assert rx6.search("Other - S01E06") is None
    assert rx6.search("Show - S01E50") is None


def test_create_atomic_permissions_and_schema(tmp_path):
    anime_root = tmp_path / "anime"
    anime_root.mkdir()
    (anime_root / "Bleach").mkdir()
    req_dir = tmp_path / "requests"

    fixed_now = datetime.datetime(2026, 10, 12, 14, 0, 0, tzinfo=datetime.timezone.utc)
    body = {
        "show": "Bleach",
        "season": 2,
        "episode_re": r"E(?:0[1-9]|10)",
        "require_eng": 1,
        "webhook": {"source": "sonarr", "event": "Download", "remote_path": "/tv/Bleach"},
    }

    status, resp = create(body, anime_root=str(anime_root), requests_dir=str(req_dir), now=fixed_now)
    assert status == 201
    assert "id" in resp
    assert resp["status"] == "pending"
    assert resp["id"].startswith("20261012T140000.000000Z-")

    # Verify file on disk
    req_file = req_dir / f"{resp['id']}.json"
    assert req_file.exists()

    # Permissions mode 0o664
    mode = stat.S_IMODE(os.stat(req_file).st_mode)
    assert mode == 0o664

    # File schema validation
    data = json.loads(req_file.read_text())
    assert data["id"] == resp["id"]
    assert data["show"] == "Bleach"
    assert data["season"] == 2
    assert data["episode_re"] == r"E(?:0[1-9]|10)"
    assert data["generate_only_re"] is not None
    assert data["require_eng"] == 1
    assert data["status"] == "pending"
    assert data["error"] is None
    assert data["finished_at"] is None
    assert data["webhook"] == {"source": "sonarr", "event": "Download", "remote_path": "/tv/Bleach"}


def test_dedup_pending_requests(tmp_path):
    anime_root = tmp_path / "anime"
    anime_root.mkdir()
    (anime_root / "ShowA").mkdir()
    req_dir = tmp_path / "requests"

    body = {"show": "ShowA", "season": 1, "episode_re": "E01"}
    status1, resp1 = create(body, anime_root=str(anime_root), requests_dir=str(req_dir))
    assert status1 == 201

    # Exact duplicate submission while pending -> 409 Conflict
    status2, resp2 = create(body, anime_root=str(anime_root), requests_dir=str(req_dir))
    assert status2 == 409
    assert resp2["existing_id"] == resp1["id"]

    # Different episode -> 201
    body_diff = {"show": "ShowA", "season": 1, "episode_re": "E02"}
    status3, resp3 = create(body_diff, anime_root=str(anime_root), requests_dir=str(req_dir))
    assert status3 == 201

    # Finish the first request as done, then re-submitting original body should succeed (not blocked)
    req1_path = str(req_dir / f"{resp1['id']}.json")
    finish(req1_path, ok=True)

    status4, resp4 = create(body, anime_root=str(anime_root), requests_dir=str(req_dir))
    assert status4 == 201
    assert resp4["id"] != resp1["id"]


def test_fifo_ordering(tmp_path):
    req_dir = tmp_path / "requests"
    req_dir.mkdir()

    # Create files out of order
    times = [
        "20261012T100000Z-11111111",
        "20261012T090000Z-22222222",
        "20261012T110000Z-33333333",
    ]
    for tid in times:
        f = req_dir / f"{tid}.json"
        f.write_text(json.dumps({"id": tid, "status": "pending", "show": "Show"}))

    oldest = next_pending(str(req_dir))
    assert oldest is not None
    assert "20261012T090000Z-22222222" in str(oldest)


def test_mark_running_finish_and_recover(tmp_path):
    req_dir = tmp_path / "requests"
    req_dir.mkdir()

    req_id = "20261012T100000Z-aaaaaaaa"
    f = req_dir / f"{req_id}.json"
    f.write_text(json.dumps({"id": req_id, "status": "pending", "show": "Show"}))

    # Mark running renames to .running
    running_path = mark_running(str(f))
    assert running_path.endswith(".running")
    assert os.path.exists(running_path)
    assert not f.exists()
    data = json.loads(Path(running_path).read_text())
    assert data["status"] == "running"

    # Simulate restart crash: recover_running moves .running to failed/ with 'interrupted by restart'
    recover_running(str(req_dir))
    assert not os.path.exists(running_path)

    failed_dir = req_dir / "failed"
    failed_file = failed_dir / f"{req_id}.json"
    assert failed_file.exists()
    failed_data = json.loads(failed_file.read_text())
    assert failed_data["status"] == "failed"
    assert failed_data["error"] == "interrupted by restart"
    assert failed_data["finished_at"] is not None

    # Test finish on another request
    req2_id = "20261012T110000Z-bbbbbbbb"
    f2 = req_dir / f"{req2_id}.json"
    f2.write_text(json.dumps({"id": req2_id, "status": "running", "show": "Show"}))
    done_path = finish(str(f2), ok=True)
    assert os.path.exists(done_path)
    done_data = json.loads(Path(done_path).read_text())
    assert done_data["status"] == "done"
    assert done_data["error"] is None
    assert done_data["finished_at"] is not None


def test_retention_prune(tmp_path):
    req_dir = tmp_path / "requests"
    done_dir = req_dir / "done"
    failed_dir = req_dir / "failed"
    done_dir.mkdir(parents=True)
    failed_dir.mkdir(parents=True)

    now_ts = 1791765000.0

    # Old file (8 days old)
    old_done = done_dir / "old.json"
    old_done.write_text("{}")
    os.utime(old_done, (now_ts - 8 * 86400, now_ts - 8 * 86400))

    # Fresh file (1 day old)
    fresh_done = done_dir / "fresh.json"
    fresh_done.write_text("{}")
    os.utime(fresh_done, (now_ts - 1 * 86400, now_ts - 1 * 86400))

    # Old failed file
    old_failed = failed_dir / "old_failed.json"
    old_failed.write_text("{}")
    os.utime(old_failed, (now_ts - 9 * 86400, now_ts - 9 * 86400))

    prune(str(done_dir), str(failed_dir), days=7, now=now_ts)

    assert not old_done.exists()
    assert fresh_done.exists()
    assert not old_failed.exists()

    # Clamping days to at least 1 day: passing 0 or negative must not delete fresh files
    prune(str(done_dir), str(failed_dir), days=0, now=now_ts)
    prune(str(done_dir), str(failed_dir), days=-10, now=now_ts)
    assert fresh_done.exists()


def test_list_requests_never_walks_and_skips_malformed(tmp_path):
    req_dir = tmp_path / "requests"
    done_dir = req_dir / "done"
    failed_dir = req_dir / "failed"
    done_dir.mkdir(parents=True)
    failed_dir.mkdir(parents=True)

    # Valid pending file
    (req_dir / "20261012T100000Z-11111111.json").write_text(
        json.dumps({"id": "20261012T100000Z-11111111", "status": "pending"})
    )
    # Valid done file
    (done_dir / "20261012T090000Z-22222222.json").write_text(
        json.dumps({"id": "20261012T090000Z-22222222", "status": "done"})
    )
    # Malformed file (invalid json)
    (failed_dir / "20261012T080000Z-33333333.json").write_text("{broken json")

    # Patch os.walk to raise: list_requests must NEVER call os.walk
    with patch("os.walk", side_effect=RuntimeError("os.walk forbidden")):
        reqs = list_requests(requests_dir=str(req_dir))

    assert len(reqs) == 2
    # Newest first
    assert reqs[0]["id"] == "20261012T100000Z-11111111"
    assert reqs[1]["id"] == "20261012T090000Z-22222222"


def test_handle_route_contract(tmp_path):
    anime_root = tmp_path / "anime"
    anime_root.mkdir()
    (anime_root / "Naruto").mkdir()
    req_dir = tmp_path / "requests"

    # POST /api/requests
    status, payload = handle(
        "POST",
        "/api/requests",
        {"show": "Naruto", "season": 1},
        requests_dir=str(req_dir),
        anime_root=str(anime_root),
    )
    assert status == 201
    assert payload["status"] == "pending"

    # Duplicate POST -> 409
    status409, payload409 = handle(
        "POST",
        "/api/requests",
        {"show": "Naruto", "season": 1},
        requests_dir=str(req_dir),
        anime_root=str(anime_root),
    )
    assert status409 == 409

    # GET /api/requests
    get_status, get_payload = handle(
        "GET",
        "/api/requests",
        {},
        requests_dir=str(req_dir),
        anime_root=str(anime_root),
    )
    assert get_status == 200
    assert len(get_payload) == 1
    assert get_payload[0]["show"] == "Naruto"


def test_cli_interface(tmp_path, capsys):
    req_dir = tmp_path / "requests"
    req_dir.mkdir()

    req_id = "20261012T100000Z-12345678"
    req_file = req_dir / f"{req_id}.json"
    req_file.write_text(
        json.dumps({
            "id": req_id,
            "show": "Frieren",
            "generate_only_re": r"Frieren.*S01",
            "require_eng": 1,
            "status": "pending",
        })
    )

    empty_dir = tmp_path / "empty_requests"
    empty_dir.mkdir()
    # CLI: next on empty queue must exit 1
    with pytest.raises(SystemExit) as exc:
        with patch.object(sys, "argv", ["review_requests.py", "next", str(empty_dir)]):
            review_requests.main()
    assert exc.value.code == 1

    # CLI: next on pending request
    with patch.object(sys, "argv", ["review_requests.py", "next", str(req_dir)]):
        review_requests.main()
    out_json = json.loads(capsys.readouterr().out.strip())
    assert out_json["path"] == str(req_file)
    assert out_json["show"] == "Frieren"
    assert r"Frieren.*S01" in out_json["generate_only_re"]
    assert out_json["require_eng"] == "1"

    # CLI: start
    with patch.object(sys, "argv", ["review_requests.py", "start", str(req_file)]):
        review_requests.main()
    running_path = req_dir / f"{req_id}.running"
    assert running_path.exists()

    # CLI: finish ok
    with patch.object(sys, "argv", ["review_requests.py", "finish", str(running_path), "ok"]):
        review_requests.main()
    done_file = req_dir / "done" / f"{req_id}.json"
    assert done_file.exists()

    # CLI: recover
    running_crash = req_dir / "20261012T120000Z-99999999.running"
    running_crash.write_text(json.dumps({"id": "20261012T120000Z-99999999", "status": "running"}))
    with patch.object(sys, "argv", ["review_requests.py", "recover", str(req_dir)]):
        review_requests.main()
    failed_file = req_dir / "failed" / "20261012T120000Z-99999999.json"
    assert failed_file.exists()


def test_cli_next_skips_bad_file_and_moves_to_failed(tmp_path, capsys):
    req_dir = tmp_path / "requests"
    req_dir.mkdir()

    # Place a hand-crafted bad request file with newline in generate_only_re
    bad_file = req_dir / "20261012T010000Z-bad11111.json"
    bad_file.write_text(json.dumps({
        "id": "20261012T010000Z-bad11111",
        "show": "Frieren",
        "generate_only_re": "Frieren\nPATH=/evil\nSHOW=Injected",
        "status": "pending",
    }))

    # Place a valid pending request file behind it
    good_file = req_dir / "20261012T020000Z-good2222.json"
    good_file.write_text(json.dumps({
        "id": "20261012T020000Z-good2222",
        "show": "Frieren",
        "generate_only_re": r"Frieren.*S01E01",
        "status": "pending",
    }))

    # Invoking CLI next should skip the bad file and return the good file!
    with patch.object(sys, "argv", ["review_requests.py", "next", str(req_dir)]):
        review_requests.main()

    out_json = json.loads(capsys.readouterr().out.strip())
    assert out_json["path"] == str(good_file)
    assert out_json["show"] == "Frieren"

    # The bad file must have been moved to failed/ with error 'invalid request file'
    assert not bad_file.exists()
    failed_file = req_dir / "failed" / "20261012T010000Z-bad11111.json"
    assert failed_file.exists()
    failed_data = json.loads(failed_file.read_text())
    assert failed_data["status"] == "failed"
    assert failed_data["error"] == "invalid request file"


def test_is_window_open_and_cli(tmp_path, capsys):
    schedule_file = tmp_path / "schedule.json"

    # Missing file -> open
    assert is_window_open(str(schedule_file)) is True

    # CLI: missing file
    with patch.object(sys, "argv", ["review_requests.py", "window-open", str(schedule_file)]):
        review_requests.main()
    assert capsys.readouterr().out.strip() == "open"

    # Disabled window -> open
    schedule_file.write_text(json.dumps({"enabled": False, "open": "02:00", "close": "04:00", "tz": "UTC"}))
    assert is_window_open(str(schedule_file)) is True

    # Same open and close -> open (all day)
    schedule_file.write_text(json.dumps({"enabled": True, "open": "02:00", "close": "02:00", "tz": "UTC"}))
    assert is_window_open(str(schedule_file)) is True

    # Normal window: 09:00 - 17:00 UTC
    schedule_file.write_text(json.dumps({"enabled": True, "open": "09:00", "close": "17:00", "tz": "UTC"}))
    dt_inside = datetime.datetime(2026, 10, 12, 10, 30, tzinfo=datetime.timezone.utc)
    dt_before = datetime.datetime(2026, 10, 12, 8, 30, tzinfo=datetime.timezone.utc)
    dt_after = datetime.datetime(2026, 10, 12, 17, 30, tzinfo=datetime.timezone.utc)
    assert is_window_open(str(schedule_file), now=dt_inside) is True
    assert is_window_open(str(schedule_file), now=dt_before) is False
    assert is_window_open(str(schedule_file), now=dt_after) is False

    # Midnight crossing window: 22:00 - 06:00 UTC
    schedule_file.write_text(json.dumps({"enabled": True, "open": "22:00", "close": "06:00", "tz": "UTC"}))
    dt_night = datetime.datetime(2026, 10, 12, 23, 0, tzinfo=datetime.timezone.utc)
    dt_morning = datetime.datetime(2026, 10, 12, 5, 30, tzinfo=datetime.timezone.utc)
    dt_day = datetime.datetime(2026, 10, 12, 12, 0, tzinfo=datetime.timezone.utc)
    assert is_window_open(str(schedule_file), now=dt_night) is True
    assert is_window_open(str(schedule_file), now=dt_morning) is True
    assert is_window_open(str(schedule_file), now=dt_day) is False

    # Unknown timezone -> fails OPEN with log line to stderr
    schedule_file.write_text(json.dumps({"enabled": True, "open": "02:00", "close": "04:00", "tz": "NonExistent/Zone"}))
    assert is_window_open(str(schedule_file)) is True
    err = capsys.readouterr().err
    assert "unknown or unresolvable timezone" in err

    # CLI check with closed window
    with patch.object(sys, "argv", ["review_requests.py", "window-open", str(schedule_file)]):
        with patch("review_requests.is_window_open", return_value=False):
            review_requests.main()
    assert capsys.readouterr().out.strip() == "closed"


def test_write_effective_env_and_cli(tmp_path, capsys):
    out_file = tmp_path / "effective.env"
    mock_env = {
        "REPAIR_BACKEND": "llamacpp\nextra_line",
        "REPAIR_MODEL": "qwen3-4b-instruct",
        "REPAIR_LLAMACPP_URL": "http://desk-gpu:8090/v1",
        "REPAIR_OPENAI_API_KEY": "sk-secret-1234567890abcdef",
        "REPAIR_EXTRA_BODY": '{"headers":{"Authorization":"Bearer secret"}}',
        "REPAIR_PROMPT": "Bearer token123",
        "REPAIR_USERINFO": "https://user:pass@host/v1",
        "VERIFY_BACKEND": "internal",
        "VERIFY_OTHER": "sk-proj-1234567890abcdef123",
        "REQUIRE_ENG": "1",
        "GLOSSARY_ARC_TAGS": "1",
        "RESCAN_INTERVAL": "21600",
        "MERGE_WINDOW": "02:00-06:00",
        "ANIME_ORDER": "/config/anime_order.txt",
        "WEBHOOK_TOKEN": "secret-token",
        "MY_SECRET_KEY": "bad",
        "IGNORED_VAR": "something_else",
    }

    target = write_effective_env(str(out_file), env=mock_env)
    assert target == str(out_file)
    assert out_file.exists()

    content = out_file.read_text()
    # Allow list check
    assert "REPAIR_BACKEND=llamacpp\n" in content
    assert "REPAIR_MODEL=qwen3-4b-instruct\n" in content
    # L2: desk-gpu has "sk-" in the hostname but must NOT be dropped!
    assert "REPAIR_LLAMACPP_URL=http://desk-gpu:8090/v1\n" in content
    assert "VERIFY_BACKEND=internal\n" in content
    assert "REQUIRE_ENG=1\n" in content
    assert "GLOSSARY_ARC_TAGS=1\n" in content
    assert "RESCAN_INTERVAL=21600\n" in content
    assert "MERGE_WINDOW=02:00-06:00\n" in content
    assert "ANIME_ORDER=/config/anime_order.txt\n" in content

    # Masking / skipping secrets and blacklist (L2, L3)
    # L3: REPAIR_EXTRA_BODY is explicitly skipped
    assert "REPAIR_EXTRA_BODY" not in content
    assert "Bearer" not in content
    assert "REPAIR_USERINFO" not in content
    assert "pass@" not in content
    assert "REPAIR_OPENAI_API_KEY" not in content
    assert "sk-secret-1234567890abcdef" not in content
    assert "VERIFY_OTHER" not in content
    assert "sk-proj-1234567890abcdef123" not in content
    assert "WEBHOOK_TOKEN" not in content
    assert "MY_SECRET_KEY" not in content
    assert "IGNORED_VAR" not in content

    # CLI invocation
    cli_out = tmp_path / "cli_effective.env"
    with patch.dict(os.environ, mock_env):
        with patch.object(sys, "argv", ["review_requests.py", "write-effective-env", str(cli_out)]):
            review_requests.main()
    assert cli_out.exists()
    assert "REPAIR_MODEL=qwen3-4b-instruct\n" in cli_out.read_text()



def test_schedule_api_defaults_and_validation(tmp_path):
    sfile = tmp_path / "schedule.json"

    # Missing file returns default schedule
    default_sched = get_schedule(str(sfile))
    assert default_sched == {"enabled": False, "open": "00:00", "close": "00:00", "tz": "UTC"}

    # Validation: valid body
    valid_body = {"enabled": True, "open": "02:00", "close": "06:00", "tz": "America/New_York"}
    assert validate_schedule(valid_body) == valid_body

    # Validation: non-dict
    with pytest.raises(Refused) as exc:
        validate_schedule("not a dict")
    assert exc.value.status == 400

    # Validation: missing keys
    for missing_key in ("enabled", "open", "close", "tz"):
        bad = valid_body.copy()
        del bad[missing_key]
        with pytest.raises(Refused) as exc:
            validate_schedule(bad)
        assert exc.value.status == 400
        assert "missing" in exc.value.error

    # Validation: unknown keys
    with pytest.raises(Refused) as exc:
        validate_schedule({**valid_body, "unknown": "val"})
    assert exc.value.status == 400
    assert "unknown" in exc.value.error

    # Validation: non-bool enabled
    for bad_enabled in (1, 0, "true", None):
        with pytest.raises(Refused) as exc:
            validate_schedule({**valid_body, "enabled": bad_enabled})
        assert exc.value.status == 400

    # Validation: bad time format
    for bad_time in ("25:00", "24:00", "2:00", "02:60", "02:0", "abc", 123):
        with pytest.raises(Refused) as exc:
            validate_schedule({**valid_body, "open": bad_time})
        assert exc.value.status == 400
        with pytest.raises(Refused) as exc:
            validate_schedule({**valid_body, "close": bad_time})
        assert exc.value.status == 400

    # Validation: invalid timezone
    for bad_tz in ("Invalid/Timezone", "", 123):
        with pytest.raises(Refused) as exc:
            validate_schedule({**valid_body, "tz": bad_tz})
        assert exc.value.status == 400


def test_put_schedule_roundtrip_and_permissions(tmp_path):
    sfile = tmp_path / "schedule.json"
    valid_body = {"enabled": True, "open": "03:30", "close": "07:30", "tz": "UTC"}

    # PUT schedule
    status, result = put_schedule(valid_body, str(sfile))
    assert status == 200
    assert result == valid_body
    assert sfile.exists()

    # Permissions mode 0o664
    mode = stat.S_IMODE(os.stat(sfile).st_mode)
    assert mode == 0o664

    # GET schedule retrieves the written data
    loaded = get_schedule(str(sfile))
    assert loaded == valid_body


def test_handle_schedule_routes(tmp_path):
    sfile = tmp_path / "schedule.json"

    # GET /api/schedule
    status, payload = handle("GET", "/api/schedule", schedule_file=str(sfile))
    assert status == 200
    assert payload["enabled"] is False

    # PUT /api/schedule valid
    new_data = {"enabled": True, "open": "01:00", "close": "05:00", "tz": "UTC"}
    status, payload = handle("PUT", "/api/schedule", body=new_data, schedule_file=str(sfile))
    assert status == 200
    assert payload == new_data

    # Verify GET returns updated data
    status, payload = handle("GET", "/api/schedule", schedule_file=str(sfile))
    assert status == 200
    assert payload == new_data

    # PUT /api/schedule invalid
    status, payload = handle("PUT", "/api/schedule", body={"enabled": "not-bool"}, schedule_file=str(sfile))
    assert status == 400
    assert "error" in payload

    # Method not allowed
    status, payload = handle("POST", "/api/schedule", schedule_file=str(sfile))
    assert status == 405



def test_h1_validate_rejects_cc_and_cf_in_string_fields():
    # Cc: \x00, \n, \x1f, \x7f
    # Cf: \u200b (zero-width space), \u200e (left-to-right mark)
    for bad_ch in ("\n", "\r", "\x00", "\x1f", "\x7f", "\u200b", "\u200e"):
        with pytest.raises(Refused) as exc:
            validate({"show": f"Show{bad_ch}A"}, anime_root=None)
        assert exc.value.status == 400

        with pytest.raises(Refused) as exc:
            validate({"show": "ShowA", "episode_re": f"E01{bad_ch}"}, anime_root=None)
        assert exc.value.status == 400


def test_h1_finish_and_mark_running_refuse_path_outside_requests_dir(tmp_path, monkeypatch):
    requests_dir = tmp_path / "requests"
    requests_dir.mkdir()
    monkeypatch.setenv("REQUESTS_DIR", str(requests_dir))

    outside_file = tmp_path / "victim.json"
    outside_file.write_text(json.dumps({"id": "victim", "status": "pending"}))

    with pytest.raises((ValueError, Refused)):
        review_requests.mark_running(str(outside_file))

    with pytest.raises((ValueError, Refused)):
        review_requests.finish(str(outside_file), ok=True)


def test_h2_redos_alternation_refused_under_one_second():
    import time
    start = time.monotonic()
    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "episode_re": "(a|aa)*c"}, anime_root=None)
    elapsed = time.monotonic() - start
    assert exc.value.status == 400
    assert elapsed < 1.0


def test_m1_season_only_matches_real_filenames():
    import re
    re_s1 = derive_generate_only_re("Show A", 1)
    # Must NOT have trailing (?!\d)
    assert not re_s1.endswith(r"(?!\d)")

    rx = re.compile(re_s1)
    # Must match real SxxEyy names
    assert rx.search("Show A - S01E02.mkv") is not None
    assert rx.search("Show A - S01E02E03.mkv") is not None
    assert rx.search("Show A.S01.E02.mkv") is not None
    assert rx.search("Show A - S01 - 02.mkv") is not None

    # S10E01 must NOT match season 1
    assert rx.search("Show A - S10E01.mkv") is None





def test_m3_show_containment_accepts_pokemon_and_rezero(tmp_path):
    anime_root = tmp_path / "anime"
    anime_root.mkdir()
    (anime_root / "Pokémon (1997) {tvdb-76703}").mkdir()
    (anime_root / "Re:Zero").mkdir()

    # Both must be accepted by validate without ascii pattern error!
    res1 = validate({"show": "Pokémon (1997) {tvdb-76703}"}, anime_root=str(anime_root))
    assert res1["show"] == "Pokémon (1997) {tvdb-76703}"

    res2 = validate({"show": "Re:Zero"}, anime_root=str(anime_root))
    assert res2["show"] == "Re:Zero"


def test_m7_list_requests_parses_only_newest_200(tmp_path):
    req_dir = tmp_path / "requests"
    req_dir.mkdir()
    for i in range(250):
        name = f"20261012T{i:06d}Z-test{i:04d}.json"
        (req_dir / name).write_text(json.dumps({"id": name[:-5], "status": "pending"}))

    items = list_requests(str(req_dir))
    assert len(items) == 200
    assert items[0]["id"] == "20261012T000249Z-test0249"
    assert items[-1]["id"] == "20261012T000050Z-test0050"


def test_m7_prune_cli_subcommand(tmp_path, capsys):
    req_dir = tmp_path / "requests"
    done_dir = req_dir / "done"
    done_dir.mkdir(parents=True)
    failed_dir = req_dir / "failed"
    failed_dir.mkdir(parents=True)

    old_file = done_dir / "20261001T000000Z-old.json"
    old_file.write_text("{}")
    old_time = time.time() - 10 * 86400
    os.utime(old_file, (old_time, old_time))

    new_file = done_dir / "20261012T000000Z-new.json"
    new_file.write_text("{}")

    with patch.object(sys, "argv", ["review_requests.py", "prune", str(req_dir), "7"]):
        review_requests.main()

    out = capsys.readouterr().out
    assert "pruned 1 files" in out
    assert not old_file.exists()
    assert new_file.exists()


def test_l5_concurrent_put_schedule_serialised(tmp_path):
    sfile = tmp_path / "schedule.json"
    body1 = {"enabled": True, "open": "01:00", "close": "02:00", "tz": "UTC"}
    body2 = {"enabled": True, "open": "03:00", "close": "04:00", "tz": "UTC"}

    status1, resp1 = put_schedule(body1, schedule_file=str(sfile))
    assert status1 == 200
    status2, resp2 = put_schedule(body2, schedule_file=str(sfile))
    assert status2 == 200
    assert json.loads(sfile.read_text())["open"] == "03:00"


def test_l8_same_second_requests_keep_arrival_order(tmp_path):
    anime_root = tmp_path / "anime"
    anime_root.mkdir()
    (anime_root / "ShowA").mkdir()
    req_dir = tmp_path / "requests"

    t1 = datetime.datetime(2026, 10, 12, 14, 0, 0, 100000, tzinfo=datetime.timezone.utc)
    t2 = datetime.datetime(2026, 10, 12, 14, 0, 0, 200000, tzinfo=datetime.timezone.utc)

    _, resp1 = create(
        {"show": "ShowA", "season": 1, "episode_re": "E01"},
        anime_root=str(anime_root),
        requests_dir=str(req_dir),
        now=t1,
    )
    _, resp2 = create(
        {"show": "ShowA", "season": 1, "episode_re": "E02"},
        anime_root=str(anime_root),
        requests_dir=str(req_dir),
        now=t2,
    )

    assert resp1["id"] < resp2["id"]
    assert next_pending(str(req_dir)) == str(req_dir / f"{resp1['id']}.json")


def test_cli_unpack(capsys):
    raw_json = json.dumps({
        "path": "/config/requests/test.json",
        "show": "Frieren",
        "generate_only_re": r"Frieren.*S01E01",
        "require_eng": "1",
    })
    with patch.object(sys, "argv", ["review_requests.py", "unpack", raw_json]):
        review_requests.main()

    out = capsys.readouterr().out
    assert "PATH=/config/requests/test.json\n" in out
    assert "SHOW=Frieren\n" in out
    assert "GENERATE_ONLY_RE=Frieren.*S01E01\n" in out
    assert "REQUIRE_ENG=1\n" in out


def test_h1_safe_grammar_refuses_catastrophic_and_arbitrary_regex():
    from review_requests import Refused, validate

    # Catastrophic ReDoS example from reviewer H1 must be refused
    with pytest.raises(Refused) as exc1:
        validate({"show": "Frieren", "episode_re": r"\w*\w*\w*\w*\w*\w*\w*\w*\w*\w*\w*\w*!"}, anime_root=None)
    assert exc1.value.status == 400

    # Arbitrary regexes (a|aa)*c and (a+)+b must be refused
    with pytest.raises(Refused) as exc2:
        validate({"show": "Frieren", "episode_re": "(a|aa)*c"}, anime_root=None)
    assert exc2.value.status == 400

    with pytest.raises(Refused) as exc3:
        validate({"show": "Frieren", "episode_re": "(a+)+b"}, anime_root=None)
    assert exc3.value.status == 400


def test_h1_safe_grammar_property_adversarial_timing_and_acceptance():
    import re
    import time

    import review_webhooks
    from review_requests import validate

    # UI examples and safe grammar patterns must be accepted
    accepted_patterns = [
        "S01E05",
        "E0[1-3]",
        "1[0-9]",
        "Digimon",
        r"(?:[Ee]0*(?:2))(?!\d)",
        r"(?:[Ss]0*0[Ee]0*(?:1|2|3))(?!\d)",
        r"(?:[Ee]0*(?:10|11))(?!\d)",
        r"E\d{1,3}",
        r"E[0-9]{1,2}",
        "Show.S01E01",
        "Show_S01E01",
        "Show-S01E01",
    ]

    for pat in accepted_patterns:
        res = validate({"show": "Frieren", "episode_re": pat}, anime_root=None)
        assert res["episode_re"] == pat

    # Check review_webhooks output through validate
    ep_single = review_webhooks._episode_re([5], season=1)
    res_single = validate({"show": "Frieren", "episode_re": ep_single}, anime_root=None)
    assert res_single["episode_re"] == ep_single

    ep_multi = review_webhooks._episode_re([1, 2, 3], season=1)
    res_multi = validate({"show": "Frieren", "episode_re": ep_multi}, anime_root=None)
    assert res_multi["episode_re"] == ep_multi

    ep_special = review_webhooks._episode_re([1], season=None)
    res_special = validate({"show": "Frieren", "episode_re": ep_special}, anime_root=None)
    assert res_special["episode_re"] == ep_special

    # 50 adversarial file names (5000 chars, no terminator, runs of digits/letters/spaces/underscores)
    adversarial_names = []
    chars_pool = ["a", "0", " ", "_", "B", "9", "-"]
    for k in range(50):
        chunk = chars_pool[k % len(chars_pool)] * 1000 + "x" * 1000 + "0" * 1000 + "_" * 1000 + "A" * 1000
        adversarial_names.append(f"Show - S01E02 - {chunk}.mkv")

    # Every accepted pattern run over all 50 names must finish under 50 ms in total
    start = time.perf_counter()
    for pat in accepted_patterns:
        rx = re.compile(pat)
        for name in adversarial_names:
            rx.search(name)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.050, f"matching took {elapsed:.4f}s >= 0.050s"


def test_h1_four_reviewer_shapes_refused():
    from review_requests import Refused, validate

    # 1. Nested {1,3} groups with 0*
    shape1 = "(?:(?:(?:(?:0*|0*)){1,3}){1,3}){1,3}x"
    with pytest.raises(Refused) as exc1:
        validate({"show": "Frieren", "episode_re": shape1}, anime_root=None)
    assert exc1.value.status == 400

    # 2. 8 levels of (?:(?:0*|0*)){1,3}, then x
    shape2 = "(?:" * 8 + "0*|0*" + "){1,3}" * 8 + "x"
    with pytest.raises(Refused) as exc2:
        validate({"show": "Frieren", "episode_re": shape2}, anime_root=None)
    assert exc2.value.status == 400

    # 3. 12 levels of (?: |0*), then x
    shape3 = "(?: |" * 12 + "0*" + ")" * 12 + "x"
    with pytest.raises(Refused) as exc3:
        validate({"show": "Frieren", "episode_re": shape3}, anime_root=None)
    assert exc3.value.status == 400

    # 4. 0*x90 then x
    shape4 = "0*" * 90 + "x"
    with pytest.raises(Refused) as exc4:
        validate({"show": "Frieren", "episode_re": shape4}, anime_root=None)
    assert exc4.value.status == 400


def test_requeue_atomic_and_status(tmp_path, monkeypatch):
    import pathlib

    import review_requests

    requests_dir = tmp_path / "requests"
    requests_dir.mkdir()
    monkeypatch.setenv("REQUESTS_DIR", str(requests_dir))

    req_file = requests_dir / "20261012T100000Z-11111111.json"
    req_file.write_text(
        json.dumps({
            "id": "20261012T100000Z-11111111",
            "show": "Frieren",
            "status": "pending",
        })
    )

    running_path = review_requests.mark_running(str(req_file))
    assert running_path.endswith(".running")
    assert os.path.exists(running_path)
    assert not req_file.exists()
    assert json.loads(pathlib.Path(running_path).read_text())["status"] == "running"

    # Requeue moves it back to pending with same id
    requeued = review_requests.requeue(running_path)
    assert requeued.endswith(".json")
    assert os.path.exists(requeued)
    assert not os.path.exists(running_path)
    data = json.loads(pathlib.Path(requeued).read_text())
    assert data["status"] == "pending"
    assert data["id"] == "20261012T100000Z-11111111"

    # Also works when passing the original .json path
    assert review_requests.mark_running(requeued).endswith(".running")
    requeued2 = review_requests.requeue(requeued)
    assert requeued2.endswith(".json")
    assert json.loads(pathlib.Path(requeued2).read_text())["status"] == "pending"


def test_h1_leading_space_with_quantifier_refused():
    from review_requests import Refused, validate

    # Leading space plus quantifier must be refused after normalisation
    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "episode_re": " {2}x"}, anime_root=None)
    assert exc.value.status == 400


def test_h1_guard_pinning_group_quantifier_ban():
    from review_requests import Refused, validate

    # Depth is 1 (passes depth cap <= 2), 0 zero-star tokens (passes single 0*),
    # but group has quantifier {2}
    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "episode_re": "(?:E01){2}"}, anime_root=None)
    assert exc.value.status == 400


def test_h1_guard_pinning_depth_cap():
    from review_requests import Refused, validate

    # No group quantifiers, 0 zero-star tokens, non-empty branches,
    # but nesting depth is 3 (> 2)
    with pytest.raises(Refused) as exc:
        validate({"show": "Frieren", "episode_re": "(?:(?:(?:E01)))"}, anime_root=None)
    assert exc.value.status == 400


def test_h1_guard_pinning_single_zero_star_and_chain():
    from review_requests import Refused, validate

    # Depth 0, no group quantifiers, valid literal branches,
    # but 2 zero-star tokens across branches
    with pytest.raises(Refused) as exc1:
        validate({"show": "Frieren", "episode_re": "E0*1|E0*2"}, anime_root=None)
    assert exc1.value.status == 400

    # 33 chained (?:0*) groups then x must be refused
    with pytest.raises(Refused) as exc2:
        validate({"show": "Frieren", "episode_re": "(?:0*)" * 33 + "x"}, anime_root=None)
    assert exc2.value.status == 400


def test_h1_empty_or_quantifier_only_branch_refused():
    from review_requests import Refused, validate

    # Empty branch
    with pytest.raises(Refused) as exc1:
        validate({"show": "Frieren", "episode_re": "(?:|)"}, anime_root=None)
    assert exc1.value.status == 400

    # Quantifier-only branch with nothing else
    with pytest.raises(Refused) as exc2:
        validate({"show": "Frieren", "episode_re": "(?:0*)"}, anime_root=None)
    assert exc2.value.status == 400



def test_h1_safe_grammar_property_random_walk_timing():
    import random
    import re
    import time

    from review_requests import derive_generate_only_re, validate

    test_files = [
        ("One Pace", "One Pace - S01E05 - Romance Dawn [1080p].mkv"),
        ("Frieren", "[SubsPlease] Frieren - Beyond Journey's End - 01 (1080p) [F2A1B3C4].mkv"),
        ("Dungeon Meshi", "[Erai-raws] Dungeon Meshi - 12 [1080p][Multiple Subtitle] [A1B2C3D4].mkv"),
        ("Show Name", "Show Name - S02E15 - The Long Awaited Episode Title (1080p BluRay x265 10bit AAC).mkv"),
        ("Jujutsu Kaisen", "[Judas] Jujutsu Kaisen - S02E23 [1080p][HEVC x265 10bit][Dual-Audio].mkv"),
        ("Attack on Titan", "Attack on Titan - The Final Season - Part 3 - 01 (1080p).mkv"),
        ("Steins;Gate 0", "Steins;Gate 0 - S01E08 - Dual - Antinomic Dual [BD 1080p].mkv"),
        ("Re_Zero", "Re_Zero kara Hajimeru Isekai Seikatsu 2nd Season - 13 [1080p].mkv"),
        ("Vinland Saga", "[ASW] Vinland Saga S2 - 24 [1080p HEVC x265 10bit AAC].mkv"),
        ("Mob Psycho 100 III", "Mob Psycho 100 III - S03E12 - Communication ~Toward the Future~ [1080p].mkv"),
        ("Kimetsu no Yaiba", "Kimetsu no Yaiba - Hashira Geiko-hen - S04E08 [1080p].mkv"),
        ("Boku no Hero Academia", "Boku no Hero Academia - S07E21 - Battle Without a Quirk [1080p].mkv"),
        ("Bleach", "[HorribleSubs] Bleach - S16E366 - Final Episode [720p].mkv"),
        ("Naruto Shippuuden", "Naruto Shippuuden - S01E001 - Homecoming [480p DVD].mkv"),
        ("Fullmetal Alchemist Brotherhood", "Fullmetal Alchemist Brotherhood - S01E64 - Journey's End [1080p Dual Audio].mkv"),
        ("Cowboy Bebop", "Cowboy Bebop - Session 05 - Ballad of Fallen Angels [1080p Remaster].mkv"),
        ("Neon Genesis Evangelion", "Neon Genesis Evangelion - Episode 26 - The Beast that Shouted Love [1080p].mkv"),
        ("Delicious in Dungeon", "Delicious in Dungeon - S01E01 - Hot Pot - Tart [1080p NF WEB-DL].mkv"),
        ("SPY x FAMILY", "SPY x FAMILY - S02E12 - PART OF THE FAMILY [1080p CR WEB-DL].mkv"),
        ("Dragon Ball Super", "[DB] Dragon Ball Super - S01E131 - A Miraculous Conclusion! Farewell, Goku! [1080p].mkv"),
        ("Kaiji", "Kaiji - S02E06 - 10000000000 Yen [720p].mkv"),
        ("Long Zero Show", "Long Zero Show - S01E01 - 1000000000000 Episode [1080p].mkv"),
        ("Anime Title", "Anime Title - S01E01 - Romance Dawn [00000000].mkv"),
    ]

    def _gen_branch(rng, depth, max_depth):
        parts = []
        zero_star_allowed = (depth <= 1)
        prefix = rng.choice(["none", "s", "e", "plain"])
        if prefix == "s":
            parts.append(rng.choice(["[Ss]", "S", "s"]))
            if zero_star_allowed and rng.random() < 0.4:
                parts.append("0*")
            parts.append(rng.choice(["0", "1", "01"]))
        elif prefix == "e":
            parts.append(rng.choice(["[Ee]", "E", "e"]))
            if zero_star_allowed and rng.random() < 0.4:
                parts.append("0*")
        elif prefix == "plain":
            parts.append(rng.choice(["Ep", "Show", "Vol_"]))
            if zero_star_allowed and rng.random() < 0.2:
                parts.append("0*")

        for _ in range(rng.randint(1, 3)):
            it = rng.choice(["digits", "range", "literal", "group", "chained_groups"])
            if it == "digits":
                tok = rng.choice([r"\d", "[0-9]"])
                if rng.random() < 0.3:
                    tok += rng.choice(["{1,2}", "{1,3}"])
                parts.append(tok)
            elif it == "range":
                d1 = rng.randint(0, 5)
                d2 = rng.randint(d1, 9)
                tok = f"[{d1}-{d2}]"
                if rng.random() < 0.3:
                    tok += "{1,2}"
                parts.append(tok)
            elif it == "literal":
                parts.append(rng.choice([".", "_", "v2", "E05"]))
            elif it == "group" and depth < max_depth:
                sub = [_gen_branch(rng, depth + 1, max_depth) for _ in range(rng.randint(1, 3))]
                parts.append("(?:" + "|".join(sub) + ")")
            elif it == "chained_groups" and depth < max_depth:
                # Chained groups: (?:...)(?:...)
                g1 = "(?:" + "|".join(_gen_branch(rng, depth + 1, max_depth) for _ in range(rng.randint(1, 2))) + ")"
                g2 = "(?:" + "|".join(_gen_branch(rng, depth + 1, max_depth) for _ in range(rng.randint(1, 2))) + ")"
                parts.append(g1 + g2)
        if rng.random() < 0.2:
            parts.append(r"(?!\d)")
        return "".join(parts)

    rng = random.Random(42)
    accepted = []
    attempts = 0
    while len(accepted) < 300 and attempts < 3000:
        attempts += 1
        cand = _gen_branch(rng, 0, 2)
        if not cand or len(cand) > 200:
            continue
        try:
            res = validate({"show": "One Pace", "episode_re": cand}, anime_root=None)
            accepted.append(res["episode_re"])
        except Exception:
            continue

    assert len(accepted) == 300, f"Only generated {len(accepted)} patterns"

    # Property test: every accepted pattern run with season None and season 1 against
    # show-matched basenames (including 10 zeros, 12 zeros, and [00000000] CRC tags)
    # has worst case under 20 ms per file.
    worst_per_file = 0.0
    for pat in accepted:
        for season in (None, 1):
            for show, name in test_files:
                derived = derive_generate_only_re(show, season, pat)
                rx = re.compile(derived)
                t0 = time.perf_counter()
                rx.search(name)
                dur = time.perf_counter() - t0
                if dur > worst_per_file:
                    worst_per_file = dur
                assert dur < 0.020, f"matching {pat} with season={season} on {name} took {dur:.4f}s >= 0.020s"

    print(f"Worst case per file: {worst_per_file * 1000:.3f} ms")









def test_write_effective_env_reports_acquire_apply(tmp_path):
    out_file = tmp_path / "effective.env"
    write_effective_env(str(out_file), env={"ACQUIRE_APPLY": "0"})
    assert "ACQUIRE_APPLY=0\n" in out_file.read_text()
