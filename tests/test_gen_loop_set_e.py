"""Regression for the 2026-09-05 vm102 finding: a standalone `timeout ...; rc=$?`
under `set -e` exits the shell with 124 the moment the timeout fires, instead of
running the rc-classified "verify TIMED OUT ... (continuing)" message that was
already written to handle exactly that case.

gen_loop.sh runs as PID 1 inside dubtitle-builder, so a 124 from set -e takes
the container down. Every container restart in the 14h ending 2026-09-05
14:00 EDT journal-confirmed exited with code 124, with VERIFY_TIMEOUT (1200s)
firing on One Pace (the WATCH_QUEUE_PIN show, run first) within ~2s of every
measured exit. The fix wraps the verify timeout in `&& rc=0 || rc=$?` so the
compound's last subcommand is always 0 and `set -e` cannot trip on the
timeout's 124.

This test parses gen_loop.sh and asserts every `timeout` invocation is wrapped
in a way that prevents `set -e` from terminating the shell. The intent is to
catch a future reader "tidying up" the asymmetry between the ACQUIRE call
(guarded with `|| echo ...`) and the VERIFY call (guarded with
`&& rc=0 || rc=$?`) by removing one of the guards and reintroducing the bug.
"""

import re
from pathlib import Path


GEN_LOOP = Path(__file__).resolve().parent.parent / "gen_loop.sh"


def _read():
    return GEN_LOOP.read_text()


def _logical_statements(src):
    """Yield (lineno, statement_text) for every `timeout` invocation.

    Each statement joins `\\`-continued lines into one logical command so
    multi-line timeouts (the ACQUIRE call at line 64 spans 4 lines) are
    treated as one unit. The line continuations are exactly what makes the
    naive "is the line protected?" check miss the ACQUIRE case.
    """
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("timeout "):
            start = i
            buf = [lines[i]]
            i += 1
            while i < len(lines) and buf[-1].rstrip().endswith("\\"):
                buf.append(lines[i])
                i += 1
            yield start + 1, "\n".join(buf)
        else:
            i += 1


def _is_protected(stmt):
    """Return True if this `timeout` is wrapped against `set -e`.

    Two protection shapes are accepted (both keep the last subcommand of
    the compound at exit status 0 so `set -e` cannot trip on the timeout's
    124):

    1. `&& rc=0 || rc=$?` anywhere in the joined statement -- the
       generate.py-style fix applied on 2026-09-05 to the verify block.
    2. A bare `||` (not part of a `&& ... || ...` chain) on a line in the
       joined statement, with a fallback command -- e.g. the ACQUIRE call
       uses `|| echo "  acquire skipped (continuing)"`.

    A bare `timeout ...</dev/null 2>&1` whose exit is captured by a NEXT
    *statement*'s `rc=$?` does NOT count: under `set -e`, the timeout's
    124 fires before the next statement runs.
    """
    if "&& rc=0 || rc=$?" in stmt:
        return True
    for line in stmt.splitlines():
        # skip lines whose `||` is the right half of a `&& ... || ...` chain
        # (already matched by the substring check above, but be explicit)
        if re.search(r"&&.*\|\|", line):
            continue
        if re.search(r"\|\|", line):
            return True
    return False


def test_set_e_is_active():
    """If set -e is missing, this whole test class is moot."""
    src = _read()
    assert re.search(r"^set -e(\s|$)", src, re.MULTILINE), (
        "gen_loop.sh no longer has `set -e` at the top of the file; the "
        "tests below assume set -e is active and are therefore meaningless."
    )


def test_no_unprotected_standalone_timeout():
    """Every `timeout` invocation must be wrapped.

    Under `set -e`, a `timeout` whose exit status is not absorbed into a
    compound (by `&& rc=0 || rc=$?` or by a trailing `|| <fallback>`)
    will fire `set -e` and take the shell down with code 124 -- and PID 1
    is gen_loop.sh, so the container exits with 124 too.
    """
    src = _read()
    unprotected = [
        (i, s) for i, s in _logical_statements(src) if not _is_protected(s)
    ]
    assert not unprotected, (
        "Unprotected `timeout` in gen_loop.sh -- under set -e, the "
        "timeout's 124 will fire before the next line runs and take the "
        "container down. Wrap with `&& rc=0 || rc=$?` (matches generate.py "
        "line 96) or `|| echo \"...\"` (matches the ACQUIRE call at line 64):\n"
        + "\n".join(f"  line {i}:\n{s}\n" for i, s in unprotected)
    )


def test_timeout_pattern_does_not_silently_swallow_real_failures():
    """Every wrapped timeout is followed by a 124-classified check OR uses
    a one-shot `|| <echo-style>` fallback that already swallows the 124.

    Two acceptable shapes:
    1. `&& rc=0 || rc=$?` followed by `[ -eq 124 ]` (verify block). The rc
       is captured and the message distinguishes timeout from other
       failures. Collapsing the two is the silent-skip failure mode the
       original verify-block comment called out.
    2. `|| echo "..."` (ACQUIRE block). The fallback is one shot and does
       not need a `[ -eq 124 ]` branch; any 124 swallows into the echo
       and the loop continues.

    A `&& rc=0 || rc=$?` chain that LACKS a `[ -eq 124 ]` check is the
    failure mode this test exists to catch.
    """
    src = _read()
    src_lines = src.splitlines()
    for i, stmt in _logical_statements(src):
        if not _is_protected(stmt):
            continue
        # `&& rc=0 || rc=$?` shape: requires an rc-classified check below.
        if "&& rc=0 || rc=$?" in stmt:
            following = "\n".join(src_lines[i : i + 6])
            assert ("-eq 124" in following) or ("124)" in following), (
                f"line {i}: `&& rc=0 || rc=$?` is the rc-classified shape; "
                f"the next 6 lines must distinguish a 124 timeout from "
                f"other failures. A future simplification could collapse "
                f"them and reintroduce the silent-skip failure mode.\n"
                f"Following lines:\n{following}"
            )