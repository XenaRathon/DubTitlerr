"""merge_pass.sh applies the stored settings (settings.json / secrets.json) at the start of EVERY pass, through the safe
exporter -- never by `source`, and whether or not an old runtime.env exists.

The harness runs the real script against a copy-by-symlink of the app dir whose repair.py is a stub that records the
environment it was started with, so the test sees exactly what a repair run would have seen."""

import json
import os
import stat
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHED = (
    "REPAIR_UNANCHORED",
    "WHISPER_BEAM_SIZE",
    "REQUIRE_ENG",
    "WATCH_QUEUE_PIN",
    "PLEX_TOKEN",
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

    def run(extra_env=None, values=None, secrets=None, raw=None, app_dir=None):
        if raw is not None:
            (config / "settings.json").write_text(raw)
        elif values is not None:
            (config / "settings.json").write_text(json.dumps({"version": 1, "rev": 1, "values": values}))
        if secrets is not None:
            (config / "secrets.json").write_text(json.dumps({"version": 1, "values": secrets, "connections": {}}))
            os.chmod(config / "secrets.json", 0o600)
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


def test_stored_values_win_over_the_container_environment(harness):
    seen, res = harness(
        {"REPAIR_UNANCHORED": "0", "WHISPER_BEAM_SIZE": "7", "REQUIRE_ENG": "1"},
        values={"REPAIR_UNANCHORED": True, "WHISPER_BEAM_SIZE": 5},
    )
    assert seen is not None, res.stdout + res.stderr
    assert (seen["REPAIR_UNANCHORED"], seen["WHISPER_BEAM_SIZE"], seen["REQUIRE_ENG"]) == ("1", "5", "1")


def test_without_a_store_the_container_environment_stands(harness):
    seen, res = harness({"WHISPER_BEAM_SIZE": "7"})
    assert seen is not None, res.stdout + res.stderr
    assert seen["WHISPER_BEAM_SIZE"] == "7"


def test_a_saved_value_still_reaches_the_pass_after_runtime_env_was_migrated_away(harness):
    (harness.config / "runtime.env.migrated").write_text("REPAIR_MODEL=old\n")
    assert not (harness.config / "runtime.env").exists()
    seen, res = harness(values={"WHISPER_BEAM_SIZE": 5}, secrets={"PLEX_TOKEN": "tok-merge"})
    assert seen["WHISPER_BEAM_SIZE"] == "5" and seen["PLEX_TOKEN"] == "tok-merge", res.stdout + res.stderr


def test_every_pass_rereads_the_files(harness):
    first, _ = harness(values={"WHISPER_BEAM_SIZE": 4})
    second, _ = harness(values={"WHISPER_BEAM_SIZE": 6})
    assert (first["WHISPER_BEAM_SIZE"], second["WHISPER_BEAM_SIZE"]) == ("4", "6")


def test_a_reset_gives_the_next_pass_the_container_value_again(harness):
    harness({"WHISPER_BEAM_SIZE": "7"}, values={"WHISPER_BEAM_SIZE": 5})
    (harness.config / "settings.json").unlink()
    seen, _ = harness({"WHISPER_BEAM_SIZE": "7"})
    assert seen["WHISPER_BEAM_SIZE"] == "7"
    assert read_env_file(harness.config / "merge-effective.env")["WHISPER_BEAM_SIZE"] == "7"


def test_a_hostile_settings_file_is_never_executed(harness):
    raw = json.dumps(
        {
            "version": 1,
            "values": {
                "WATCH_QUEUE_PIN": "$(touch MARKER_ONE); `touch MARKER_TWO`",
                "LD_PRELOAD": "/tmp/evil.so",
                "MARK": "changed",
                "WHISPER_BEAM_SIZE": "5; touch MARKER_THREE",
            },
        }
    )
    seen, res = harness({"WHISPER_BEAM_SIZE": "7"}, raw=raw)
    assert seen is not None, res.stdout + res.stderr
    assert seen["WATCH_QUEUE_PIN"] == "$(touch MARKER_ONE); `touch MARKER_TWO`"
    assert seen["WHISPER_BEAM_SIZE"] == "7" and seen["MARK"] == "untouched" and seen["LD_PRELOAD"] in (None, "")
    for marker in ("MARKER_ONE", "MARKER_TWO", "MARKER_THREE"):
        assert not os.path.exists(os.path.join(harness.tmp, "library", marker)) and not os.path.exists(marker)


def test_a_missing_exporter_does_not_stop_the_pass(harness):
    (harness.app / "review_settings_write.py").unlink()
    seen, res = harness({"WHISPER_BEAM_SIZE": "7"}, values={"WHISPER_BEAM_SIZE": 5})
    assert seen is not None, res.stdout + res.stderr
    assert seen["WHISPER_BEAM_SIZE"] == "7", "fails open to the container environment"


def test_the_script_runs_the_exporter_unconditionally_and_never_sources_a_settings_file():
    code = [ln for ln in open(os.path.join(REPO, "merge_pass.sh")).read().splitlines() if not ln.lstrip().startswith("#")]
    assert not [
        ln
        for ln in code
        if ("settings.json" in ln or "runtime.env" in ln) and ("source" in ln or ". " in ln.split("settings")[0])
    ]
    guard = [ln for ln in code if "review_settings_write.py" in ln and ln.lstrip().startswith("if [")]
    assert guard and "runtime.env" not in guard[0] and "settings.json" not in guard[0]
    assert any("export --scope merge" in ln for ln in code)


# --- the pass reports what it runs with (merge-effective.env) and no longer hides the exporter's complaints --------------


def read_env_file(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def test_the_pass_writes_its_own_effective_file_with_the_applied_values(harness):
    seen, res = harness(
        {"WHISPER_BEAM_SIZE": "7"},
        values={"WHISPER_BEAM_SIZE": 5, "REPAIR_UNANCHORED": True},
        secrets={"PLEX_TOKEN": "tok-merge"},
    )
    assert seen is not None, res.stdout + res.stderr
    report = read_env_file(harness.config / "merge-effective.env")
    assert report["WHISPER_BEAM_SIZE"] == "5" and report["REPAIR_UNANCHORED"] == "1"
    assert "PLEX_TOKEN" not in report


def test_the_merge_report_never_touches_the_generate_loops_effective_file(harness):
    (harness.config / "effective.env").write_text("WHISPER_BEAM_SIZE=the-generate-loops-view\n")
    harness({"WHISPER_BEAM_SIZE": "7"}, values={"WHISPER_BEAM_SIZE": 5})
    assert (harness.config / "effective.env").read_text() == "WHISPER_BEAM_SIZE=the-generate-loops-view\n"


def test_a_missing_config_directory_is_not_an_error_and_nothing_is_written_there(harness, tmp_path):
    seen, res = harness({"CONFIG_DIR": str(tmp_path / "no-such-config")})
    assert seen is not None, res.stdout + res.stderr
    assert not (tmp_path / "no-such-config").exists()


def test_the_exporters_complaint_reaches_the_passes_stderr(harness):
    seen, res = harness({"WHISPER_BEAM_SIZE": "7"}, raw="{nope")
    assert seen["WHISPER_BEAM_SIZE"] == "7"
    assert "review_settings_write: ignored:" in res.stderr and "not valid JSON" in res.stderr


def test_a_hostile_key_in_settings_json_creates_no_file_through_merge_pass(harness):
    """Script-level: the key is not a registry name, so it never reaches the shell; nothing it spells out is executed."""
    hostile = "x; touch PWNED; #"
    raw = json.dumps({"version": 1, "values": {hostile: "v", "WHISPER_BEAM_SIZE": 5}})
    secrets = {hostile: "s"}
    seen, res = harness({"WHISPER_BEAM_SIZE": "7"}, raw=raw, secrets=secrets)
    assert seen is not None, res.stdout + res.stderr
    assert seen["WHISPER_BEAM_SIZE"] == "5"
    root = harness.tmp / "library"
    for place in (root, harness.config, harness.app, harness.tmp, harness.tmp / "fakebin"):
        assert not (place / "PWNED").exists()
    assert not os.path.exists("PWNED")
