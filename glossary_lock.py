"""One advisory lock per glossary file, so overlapping stages cannot lose each other's updates.

Every stage that rewrites a glossary (verify, tag_arcs, acquire --apply, mine_glossary, the --review / --revert CLIs) reads the
JSON, does slow network or LLM work and writes the whole file back. Two overlapping runs (a manual run during the nightly pass)
silently lost one side's changes. ``locked(path, stage)`` takes ``<glossary>.lock`` with flock(LOCK_EX | LOCK_NB), retrying for a
short wait (GLOSSARY_LOCK_WAIT seconds, default 5); if it stays busy it yields False after logging
'glossary busy: <stage> skipped', and the caller returns without touching the file, exit code 0, so the nightly loop never wedges.

The lock file is named '<glossary>.json.lock': it does not end in .json, so glossary discovery (globs and suffix checks on
.json) never mistakes it for a glossary. flock locks belong to the open file, so two threads of one process and two processes
exclude each other alike, and the OS drops the lock when its holder dies. Where the lock cannot be made (an unwritable
directory, no fcntl) the stage proceeds: it could not write the glossary there either, and its own error handling applies."""

from __future__ import annotations

import contextlib
import os
import time

try:
    import fcntl
except ImportError:  # pragma: no cover -- not POSIX
    fcntl = None


def log(*a):
    print(*a, flush=True)


def lock_path(gloss_path: str) -> str:
    return gloss_path + ".lock"


def wait_seconds() -> float:
    """GLOSSARY_LOCK_WAIT (default 5): how long a stage waits for a busy glossary before skipping. Garbage -> 5."""
    try:
        return max(0.0, float(os.environ.get("GLOSSARY_LOCK_WAIT", "5")))
    except ValueError:
        return 5.0


@contextlib.contextmanager
def locked(gloss_path: str, stage: str, wait: float | None = None):
    """Yield True with the lock held, or False (busy, logged) without it. Released on exit, exception or not."""
    if fcntl is None:
        yield True
        return
    try:
        fd = os.open(lock_path(gloss_path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        yield True
        return
    got = False
    try:
        deadline = time.monotonic() + (wait_seconds() if wait is None else wait)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
        if not got:
            log(f"glossary busy: {stage} skipped")
        yield got
    finally:
        if got:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
