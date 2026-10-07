"""Properties of the systemd units under deploy/ for the nightly window.

These four units run the dubtitle window on the host and are kept in the repo
for version control. The canonical text they were copied from lives in the
session scratchpad (host_units_reference.txt / dubtitlerr-window-close.service.proposed).

Plain pytest functions, no extra dependencies.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = REPO_ROOT / "deploy"

CLOSE_SERVICE = DEPLOY / "dubtitlerr-window-close.service"
CLOSE_TIMER = DEPLOY / "dubtitlerr-window-close.timer"
OPEN_SERVICE = DEPLOY / "dubtitlerr-window-open.service"
OPEN_TIMER = DEPLOY / "dubtitlerr-window-open.timer"

# The media mount path hard-coded into the sweep command.
LIBRARY = "/mnt/r520-media-full/Anime Library"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
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


def systemd_unescape(line):
    """Undo the systemd escaping used in these units.

    ``$$`` -> ``$``, ``%%`` -> ``%``, ``\\x27`` -> single quote, ``\\"`` -> double quote. Any
    other backslash escape is a bug in the unit and is asserted against.
    """
    out = line.replace("\\x27", "'").replace('\\"', '"')
    out = out.replace("$$", "$").replace("%%", "%")
    assert "\\" not in out, f"unexpected backslash escape remains: {out!r}"
    return out


def parse_seconds(text):
    """Parse a systemd time span ('900', '25min', '3h', '1h 30min') to seconds."""
    unit_seconds = {
        "us": 1e-6,
        "ms": 1e-3,
        "s": 1,
        "sec": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
    }
    text = text.strip()
    total = 0.0
    for number, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)", text):
        if unit == "":
            total += float(number)
        else:
            assert unit in unit_seconds, f"unknown time unit {unit!r} in {text!r}"
            total += float(number) * unit_seconds[unit]
    return total


def sh_c_script(value):
    """Extract the shell script from an unescaped ``/bin/sh -c ...`` ExecStart."""
    m = re.match(r"^/bin/sh\s+-c\s+(.*)$", value, re.S)
    assert m, f"not an sh -c ExecStart: {value!r}"
    body = m.group(1).strip()
    if body[:1] in ("'", '"'):
        assert body[-1] == body[0], f"unbalanced quoting: {body!r}"
        body = body[1:-1]
    return body


# --------------------------------------------------------------------------- #
# (a) helper smoke test
# --------------------------------------------------------------------------- #
def test_parse_unit_helper_reads_exec_and_keys():
    unit = parse_unit(OPEN_SERVICE)
    assert unit["keys"]["Type"] == "oneshot"
    assert len(unit["exec_start"]) == 1
    assert unit["exec_start"][0]["prefix"] == ""


# --------------------------------------------------------------------------- #
# (b) close.service timing
# --------------------------------------------------------------------------- #
def test_close_service_timeout_exceeds_stop_grace_plus_sweep():
    unit = parse_unit(CLOSE_SERVICE)
    first = unit["exec_start"][0]
    assert first["prefix"] == "", "the first ExecStart must not carry a '-'/'@' prefix"

    m = re.search(r"docker\s+stop\s+-t\s+(\d+)", first["value"])
    assert m, f"no `docker stop -t` in {first['value']!r}"
    stop_grace = int(m.group(1))
    assert stop_grace >= 600, f"docker stop grace {stop_grace}s is below the 600s floor"

    timeout = parse_seconds(unit["keys"]["TimeoutStartSec"])
    assert timeout > stop_grace + 60, (
        f"TimeoutStartSec {timeout}s must exceed stop grace {stop_grace}s + 60s"
    )


# --------------------------------------------------------------------------- #
# (c) no systemd expansions in close.service
# --------------------------------------------------------------------------- #
def test_close_service_escapes_dollars_and_has_no_specifiers():
    unit = parse_unit(CLOSE_SERVICE)
    for entry in unit["exec_start"]:
        value = entry["value"]
        stripped = re.sub(r"\$\$", "", value)
        assert "$" not in stripped, (
            f"a single (expanding) $ remains in ExecStart: {value!r}"
        )


def test_no_unit_has_a_bare_percent_in_exec_start():
    # In a unit file '%' starts a specifier (%n, %i, ...); a literal percent MUST be '%%'
    # (systemd.unit(5)). A bare '%' (even one that looks harmless, like the shell's
    # ${f%.ext}) is an unknown specifier: kept or the whole line rejected, by version.
    for unit_path in (CLOSE_SERVICE, CLOSE_TIMER, OPEN_SERVICE, OPEN_TIMER, DEPLOY / "dubtitlerr-publish.service"):
        for entry in parse_unit(unit_path)["exec_start"]:
            rest = entry["value"].replace("%%", "")
            assert "%" not in rest, f"{unit_path.name}: bare % in ExecStart (write %%): {entry['value']!r}"


# --------------------------------------------------------------------------- #
# (d) unescape helper
# --------------------------------------------------------------------------- #
def test_systemd_unescape():
    assert systemd_unescape("$$c") == "$c"
    assert systemd_unescape("${f%%.ext}") == "${f%.ext}"
    assert systemd_unescape("\\x27quoted\\x27") == "'quoted'"
    assert systemd_unescape('\\"quoted\\"') == '"quoted"'
    # exercising the guard directly
    try:
        systemd_unescape("bad\\n")
    except AssertionError:
        pass
    else:  # pragma: no cover
        raise AssertionError("systemd_unescape should reject unknown escapes")


# --------------------------------------------------------------------------- #
# (e) muxtmp sweep
# --------------------------------------------------------------------------- #
def test_sweep_removes_orphan_muxtmp_and_keeps_recovery(tmp_path):
    unit = parse_unit(CLOSE_SERVICE)
    candidates = [e for e in unit["exec_start"] if "muxtmp" in e["value"]]
    assert len(candidates) == 1, "expected exactly one ExecStart mentioning muxtmp"

    script = sh_c_script(systemd_unescape(candidates[0]["value"]))
    script = script.replace(LIBRARY, str(tmp_path))

    def touch(p):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

    orphan = tmp_path / "Show Name" / "X.muxtmp.mkv"
    kept = tmp_path / "Show [1080p]" / "Y.muxtmp.mkv"
    recovery = tmp_path / "Show [1080p]" / "Y.dubtitles.mux-recovery"
    recovered = tmp_path / "Show {S01}" / "Z.muxtmp.mkv.recovered"
    normal = tmp_path / "Show's" / "Z.mkv"
    for p in (orphan, kept, recovery, recovered, normal):
        touch(p)

    proc = subprocess.run(
        ["sh", "-c", script], shell=False, capture_output=True, text=True
    )
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"

    assert not orphan.exists(), "orphan .muxtmp.mkv should have been removed"
    assert kept.exists(), "a .muxtmp.mkv with a recovery marker must be kept"
    assert recovery.exists(), "the recovery marker itself must survive"
    assert recovered.exists(), ".muxtmp.mkv.recovered must be untouched"
    assert normal.exists(), "a normal episode must be untouched"


# --------------------------------------------------------------------------- #
# (f) soft-exit code check
# --------------------------------------------------------------------------- #
def test_exit_code_check_passes_on_0_and_warns_on_137(tmp_path):
    unit = parse_unit(CLOSE_SERVICE)
    candidates = [e for e in unit["exec_start"] if "docker inspect" in e["value"]]
    assert len(candidates) == 1, "expected exactly one ExecStart mentioning docker inspect"

    stub = tmp_path / "docker"
    stub.write_text('#!/bin/sh\necho "$STUB_DOCKER_EXIT"\n')
    stub.chmod(0o755)

    for code, should_warn in (("0", False), ("137", True)):
        script = sh_c_script(systemd_unescape(candidates[0]["value"]))
        script = script.replace("/usr/bin/docker", str(stub))
        env = dict(os.environ, STUB_DOCKER_EXIT=code)
        proc = subprocess.run(
            ["sh", "-c", script],
            shell=False,
            capture_output=True,
            text=True,
            env=env,
        )
        out = proc.stdout
        assert f"exit code: {code}" in out, out
        if should_warn:
            assert "WARNING" in out, f"expected a WARNING for exit code {code}: {out}"
        else:
            assert "WARNING" not in out, f"unexpected WARNING for exit code {code}: {out}"


# --------------------------------------------------------------------------- #
# (g) timers and open service
# --------------------------------------------------------------------------- #
def test_timers_pinned_to_household_timezone_and_not_persistent():
    for timer in (CLOSE_TIMER, OPEN_TIMER):
        unit = parse_unit(timer)
        assert "America/New_York" in unit["keys"]["OnCalendar"], timer
        assert unit["keys"]["Persistent"] == "false", timer


def test_open_service_starts_the_container():
    unit = parse_unit(OPEN_SERVICE)
    assert len(unit["exec_start"]) == 1
    assert "docker start dubtitle-builder" in unit["exec_start"][0]["value"]
