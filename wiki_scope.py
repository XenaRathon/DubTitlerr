"""Wiki-scoping module for subtitle glossaries.

Resolves the wiki page titles ("spelling universe") for a show/season when the show
has no arc names in its metadata (e.g. Naruto, Pokemon, single-season shows).
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Callable, NamedTuple

from glossary_verify import _extract_links, _http_json


class ScopeResult(NamedTuple):
    titles: set[str]
    complete: bool
    rung: str
    notes: list[str]


DEFAULT_GLOBAL_DENY = [
    r"::",
]

DEFAULT_SEASON_DENY = [
    r"^EP\d+",
    r"\(EP\d+\)$",
    r"^Category:",
    r"^File:",
]


DEFAULT_STRUCTURAL_DENY = [
    r"^Chapter\s+\d+",
    r"^Volume\s+\d+",
    r"^Episode\s+\d+",
    r"^Main\s+Page$",
    r".*\s+Wiki$",
]


def normalize_title(title: str) -> str:
    """Normalise title: strip fragment, underscores to spaces, collapse spaces, uppercase first letter."""
    title = title.strip()
    if "#" in title:
        title = title.split("#")[0].strip()
    title = title.replace("_", " ").strip()
    title = re.sub(r"\s+", " ", title)
    if title:
        title = title[0].upper() + title[1:]
    return title


def _is_denied(title: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if re.search(pat, title, re.IGNORECASE):
            return True
    return False


def _parse_arc_rows(wt: str) -> tuple[list[tuple[str, set[int]]], list[str]]:
    """Parse wikitext table rows into (arc_title, episode_set) tuples and unparseable notes."""
    arcs: list[tuple[str, set[int]]] = []
    notes: list[str] = []
    rows = re.split(r"\n\|-", wt)
    for raw_row in rows:
        lines = [line.strip() for line in raw_row.splitlines() if line.strip()]
        if not lines or any(ln.startswith("!") for ln in lines):
            continue
        cells: list[str] = []
        for ln in lines:
            if ln.startswith("|") and not ln.startswith("|-") and not ln.startswith("|}"):
                parts = re.split(r"\|\|", ln[1:])
                for p in parts:
                    cells.append(p.strip())
        if not cells:
            continue

        arc_title = None
        for c in cells[:2]:
            m = re.search(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", c)
            if m:
                arc_title = m.group(1).strip()
                break
        if not arc_title:
            continue

        ep_cell = ""
        if len(cells) >= 4:
            ep_cell = cells[2]
        elif len(cells) == 3:
            ep_cell = cells[2] if re.search(r"\d+", cells[2]) else cells[1]
        elif len(cells) == 2:
            ep_cell = cells[1]

        if ep_cell in ("—", "-", "–", "N/A", "n/a", ""):
            continue

        episodes: set[int] = set()
        parts = [p.strip() for p in ep_cell.split(",") if p.strip()]
        for p in parts:
            m_range = re.match(r"^(\d+)\s*[-–—]\s*(\d+)$", p)
            m_single = re.match(r"^(\d+)$", p)
            if m_range:
                start, end = int(m_range.group(1)), int(m_range.group(2))
                if start <= end:
                    episodes.update(range(start, end + 1))
            elif m_single:
                episodes.add(int(m_single.group(1)))

        if episodes:
            arcs.append((arc_title, episodes))
        else:
            notes.append(f"unparseable arc row: {arc_title} ({ep_cell})")

    return arcs, notes


def _extract_table_episode_titles(wt: str) -> set[str]:
    """Extract episode titles and non-code link targets from wikitext episode tables."""
    episodes: set[str] = set()
    if not wt:
        return episodes

    tables = re.findall(r"(\{\|.*?\|\})", wt, re.DOTALL)
    for tbl in tables:
        rows = re.split(r"\n\|-", tbl)
        title_col_idx = None

        for raw_row in rows:
            lines = [ln.strip() for ln in raw_row.splitlines() if ln.strip()]
            if not lines:
                continue

            # Header row check
            if any(ln.startswith("!") for ln in lines):
                header_cells: list[str] = []
                for ln in lines:
                    if ln.startswith("!"):
                        parts = re.split(r"!!", ln[1:])
                        for p in parts:
                            if "|" in p:
                                p = p.split("|")[-1]
                            header_cells.append(p.strip())
                for idx, h in enumerate(header_cells):
                    if re.search(r"title", h, re.IGNORECASE):
                        title_col_idx = idx
                        break
                continue

            # Only process data rows if this table has an episode title column
            if title_col_idx is None:
                continue

            # Data row
            cells: list[str] = []
            for ln in lines:
                if ln.startswith("|") and not ln.startswith("|-") and not ln.startswith("|}"):
                    content = ln[1:]
                    parts = re.split(r"\|\|", content)
                    for p in parts:
                        p_str = p.strip()
                        # If cell has style/attribute separator: style="..." | text
                        has_link = "[[" in p_str and "]]" in p_str
                        pipe_in_link = has_link and p_str.find("[[") < p_str.find("|") < p_str.find("]]")
                        if "|" in p_str and not pipe_in_link:
                            pipe_parts = p_str.split("|")
                            if any(attr in pipe_parts[0] for attr in ("style=", "class=", "rowspan=", "colspan=")):
                                p_str = "|".join(pipe_parts[1:]).strip()
                        cells.append(p_str)

            if not cells or len(cells) <= title_col_idx:
                continue

            # Extract from title column
            raw_cell = cells[title_col_idx]
            for m in re.finditer(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", raw_cell):
                episodes.add(m.group(1).strip())
            clean_text = re.sub(r"\[\[(?:[^\]|#]+\|)?([^\]]*)\]\]", r"\1", raw_cell)
            clean_text = re.sub(r"'''+|''+|\<[^\>]*\>", "", clean_text).strip()
            if clean_text:
                episodes.add(clean_text)

            # In this episode table, also check if epicode cell has a link that is not EP\d+ or number
            if len(cells) > 0:
                for m in re.finditer(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", cells[0]):
                    target = m.group(1).strip()
                    if not re.match(r"^EP\d+$", target) and not re.match(r"^\d+$", target):
                        episodes.add(target)

    return episodes


def resolve_scope(
    cfg: dict | None,
    season: int | str | None = None,
    episode_numbers: list[int] | set[int] | None = None,
    http: Callable[[str], dict] | None = None,
) -> ScopeResult:
    """Resolve wiki page titles for a show/season without arc names.

    Pure and testable; all HTTP operations go through the injected `http` callable.
    """
    if not cfg or not isinstance(cfg, dict):
        return ScopeResult(titles=set(), complete=False, rung="none", notes=["missing or empty wiki_scope configuration"])

    rung = cfg.get("rung")
    if rung not in ("arc_index", "season_page", "whole_wiki"):
        return ScopeResult(titles=set(), complete=False, rung="none", notes=[f"unsupported rung: {rung!r}"])

    wiki = cfg.get("wiki", "").rstrip("/")
    if not wiki:
        return ScopeResult(titles=set(), complete=False, rung=rung, notes=["missing wiki api url in config"])

    fetch_json = http or _http_json
    notes: list[str] = []
    custom_deny = list(cfg.get("deny") or [])

    # Calculate absolute episode numbers if provided
    offsets = cfg.get("season_offsets") or {}
    offset = 0
    if season is not None:
        offset = int(offsets.get(str(season), offsets.get(season, 0)))

    if episode_numbers is not None:
        req_eps = {int(e) + offset for e in episode_numbers}
    else:
        req_eps = set()

    # -------------------------------------------------------------------------
    # Rung 1: arc_index
    # -------------------------------------------------------------------------
    if rung == "arc_index":
        index_page = cfg.get("index_page", "Plot of Naruto")
        url = f"{wiki}?action=parse&page={urllib.parse.quote(index_page)}&prop=wikitext&format=json"
        try:
            resp = fetch_json(url)
        except Exception as e:
            msg = f"http error fetching index page {index_page}: {e}"
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=[msg])

        if not resp or "error" in resp:
            err = resp.get("error") if resp else "empty response"
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=[f"error in index page response: {err}"])

        wt = resp.get("parse", {}).get("wikitext", {}).get("*", "")
        arcs, parse_notes = _parse_arc_rows(wt)
        notes.extend(parse_notes)

        # Match arcs overlapping the requested absolute episode numbers
        matching_arcs = [arc_title for arc_title, arc_eps in arcs if not req_eps or bool(arc_eps & req_eps)]

        all_titles: set[str] = set()
        complete = True

        for arc_title in matching_arcs:
            arc_url = f"{wiki}?action=parse&page={urllib.parse.quote(arc_title)}&prop=wikitext&format=json"
            try:
                arc_resp = fetch_json(arc_url)
            except Exception as e:
                complete = False
                notes.append(f"http error fetching arc page {arc_title}: {e}")
                continue

            if not arc_resp or "error" in arc_resp:
                complete = False
                notes.append(f"error response for arc page {arc_title}: {arc_resp.get('error') if arc_resp else 'empty'}")
                continue

            arc_wt = arc_resp.get("parse", {}).get("wikitext", {}).get("*", "")
            links = _extract_links(arc_wt)
            all_titles.update(links)

        deny_patterns = DEFAULT_GLOBAL_DENY + custom_deny
        filtered = {
            normalize_title(t)
            for t in all_titles
            if normalize_title(t) and not _is_denied(t, deny_patterns)
        }
        return ScopeResult(titles=filtered, complete=complete, rung=rung, notes=notes)

    # -------------------------------------------------------------------------
    # Rung 2: season_page
    # -------------------------------------------------------------------------
    if rung == "season_page":
        season_fmt = cfg.get("season_page", "S{season:02d}")
        if season is None:
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=["season number required for season_page rung"])

        try:
            page_title = season_fmt.format(season=int(season))
        except Exception as e:
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=[f"failed to format season_page: {e}"])

        url = f"{wiki}?action=parse&page={urllib.parse.quote(page_title)}&prop=links|wikitext&format=json"
        try:
            resp = fetch_json(url)
        except Exception as e:
            msg = f"http error fetching season page {page_title}: {e}"
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=[msg])

        if not resp or "error" in resp:
            err = resp.get("error") if resp else "empty response"
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=[f"error in season page response: {err}"])

        raw_titles: set[str] = set()
        parse_obj = resp.get("parse", {})
        if "links" in parse_obj:
            raw_titles = {item["*"] for item in parse_obj["links"] if item.get("ns") in (0, None)}
        elif "wikitext" in parse_obj:
            raw_titles = _extract_links(parse_obj["wikitext"].get("*", ""))

        season_wt = parse_obj.get("wikitext", {}).get("*", "")
        table_episodes: set[str] = set()

        ep_list_page_cfg = cfg.get("episode_list_page")
        if ep_list_page_cfg:
            try:
                ep_list_page = ep_list_page_cfg.format(season=int(season))
            except Exception:
                ep_list_page = str(ep_list_page_cfg)
            ep_url = f"{wiki}?action=parse&page={urllib.parse.quote(ep_list_page)}&prop=wikitext&format=json"
            try:
                ep_resp = fetch_json(ep_url)
                if ep_resp and "parse" in ep_resp:
                    ep_wt = ep_resp.get("parse", {}).get("wikitext", {}).get("*", "")
                    table_episodes.update(_extract_table_episode_titles(ep_wt))
                else:
                    err_msg = ep_resp.get("error") if ep_resp else "empty"
                    notes.append(f"warning: error fetching episode_list_page {ep_list_page}: {err_msg}")
            except Exception as e:
                notes.append(f"warning: http error fetching episode_list_page {ep_list_page}: {e}")
        elif season_wt:
            table_episodes.update(_extract_table_episode_titles(season_wt))

        deny_patterns = DEFAULT_GLOBAL_DENY + DEFAULT_SEASON_DENY + custom_deny
        normalized_table_episodes = {normalize_title(t) for t in table_episodes if normalize_title(t)}

        filtered = {
            normalize_title(t)
            for t in raw_titles
            if normalize_title(t)
            and not _is_denied(t, deny_patterns)
            and normalize_title(t) not in normalized_table_episodes
        }
        return ScopeResult(titles=filtered, complete=True, rung=rung, notes=notes)

    # -------------------------------------------------------------------------
    # Rung 3: whole_wiki
    # -------------------------------------------------------------------------
    if rung == "whole_wiki":
        all_raw_titles: set[str] = set()
        complete = True
        apcontinue: str | None = None
        max_pages = 10
        pages_fetched = 0

        while pages_fetched < max_pages:
            url = f"{wiki}?action=query&list=allpages&apnamespace=0&aplimit=500&format=json"
            if apcontinue:
                url += f"&apcontinue={urllib.parse.quote(str(apcontinue))}"

            try:
                resp = fetch_json(url)
                pages_fetched += 1
            except Exception as e:
                complete = False
                notes.append(f"http error fetching allpages (page {pages_fetched}): {e}")
                break

            if not resp or "error" in resp:
                complete = False
                err = resp.get("error") if resp else "empty response"
                notes.append(f"error in allpages response: {err}")
                break

            for p in resp.get("query", {}).get("allpages", []):
                title = p.get("title")
                if title:
                    all_raw_titles.add(title)

            apcontinue = resp.get("continue", {}).get("apcontinue")
            if not apcontinue:
                break
        else:
            if apcontinue:
                complete = False
                notes.append("allpages exceeded 10-page limit (continuation truncated)")

        deny_patterns = DEFAULT_GLOBAL_DENY + DEFAULT_STRUCTURAL_DENY + custom_deny
        filtered = {
            normalize_title(t)
            for t in all_raw_titles
            if normalize_title(t) and not _is_denied(t, deny_patterns)
        }
        return ScopeResult(titles=filtered, complete=complete, rung=rung, notes=notes)

    return ScopeResult(titles=set(), complete=False, rung="none", notes=["unhandled execution path"])
