import contextlib
import datetime
import fcntl
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import uuid
import zoneinfo
from typing import Any

REQUESTS_DIR = os.environ.get("REQUESTS_DIR", "/config/requests")
ANIME_ROOT = os.environ.get("ANIME_ROOT", "/media/Anime Library")

ALLOWED_BODY_KEYS = frozenset(("show", "season", "episode_re", "require_eng", "webhook"))


class Refused(Exception):
    """Raised when a request fails validation. Carries HTTP status code and error message."""

    def __init__(self, status: int, error: str):
        super().__init__(error)
        self.status = status
        self.error = error


def _has_control_or_format_chars(s: str) -> bool:
    """True if string contains any Unicode Cc (control) or Cf (format) characters."""
    return any(unicodedata.category(c) in ("Cc", "Cf") for c in s)


def normalize_episode_re(ep: str | None) -> str | None:
    """Normalize episode_re by stripping whitespace."""
    if ep is None:
        return None
    s = ep.strip()
    return s if s else None


def _validate_episode_re_grammar(pattern: str) -> None:
    r"""Validate episode_re against a strict safe grammar to prevent ReDoS and hangs.

    Allowed tokens:
    - ASCII letters and digits ([A-Za-z0-9])
    - Space, dot (literal or escaped), underscore, hyphen ([ ._-], r'\.')
    - Non-capturing parentheses (?: ... ) capped at nesting depth 2
    - Alternation bar (|) capped at 50 branches total
    - Character classes [Ee] and [Ss]
    - Zero repetition 0* (only after [Ee], [Ss], or digit-free literal start of branch;
      at most once in entire pattern; depth <= 1)
    - Escaped digit \d
    - Negative lookahead (?!\d)
    - Digit classes [0-9] and digit ranges [0-9]-[0-9] (e.g. [1-3])
    - Bounded repetition {1,3} on a single repeatable token (groups take NO quantifier)
    No empty or quantifier-only branches like (?:0*).
    No unbounded quantifiers (*, +, ?), no backreferences, no lookbehind,
    no .* or \w* or \s*. Max 200 chars.
    """
    if len(pattern) > 200:
        raise Refused(400, "episode_re exceeds max length of 200 characters")
    if _has_control_or_format_chars(pattern):
        raise Refused(400, "control or format characters not allowed in episode_re")
    if pattern.count("|") > 49:
        raise Refused(400, "number of alternation branches exceeds maximum of 50")

    try:
        re.compile(pattern)
    except re.error as e:
        raise Refused(400, f"invalid episode_re regex: {e}") from None

    if "(?<=" in pattern or "(?<!" in pattern.replace(r"(?!\d)", ""):
        raise Refused(400, "lookbehind regex is not permitted")
    if re.search(r"\\[1-9]|\(\?P=", pattern):
        raise Refused(400, "backreferences are not permitted")

    def _new_branch():
        return {
            "branch_has_digits": False,
            "branch_has_only_literals": True,
            "last_token_was_es": False,
            "last_token_was_es_type": None,
            "has_substantive_tokens": False,
        }

    branch_stack = [_new_branch()]
    open_groups = 0
    last_token_repeatable = False
    total_zero_star_count = 0
    zero_star_after_s = 0
    zero_star_after_e = 0
    i = 0
    n = len(pattern)

    while i < n:
        if pattern[i:].startswith(r"(?!\d)"):
            cur = branch_stack[-1]
            cur["last_token_was_es"] = False
            cur["last_token_was_es_type"] = None
            cur["branch_has_only_literals"] = False
            i += 6
            last_token_repeatable = False
            continue

        if pattern[i:].startswith(r"(?:"):
            open_groups += 1
            if open_groups > 2:
                raise Refused(400, "group nesting depth exceeds maximum of 2")
            branch_stack.append(_new_branch())
            i += 3
            last_token_repeatable = False
            continue

        if pattern[i] == ")":
            if open_groups <= 0:
                raise Refused(400, "unbalanced parentheses in episode_re")
            open_groups -= 1
            closing_branch = branch_stack.pop()
            if not closing_branch["has_substantive_tokens"]:
                raise Refused(400, "empty or quantifier-only branch in episode_re")
            cur = branch_stack[-1]
            cur["last_token_was_es"] = False
            cur["last_token_was_es_type"] = None
            cur["branch_has_only_literals"] = False
            cur["has_substantive_tokens"] = True
            i += 1
            # Groups take NO quantifier: after ')' the last token is not repeatable
            last_token_repeatable = False
            continue

        if pattern[i] == "|":
            if not branch_stack[-1]["has_substantive_tokens"]:
                raise Refused(400, "empty or quantifier-only branch in episode_re")
            branch_stack[-1] = _new_branch()
            i += 1
            last_token_repeatable = False
            continue

        if pattern[i:].startswith("0*"):
            if open_groups > 1:
                raise Refused(400, "0* is not allowed inside nested groups")
            cur = branch_stack[-1]
            is_after_es = cur["last_token_was_es"]
            is_literal_start = cur["branch_has_only_literals"] and not cur["branch_has_digits"]
            if not (is_after_es or is_literal_start):
                raise Refused(400, "0* is only allowed directly after [Ee]/[Ss] or a digit-free literal branch prefix")

            if cur["last_token_was_es_type"] == "S":
                zero_star_after_s += 1
            elif cur["last_token_was_es_type"] == "E":
                zero_star_after_e += 1

            total_zero_star_count += 1
            # At most one 0* in the whole pattern, unless it matches the specials anchor ([Ss]0*...[Ee]0*)
            specials_two = (
                total_zero_star_count == 2
                and zero_star_after_s == 1
                and zero_star_after_e == 1
            )
            if total_zero_star_count > 2 or (total_zero_star_count == 2 and not specials_two):
                raise Refused(400, "0* is allowed at most once in episode_re")

            cur["last_token_was_es"] = False
            cur["last_token_was_es_type"] = None
            cur["branch_has_only_literals"] = False
            i += 2
            last_token_repeatable = False
            continue

        if pattern[i:].startswith(r"\d"):
            cur = branch_stack[-1]
            cur["branch_has_digits"] = True
            cur["branch_has_only_literals"] = False
            cur["last_token_was_es"] = False
            cur["last_token_was_es_type"] = None
            cur["has_substantive_tokens"] = True
            i += 2
            last_token_repeatable = True
            continue

        if pattern[i:].startswith(r"\."):
            cur = branch_stack[-1]
            cur["last_token_was_es"] = False
            cur["last_token_was_es_type"] = None
            cur["has_substantive_tokens"] = True
            i += 2
            last_token_repeatable = True
            continue

        if pattern[i:].startswith(("[Ee]", "[eE]", "[Ss]", "[sS]")):
            cur = branch_stack[-1]
            cur["last_token_was_es"] = True
            cur["last_token_was_es_type"] = "S" if pattern[i + 1] in "Ss" else "E"
            cur["branch_has_only_literals"] = False
            cur["has_substantive_tokens"] = True
            i += 4
            last_token_repeatable = True
            continue

        m_range = re.match(r"^\[([0-9])-([0-9])\]", pattern[i:])
        if m_range:
            start_d = int(m_range.group(1))
            end_d = int(m_range.group(2))
            if start_d > end_d:
                raise Refused(400, "invalid character class range in episode_re")
            cur = branch_stack[-1]
            cur["branch_has_digits"] = True
            cur["branch_has_only_literals"] = False
            cur["last_token_was_es"] = False
            cur["last_token_was_es_type"] = None
            cur["has_substantive_tokens"] = True
            i += len(m_range.group(0))
            last_token_repeatable = True
            continue

        m_bound = re.match(r"^\{([1-3])(?:,([1-3]))?\}", pattern[i:])
        if m_bound:
            if not last_token_repeatable:
                raise Refused(400, "quantifier must follow a repeatable token")
            min_r = int(m_bound.group(1))
            max_r = int(m_bound.group(2)) if m_bound.group(2) else min_r
            if min_r > max_r:
                raise Refused(400, "invalid repetition bounds in episode_re")
            cur = branch_stack[-1]
            cur["last_token_was_es"] = False
            cur["last_token_was_es_type"] = None
            cur["branch_has_only_literals"] = False
            i += len(m_bound.group(0))
            last_token_repeatable = False
            continue

        c = pattern[i]
        if c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-":
            cur = branch_stack[-1]
            if c != " ":
                cur["has_substantive_tokens"] = True
            if c in "0123456789":
                cur["branch_has_digits"] = True
            if c in "Ee":
                cur["last_token_was_es"] = True
                cur["last_token_was_es_type"] = "E"
            elif c in "Ss":
                cur["last_token_was_es"] = True
                cur["last_token_was_es_type"] = "S"
            else:
                cur["last_token_was_es"] = False
                cur["last_token_was_es_type"] = None
            i += 1
            last_token_repeatable = True
            continue

        raise Refused(400, f"unsupported token or construct in episode_re: '{c}'")

    if open_groups != 0:
        raise Refused(400, "unclosed non-capturing group in episode_re")

    if not branch_stack[-1]["has_substantive_tokens"]:
        raise Refused(400, "empty or quantifier-only branch in episode_re")



