#!/usr/bin/env python3
"""Append-only journal of completed glossary adjudications, so a hard interruption loses at most the call in flight.

Why it exists. glossary_verify._verify() collects every adjudication and applies+writes them as ONE batch; glossary_acquire's
escalate() keeps its pair answers in memory and acquire_cache.save() runs only after escalation (or on a COOPERATIVE
stop); tier B's
per-term results wait for the single glossary write. A timeout, SIGKILL or host failure therefore throws away every
LLM call already
paid for (~1.3 s each, hundreds per show). This journal writes each successful answer to disk the moment it exists.

Format (JSON Lines, one object per line, UTF-8):
    {"v": 1, "stage": "verify"|"acquire", "key": "pick\\x1f<term>" | "pair\\x1f<variant>\\x1f<canonical>",
     "prov": {...what the answer depended on...}, "result": {...the adjudication...}, "at": <epoch seconds>}

Location: one file per show and stage, beside the stage's existing cache (verify: WIKI_CACHE_DIR; acquire: next to the glossary,
where acquire_cache lives).

Rules, deliberately the same ones acquire_cache learned the hard way:
  * It memoises the expensive ADJUDICATION, never a frequency-dependent final verdict: every token still flows through the whole
    pipeline on every run, so a dry run reports completely and a later apply still surfaces accepted proposals and review flags.
  * An answer that is not a real adjudication is NEVER written: the backend raised, returned nothing or something unparseable
    ("unavailable"), a decision call failed, or the answer is the LOCAL fallback of a hosted backend (it would be served later as
    if the hosted model had said it). Those stay retryable.
  * PROVENANCE. Each line records what the answer depended on (the show, the candidate list or both context lists as hashes, the
    backend, the model, the prompt version, the decision threshold). A line whose provenance differs from the current request is
    IGNORED, not deleted; an unrelated edit does not invalidate anything, a changed input is never served stale.
    VERIFY_NO_JOURNAL=1
    / ACQUIRE_NO_CACHE=1 re-evaluate everything.
  * Crash safety. One os.write per line under O_APPEND, fsynced; appenders hold a shared flock, compaction an exclusive one, so no
    line is lost to a concurrent rewrite. A torn last line (the process died mid-write) is skipped on load and the next append
    starts on its own line (the unresolved.py pattern). A corrupt or unreadable journal is logged once and the run carries on
    without it: it is an optimisation and must never raise or change what the pipeline decides.
  * Lifecycle. compact() (called after a clean apply) rewrites the file atomically (tmp + rename) to the latest line per key,
    drops lines older than MAX_AGE_DAYS and lines of a different format version, so it never grows without bound.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import threading
import time

from common import SIDECAR_MODE, log

VERSION = 1
MAX_AGE_DAYS = 30
SEP = "\x1f"


def digest(obj) -> str:
    """A short stable hash of a JSON-able value (a candidate list, a context list) for provenance."""
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def journalable(result) -> bool:
    """Whether ``result`` is a real adjudication worth remembering (see the module docstring)."""
    return isinstance(result, dict) and not result.get("unavailable") and not result.get("fallback")


@contextlib.contextmanager
def _flock(path: str, exclusive: bool):
    try:
        import fcntl

        fd = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
    except (ImportError, OSError):
        yield
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        os.close(fd)  # closing releases the lock


class Journal:
    """One stage's journal for one show. Never raises."""

    def __init__(self, path: str, stage: str, clock=time.time, max_age_days: float = MAX_AGE_DAYS, read: bool = True):
        self.path, self.stage, self.clock, self.max_age = path, stage, clock, max_age_days * 86400
        self.read = read  # False: lookup() never serves a stored answer (a forced re-evaluation); record() still writes
        self._lock = threading.Lock()
        self._broken = False
        self._entries: dict[str, dict] = {}
        self.skipped = 0  # lines ignored on load (torn, not JSON, wrong shape)
        self._load()

    # ---- reading -------------------------------------------------------------------------------------------------------

    def _read_lines(self) -> list[dict]:
        out, skipped = [], 0
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        e = json.loads(raw)
                    except ValueError:
                        skipped += 1  # a torn final line, or damage: skipped, never fatal
                        continue
                    if (
                        isinstance(e, dict)
                        and e.get("v") == VERSION
                        and e.get("stage") == self.stage
                        and isinstance(e.get("key"), str)
                        and isinstance(e.get("prov"), dict)
                        and isinstance(e.get("result"), dict)
                    ):
                        out.append(e)
                    else:
                        skipped += 1
        except FileNotFoundError:
            return []
        except OSError as exc:
            self._break(f"unreadable ({exc.__class__.__name__})")
            return []
        self.skipped = skipped
        return out

    def _load(self) -> None:
        for e in self._read_lines():  # later lines win: the latest answer per key
            self._entries[e["key"]] = e
        if self.skipped:
            log(f"{self.stage} journal {os.path.basename(self.path)}: {self.skipped} unreadable line(s) skipped")

    def _break(self, why: str) -> None:
        if not self._broken:
            log(f"{self.stage} journal {os.path.basename(self.path)} {why}: continuing without it")
        self._broken = True

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, key: str, prov: dict) -> dict | None:
        """The remembered result for ``key``, only if it was computed from exactly ``prov``; else None (a miss, never
        an error)."""
        if not self.read:
            return None
        with self._lock:
            e = self._entries.get(key)
        if e is None or e["prov"] != prov:
            return None
        return dict(e["result"])

    # ---- writing -------------------------------------------------------------------------------------------------------

    def record(self, key: str, prov: dict, result) -> bool:
        """Append one completed adjudication, durably, before the caller moves on. False when it was not written."""
        if self._broken or not journalable(result):
            return False
        entry = {"v": VERSION, "stage": self.stage, "key": key, "prov": prov, "result": result, "at": self.clock()}
        try:
            line = (json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        except (TypeError, ValueError):
            return False
        try:
            with self._lock, _flock(self.path, exclusive=False):
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT, SIDECAR_MODE)
                try:
                    size = os.fstat(fd).st_size
                    if size and os.pread(fd, 1, size - 1) != b"\n":
                        line = b"\n" + line  # a torn tail: start this record on its own line
                    os.write(fd, line)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self._entries[key] = entry
            return True
        except OSError as exc:
            self._break(f"not writable ({exc.__class__.__name__})")
            return False

    def compact(self) -> int:
        """Rewrite to the latest line per key, minus anything older than MAX_AGE_DAYS. Atomic; idempotent. Returns lines kept."""
        if self._broken:
            return 0
        tmp = None
        try:
            with self._lock, _flock(self.path, exclusive=True):
                lines = self._read_lines()
                if not lines and not os.path.exists(self.path):
                    return 0
                latest: dict[str, dict] = {}
                for e in lines:
                    latest[e["key"]] = e
                cutoff = self.clock() - self.max_age
                kept = [e for e in latest.values() if isinstance(e.get("at"), (int, float)) and e["at"] >= cutoff]
                kept.sort(key=lambda e: (e["at"], e["key"]))
                body = "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in kept)
                try:
                    if open(self.path, encoding="utf-8", errors="replace").read() == body:
                        self._entries = {e["key"]: e for e in kept}
                        return len(kept)  # already compact: leave the file (and its mtime) alone
                except OSError:
                    pass
                fd, tmp = tempfile.mkstemp(
                    dir=os.path.dirname(self.path) or ".", prefix=os.path.basename(self.path) + ".", suffix=".tmp"
                )
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(body)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(tmp, SIDECAR_MODE)
                os.replace(tmp, self.path)
                tmp = None
                self._entries = {e["key"]: e for e in kept}
                return len(kept)
        except OSError as exc:
            self._break(f"could not be compacted ({exc.__class__.__name__})")
            return 0
        finally:
            if tmp is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)


def pick_key(term: str) -> str:
    return f"pick{SEP}{term}"


def pair_key(variant: str, canonical: str) -> str:
    return f"pair{SEP}{variant}{SEP}{canonical}"
