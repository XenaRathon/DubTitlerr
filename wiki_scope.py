"""Wiki-scoping module for subtitle glossaries.

Resolves the wiki page titles ("spelling universe") for a show/season when the show
has no arc names in its metadata (e.g. Naruto, Pokemon, single-season shows).
"""

from __future__ import annotations

import html
import os
import re
import urllib.parse
from typing import Callable, NamedTuple

import glossary_verify
from glossary_verify import _extract_links, _http_json, redirect_targets


class ScopeResult(NamedTuple):
    titles: set[str]
    complete: bool
    rung: str
    notes: list[str]


DEFAULT_GLOBAL_DENY = [
    r"::",
    r"^List of\b",
    r"\(disambiguation\)$",
    r"^(Season|Series)\s+\d+",
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


def _validate_wiki_url(wiki: str) -> tuple[bool, str]:
    """Validate wiki URL scheme (https) and host against allowed suffixes."""
    parsed = urllib.parse.urlsplit(wiki)
    if parsed.scheme != "https":
        return False, f"wiki url must use https scheme: {wiki!r}"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, f"missing host in wiki url: {wiki!r}"

    allowed = [".fandom.com", "fandom.com", "bulbapedia.bulbagarden.net"]
    env_allow = os.environ.get("WIKI_HOST_ALLOW", "")
    if env_allow:
        for extra in env_allow.split(","):
            extra = extra.strip().lower()
            if extra:
                allowed.append(extra)

    for a in allowed:
        if host == a or host.endswith(a if a.startswith(".") else "." + a):
            return True, ""
    return False, f"disallowed wiki host {host!r} (not in allowed hosts)"


def _resolve_redirects(
    wiki: str,
    titles: set[str],
    fetch_json: Callable[[str], dict],
) -> tuple[set[str], bool]:
    """Resolve redirect titles using glossary_verify.redirect_targets helper."""
    if not titles:
        return set(), True

    orig_http = glossary_verify._http_json
    try:
        glossary_verify._http_json = fetch_json
        targets, redirs_ok = redirect_targets(wiki, titles)
    except Exception:
        return titles, False
    finally:
        glossary_verify._http_json = orig_http

    resolved = set(titles) | set(targets.values())
    return resolved, redirs_ok


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


_H2_RE = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.M)
# An episode column: Episode(s), Ep / Ep. / Eps / Eps., Anime. Word-bounded on letters, so Step, Epic and Reps do not match.
_EP_HEADER = re.compile(r"(?<![A-Za-z])(?:episodes?|eps?|anime)(?![A-Za-z])", re.IGNORECASE)


def _clean_cell(cell: str) -> str:
    """A table cell as plain text: links reduced to their display text ([[Steam Ninja Scrolls Arc|106-111]] -> 106-111),
    quotes and tags dropped, HTML entities decoded (&ndash;)."""
    cell = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", cell)
    cell = re.sub(r"\'\'+|<[^>]*>", "", cell)
    return html.unescape(cell).replace("\xa0", " ").strip()