def validate(body: dict, anime_root: str | None = None) -> dict:
    """Validate request body.

    Enforces containment under ANIME_ROOT, rejects path traversal and control/format chars,
    and protects against ReDoS by rejecting lookbehind, backreferences, nested quantifiers,
    alternation in quantified groups, and ungrammatical or backtracking episode_re patterns.
    Returns cleaned dictionary or raises Refused(status, error).
    """
    if not isinstance(body, dict):
        raise Refused(400, "request body must be a JSON object")

    unknown = set(body.keys()) - ALLOWED_BODY_KEYS
    if unknown:
        raise Refused(400, f"unknown keys: {', '.join(sorted(unknown))}")

    for k, v in body.items():
        if isinstance(v, str):
            if any(c in v for c in "\r\n=\0") or _has_control_or_format_chars(v):
                raise Refused(400, f"invalid character in {k}: control characters not permitted")

    if "show" not in body or not isinstance(body["show"], str):
        raise Refused(400, "show is required and must be a string")

    show = body["show"].strip()
    if not show:
        raise Refused(400, "show must not be empty")

    if "/" in show or "\\" in show or ".." in show or "\0" in show:
        raise Refused(400, "invalid show name: path traversal characters not permitted")

    if _has_control_or_format_chars(show):
        raise Refused(400, "control or format characters not allowed in show name")

    if anime_root is not None:
        real_anime = os.path.realpath(anime_root)
        show_dir = os.path.join(anime_root, show)
        real_show = os.path.realpath(show_dir)
        if not (real_show.startswith(real_anime + os.sep) and os.path.isdir(real_show)):
            if not os.path.isdir(show_dir):
                raise Refused(400, f"show directory not found: {show}")
            raise Refused(400, "show path escapes anime root")

    season = body.get("season")
    if season is not None:
        if isinstance(season, bool) or not isinstance(season, int) or season <= 0:
            raise Refused(400, "season must be a positive integer or null")

    episode_re = body.get("episode_re")
    if episode_re is not None:
        if not isinstance(episode_re, str):
            raise Refused(400, "episode_re must be a string or null")
        norm_ep = normalize_episode_re(episode_re)
        if norm_ep is None:
            raise Refused(400, "episode_re must not be empty")
        _validate_episode_re_grammar(norm_ep)
        episode_re = norm_ep

    require_eng = body.get("require_eng")
    if require_eng is not None:
        if isinstance(require_eng, bool) or require_eng not in (0, 1):
            raise Refused(400, "require_eng must be 0, 1, or null")

    webhook = body.get("webhook")
    if webhook is not None and not isinstance(webhook, dict):
        raise Refused(400, "webhook must be an object or null")

    return {
        "show": show,
        "season": season,
        "episode_re": episode_re,
        "require_eng": require_eng,
        "webhook": webhook,
    }


