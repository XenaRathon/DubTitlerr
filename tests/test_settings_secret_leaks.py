"""[S-7] A saved secret is write-only: after a Plex token is saved, the string appears in no response body, no log line and
neither effective.env report. (Task 11 extends this to a Connection's API key.)"""

import json
import os
import subprocess
import sys

import pytest

import review_auth
import review_requests
import review_server as rs
import settings_api as api

TOKEN = "plex-tok-7f3a91c2d8e54b60"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name, value in {
        "REVIEW_AUTH": "off",
        "CONFIG_DIR": str(tmp_path),
        "EFFECTIVE_ENV_FILE": str(tmp_path / "effective.env"),
        "REQUESTS_DIR": str(tmp_path / "requests"),
        "SCHEDULE_FILE": str(tmp_path / "schedule.json"),
        "ANIME_ROOT": str(tmp_path / "media"),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(api, "_secrets_writable", lambda: True)
    return {k: os.environ[k] for k in ("CONFIG_DIR", "EFFECTIVE_ENV_FILE")}


def exported_environment(scope, tmp_path):
    out = subprocess.run(
        [sys.executable, os.path.join(REPO, "review_settings_write.py"), "export", "--scope", scope, "--plain"],
        env={**os.environ, "CONFIG_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_a_saved_token_appears_in_no_response_log_or_report(env, tmp_path, capsys):
    _, cur = api.handle("GET", "/api/settings", None, environ=env)
    rev = cur["revision"]
    status, payload = api.handle(
        "PUT",
        "/api/settings",
        {"revision": rev, "values": {"PLEX_TOKEN": TOKEN, "WHISPER_BEAM_SIZE": 5}},
        environ=env,
    )
    assert status == 200, payload
    bodies = [json.dumps(payload)]

    # sends a rejected secret (TOKEN + "\n") asserting the 400 does not echo it
    bad_status, bad_payload = api.handle(
        "PUT",
        "/api/settings",
        {"revision": payload["revision"], "values": {"PLEX_TOKEN": TOKEN + "\n"}},
        environ=env,
    )
    assert bad_status == 400
    assert TOKEN not in json.dumps(bad_payload)
    bodies.append(json.dumps(bad_payload))

    calls = [
        ("GET", "/api/settings/schema", None),
        ("GET", "/api/settings", None),
        ("POST", "/api/settings/reset", {"keys": ["MINE_MIN_COUNT"]}),
    ]
    for method, path, call_body in calls:
        bodies.append(json.dumps(api.handle(method, path, call_body, environ=env)[1]))

    # walks every GET in review_auth.ROUTE_ROLES
    for method, path in review_auth.ROUTE_ROLES:
        if method == "GET":
            res = rs.route("GET", path, {}, None)
            if isinstance(res, tuple) and len(res) >= 2:
                body = res[1].decode("utf-8", "replace") if isinstance(res[1], bytes) else json.dumps(res[1], default=str)
                bodies.append(body)

    reports = []
    for scope in ("gen", "merge"):
        path = tmp_path / f"{scope}-effective.env"
        review_requests.write_effective_env(str(path), env=exported_environment(scope, tmp_path))
        reports.append(path.read_text())
    assert all("WHISPER_BEAM_SIZE=5" in r for r in reports), "the report is not empty: the secret was filtered, not missing"

    captured = capsys.readouterr()
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err

    for text in [*bodies, captured.out, captured.err, *reports]:
        assert TOKEN not in text
