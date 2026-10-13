"""merge_pass.sh applies /config/runtime.env at the start of EVERY pass, through the safe exporter -- never by `source`.

The harness runs the real script against a copy-by-symlink of the app dir whose repair.py is a stub that records the
environment it was started with, so the test sees exactly what a repair run would have seen."""

import json
import os
import stat
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = {"local": {"backend": "llamacpp", "url": "http://host.docker.internal:8090/v1/chat/completions"}}
WATCHED = (
    "REPAIR_MODEL",
    "REPAIR_BACKEND",
    "REPAIR_LLAMACPP_URL",
    "REQUIRE_ENG",
    "VERIFY_BACKEND",
    "VERIFY_DECISION_MODEL",
    "LD_PRELOAD",
    "MARK",
)

STUB_REPAIR = """\
import json, os, sys
keys = %r
open(os.environ["DUMP"], "w").write(json.dumps({k: os.environ.get(k) for k in keys}))
"""


@pytest.fixture
def harness(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    for name in os.listdir(REPO):
        if name.endswith(".py") and name != "repair.py":
            os.symlink(os.path.join(REPO, name), app / name)
    for sub in ("shell", "data"):
        os.symlink(os.path.join(REPO, sub), app / sub)
    (app / "repair.py").write_text(STUB_REPAIR % (WATCHED,))
    config = tmp_path / "config"
    config.mkdir()
    root = tmp_path / "library"
    (root / "Show").mkdir(parents=True)
    (root / "Show" / "ep01.eng.dubtitles.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    for tool in ("ffmpeg", "mkvmerge"):
        p = bindir / tool
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    def run(extra_env=None, runtime=None, app_dir=None):
        if runtime is not None:
            (config / "runtime.env").write_text(runtime)
        dump = tmp_path / "dump.json"
        if dump.exists():
            dump.unlink()
        env = {k: v for k, v in os.environ.items() if k not in WATCHED}
        env.update(
            PATH=f"{bindir}{os.pathsep}{env['PATH']}",
            MERGE_ROOTS=str(root),
            APP_DIR=str(app_dir or app),
            CONFIG_DIR=str(config),
            DUMP=str(dump),
            REPAIR_PROFILES=json.dumps(PROFILES),
            RUNTIME_VERIFY_BACKENDS="llamacpp,ollama,openai,decision",
            MARK="untouched",
        )
        env.update(extra_env or {})
        res = subprocess.run(
            ["/bin/sh", os.path.join(REPO, "merge_pass.sh")], env=env, cwd=str(root), capture_output=True, text=True, timeout=120
        )
        seen = json.loads(dump.read_text()) if dump.exists() else None
        return seen, res

    run.config = config
    run.app = app
    run.tmp = tmp_path
    return run


def test_runtime_values_win_over_the_container_environment(harness):
    seen, res = harness(
        {"REPAIR_MODEL": "from-container", "REPAIR_BACKEND": "container-backend", "REQUIRE_ENG": "1"},
        runtime="REPAIR_MODEL=from-runtime\nREQUIRE_ENG=0\nREPAIR_PROFILE=local\nVERIFY_BACKEND=openai\n",
    )
    assert seen is not None, res.stdout + res.stderr
    assert seen["REPAIR_MODEL"] == "from-runtime"
    assert seen["REQUIRE_ENG"] == "0"
    assert seen["REPAIR_BACKEND"] == "llamacpp"
    assert seen["REPAIR_LLAMACPP_URL"] == PROFILES["local"]["url"]
    assert seen["VERIFY_BACKEND"] == "openai"


def test_without_a_runtime_file_the_container_environment_stands(harness):
    seen, res = harness({"REPAIR_MODEL": "from-container", "REQUIRE_ENG": "1"})
    assert seen is not None, res.stdout + res.stderr
    assert seen["REPAIR_MODEL"] == "from-container" and seen["REQUIRE_ENG"] == "1"


def test_keys_missing_from_the_runtime_file_keep_the_container_value(harness):
    seen, _ = harness({"REPAIR_MODEL": "from-container", "VERIFY_BACKEND": "decision"}, runtime="REQUIRE_ENG=0\n")
    assert seen["REPAIR_MODEL"] == "from-container" and seen["VERIFY_BACKEND"] == "decision"
    assert seen["REQUIRE_ENG"] == "0"


def test_every_pass_rereads_the_file(harness):
    first, _ = harness(runtime="REPAIR_MODEL=model-one\n")
    second, _ = harness(runtime="REPAIR_MODEL=model-two\n")
    assert (first["REPAIR_MODEL"], second["REPAIR_MODEL"]) == ("model-one", "model-two")


def test_a_hostile_runtime_file_is_never_executed(harness):
    hostile = (
        "REPAIR_MODEL=$(touch MARKER_ONE)\n"
        "REPAIR_MODEL=`touch MARKER_TWO`\n"
        "VERIFY_DECISION_MODEL=a;touch MARKER_THREE\n"
        "touch MARKER_FOUR\n"
        "LD_PRELOAD=/tmp/evil.so\n"
        "MARK=changed\n"
        "REPAIR_MODEL=fine-model\n"
    )
    seen, res = harness({"REPAIR_MODEL": "from-container"}, runtime=hostile)
    assert seen is not None, res.stdout + res.stderr
    assert seen["REPAIR_MODEL"] == "fine-model"
    assert seen["LD_PRELOAD"] is None or seen["LD_PRELOAD"] == ""
    assert seen["MARK"] == "untouched" and seen["VERIFY_DECISION_MODEL"] is None
    for marker in ("MARKER_ONE", "MARKER_TWO", "MARKER_THREE", "MARKER_FOUR"):
        assert not os.path.exists(os.path.join(harness.tmp, "library", marker))
        assert not os.path.exists(marker)


def test_a_missing_exporter_does_not_stop_the_pass(harness):
    (harness.app / "review_settings_write.py").unlink()
    seen, res = harness({"REPAIR_MODEL": "from-container"}, runtime="REPAIR_MODEL=from-runtime\n")
    assert seen is not None, res.stdout + res.stderr
    assert seen["REPAIR_MODEL"] == "from-container", "fails open to the container environment"


def test_the_script_never_sources_the_file():
    text = open(os.path.join(REPO, "merge_pass.sh")).read()
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code if "runtime.env" in ln and (". " in ln.split("runtime.env")[0] or "source" in ln)]
    assert any("review_settings_write.py" in ln and "export" in ln for ln in code)


# --- the pass reports what it runs with (merge-effective.env) and no longer hides the exporter's complaints --------------


def read_env_file(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def test_the_pass_writes_its_own_effective_file_with_the_applied_values(harness):
    seen, res = harness(
        {"REPAIR_MODEL": "from-container", "VERIFY_BACKEND": "llamacpp"},
        runtime="REPAIR_MODEL=from-runtime\nREPAIR_PROFILE=local\n",
    )
    assert seen is not None, res.stdout + res.stderr
    report = read_env_file(harness.config / "merge-effective.env")
    assert report["REPAIR_MODEL"] == "from-runtime"
    assert report["REPAIR_BACKEND"] == "llamacpp"
    assert report["REPAIR_LLAMACPP_URL"] == PROFILES["local"]["url"]


def test_the_merge_report_never_touches_the_generate_loops_effective_file(harness):
    (harness.config / "effective.env").write_text("REPAIR_MODEL=the-generate-loops-view\n")
    harness({"REPAIR_MODEL": "from-container"}, runtime="REPAIR_MODEL=from-runtime\n")
    assert (harness.config / "effective.env").read_text() == "REPAIR_MODEL=the-generate-loops-view\n"


def test_after_a_reset_the_next_pass_reports_the_container_values_again(harness):
    harness({"REPAIR_MODEL": "from-container"}, runtime="REPAIR_MODEL=from-runtime\n")
    (harness.config / "runtime.env").unlink()
    harness({"REPAIR_MODEL": "from-container"})
    assert read_env_file(harness.config / "merge-effective.env")["REPAIR_MODEL"] == "from-container"


def test_a_missing_config_directory_is_not_an_error_and_nothing_is_written_there(harness, tmp_path):
    seen, res = harness({"CONFIG_DIR": str(tmp_path / "no-such-config")})
    assert seen is not None, res.stdout + res.stderr
    assert not (tmp_path / "no-such-config").exists()


def test_the_exporters_complaint_reaches_the_passes_stderr(harness):
    seen, res = harness(runtime="REPAIR_MODEL=bad model\nREPAIR_MODEL=ok-model\n")
    assert seen["REPAIR_MODEL"] == "ok-model"
    assert "review_settings_write: ignored:" in res.stderr and "1 invalid line" in res.stderr


def test_merge_pass_uses_the_default_scope_so_the_profile_applies(harness):
    seen, _ = harness(runtime="REPAIR_PROFILE=local\n")
    assert seen["REPAIR_BACKEND"] == "llamacpp" and seen["REPAIR_LLAMACPP_URL"] == PROFILES["local"]["url"]