_SKIP_SHOW_DIRS = ("lost+found",)


def list_shows(anime_root: str | None = None) -> list[str]:
    """Show directory names directly under the library root that validate() accepts, sorted.

    One directory level only; symlinks, dot and @ directories (NAS metadata) and lost+found are skipped.
    Each name goes through validate() itself, so every listed show is
    one a run request can name; anything it refuses (traversal characters, a symlink out of the
    root, control characters) is left out."""
    aroot = anime_root or os.environ.get("ANIME_ROOT", ANIME_ROOT)
    try:
        names = [
            e.name
            for e in os.scandir(aroot)
            if e.is_dir(follow_symlinks=False) and e.name not in _SKIP_SHOW_DIRS and e.name[0] not in ".@"
        ]
    except OSError:
        return []
    out = []
    for name in names:
        try:
            if validate({"show": name}, anime_root=aroot)["show"] == name:
                out.append(name)
        except Refused:
            pass
    return sorted(out)


def derive_generate_only_re(show: str, season: int | None = None, episode_re: str | None = None) -> str:
    r"""Derive GENERATE_ONLY_RE regex for filename matching with season/episode branches."""
    ep = normalize_episode_re(episode_re)
    if season is None and not ep:
        return ""

    if season is not None and ep:
        if ep.endswith(r"(?!\d)"):
            ep = ep[:-len(r"(?!\d)")]
        branch = f"(?:^|[\\W_])[Ss]0*{season}(?:[\\W_Ee]|(?=[Ee])).*(?:{ep})(?!\\d)"
    elif season is not None:
        # Season-only branch: do NOT append (?!\d) because [Ss]0*1(?=[Ee]|[\W_]|$) already bounds the number
        branch = f"(?:^|[\\W_])[Ss]0*{season}(?=[Ee]|[\\W_]|$)"
    else:
        if ep and ep.endswith(r"(?!\d)"):
            ep = ep[:-len(r"(?!\d)")]
        branch = f"(?:{ep})(?!\\d)"

    if not (branch.startswith("(?:") and branch.endswith(")")):
        branch = f"(?:{branch})"

    return branch



