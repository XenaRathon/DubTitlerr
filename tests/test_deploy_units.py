"""Properties of the systemd units under deploy/.

The nightly window units (`dubtitlerr-window-open`/`-close` and their timers) were
removed in the 1.0 cleanup: the window is now scheduled in the web UI's Runs page,
not on the host. What remains in `deploy/` is the subtitle-publish job, and this
file checks its units.

Plain pytest functions, no extra dependencies.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = REPO_ROOT / "deploy"

PUBLISH_SERVICE = DEPLOY / "dubtitlerr-publish.service"
PUBLISH_TIMER = DEPLOY / "dubtitlerr-publish.timer"


def parse_unit(path):
    """Read a systemd unit file.

    Returns ``{"exec_start": [...], "keys": {...}}`` where each ExecStart entry
    is ``{"prefix": "", "-" or "@", "value": <rest>}`` (the documented prefix
    flag is stripped from ``value`` and remembered) and ``keys`` maps every
    other ``Key=Value`` line to its raw value. Comments and section headers are
    ignored.
    """
    path = Path(path)
    exec_start = []
    keys = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "ExecStart":
            prefix = ""
            if value[:1] in ("-", "@"):
                prefix, value = value[0], value[1:]
            exec_start.append({"prefix": prefix, "value": value})
        else:
            keys[key] = value
    return {"exec_start": exec_start, "keys": keys}


def test_publish_units_have_no_bare_percent_in_exec_start():
    # In a unit file '%' starts a specifier (%n, %i, ...); a literal percent MUST be '%%'
    # (systemd.unit(5)). A bare '%' (even one that looks harmless, like the shell's
    # ${f%.ext}) is an unknown specifier: kept or the whole line rejected, by version.
    for unit_path in (PUBLISH_SERVICE, PUBLISH_TIMER):
        for entry in parse_unit(unit_path)["exec_start"]:
            rest = entry["value"].replace("%%", "")
            assert "%" not in rest, f"{unit_path.name}: bare % in ExecStart (write %%): {entry['value']!r}"


def test_publish_service_uses_image_env_var():
    # We parse the file manually since parse_unit fails on continuation lines
    text = PUBLISH_SERVICE.read_text()

    # Check DUBTITLERR_IMAGE default is set before EnvironmentFile
    env_image = False
    env_file_after = False
    for line in text.splitlines():
        if line.startswith("Environment=DUBTITLERR_IMAGE="):
            env_image = True
        elif line.startswith("EnvironmentFile=-/etc/default/dubtitlerr-publish"):
            if env_image:
                env_file_after = True

    assert env_file_after, "DUBTITLERR_IMAGE default must be set before EnvironmentFile"

    # Extract ExecStart properly
    exec_start = ""
    # Use python string operations to join lines correctly
    raw_lines = text.split('\n')
    joined_lines = []
    current_line = ""
    for line in raw_lines:
        if line.endswith('\\'):
            current_line += line[:-1] + ' '
        else:
            current_line += line
            joined_lines.append(current_line)
            current_line = ""

    for line in joined_lines:
        if line.startswith('ExecStart='):
            exec_start = line.split('=', 1)[1].strip()
            break

    # Remove prefix if present
    if exec_start.startswith('-') or exec_start.startswith('@'):
        exec_start = exec_start[1:].strip()

    # Assert image is ${DUBTITLERR_IMAGE}
    assert "${DUBTITLERR_IMAGE}" in exec_start, f"ExecStart must use ${{DUBTITLERR_IMAGE}}, got {exec_start}"
    assert "dubtitle-builder:0.1.0" not in exec_start, "ExecStart must not use hardcoded dubtitle-builder:0.1.0"

    # Assert no -v ...:/app mount remains
    assert ":/app" not in exec_start, "ExecStart must not contain the /app bind mount"
    assert "APP_DIR=/app" not in exec_start, "ExecStart must not contain the APP_DIR=/app env var"

    # Assert GITHUB_PAT never appears with =
    assert "GITHUB_PAT=" not in exec_start, "GITHUB_PAT token must not appear with = in docker run arguments"
