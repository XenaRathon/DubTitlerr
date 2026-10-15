"""The glossary editor backend: GET/POST /api/glossary (specs/webui-glossary-editor/spec.md).

Edits only ``names``, ``phrases``, ``hard_fixes`` and the ``wiki`` override of a deployed glossary; every other key (the
machine-owned verified/flagged/acquired/known/_curated, any underscore key, initial_prompt, ...) is
loaded and written back untouched. ``show`` is resolved only against the server-side list of
``*.json`` in decisions.GLOSSARY_DIR, never used as a path, and no media tree is ever walked.

A write holds glossary_lock.locked(path, "webui"), refuses a stale ``expected_version`` (sha256 of
the raw file bytes), copies the prior file to ``<file>.bak-<UTC timestamp>`` (newest 20 kept), and
swaps the new content in with a temp file plus os.replace in the same directory."""

import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata

import decisions
import glossary_lock
import glossary_verify
from common import log

EDITABLE = ("names", "phrases", "hard_fixes")
OPS = ("add", "update", "delete")
KEEP_BACKUPS = 20
MAX_BODY = 64 * 1024
MAX_WIKI = 300
_LIMITS = {"names": 80, "phrases": 120, "hard_fixes": 120}
# Sidecars that live next to a glossary and are not glossaries themselves.
_SIDECAR = re.compile(r"\.(acquire-cache|lastrun|journal)\.json$|\.review-pending|\.bak-")
# Characters no term may carry: controls, format/bidi/zero-width, surrogates, private use, and the line and
# paragraph separators (which would split an audit log line). A plain space (Zs) is fine.
_BAD_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Co", "Zl", "Zp"))


class _Refused(Exception):
    """A request that fails validation: carries the (status, payload) to answer with."""

    def __init__(self, status, error, **extra):
        super().__init__(error)
        self.reply = (status, {"error": error, **extra})


def _dir():
    return decisions.GLOSSARY_DIR


def _path(show):
    return os.path.join(_dir(), show + ".json")


def list_shows(gdir=None):
    """Sorted stems of the glossary files in the directory; sidecars and backups are not glossaries."""
    root = gdir or _dir()
    try:
        entries = list(os.scandir(root))
        real_root = os.path.realpath(root)
    except OSError:
        return []
    return sorted(
        e.name[:-5]
        for e in entries
        if e.name.endswith(".json")
        and not _SIDECAR.search(e.name)
        and e.is_file(follow_symlinks=False)  # a regular file: not a symlink, not a directory
        and os.path.realpath(e.path).startswith(real_root + os.sep)
    )


def _check_show(show):
    """Resolve ``show`` against the server-side list. Anything that could be a path never reaches the disk."""
    if not isinstance(show, str) or not show or show in (".", "..") or any(c in show for c in "/\\\x00"):
        raise _Refused(400, "invalid show")
    if show not in list_shows():
        raise _Refused(404, "no such glossary")
    return show