def create(
    body: dict,
    anime_root: str | None = None,
    requests_dir: str | None = None,
    now: datetime.datetime | float | None = None,
) -> tuple[int, dict]:
    """Create a new run request in the queue.

    Atomic write with 0664 mode. Serialized with fcntl.flock to prevent races.
    """
    rdir = requests_dir or os.environ.get("REQUESTS_DIR", REQUESTS_DIR)
    aroot = anime_root or os.environ.get("ANIME_ROOT", ANIME_ROOT)

    clean = validate(body, anime_root=aroot)
    os.makedirs(rdir, exist_ok=True)

    lock_file = os.path.join(rdir, ".requests.lock")
    lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o664)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Check for identical pending request
        try:
            for entry in os.scandir(rdir):
                if entry.is_file() and entry.name.endswith(".json") and not entry.name.startswith("."):
                    try:
                        with open(entry.path, encoding="utf-8") as f:
                            existing = json.load(f)
                        if existing.get("status") == "pending":
                            if (
                                existing.get("show") == clean["show"]
                                and existing.get("season") == clean["season"]
                                and existing.get("episode_re") == clean["episode_re"]
                            ):
                                return 409, {
                                    "error": "identical request already pending",
                                    "existing_id": existing.get("id", entry.name[:-5]),
                                }
                    except (OSError, ValueError):
                        continue
        except OSError:
            pass

        # Timestamp & ID with microsecond precision
        if now is None:
            dt = datetime.datetime.now(datetime.timezone.utc)
        elif isinstance(now, (int, float)):
            dt = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)
        elif isinstance(now, datetime.datetime):
            dt = now if now.tzinfo is not None else now.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = datetime.datetime.now(datetime.timezone.utc)

        ts_str = dt.strftime("%Y%m%dT%H%M%S.%fZ")
        hex_id = uuid.uuid4().hex[:8]
        req_id = f"{ts_str}-{hex_id}"

        gen_re = derive_generate_only_re(clean["show"], clean["season"], clean["episode_re"])

        doc = {
            "id": req_id,
            "webhook": clean.get("webhook"),
            "created_at": dt.isoformat(),
            "show": clean["show"],
            "season": clean["season"],
            "episode_re": clean["episode_re"],
            "generate_only_re": gen_re,
            "require_eng": clean["require_eng"],
            "status": "pending",
            "error": None,
            "finished_at": None,
        }

        dest_path = os.path.join(rdir, f"{req_id}.json")
        tmp_path = os.path.join(rdir, f".{req_id}.tmp")

        payload = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o664)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)

        with contextlib.suppress(OSError):
            os.chmod(tmp_path, 0o664)

        os.replace(tmp_path, dest_path)

        with contextlib.suppress(OSError):
            dfd = os.open(rdir, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)

        return 201, {"id": req_id, "status": "pending"}

    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def list_requests(requests_dir: str | None = None, now: Any = None) -> list[dict]:
    """List requests across requests_dir, done/, and failed/.

    Uses os.scandir only (no os.walk). Names sorted newest first, at most 200 files opened/parsed.
    """
    rdir = requests_dir or os.environ.get("REQUESTS_DIR", REQUESTS_DIR)
    dirs_to_scan = [rdir, os.path.join(rdir, "done"), os.path.join(rdir, "failed")]

    entries = []
    for d in dirs_to_scan:
        if not os.path.isdir(d):
            continue
        try:
            for entry in os.scandir(d):
                if not entry.is_file():
                    continue
                name = entry.name
                if name.startswith("."):
                    continue
                if not (name.endswith(".json") or name.endswith(".running")):
                    continue
                entries.append((entry.name, entry.path))
        except OSError:
            continue

    entries.sort(key=lambda x: x[0], reverse=True)

    items = []
    for _name, path in entries:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and ("id" in data or "status" in data):
                items.append(data)
                if len(items) >= 200:
                    break
        except (OSError, ValueError):
            continue

    return items


def prune(
    done_dir: str,
    failed_dir: str,
    days: int = 7,
    now: datetime.datetime | float | None = None,
) -> int:
    """Prune files in done_dir and failed_dir older than `days`."""
    days = max(1, int(days))
    if now is None:
        now_ts = time.time()
    elif isinstance(now, (int, float)):
        now_ts = float(now)
    elif isinstance(now, datetime.datetime):
        now_ts = now.timestamp()
    else:
        now_ts = time.time()

    cutoff = now_ts - days * 86400
    pruned = 0

    for d in (done_dir, failed_dir):
        if not os.path.isdir(d):
            continue
        try:
            for entry in os.scandir(d):
                if entry.is_file() and entry.name.endswith(".json") and not entry.name.startswith("."):
                    try:
                        st = entry.stat()
                        if st.st_mtime < cutoff:
                            os.unlink(entry.path)
                            pruned += 1
                    except OSError:
                        continue
        except OSError:
            continue

    return pruned