def _parse_arc_rows(
    wt: str,
    arc_column: str | None = None,
    episode_column: str | None = None,
    part: str | None = None,
) -> tuple[list[tuple[str, set[int]]], list[str], list[str]]:
    """Parse wikitext tables into ([(arc_title, episodes)], unparseable notes, parts that had arcs).

    A "part" is the level-2 heading (== Part II ==) a table sits under; tables before any heading share the part "". Index
    pages such as 'Plot of Naruto' keep one table per part and each part numbers its own episodes from 1, so ``part`` (the
    heading, compared case-insensitively and exactly: "Part I" is not "Part II") restricts the parse to that part's tables.
    The arc column is the header containing ``arc_column``, else one containing "Arc", else "Title"/"Name"; the episode
    column is the header containing ``episode_column``, else Episode(s)/Ep/Eps/Anime."""
    arcs: list[tuple[str, set[int]]] = []
    notes: list[str] = []
    parts: list[str] = []
    if not wt:
        return arcs, notes, parts
    headings = [(m.start(), m.group(1).strip()) for m in _H2_RE.finditer(wt)]
    want = part.strip().casefold() if part else None

    for tm in re.finditer(r"(\{\|.*?\|\})", wt, re.DOTALL):
        tbl = tm.group(1)
        here = ""
        for pos, name in headings:
            if pos < tm.start():
                here = name
        if want is not None and here.casefold() != want:
            continue
        rows = re.split(r"\n\|-", tbl)
        arc_col_idx = None
        ep_col_idx = None
        found = False

        for raw_row in rows:
            lines = [line.strip() for line in raw_row.splitlines() if line.strip()]
            if not lines:
                continue

            # Header row check
            if any(ln.startswith("!") for ln in lines):
                header_cells: list[str] = []
                for ln in lines:
                    if ln.startswith("!"):
                        for p in re.split(r"!!", ln[1:]):
                            if "|" in p:
                                p = p.split("|")[-1]
                            header_cells.append(p.strip())
                arc_col_idx = ep_col_idx = None
                for idx, h in enumerate(header_cells):
                    if episode_column and episode_column.lower() in h.lower():
                        ep_col_idx = idx
                    elif not episode_column and _EP_HEADER.search(h):
                        ep_col_idx = idx
                for pattern in ([re.escape(arc_column)] if arc_column else []) + [r"Arc", r"Title|Name"]:
                    hit = [i for i, h in enumerate(header_cells) if re.search(pattern, h, re.IGNORECASE) and i != ep_col_idx]
                    if hit:
                        arc_col_idx = hit[0]
                        break
                continue

            # Skip table if it has neither arc_col_idx nor ep_col_idx
            if arc_col_idx is None or ep_col_idx is None:
                continue

            # Data row
            cells: list[str] = []
            for ln in lines:
                if ln.startswith("|") and not ln.startswith("|-") and not ln.startswith("|}"):
                    for p in re.split(r"\|\|", ln[1:]):
                        cells.append(p.strip())
            if not cells or len(cells) <= max(arc_col_idx, ep_col_idx):
                continue

            # Extract arc title from arc column
            arc_cell = cells[arc_col_idx]
            arc_title = None
            for m in re.finditer(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]", arc_cell):
                target = m.group(1).strip()
                if not re.search(r"^(Chapter|Volume|Episode)\s+\d+", target, re.IGNORECASE):
                    arc_title = target
                    break

            if not arc_title:
                continue

            # Extract episodes from episode column
            ep_cell = _clean_cell(cells[ep_col_idx])
            if ep_cell in ("—", "-", "–", "N/A", "n/a", ""):
                continue

            episodes: set[int] = set()
            for p in (p.strip() for p in ep_cell.split(",") if p.strip()):
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
                found = True
            else:
                notes.append(f"unparseable arc row: {arc_title} ({ep_cell})")
        if found and here not in parts:
            parts.append(here)

    return arcs, notes, parts


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