def _load(show):
    """(raw bytes, parsed dict) of a deployed glossary, or a _Refused for a missing/unreadable/corrupt file."""
    try:
        fd = os.open(_path(show), os.O_RDONLY | os.O_NOFOLLOW)  # a symlink swapped in after listing is refused
        with os.fdopen(fd, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        raise _Refused(404, "no such glossary") from None
    except OSError:
        raise _Refused(500, "glossary unreadable") from None
    try:
        cfg = json.loads(raw.decode("utf-8"))
    except ValueError:  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        raise _Refused(500, "glossary corrupt") from None
    if not isinstance(cfg, dict):
        raise _Refused(500, "glossary corrupt")
    # A present editable key of the wrong type would be rewritten as something else (a string iterated into
    # characters, pairs flattened into a dict). null means "absent" and stays tolerated.
    for key, want in (("names", list), ("phrases", list), ("hard_fixes", dict)):
        if cfg.get(key) is not None and not isinstance(cfg[key], want):
            raise _Refused(500, "glossary corrupt")
    return raw, cfg


def _version(raw):
    return hashlib.sha256(raw).hexdigest()


def read_show(show):
    try:
        raw, cfg = _load(_check_show(show))
    except _Refused as r:
        return r.reply
    return 200, {
        "show": show,
        "version": _version(raw),
        "names": list(cfg.get("names") or []),
        "phrases": list(cfg.get("phrases") or []),
        "hard_fixes": dict(cfg.get("hard_fixes") or {}),
        "wiki": cfg["wiki"] if isinstance(cfg.get("wiki"), str) else "",
    }


def _text(value, key, what):
    """A trimmed, length-bounded string without control characters."""
    if not isinstance(value, str):
        raise _Refused(400, f"{what} must be a string")
    value = unicodedata.normalize("NFC", value.strip())
    if not value or len(value) > _LIMITS[key]:
        raise _Refused(400, f"{what} must be 1-{_LIMITS[key]} characters")
    if any(unicodedata.category(c) in _BAD_CATEGORIES for c in value):
        raise _Refused(400, f"{what} must not contain control or invisible characters")
    if key in ("names", "phrases") and "\\" in value:
        raise _Refused(400, f"{what} must not contain a backslash")
    if key == "phrases" and " " not in value:
        raise _Refused(400, "a phrase needs a space; single words belong in names")
    return value


def _wiki(value):
    """The trimmed wiki override as typed ("" clears it). The URL rules are glossary_verify.normalize_api's, not copied."""
    if not isinstance(value, str):
        raise _Refused(400, "wiki must be a string")
    value = unicodedata.normalize("NFC", value.strip())
    if len(value) > MAX_WIKI:
        raise _Refused(400, f"wiki must be at most {MAX_WIKI} characters")
    if any(unicodedata.category(c) in _BAD_CATEGORIES for c in value):
        raise _Refused(400, "wiki must not contain control or invisible characters")
    if value and (
        glossary_verify.normalize_api(value) is None or glossary_verify._wiki_url_problem(value, glossary_verify._wiki_schemes())
    ):
        raise _Refused(
            400,
            "wiki must be an https URL (http only with WIKI_ALLOW_HTTP=1) with a public host and no credentials, e.g. https://yugioh.fandom.com",
        )
    return value


def wiki_test(body):
    """(status, payload) for POST /api/glossary/wiki-test: one siteinfo GET through glossary_verify's own fetch."""
    url = body.get("url") if isinstance(body, dict) else None
    api = glossary_verify.normalize_api(url) if isinstance(url, str) and url.strip() else None
    if api is None:
        return 400, {"error": "url must be an https URL (http only with WIKI_ALLOW_HTTP=1) with a public host and no credentials"}
    try:
        sitename = glossary_verify._http_json(api + "?action=query&meta=siteinfo&format=json")["query"]["general"]["sitename"]
    except KeyError:
        return 200, {"ok": False, "api": api, "error": "no MediaWiki siteinfo in the response"}
    except Exception as exc:  # any fetch failure is a result for the operator, not a server error
        return 200, {"ok": False, "api": api, "error": (str(exc) or type(exc).__name__)[:200]}
    return 200, {"ok": True, "api": api, "sitename": sitename}


def _nfc(value):
    return unicodedata.normalize("NFC", str(value))


def _fold(value):
    return _nfc(value).lower()


def apply_op(cfg, req):
    """(new cfg, term, value) with one validated edit applied; raise _Refused otherwise. Pure: no I/O.

    ``term`` and ``value`` are the validated (trimmed, NFC) strings; ``value`` is None unless the op carries one."""
    op, key = req.get("op"), req.get("key")
    if op not in OPS:
        raise _Refused(400, "op must be add, update or delete")
    if key not in EDITABLE:
        raise _Refused(400, "key must be names, phrases or hard_fixes")
    term = _text(req.get("term"), key, "term")
    new = dict(cfg)
    value = None
    if key == "hard_fixes":
        fixes = dict(new.get("hard_fixes") or {})
        have = {_fold(k): k for k in fixes}  # load lowercases keys, so duplicates are case-insensitive
        existing = have.get(_fold(term))
        if op == "delete":
            if existing is None:
                raise _Refused(400, "no such term")
            del fixes[existing]
        else:
            value = _text(req.get("value"), key, "value")
            if _fold(term) == _fold(value):
                raise _Refused(400, "a fix must change the text")
            if op == "add":
                if existing is not None:
                    raise _Refused(400, "term already exists")
                fixes[term] = value
            else:
                if existing is None:
                    raise _Refused(400, "no such term")
                fixes[existing] = value
        new["hard_fixes"] = fixes
        return new, term, value
    items = list(new.get(key) or [])
    # Compared NFC-folded so a decomposed spelling finds its composed twin; stored entries are never rewritten.
    folded = [_nfc(i) for i in items]
    if op == "add":
        if term in folded:
            raise _Refused(400, "term already exists")
        items.append(term)
    elif term not in folded:
        raise _Refused(400, "no such term")
    elif op == "delete":
        del items[folded.index(term)]
    else:
        value = _text(req.get("value"), key, "value")
        if value == term:
            raise _Refused(400, "a rename must change the text")
        if value in folded:
            raise _Refused(400, "term already exists")
        items[folded.index(term)] = value
    new[key] = items
    return new, term, value


def _dump(raw, cfg):
    """Serialize ``cfg`` in the file's own style: its indent width (or tab) and trailing newline."""
    m = re.search(rb"\n([ \t]+)\S", raw)
    indent = "\t" if m and m.group(1).startswith(b"\t") else (len(m.group(1)) if m else 2)
    text = json.dumps(cfg, indent=indent, ensure_ascii=False)
    return (text + ("\n" if raw.endswith(b"\n") else "")).encode("utf-8")


def prune_backups(path, keep=KEEP_BACKUPS):
    """Keep only the newest ``keep`` ``<path>.bak-*`` files (the UTC stamp sorts chronologically)."""
    d, base = os.path.split(path)
    old = sorted(n for n in os.listdir(d) if n.startswith(base + ".bak-"))
    for name in old[: max(0, len(old) - keep)]:
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(d, name))


