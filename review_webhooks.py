"""Sonarr/Radarr webhook receiver helpers (specs/arr-webhooks).

Turns Download/Upgrade events into run-request queue files; the loop stays the sole
executor. Pure functions with injected inputs (environ dicts, create/list_requests
callables) so tests need no server. The boss registers the routes; OPEN_ROUTES is
untouched and the token never appears in a log line, an error, or a payload --
this module has no logging at all.
"""

import datetime
import json
import os
import re
import secrets
import time
import urllib.parse

BODY_CAP = 256 * 1024
DEDUP_WINDOW_S = 24 * 3600
DEFAULT_ANIME_ROOT = "/media/Anime Library"

WEBHOOK_ROUTES = ("/api/webhook/sonarr", "/api/webhook/radarr")
TEST_MESSAGE = "webhook works, nothing enqueued"


def parse_mappings(text):
    """Parse REMOTE_PATH_MAPPINGS ("remote=local;...") into (remote, local) pairs, longest first.

    Entries with an extra '=' or empty sides cannot be mapped safely and are skipped.
    """
    out = []
    for entry in (text or "").split(";"):
        if entry.count("=") != 1:
            continue
        remote, local = entry.split("=", 1)
        # A trailing slash would break the component-boundary match below.
        remote, local = remote.strip().rstrip("/"), local.strip().rstrip("/")
        if not remote or not local:
            continue
        out.append((remote, local))
    out.sort(key=lambda kv: len(kv[0]), reverse=True)
    return out


def map_path(path, mappings):
    """Rewrite an arr-side path through the first (longest) matching remote prefix."""
    path = (path or "").replace("\\", "/")
    for remote, local in mappings or []:
        if path == remote:
            return local
        if path.startswith(remote + "/"):
            return local + path[len(remote) :]
    return path


def check_token(presented, environ=None):
    """None when the webhook token matches; (404/401/403, payload) otherwise.

    Unset WEBHOOK_TOKEN hides the routes entirely behind "no such route".
    """
    env = os.environ if environ is None else environ
    expected = env.get("WEBHOOK_TOKEN") or ""
    if not expected:
        return 404, {"error": "no such route"}
    if not presented:
        return 401, {"error": "a token is required"}
    try:
        ok = secrets.compare_digest(str(presented), expected)
    except TypeError:
        # str compare_digest is ASCII-only; compare UTF-8 bytes instead of failing open.
        ok = secrets.compare_digest(str(presented).encode("utf-8"), expected.encode("utf-8"))
    if not ok:
        return 403, {"error": "wrong token"}
    return None


def resolve_show(local_path, anime_root):
    """First path component below ANIME_ROOT after realpath confinement, else None.

    realpath (not abspath) so symlinks and ".." escaping the root resolve outside it.
    """
    if not local_path or not anime_root:
        return None
    # Arr may run on Windows; its separators are normalized before confinement.
    real_root = os.path.realpath(anime_root.replace("\\", "/"))
    real_path = os.path.realpath(local_path.replace("\\", "/"))
    if real_path == real_root or not real_path.startswith(real_root + os.sep):
        return None
    first = os.path.relpath(real_path, real_root).split(os.sep)[0]
    if first in ("", ".", ".."):
        return None
    return first


def _path_episodes(text):
    """(season, [episodes]) parsed from one SxxEyy... path, or (None, [])."""
    match = re.search(r"[Ss](\d+)[Ee](\d+)", text or "")
    if not match:
        return None, []
    season = int(match.group(1))
    episodes = [int(match.group(2))]
    episodes.extend(int(n) for n in re.findall(r"[Ee](\d+)", text[match.end() :]))
    return season, episodes


def episodes_from_payload(payload):
    """(season int|None, [episode ints]) for a Sonarr payload.

    SxxEyy (including multi-episode S01E01E02) wins; otherwise episodes[].seasonNumber
    with every episodes[].episodeNumber; otherwise a show-only (None, []).
    """
    payload = payload if isinstance(payload, dict) else {}
    files = payload.get("episodeFiles")
    if isinstance(files, dict):
        files = [files]
    if isinstance(payload.get("episodeFile"), dict):
        files = list(files or []) + [payload["episodeFile"]]
    season, episodes = None, []
    for item in files or []:
        if not isinstance(item, dict):
            continue
        text = item.get("relativePath") or item.get("path") or ""
        found_season, found = _path_episodes(text)
        if found:
            if season is None:
                season = found_season
            for number in found:
                if number not in episodes:
                    episodes.append(number)
    if episodes:
        return season, episodes
    numbers = payload.get("episodes")
    if isinstance(numbers, list) and numbers:
        first = numbers[0] if isinstance(numbers[0], dict) else {}
        season = first.get("seasonNumber") if isinstance(first.get("seasonNumber"), int) else None
        episodes = [e["episodeNumber"] for e in numbers if isinstance(e, dict) and isinstance(e.get("episodeNumber"), int)]
        return season, episodes
    return None, []