def _part_for(cfg: dict, season) -> str | None:
    """The index-page part (section heading) to read: cfg['season_parts'][season] if present, else cfg['part'], else None."""
    sp = cfg.get("season_parts")
    if isinstance(sp, dict) and season is not None:
        chosen = sp.get(str(season), sp.get(season))
        if isinstance(chosen, str) and chosen.strip():
            return chosen
    part = cfg.get("part")
    return part if isinstance(part, str) and part.strip() else None


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

    valid_host, host_err = _validate_wiki_url(wiki)
    if not valid_host:
        return ScopeResult(titles=set(), complete=False, rung="none", notes=[host_err])

    fetch_json = http or _http_json
    notes: list[str] = []
    custom_deny = list(cfg.get("deny") or [])

    # Calculate absolute episode numbers if provided
    offsets = cfg.get("season_offsets") or {}
    offset = 0
    if season is not None:
        raw_offset = offsets.get(str(season), offsets.get(season, 0))
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError) as e:
            return ScopeResult(
                titles=set(),
                complete=False,
                rung=rung,
                notes=[f"invalid season_offsets value for season {season!r}: {raw_offset!r} ({e})"],
            )

    if episode_numbers is not None:
        try:
            req_eps = {int(e) + offset for e in episode_numbers}
        except (ValueError, TypeError) as e:
            return ScopeResult(
                titles=set(),
                complete=False,
                rung=rung,
                notes=[f"invalid episode number in episode_numbers: {e}"],
            )
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
        part = _part_for(cfg, season)
        arcs, parse_notes, parts = _parse_arc_rows(
            wt, arc_column=cfg.get("arc_column"), episode_column=cfg.get("episode_column"), part=part
        )
        notes.extend(parse_notes)
        if part is None and len(parts) > 1:
            # Each part numbers its own episodes from 1: merging the tables would pick the arcs of several series.
            return ScopeResult(
                titles=set(),
                complete=False,
                rung=rung,
                notes=notes + [f"index page has several parts {parts}: set cfg['part'] or cfg['season_parts']"],
            )
        if part is not None and not arcs:
            notes.append(f"no arc rows under the part {part!r} (parts with arcs on the page: see index page headings)")

        if not arcs:
            return ScopeResult(
                titles=set(),
                complete=False,
                rung=rung,
                notes=notes + ["no parseable arc rows found in index page"],
            )

        matching_arcs = [arc_title for arc_title, arc_eps in arcs if not req_eps or bool(arc_eps & req_eps)]
        if not matching_arcs:
            return ScopeResult(
                titles=set(),
                complete=False,
                rung=rung,
                notes=notes + ["no matching arcs found for requested episodes"],
            )

        complete = True
        if req_eps:
            all_arc_eps = set().union(*(arc_eps for _, arc_eps in arcs))
            uncovered = req_eps - all_arc_eps
            if uncovered:
                complete = False
                notes.append(f"requested episodes not covered by any arc: {sorted(uncovered)}")

        all_titles: set[str] = set()

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
            links = _extract_links(arc_wt, normalise=True)
            all_titles.update(links)

        # Resolve redirects
        all_titles, redirs_ok = _resolve_redirects(wiki, all_titles, fetch_json)
        if not redirs_ok:
            complete = False
            notes.append("redirect resolution incomplete or failed")

        deny_patterns = DEFAULT_GLOBAL_DENY + custom_deny
        filtered = {normalize_title(t) for t in all_titles if normalize_title(t) and not _is_denied(t, deny_patterns)}
        return ScopeResult(titles=filtered, complete=complete, rung=rung, notes=notes)

    # -------------------------------------------------------------------------
    # Rung 2: season_page
    # -------------------------------------------------------------------------
    if rung == "season_page":
        season_fmt = cfg.get("season_page", "S{season:02d}")
        if season is None:
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=["season number required for season_page rung"])

        try:
            s_int = int(season)
        except (ValueError, TypeError) as e:
            return ScopeResult(titles=set(), complete=False, rung=rung, notes=[f"invalid season number: {season!r} ({e})"])

        page_title = season_fmt.replace("{season:02d}", f"{s_int:02d}").replace("{season}", str(s_int))

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
            raw_titles = _extract_links(parse_obj["wikitext"].get("*", ""), normalise=True)

        season_wt = parse_obj.get("wikitext", {}).get("*", "")
        table_episodes: set[str] = set()
        complete = True

        ep_list_page_cfg = cfg.get("episode_list_page")
        if ep_list_page_cfg:
            ep_list_page = str(ep_list_page_cfg).replace("{season:02d}", f"{s_int:02d}").replace("{season}", str(s_int))
            ep_url = f"{wiki}?action=parse&page={urllib.parse.quote(ep_list_page)}&prop=wikitext&format=json"
            try:
                ep_resp = fetch_json(ep_url)
                if ep_resp and "parse" in ep_resp:
                    ep_wt = ep_resp.get("parse", {}).get("wikitext", {}).get("*", "")
                    table_episodes.update(_extract_table_episode_titles(ep_wt))
                else:
                    complete = False
                    err_msg = ep_resp.get("error") if ep_resp else "empty"
                    notes.append(f"error fetching episode_list_page {ep_list_page}: {err_msg}")
            except Exception as e:
                complete = False
                notes.append(f"http error fetching episode_list_page {ep_list_page}: {e}")
        elif season_wt:
            table_episodes.update(_extract_table_episode_titles(season_wt))

        # Resolve redirects
        raw_titles, redirs_ok = _resolve_redirects(wiki, raw_titles, fetch_json)
        if not redirs_ok:
            complete = False
            notes.append("redirect resolution incomplete or failed")

        deny_patterns = DEFAULT_GLOBAL_DENY + DEFAULT_SEASON_DENY + custom_deny
        normalized_table_episodes = {normalize_title(t) for t in table_episodes if normalize_title(t)}

        filtered = {
            normalize_title(t)
            for t in raw_titles
            if normalize_title(t) and not _is_denied(t, deny_patterns) and normalize_title(t) not in normalized_table_episodes
        }
        return ScopeResult(titles=filtered, complete=complete, rung=rung, notes=notes)

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
        filtered = {normalize_title(t) for t in all_raw_titles if normalize_title(t) and not _is_denied(t, deny_patterns)}
        return ScopeResult(titles=filtered, complete=complete, rung=rung, notes=notes)

    return ScopeResult(titles=set(), complete=False, rung="none", notes=["unhandled execution path"])
