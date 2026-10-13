"""gen_loop.sh must pass the container's REQUIRE_ENG through to generate.py (default 1).

It used to hardcode REQUIRE_ENG=1 in the call's env prefix, so compose.yaml's value was
ignored. Runs the real script against a stub APP_DIR whose generate.py records the env it got
and touches the stop flag, so the loop exits 0 after one pass."""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

STUB_GENERATE = """\
import os, pathlib
pathlib.Path(os.environ["RECORD"]).write_text(os.environ.get("REQUIRE_ENG", "<unset>"))
pathlib.Path(os.environ["STOP_FLAG"]).touch()
"""


def _run_gen_loop(tmp_path, require_eng):
    app = tmp_path / "app"
    (app / "shell").mkdir(parents=True)
    shutil.copy(REPO / "shell" / "lib.sh", app / "shell" / "lib.sh")
    (app / "generate.py").write_text(STUB_GENERATE)
    (app / "mine_glossary.py").write_text("")
    anime = tmp_path / "anime"
    (anime / "Show").mkdir(parents=True)
    order = tmp_path / "order.txt"
    order.write_text("Show\n")
    record = tmp_path / "record"
    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_ENG", "WATCH_QUEUE_WINDOW_DAYS")}
    env.update(
        APP_DIR=str(app),
        ANIME_ROOT=str(anime),
        ANIME_ORDER=str(order),
        GLOSSARY_DIR=str(tmp_path / "gloss"),
        STOP_FLAG=str(tmp_path / "stop"),
        RECORD=str(record),
        RESCAN_INTERVAL="0",
    )
    if require_eng is not None:
        env["REQUIRE_ENG"] = require_eng
    proc = subprocess.run(["sh", str(REPO / "gen_loop.sh")], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return record.read_text()


def test_require_eng_from_environment_reaches_generate(tmp_path):
    assert _run_gen_loop(tmp_path, "0") == "0"


def test_require_eng_defaults_to_one(tmp_path):
    assert _run_gen_loop(tmp_path, None) == "1"
