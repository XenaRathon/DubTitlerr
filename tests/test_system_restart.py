"""[S-12] POST /api/system/restart writes the soft-stop flag; the loops finish the episode in flight and exit 0; /api/status
carries a boot_id that changes on every container start."""

import os
import re
import subprocess
import time

import common
import review_status
import settings_api as api

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_restart_writes_the_stop_flag_and_answers_202_with_the_current_boot_id(tmp_path, monkeypatch):
    flag = tmp_path / "stop"
    monkeypatch.setenv("DT_CONTAINER_BOOT_ID", "boot-one")
    status, payload = api.handle("POST", "/api/system/restart", {}, environ={"STOP_FLAG": str(flag)})
    assert (status, payload) == (202, {"ok": True, "boot_id": "boot-one"}) and flag.exists()
    assert api.handle("POST", "/api/system/restart", {}, environ={"STOP_FLAG": str(flag)})[0] == 202, "asking twice is harmless"


def test_an_unwritable_flag_is_a_500_that_names_only_the_error_class(tmp_path):
    status, payload = api.handle("POST", "/api/system/restart", {}, environ={"STOP_FLAG": str(tmp_path / "no-dir" / "stop")})
    assert status == 500 and "FileNotFoundError" in payload["error"] and str(tmp_path) not in payload["error"]


def test_restart_is_an_admin_route():
    assert api.ROLE_ENTRIES[("POST", "/api/system/restart")] == "admin"


def test_boot_id_is_the_container_start_id_or_a_stable_per_process_fallback(monkeypatch):
    monkeypatch.setenv("DT_CONTAINER_BOOT_ID", "abc")
    assert common.boot_id() == "abc"
    monkeypatch.delenv("DT_CONTAINER_BOOT_ID")
    assert common.boot_id() == common.boot_id() and len(common.boot_id()) == 32


def test_status_carries_the_boot_id_even_while_the_cache_warms(monkeypatch):
    monkeypatch.setenv("DT_CONTAINER_BOOT_ID", "boot-two")
    status, payload = review_status.handle("GET", "/api/status", stems_cache=None)
    assert status == 503 and payload["boot_id"] == "boot-two"
    status, payload = review_status.handle("GET", "/api/status", {}, stems_cache=(0, [], 0.0), now=1.0)
    assert status == 200 and payload["boot_id"] == "boot-two"


def test_container_run_exports_one_boot_id_before_it_starts_any_child():
    """The id is named DT_CONTAINER_BOOT_ID, not DT_BOOT_ID: the DT_BOOT_<KEY> prefix is the exporter's, and a setting called ID
    would collide with it."""
    text = open(os.path.join(REPO, "container_run.sh")).read()
    assert text.index("export DT_CONTAINER_BOOT_ID") < text.index("# merge loop in the background")
    lines = [
        ln for ln in text.splitlines() if ln.startswith("DT_CONTAINER_BOOT_ID=") or ln.startswith("export DT_CONTAINER_BOOT_ID")
    ]
    ids = {
        subprocess.run(
            ["sh", "-c", "\n".join(lines) + '\necho "$DT_CONTAINER_BOOT_ID"'], capture_output=True, text=True
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(ids) == 2 and all(re.fullmatch(r"[0-9a-f-]{36}|\d+", i) for i in ids)


def test_a_restart_request_ends_the_whole_container_script_with_exit_0_after_the_work_in_flight(tmp_path):
    """GUARD, not a red-first test: the soft stop already works in today's container_run.sh, so this passes before any change in
    this task. It pins that the restart request keeps ending the container cleanly.

    The real container_run.sh runs over stub loops: the generate loop finishes its 'episode' once the flag exists, the merge
    loop is allowed to finish, the supervisor prints 'soft stop complete' and exits 0 (the restart policy then restarts it)."""
    app = tmp_path / "app"
    (app / "shell").mkdir(parents=True)
    os.symlink(os.path.join(REPO, "shell", "lib.sh"), app / "shell" / "lib.sh")
    gen_loop = (
        "#!/bin/sh\n"
        '. "$APP_DIR/shell/lib.sh"\n'
        'touch "$TMP_DIR/gen-started"\n'
        "while ! stop_requested; do sleep 0.2; done\n"
        "sleep 1\n"
        'touch "$TMP_DIR/gen-finished"\n'
        "exit 0\n"
    )
    (app / "gen_loop.sh").write_text(gen_loop)
    (app / "merge_pass.sh").write_text("#!/bin/sh\nexit 0\n")
    (app / "review_server.py").write_text("import time\ntime.sleep(8)\n")
    flag = tmp_path / "stop"
    env = {
        **os.environ,
        "APP_DIR": str(app),
        "STOP_FLAG": str(flag),
        "TMP_DIR": str(tmp_path),
        "MERGE_INTERVAL": "1",
        "CONFIG_DIR": str(tmp_path),
    }
    proc = subprocess.Popen(
        ["sh", os.path.join(REPO, "container_run.sh")], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        deadline = time.time() + 20
        while not (tmp_path / "gen-started").exists() and time.time() < deadline:
            time.sleep(0.1)
        assert (tmp_path / "gen-started").exists()
        assert api.handle("POST", "/api/system/restart", {}, environ=env)[0] == 202
        out, _ = proc.communicate(timeout=40)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0 and "soft stop complete" in out and (tmp_path / "gen-finished").exists()


def test_the_boot_id_name_cannot_collide_with_the_exporters_boot_copies():
    text = open(os.path.join(REPO, "container_run.sh")).read()
    assert "DT_BOOT_ID" not in text and "DT_CONTAINER_BOOT_ID" in text
    assert "DT_BOOT_ID" not in open(os.path.join(REPO, "common.py")).read()


def test_the_healthcheck_follows_review_port():
    body = open(os.path.join(REPO, "Dockerfile.builder")).read()
    line = next(ln for ln in body.splitlines() if ln.startswith("HEALTHCHECK"))
    assert "REVIEW_PORT" in line and "8842" in line and "/healthz" in line, "port from REVIEW_PORT, 8842 only as the default"
    assert "127.0.0.1:8842" not in line


def test_the_port_help_says_the_compose_mapping_must_match():
    import settings_registry as reg

    help_text = reg.REGISTRY["REVIEW_PORT"]["help"]
    assert "compose" in help_text.lower() and "port mapping" in help_text.lower()


def test_the_server_routes_restart_through_the_settings_api_and_names_the_principal(tmp_path, monkeypatch, capsys):
    import review_auth
    import review_server as rs

    flag = tmp_path / "stop"
    monkeypatch.setenv("STOP_FLAG", str(flag))
    monkeypatch.setenv("DT_CONTAINER_BOOT_ID", "boot-route")
    principal = review_auth.Principal("session", "alice", "admin")
    decision = review_auth.Decision("admin", None, "", "admin", True, principal)
    monkeypatch.setattr(review_auth, "decide", lambda *a, **k: decision)
    status, payload = rs.route("POST", "/api/system/restart", {}, None)
    assert (status, payload) == (202, {"ok": True, "boot_id": "boot-route"}) and flag.exists()
    assert "restart requested by session:alice" in capsys.readouterr().out
