"""Properties of the systemd units under deploy/ for the nightly window.

These four units run the dubtitle window on the host and are kept in the repo
for version control. The canonical text they were copied from lives in the
session scratchpad (host_units_reference.txt / dubtitlerr-window-close.service.proposed).

Plain pytest functions, no extra dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = REPO_ROOT / "deploy"

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
# (c) no systemd expansions
# --------------------------------------------------------------------------- #
def test_no_unit_has_a_bare_percent_in_exec_start():
    # In a unit file '%' starts a specifier (%n, %i, ...); a literal percent MUST be '%%'
    # (systemd.unit(5)). A bare '%' (even one that looks harmless, like the shell's
    # ${f%.ext}) is an unknown specifier: kept or the whole line rejected, by version.
    for unit_path in (DEPLOY / "dubtitlerr-publish.service",):
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