def request_shows(requests_dir: str | None = None, days: int = 7) -> list[str]:
    """Sorted show names that have a run request: pending, running, or finished OK within `days`.

    Read-only. Failed requests do not count (nothing was built for them); unsafe or unreadable entries are skipped.
    """
    rdir = requests_dir or os.environ.get("REQUESTS_DIR", REQUESTS_DIR)
    cutoff = time.time() - max(1, int(days)) * 86400
    shows = set()
    for d in (rdir, os.path.join(rdir, "done")):
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for entry in entries:
            if not entry.is_file() or entry.name.startswith(".") or not entry.name.endswith((".json", ".running")):
                continue
            try:
                if d != rdir and entry.stat().st_mtime < cutoff:
                    continue
                with open(entry.path, encoding="utf-8") as f:
                    show = json.load(f).get("show")
            except (OSError, ValueError, AttributeError):
                continue
            if (
                isinstance(show, str)
                and show
                and show != "."
                and not any(bad in show for bad in ("/", "\\", "..", "\0"))
                and not _has_control_or_format_chars(show)
            ):
                shows.add(show)
    return sorted(shows)


def next_pending(dir: str | None = None) -> str | None:
    """Find the oldest pending request path (FIFO by filename timestamp)."""
    rdir = dir or os.environ.get("REQUESTS_DIR", REQUESTS_DIR)
    if not os.path.isdir(rdir):
        return None

    candidates = []
    try:
        for entry in os.scandir(rdir):
            if entry.is_file() and entry.name.endswith(".json") and not entry.name.startswith("."):
                candidates.append((entry.name, entry.path))
    except OSError:
        return None

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    for _name, path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") == "pending":
                return path
        except (OSError, ValueError):
            continue

    return None


def _check_requests_dir_containment(path: str, requests_dir: str | None = None) -> None:
    """Ensure path is directly inside REQUESTS_DIR."""
    rdir = requests_dir or os.environ.get("REQUESTS_DIR")
    if rdir is None:
        if os.path.isdir(REQUESTS_DIR):
            rdir = REQUESTS_DIR
        else:
            return
    rdir_real = os.path.realpath(rdir)
    path_real = os.path.realpath(path)
    if os.path.dirname(path_real) != rdir_real:
        raise ValueError(f"path {path} is not directly inside REQUESTS_DIR {rdir_real}")


def mark_running(path: str, requests_dir: str | None = None) -> str:
    """Mark a pending request as running, renaming it to .running on disk."""
    _check_requests_dir_containment(path, requests_dir)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    data["status"] = "running"
    if path.endswith(".json"):
        running_path = path[:-5] + ".running"
    else:
        running_path = path + ".running"

    tmp_path = running_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    os.replace(tmp_path, running_path)
    if os.path.exists(path) and os.path.abspath(path) != os.path.abspath(running_path):
        with contextlib.suppress(OSError):
            os.unlink(path)

    return running_path


def requeue(path: str, requests_dir: str | None = None) -> str:
    """Move a running request back to pending status atomically."""
    actual_path = path
    if not os.path.exists(actual_path):
        if actual_path.endswith(".json") and os.path.exists(actual_path[:-5] + ".running"):
            actual_path = actual_path[:-5] + ".running"
        elif actual_path.endswith(".running") and os.path.exists(actual_path[:-8] + ".json"):
            actual_path = actual_path[:-8] + ".json"
    _check_requests_dir_containment(actual_path, requests_dir)
    with open(actual_path, encoding="utf-8") as f:
        data = json.load(f)

    data["status"] = "pending"
    if actual_path.endswith(".running"):
        pending_path = actual_path[:-8] + ".json"
    elif actual_path.endswith(".json"):
        pending_path = actual_path
    else:
        pending_path = actual_path + ".json"

    tmp_path = pending_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    os.replace(tmp_path, pending_path)
    if os.path.exists(actual_path) and os.path.abspath(actual_path) != os.path.abspath(pending_path):
        with contextlib.suppress(OSError):
            os.unlink(actual_path)

    return pending_path


def finish(
    path: str,
    ok: bool,
    error: str | None = None,
    now: datetime.datetime | float | None = None,
    requests_dir: str | None = None,
) -> str:
    """Move a running/pending request to done/ or failed/ with finished_at and error filled."""
    actual_path = path
    if not os.path.exists(actual_path):
        if actual_path.endswith(".json") and os.path.exists(actual_path[:-5] + ".running"):
            actual_path = actual_path[:-5] + ".running"
        elif actual_path.endswith(".running") and os.path.exists(actual_path[:-8] + ".json"):
            actual_path = actual_path[:-8] + ".json"
    _check_requests_dir_containment(actual_path, requests_dir)
    with open(actual_path, encoding="utf-8") as f:
        data = json.load(f)

    if now is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    elif isinstance(now, (int, float)):
        dt = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)
    elif isinstance(now, datetime.datetime):
        dt = now if now.tzinfo is not None else now.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = datetime.datetime.now(datetime.timezone.utc)

    req_id = data.get("id") or os.path.basename(actual_path).split(".")[0]
    data["status"] = "done" if ok else "failed"
    data["error"] = None if ok else (error or "failed")
    data["finished_at"] = dt.isoformat()

    parent_dir = os.path.dirname(os.path.abspath(actual_path))
    target_dir = os.path.join(parent_dir, "done" if ok else "failed")
    os.makedirs(target_dir, exist_ok=True)

    dest_path = os.path.join(target_dir, f"{req_id}.json")
    tmp_path = os.path.join(target_dir, f".{req_id}.tmp")

    payload = (json.dumps(data, indent=2) + "\n").encode("utf-8")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o664)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)

    with contextlib.suppress(OSError):
        os.chmod(tmp_path, 0o664)

    os.replace(tmp_path, dest_path)

    if os.path.abspath(actual_path) != os.path.abspath(dest_path) and os.path.exists(actual_path):
        with contextlib.suppress(OSError):
            os.unlink(actual_path)

    return dest_path