def _episode_re(episodes, season=None):
    """Episode-only branches anchored on E; derive_generate_only_re adds the season token.

    Specials (season None) carry their own [Ss]0*0[Ee] anchor so they never match
    another season. Anything over 200 characters is left to the caller, which
    falls back to a season-only request (review_requests.validate caps at 200).
    """
    if not episodes:
        return None
    inner = "|".join(str(number) for number in episodes)
    if season is None:
        return f"(?:[Ss]0*0[Ee]0*(?:{inner}))" + r"(?!\d)"
    return f"(?:[Ee]0*(?:{inner}))" + r"(?!\d)"


def _sonarr_request(payload, env, anime_root):
    event = payload.get("eventType") if isinstance(payload, dict) else None
    if event == "Test":
        return "test", TEST_MESSAGE
    if event not in ("Download", "Upgrade"):
        return "ignored", f"event {event} ignored"
    series = payload.get("series") if isinstance(payload, dict) else None
    remote_series = series.get("path") if isinstance(series, dict) else None
    if not remote_series:
        return "ignored", "missing series path"
    mappings = parse_mappings(env.get("REMOTE_PATH_MAPPINGS") or "")
    show = resolve_show(map_path(remote_series, mappings), anime_root)
    if show is None:
        return "ignored", "series path outside anime library"
    season, episodes = episodes_from_payload(payload)
    if season == 0:
        # Specials: review_requests.validate rejects season 0, so the request
        # carries no season and the episode regex scopes it.
        season = None
    files = payload.get("episodeFiles")
    if isinstance(files, dict):
        files = [files]
    remote_path = remote_series
    for item in files or []:
        if isinstance(item, dict) and item.get("path"):
            remote_path = item["path"]
            break
    else:
        single = payload.get("episodeFile")
        if isinstance(single, dict) and single.get("path"):
            remote_path = single["path"]
    episode_re = _episode_re(episodes, season)
    if episode_re is not None and len(episode_re) > 200:
        episode_re = None
    return "enqueue", {
        "show": show,
        "season": season,
        "episode_re": episode_re,
        "webhook": {"source": "sonarr", "event": event, "remote_path": remote_path},
    }


def _radarr_request(payload, env, anime_root):
    event = payload.get("eventType") if isinstance(payload, dict) else None
    if event == "Test":
        return "test", TEST_MESSAGE
    if event != "Download":
        return "ignored", f"event {event} ignored"
    movie = payload.get("movie") if isinstance(payload, dict) else None
    remote_folder = movie.get("folderPath") if isinstance(movie, dict) else None
    if not remote_folder:
        return "ignored", "missing movie path"
    mappings = parse_mappings(env.get("REMOTE_PATH_MAPPINGS") or "")
    show = resolve_show(map_path(remote_folder, mappings), anime_root)
    if show is None:
        return "ignored", "movie outside anime library"
    item = payload.get("movieFile")
    remote_path = remote_folder
    if isinstance(item, dict) and item.get("path"):
        remote_path = item["path"]
    return "enqueue", {
        "show": show,
        "season": None,
        "episode_re": None,
        "webhook": {"source": "radarr", "event": event, "remote_path": remote_path},
    }


def is_anime_hint(payload):
    """True when the payload hints at anime: series.type is "anime" or
    malIds/aniListIds is a non-empty list. Informational only -- never a filter;
    path confinement under ANIME_ROOT stays the gate. Malformed id fields
    (strings, null) read as absent rather than crashing."""
    series = payload.get("series") if isinstance(payload, dict) else None
    if not isinstance(series, dict):
        return False
    if series.get("type") == "anime":
        return True
    for key in ("malIds", "aniListIds"):
        ids = series.get(key)
        if isinstance(ids, list) and ids:
            return True
    return False