def _write(path, new_bytes):
    """Back up the current file, then replace it atomically. Returns the backup's file name."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = f"{path}.bak-{stamp}"
    n = 0
    while os.path.exists(backup):  # two writes in one clock tick must not overwrite the first undo point
        n += 1
        backup = f"{path}.bak-{stamp}-{n}"  # sorts after the plain stamp, so prune still keeps the newest
    tmp = None
    try:
        shutil.copy2(path, backup)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".glossary-", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        # Nothing was committed: neither the temp file nor the undo copy of an edit that never happened may stay.
        for leftover in (tmp, backup):
            if leftover:
                with contextlib.suppress(OSError):
                    os.unlink(leftover)
        raise
    with contextlib.suppress(OSError):  # make the rename itself durable; the edit is committed either way
        dfd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    with contextlib.suppress(OSError):  # the edit is committed; a failed prune must not turn it into an error
        prune_backups(path)
    return os.path.basename(backup)


def write_show(body, operator, role="user"):
    try:
        if len(json.dumps(body, ensure_ascii=False).encode("utf-8", "surrogatepass")) > MAX_BODY:
            raise _Refused(413, "body too large")
        if "wiki" in body and role != "admin":  # the route is user-level for term edits; the wiki steers fetches
            raise _Refused(403, "admin only")
        show = _check_show(body.get("show"))
        expected = body.get("expected_version")
        if not isinstance(expected, str) or not expected:
            raise _Refused(400, "expected_version is required")
        path = _path(show)
        with glossary_lock.locked(path, "webui") as got:
            if not got:
                return 503, {"error": "glossary busy"}
            raw, cfg = _load(show)  # re-read under the lock: the version check and the write see one file
            if _version(raw) != expected:
                return 409, {"error": "version conflict", "version": _version(raw)}
            new, term, value = cfg, None, None
            if "op" in body or "wiki" not in body:
                new, term, value = apply_op(cfg, body)
            wiki = None
            if "wiki" in body:
                wiki = _wiki(body["wiki"])
                new = dict(new)
                if wiki:
                    new["wiki"] = wiki
                else:
                    new.pop("wiki", None)
            new_bytes = _dump(raw, new)
            try:
                backup = _write(path, new_bytes)
            except OSError:
                return 500, {"error": "glossary write failed"}
    except _Refused as r:
        return r.reply
    at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    if term is not None:
        shown = "" if value is None else f" value={json.dumps(value, ensure_ascii=False)}"
        log(
            f"glossary edit: at={at} operator={operator} show={json.dumps(show)} op={body['op']} "
            f"key={body['key']} term={json.dumps(term, ensure_ascii=False)}{shown} backup={backup}"
        )
    if wiki is not None:
        log(
            f"glossary edit: at={at} operator={operator} show={json.dumps(show)} op={'set' if wiki else 'delete'} "
            f"key=wiki value={json.dumps(wiki, ensure_ascii=False)} backup={backup}"
        )
    return 200, {"ok": True, "show": show, "version": _version(new_bytes), "backup": backup, "reapply_hint": True}


def handle(method, path, body, operator="anonymous", role="user"):
    """(status, payload) for /api/glossary. Authentication is the caller's: route() has already checked the token."""
    if path != "/api/glossary":
        return 404, {"error": "no such route"}
    if method == "GET":
        show = body.get("show") if isinstance(body, dict) else None
        if show is None or show == "":
            return 200, {"shows": list_shows()}
        return read_show(show)
    if method == "POST":
        if not isinstance(body, dict):
            return 400, {"error": "a JSON object is required"}
        return write_show(body, operator, role)
    return 404, {"error": "no such route"}