def recover_running(requests_dir: str | None = None, now: Any = None) -> list[str]:
    """Recover leftover .running files by moving them to failed/ with 'interrupted by restart'."""
    rdir = requests_dir or os.environ.get("REQUESTS_DIR", REQUESTS_DIR)
    if not os.path.isdir(rdir):
        return []

    recovered = []
    try:
        for entry in os.scandir(rdir):
            if entry.is_file() and entry.name.endswith(".running") and not entry.name.startswith("."):
                dest = finish(entry.path, ok=False, error="interrupted by restart", now=now)
                recovered.append(dest)
    except OSError:
        pass
    return recovered


def is_window_open(schedule_file: str | None = None, now: datetime.datetime | None = None) -> bool:
    """Determine if current time is within schedule window."""
    sfile = schedule_file or os.environ.get("SCHEDULE_FILE", "/config/schedule.json")
    if not os.path.isfile(sfile):
        return True

    try:
        with open(sfile, encoding="utf-8") as f:
            sched = json.load(f)
    except Exception:
        return True

    if not isinstance(sched, dict) or not sched.get("enabled", False):
        return True

    tz_str = sched.get("tz", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(tz_str)
    except Exception as e:
        print(f"review_requests: warning: unknown or unresolvable timezone {tz_str}: {e}; failing open", file=sys.stderr)
        return True

    cur_dt = now.astimezone(tz) if now is not None else datetime.datetime.now(tz)

    open_str = sched.get("open", "00:00")
    close_str = sched.get("close", "00:00")

    try:
        oh, om = map(int, open_str.split(":"))
        ch, cm = map(int, close_str.split(":"))
    except Exception:
        return True

    cur_min = cur_dt.hour * 60 + cur_dt.minute
    open_min = oh * 60 + om
    close_min = ch * 60 + cm

    if open_min == close_min:
        return True
    elif open_min < close_min:
        return open_min <= cur_min < close_min
    else:
        return cur_min >= open_min or cur_min < close_min


EFFECTIVE_ENV_ALLOW_PREFIXES = ("REPAIR_", "VERIFY_")
EFFECTIVE_ENV_ALLOW_EXACT = frozenset((
    "REQUIRE_ENG",
    "GLOSSARY_ARC_TAGS",
    "RESCAN_INTERVAL",
    "MERGE_WINDOW",
    "ANIME_ORDER",
    "ACQUIRE_BACKEND",
    "WHISPER_MODEL",
    "COMPUTE_TYPE",
    "MERGE_ROOTS",
    "ACQUIRE_APPLY",
))
EFFECTIVE_ENV_SKIP_SUBSTRINGS = ("KEY", "TOKEN", "PASSWORD", "SECRET")
_SECRET_VALUE_RE = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{16,}|\bBearer\b")
_MIN_SECRET_LEN = 8  # shorter values are too common to match against other lines


def _strip_url_userinfo(val: str) -> str:
    """Strip user info by rebuilding netloc from urlsplit().hostname and port.

    A raw @ in the password must not leak a fragment.
    """
    if "://" not in val:
        return val
    try:
        parts = urllib.parse.urlsplit(val)
    except ValueError:
        return val
    if not parts.scheme or not parts.netloc or not parts.hostname:
        return val
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{parts.port}" if parts.port else "")
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _reportable(key: str) -> bool:
    """Every registry key a builder process reads is reported, so the page can tell a pending change from an applied one."""
    try:
        import settings_registry
    except ImportError:  # a minimal app directory without the registry keeps the fixed allow-list above
        return False
    entry = settings_registry.REGISTRY.get(key)
    return entry is not None and not entry["secret"] and bool({"gen", "merge"} & set(entry["scope"]))


def _known_secret_values(source_env: dict) -> list:
    """The values of every secret the registry knows (and the per-stage key holders), so no other line can repeat one."""
    try:
        import settings_registry
    except ImportError:
        registry = {}
    else:
        registry = settings_registry.REGISTRY
    out = []
    for k, v in source_env.items():
        secret = (k in registry and registry[k]["secret"]) or k.startswith("DT_CONN_KEY_")
        if secret and len(str(v)) >= _MIN_SECRET_LEN:
            out.append(str(v))
    return out


def write_effective_env(out_file: str | None = None, env: dict | None = None) -> str:
    """Write the effective-env report atomically (mode 0640): allowed variables only, no secret, no repeated secret value, and
    the user info of every URL stripped (the report is for display, so a URL keeps its host, port and path)."""
    target = out_file or os.environ.get(
        "EFFECTIVE_ENV_FILE",
        os.path.join(os.environ.get("CONFIG_DIR", "/config"), "effective.env"),
    )
    source_env = env if env is not None else os.environ
    secret_values = _known_secret_values(source_env)

    lines = []
    for k in sorted(source_env.keys()):
        if k.endswith("_EXTRA_BODY"):
            continue
        allowed = any(k.startswith(p) for p in EFFECTIVE_ENV_ALLOW_PREFIXES) or (k in EFFECTIVE_ENV_ALLOW_EXACT)
        allowed = allowed or _reportable(k)
        if not allowed:
            continue
        if any(s in k for s in EFFECTIVE_ENV_SKIP_SUBSTRINGS):
            continue
        v = _strip_url_userinfo(str(source_env[k]))
        if _SECRET_VALUE_RE.search(v) or any(secret in v for secret in secret_values):
            continue
        val = v.splitlines()[0] if v else ""
        lines.append(f"{k}={val}\n")

    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    tmp = target + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o640)  # umask-proof: the host user reads the report, other users do not
        f.writelines(lines)
    os.replace(tmp, target)
    return target