def build_request(source, payload, environ, anime_root):
    """("enqueue", body_for_create) | ("ignored", reason) | ("test", message)."""
    env = os.environ if environ is None else environ
    if source == "radarr":
        return _radarr_request(payload, env, anime_root)
    return _sonarr_request(payload, env, anime_root)


def _as_timestamp(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime.datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    if isinstance(value, str):
        try:
            dt = datetime.datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    return None


def _dedup_hit(items, show, remote_path, now_ts):
    """Id of a pending/done request for the same series plus file path within 24 h, else None.

    failed/ entries never block; entries without a readable timestamp cannot prove
    themselves inside the window, so they don't block either (create()'s own 409
    still guards an identical pending request).
    """
    for item in items or []:
        if not isinstance(item, dict) or item.get("status") == "failed":
            continue
        if item.get("show") != show:
            continue
        webhook = item.get("webhook")
        if not isinstance(webhook, dict) or webhook.get("remote_path") != remote_path:
            continue
        created = _as_timestamp(item.get("created_at"))
        if created is None or not 0 <= now_ts - created <= DEDUP_WINDOW_S:
            continue
        if item.get("id"):
            return item["id"]
    return None


def _present_token(headers, query):
    if headers:
        for name, value in headers.items():
            if isinstance(name, str) and name.lower() == "x-webhook-token":
                if value:
                    return value
                break
    values = query.get("token")
    if values:
        return values[0] or None
    return None


def handle(
    method,
    path,
    body=None,
    headers=None,
    environ=None,
    create=None,
    list_requests=None,
    anime_root=None,
    now=None,
):
    """POST /api/webhook/sonarr and /api/webhook/radarr; 404 otherwise.

    body is the parsed JSON (a dict), raw bytes/str (checked against the 256 KiB
    cap, then parsed), or None when the caller could not parse it (400). create
    and list_requests default to review_requests at call time; tests inject fakes.
    """
    env = os.environ if environ is None else environ
    route, _, query_string = (path or "").partition("?")
    if method != "POST" or route not in WEBHOOK_ROUTES:
        return 404, {"error": "no such route"}
    query = urllib.parse.parse_qs(query_string, keep_blank_values=True)
    allowed = check_token(_present_token(headers, query), env)
    if allowed is not None:
        return allowed
    if isinstance(body, dict):
        payload = body
    elif body is None:
        return 400, {"error": "invalid JSON"}
    elif isinstance(body, (bytes, bytearray, str)):
        raw = body if isinstance(body, str) else bytes(body)
        if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > BODY_CAP:
            return 413, {"error": "body too large"}
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return 400, {"error": "invalid JSON"}
        if not isinstance(payload, dict):
            return 400, {"error": "invalid JSON"}
    else:
        return 400, {"error": "invalid JSON"}
    source = "radarr" if route.endswith("/radarr") else "sonarr"
    aroot = anime_root or env.get("ANIME_ROOT") or DEFAULT_ANIME_ROOT
    now_ts = _as_timestamp(now)
    if now_ts is None:
        now_ts = time.time()
    action, data = build_request(source, payload, env, aroot)
    if action == "test":
        return 200, {"ok": True, "message": data}
    if action == "ignored":
        return 200, {"ok": True, "ignored": True, "reason": data}
    if create is None or list_requests is None:
        import review_requests

        create = create or review_requests.create
        list_requests = list_requests or review_requests.list_requests
    # Informational only: tells the caller the payload looked like anime. Never
    # a filter -- ignored/test responses and path confinement are untouched.
    hint = {"hint": "anime"} if is_anime_hint(payload) else {}
    hit = _dedup_hit(list_requests(), data["show"], data["webhook"]["remote_path"], now_ts)
    if hit is not None:
        return 200, {"ok": True, "id": hit, **hint}
    try:
        status, result = create(data, anime_root=aroot, now=now)
    except Exception as e:
        if hasattr(e, "status") and hasattr(e, "error"):
            # A refusal (missing show dir, invalid show, over-long regex) is not
            # an error to Sonarr: the hook stays green and the file waits.
            return 200, {"ok": True, "ignored": True, "reason": e.error}
        raise
    if status == 409:
        return 200, {"ok": True, "id": result.get("existing_id"), **hint}
    return 200, {"ok": True, "id": result.get("id"), **hint}
