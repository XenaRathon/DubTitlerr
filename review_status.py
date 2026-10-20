"""Read-only episode status dashboard backend (specs/webui-status-dashboard/spec.md).

GET /api/status returns pipeline progress per episode without performing filesystem tree walks.
Stems are sourced from the existing _STEMS_CACHE in review_server.py.
Sidecar inspection is bounded to at most 5 small sidecar reads per stem, only for the requested
page slice.
"""

import json
import math
import os
import time

import common
import decisions
import unresolved

STAGES = ("transcribed", "repaired", "muxed", "failed", "stale", "pending-review")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _parse_int(val, default: int, min_val: int = 1, max_val: int | None = None) -> int:
    try:
        n = int(val)
        if n < min_val:
            return default
        if max_val is not None and n > max_val:
            return max_val
        return n
    except (TypeError, ValueError):
        return default


def _num(v) -> float | None:
    """Finite float guard (M4): returns float or None if missing, NaN, or infinite."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _extract_stems(stems_cache) -> tuple[list[str], float | None]:
    """Unpack (stems, filled_at) from cache structure."""
    if stems_cache is None:
        return [], None
    if isinstance(stems_cache, tuple):
        if len(stems_cache) >= 3 and isinstance(stems_cache[1], list):
            return list(stems_cache[1]), _num(stems_cache[2])
        if len(stems_cache) == 2 and isinstance(stems_cache[1], list):
            return list(stems_cache[1]), None
        return [], None
    if isinstance(stems_cache, list):
        return list(stems_cache), None
    return [], None


def _stem_metadata(stem: str) -> tuple[str, str, str]:
    """Derive (show, season, episode) from stem path without filesystem access."""
    episode = os.path.basename(stem)
    season_dir = os.path.dirname(stem)
    season = os.path.basename(season_dir)
    show_dir = os.path.dirname(season_dir)
    show = os.path.basename(show_dir)
    return show, season, episode


def _read_repair_summary(stem: str) -> str | None:
    """Open .dubtitles.repair-summary.json directly without duplicate exists() calls."""
    path = stem + ".dubtitles.repair-summary.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                model = data.get("model")
                return str(model) if model is not None else None
    except (OSError, ValueError, TypeError):
        pass
    return None


def _pending_count(stem: str, open_entries, stores: dict) -> int:
    """Compute pending review count via provided open_entries callable and decisions.show_for."""
    if open_entries is None:
        return 0
    try:
        entries = open_entries(stem)
        if not entries:
            return 0
        sh = decisions.show_for(stem)
        if sh not in stores:
            stores[sh] = decisions.load(sh, decisions.DECISIONS_DIR) if sh else {}
        live = unresolved.undecided(entries, stores[sh])
        return len(live)
    except Exception:
        return 0


def _determine_outcome(stages: dict, default: str = "unknown") -> str:
    if not stages:
        return default
    for st in common.STAGE_ORDER:
        if st in stages and isinstance(stages[st], dict):
            out = stages[st].get("outcome")
            if out and out not in common._PASSED_OUTCOMES:
                return str(out)
    for st in reversed(common.STAGE_ORDER):
        if st in stages and isinstance(stages[st], dict):
            out = stages[st].get("outcome")
            if out:
                return str(out)
    for _st, info in stages.items():
        if isinstance(info, dict) and "outcome" in info:
            return str(info["outcome"])
    return default


def _inspect_episode(stem: str, open_entries, stores: dict) -> dict:
    show, season, episode = _stem_metadata(stem)

    # 1. Fail poison marker check (.dubtitles.fail)
    has_fail = os.path.exists(stem + ".dubtitles.fail")

    # 2. Done stamp check (.dubtitles.done)
    stamp = common.read_stamp(stem + common.STAMP_SUFFIX)
    text_version = None
    mtime = None
    is_muxed = False
    is_stale = False
    if stamp is not None and isinstance(stamp, dict):
        tv = common._tier_version(stamp, "transcribe_version")
        xv = common._tier_version(stamp, "text_version")
        text_version = xv
        is_stale = (
            tv is None
            or tv < common.TRANSCRIBE_VERSION
            or xv is None
            or xv < common.TEXT_VERSION
        )
        mtime = _num(stamp.get("mtime"))
        is_muxed = bool(stamp.get("muxed"))

    # 3. Stages sidecar (.dubtitles.stages.json) - read ONCE, normalised (H2)
    stages_path = stem + common.STAGES_SUFFIX
    try:
        with open(stages_path, encoding="utf-8") as f:
            stages_raw = json.load(f)
    except (OSError, ValueError):
        stages_raw = {}
    stages = (
        {k: v for k, v in stages_raw.items() if isinstance(v, dict)}
        if isinstance(stages_raw, dict)
        else {}
    )

    # 4. Repair summary (.dubtitles.repair-summary.json) - open directly
    repair_model = _read_repair_summary(stem)

    # 5. Pending review count via open_entries (no disk queue read)
    pending_count = _pending_count(stem, open_entries, stores)

    # Compute failed stage from normalised dict without disk re-read
    failed_stg = None
    names = [st for st in common.STAGE_ORDER if st in stages] + [st for st in stages if st not in common.STAGE_ORDER]
    for st in names:
        out = stages[st].get("outcome")
        if out not in common._PASSED_OUTCOMES:
            failed_stg = st
            break

    # Stage classification
    if has_fail:
        stage = "failed"
        last_outcome = "crashed"
    elif failed_stg:
        stage = "failed"
        last_outcome = stages.get(failed_stg, {}).get("outcome", "unknown")
    elif stamp is not None and is_stale:
        stage = "stale"
        last_outcome = _determine_outcome(stages, default="ok" if stamp else "unknown")
    elif pending_count > 0:
        stage = "pending-review"
        last_outcome = _determine_outcome(stages, default="ok" if stamp else "unknown")
    elif stamp is not None and is_muxed:
        stage = "muxed"
        last_outcome = _determine_outcome(stages, default="ok")
    elif repair_model is not None or "repair" in stages:
        stage = "repaired"
        last_outcome = _determine_outcome(stages, default="ok" if "repair" in stages else "unknown")
    else:
        stage = "transcribed"
        last_outcome = _determine_outcome(stages, default="unknown")

    # updated_at calculation with finite float guard (M4)
    updated_at = mtime
    if stages:
        for s_info in stages.values():
            s_at = _num(s_info.get("at"))
            if s_at is not None:
                if updated_at is None or s_at > updated_at:
                    updated_at = s_at

    return {
        "show": show,
        "season": season,
        "episode": episode,
        "stem": stem,
        "stage": stage,
        "last_outcome": last_outcome,
        "repair_model": repair_model,
        "text_version": text_version,
        "pending_review_count": pending_count,
        "updated_at": updated_at,
    }


def _inspect_episode_safe(stem: str, open_entries, stores: dict) -> dict:
    """Inspect one stem wrapped in safe fallback (H2)."""
    show, season, episode = _stem_metadata(stem)
    try:
        return _inspect_episode(stem, open_entries, stores)
    except Exception:
        return {
            "show": show,
            "season": season,
            "episode": episode,
            "stem": stem,
            "stage": "transcribed",
            "last_outcome": "unknown",
            "repair_model": None,
            "text_version": None,
            "pending_review_count": 0,
            "updated_at": None,
        }


def _read_header(now, filled_at, episodes_on_page: list[dict], total: int, page: int, limit: int, pages: int) -> dict:
    hb = common.read_heartbeat()
    builder_heartbeat_age_s = None
    last_sweep_end = None
    current_show = None

    if hb is not None and isinstance(hb, dict):
        last_sweep_end = _num(hb.get("last_sweep_end"))
        c_show = hb.get("current_show")
        current_show = str(c_show) if c_show is not None else None

        hb_path = getattr(common, "HEARTBEAT_PATH", "/config/heartbeat.json")
        try:
            builder_heartbeat_age_s = _num(max(0.0, round(time.time() - os.path.getmtime(hb_path), 1)))
        except OSError:
            if last_sweep_end is not None:
                builder_heartbeat_age_s = _num(max(0.0, round(time.time() - last_sweep_end, 1)))
            elif hb.get("last_sweep_start") is not None:
                start = _num(hb.get("last_sweep_start"))
                if start is not None:
                    builder_heartbeat_age_s = _num(max(0.0, round(time.time() - start, 1)))

    cache_age_s = None
    if now is not None and filled_at is not None:
        now_f = _num(now)
        filled_f = _num(filled_at)
        if now_f is not None and filled_f is not None:
            cache_age_s = _num(max(0.0, round(now_f - filled_f, 1)))

    counts_per_stage = {st: 0 for st in STAGES}
    for ep in episodes_on_page:
        st = ep.get("stage")
        if st in counts_per_stage:
            counts_per_stage[st] += 1

    return {
        "builder_heartbeat_age_s": builder_heartbeat_age_s,
        "last_sweep_end": last_sweep_end,
        "current_show": current_show,
        "counts_per_stage": counts_per_stage,
        "counts_scope": "page",
        "cache_age_s": cache_age_s,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def handle_status(
    query: dict | None = None,
    stems_cache=None,
    open_entries=None,
    now=None,
) -> tuple[int, dict]:
    """Return status and JSON payload for GET /api/status."""
    if stems_cache is None:
        return 503, {"error": "cache warming", "boot_id": common.boot_id()}

    # Handle positional 3rd argument passed as now
    if isinstance(open_entries, (int, float)) and now is None:
        now = open_entries
        open_entries = None

    stems, filled_at = _extract_stems(stems_cache)

    query = query or {}
    req_show = query.get("show")
    if req_show:
        req_show = str(req_show).strip()
        filtered = [s for s in stems if _stem_metadata(s)[0] == req_show]
    else:
        filtered = stems

    total = len(filtered)
    limit = _parse_int(query.get("limit"), DEFAULT_LIMIT, min_val=1, max_val=MAX_LIMIT)
    pages = math.ceil(total / limit) if total > 0 else 1
    page = _parse_int(query.get("page"), 1, min_val=1)

    if page > pages or total == 0:
        slice_stems = []
    else:
        start = (page - 1) * limit
        end = start + limit
        slice_stems = filtered[start:end]

    stores: dict = {}
    episodes = [_inspect_episode_safe(stem, open_entries, stores) for stem in slice_stems]
    header = _read_header(now, filled_at, episodes, total=total, page=page, limit=limit, pages=pages)

    return 200, {"header": header, "episodes": episodes, "boot_id": common.boot_id()}


def handle(
    method: str,
    path: str,
    body: dict | None = None,
    token=None,
    stems_cache=None,
    open_entries=None,
    now=None,
) -> tuple[int, dict]:
    """Route handler conforming to parallel webui specs."""
    if path != "/api/status":
        return 404, {"error": "no such route"}
    if method != "GET":
        return 405, {"error": "method not allowed"}
    return handle_status(body or {}, stems_cache=stems_cache, open_entries=open_entries, now=now)