SCHEDULE_FILE = os.environ.get("SCHEDULE_FILE", "/config/schedule.json")
SCHEDULE_SCHEMA_KEYS = frozenset(("enabled", "open", "close", "tz"))
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DEFAULT_SCHEDULE = {
    "enabled": False,
    "open": "00:00",
    "close": "00:00",
    "tz": "UTC",
}


def get_schedule(schedule_file: str | None = None) -> dict:
    """Read schedule from schedule.json, returning defaults if missing or invalid."""
    sfile = schedule_file or os.environ.get("SCHEDULE_FILE", SCHEDULE_FILE)
    if not os.path.isfile(sfile):
        return dict(DEFAULT_SCHEDULE)

    try:
        with open(sfile, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULT_SCHEDULE)
        return {
            "enabled": bool(data.get("enabled", False)),
            "open": str(data.get("open", "00:00")),
            "close": str(data.get("close", "00:00")),
            "tz": str(data.get("tz", "UTC")),
        }
    except Exception:
        return dict(DEFAULT_SCHEDULE)


def validate_schedule(body: dict) -> dict:
    """Validate schedule payload."""
    if not isinstance(body, dict):
        raise Refused(400, "schedule body must be a JSON object")

    missing = [k for k in ("enabled", "open", "close", "tz") if k not in body]
    if missing:
        raise Refused(400, f"missing required schedule keys: {', '.join(missing)}")

    unknown = set(body.keys()) - SCHEDULE_SCHEMA_KEYS
    if unknown:
        raise Refused(400, f"unknown keys: {', '.join(sorted(unknown))}")

    if not isinstance(body["enabled"], bool):
        raise Refused(400, "enabled is required and must be a boolean")
    enabled = body["enabled"]

    open_time = body["open"]
    if not isinstance(open_time, str) or not TIME_RE.match(open_time):
        raise Refused(400, "open must be in HH:MM format (00:00 to 23:59)")

    close_time = body["close"]
    if not isinstance(close_time, str) or not TIME_RE.match(close_time):
        raise Refused(400, "close must be in HH:MM format (00:00 to 23:59)")

    tz = body["tz"]
    if not isinstance(tz, str) or not tz.strip():
        raise Refused(400, "tz is required and must be an IANA timezone name")
    tz = tz.strip()

    try:
        zoneinfo.ZoneInfo(tz)
    except Exception:
        raise Refused(400, f"invalid timezone: {tz}") from None

    return {
        "enabled": enabled,
        "open": open_time,
        "close": close_time,
        "tz": tz,
    }


def put_schedule(body: dict, schedule_file: str | None = None) -> tuple[int, dict]:
    """Atomically write schedule with 0o664 permissions, serialized with file lock."""
    clean = validate_schedule(body)
    sfile = schedule_file or os.environ.get("SCHEDULE_FILE", SCHEDULE_FILE)
    parent = os.path.dirname(os.path.abspath(sfile))
    os.makedirs(parent, exist_ok=True)

    lock_file = os.path.join(parent, ".schedule.lock")
    lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o664)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        payload = (json.dumps(clean, indent=2) + "\n").encode("utf-8")
        fd, tmp_path = tempfile.mkstemp(prefix=".schedule-", suffix=".tmp", dir=parent)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)

        with contextlib.suppress(OSError):
            os.chmod(tmp_path, 0o664)

        os.replace(tmp_path, sfile)

        with contextlib.suppress(OSError):
            dfd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    return 200, clean


def handle(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    environ: dict | None = None,
    requests_dir: str | None = None,
    anime_root: str | None = None,
    schedule_file: str | None = None,
    now: datetime.datetime | float | None = None,
) -> tuple[int, Any]:
    """Handle HTTP requests for /api/requests and /api/schedule."""
    clean_path = path.split("?")[0].rstrip("/")
    if clean_path == "/api/requests":
        if method == "GET":
            items = list_requests(requests_dir=requests_dir, now=now)
            return 200, items

        if method == "POST":
            try:
                return create(body or {}, anime_root=anime_root, requests_dir=requests_dir, now=now)
            except Refused as r:
                return r.status, {"error": r.error}

        return 405, {"error": "method not allowed"}

    if clean_path == "/api/schedule":
        if method == "GET":
            return 200, get_schedule(schedule_file=schedule_file)

        if method == "PUT":
            try:
                return put_schedule(body or {}, schedule_file=schedule_file)
            except Refused as r:
                return r.status, {"error": r.error}

        return 405, {"error": "method not allowed"}

    return 404, {"error": "not found"}


def main() -> None:
    """CLI for shell loops (next | unpack | start | finish | recover | prune | shows | window-open | write-effective-env)."""
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: review_requests.py next [DIR]|unpack JSON|start PATH|requeue PATH|"
            "finish PATH ok|fail [reason]|recover [DIR]|prune [DIR] [DAYS]|"
            "shows [DIR] [DAYS]|window-open [FILE]|write-effective-env [FILE]",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = args[0]
    if cmd == "next":
        target_dir = args[1] if len(args) > 1 else None
        rdir = target_dir or os.environ.get("REQUESTS_DIR", REQUESTS_DIR)
        while True:
            p = next_pending(rdir)
            if not p:
                sys.exit(1)
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("request file is not a JSON object")

                show = data.get("show")
                gen_re = data.get("generate_only_re")
                req_eng = data.get("require_eng")

                if not isinstance(show, str) or not show:
                    raise ValueError("invalid show name")
                if "/" in show or "\\" in show or ".." in show or "\0" in show:
                    raise ValueError("path traversal in show name")
                if _has_control_or_format_chars(show):
                    raise ValueError("control chars in show name")

                if gen_re is not None:
                    if not isinstance(gen_re, str) or _has_control_or_format_chars(gen_re):
                        raise ValueError("control chars in generate_only_re")

                if req_eng is not None and (isinstance(req_eng, bool) or req_eng not in (0, 1, "0", "1")):
                    raise ValueError("invalid require_eng")

                out_doc = {
                    "path": p,
                    "show": show,
                    "generate_only_re": gen_re or "",
                    "require_eng": "" if req_eng is None else str(req_eng),
                }
                print(json.dumps(out_doc))
                break
            except Exception as e:
                print(f"skipping invalid request file {p}: {e}", file=sys.stderr)
                finish(p, ok=False, error="invalid request file")

    elif cmd == "unpack":
        if len(args) < 2:
            sys.exit(1)
        data = json.loads(args[1])
        print(f"PATH={data.get('path', '')}")
        print(f"SHOW={data.get('show', '')}")
        print(f"GENERATE_ONLY_RE={data.get('generate_only_re', '')}")
        print(f"REQUIRE_ENG={data.get('require_eng', '')}")

    elif cmd == "start":
        if len(args) < 2:
            print("Usage: review_requests.py start PATH", file=sys.stderr)
            sys.exit(1)
        try:
            mark_running(args[1])
        except Exception as e:
            print(f"error marking running: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "requeue":
        if len(args) < 2:
            print("Usage: review_requests.py requeue PATH", file=sys.stderr)
            sys.exit(1)
        try:
            requeue(args[1])
        except Exception as e:
            print(f"error requeuing request: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "finish":
        if len(args) < 3:
            print("Usage: review_requests.py finish PATH ok|fail [reason]", file=sys.stderr)
            sys.exit(1)
        path = args[1]
        outcome = args[2]
        ok = outcome == "ok"
        reason = args[3] if len(args) > 3 else None
        try:
            finish(path, ok=ok, error=reason)
        except Exception as e:
            print(f"error finishing request: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "recover":
        target_dir = args[1] if len(args) > 1 else None
        recover_running(target_dir)

    elif cmd == "prune":
        target_dir = args[1] if len(args) > 1 else None
        rdir = target_dir or os.environ.get("REQUESTS_DIR", REQUESTS_DIR)
        days = int(args[2]) if len(args) > 2 else 7
        pruned = prune(os.path.join(rdir, "done"), os.path.join(rdir, "failed"), days=days)
        print(f"pruned {pruned} files")

    elif cmd == "shows":
        days = int(args[2]) if len(args) > 2 else 7
        for show in request_shows(args[1] if len(args) > 1 else None, days=days):
            print(show)

    elif cmd == "window-open":
        sfile = args[1] if len(args) > 1 else None
        print("open" if is_window_open(sfile) else "closed")

    elif cmd == "write-effective-env":
        out = args[1] if len(args) > 1 else None
        write_effective_env(out)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
