#!/usr/bin/env python3
"""Per-show glossary loading + name correction, shared by generate.py and repair.py.

The deterministic correction is tiered for PRECISION (the old blanket fuzzy matcher
mis-capitalized ordinary words like pirates->Pirate, along->Arlong):

  1. phrase hard_fixes   (multi-word keys, word-boundary, case-insensitive)
  2. exact-token hard_fixes
  3. guarded fuzzy       (only NON-English tokens; length-scaled cutoff; never a
                          one-char insert/delete edit)

Recall for far mishears (spondum->Spandam) comes from curated hard_fixes; the rest is
left to the C3 LLM repair stage. ``name_suspect`` flags lines the LLM should look at.

Pure stdlib + a wordlist file — unit-testable without CUDA/LLM. See
specs/c1-glossary-precision/spec.md.  Built with help of Claude (Anthropic).
"""

from __future__ import annotations

import difflib
import json
import os
import re

try:  # V2 A4: tier-4 phonetic match. Optional dep -- degrade to the
    import jellyfish  # existing 3-tier behavior if it isn't installed (see Dockerfile.builder).
except ImportError:
    jellyfish = None

# Guarded-fuzzy thresholds: short words demand near-identical matches.
MIN_FUZZY_LEN = 4


def fuzzy_cutoff(n: int) -> float:
    return 0.95 if n <= 5 else (0.90 if n <= 7 else 0.84)


# Wordlist for the English-word gate: the apt `wamerican` dict in the image, plus a
# bundled fallback shipped next to this module (also what the tests use).
WORDLIST_PATH = os.environ.get("WORDLIST_PATH", "/usr/share/dict/american-english")
_BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "common_words.txt")
_WORDS: set[str] | None = None


def _read_words(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return {ln.strip().lower() for ln in f if ln.strip() and "'" not in ln}
    except OSError:
        return set()


def _load_words() -> set[str]:
    global _WORDS
    if _WORDS is None:
        _WORDS = _read_words(_BUNDLED) | _read_words(WORDLIST_PATH)
    return _WORDS


def is_english(token: str) -> bool:
    """True if the bare token is a real English word (so the fuzzy must not rewrite it)."""
    return token.lower() in _load_words()


def load_dict(cfg: dict) -> dict:
    """Normalize a raw glossary dict into {names, phrases, token_fixes, phrase_fixes,
    initial_prompt, show}: split hard_fixes into phrase (has space) vs token maps."""
    token_fixes, phrase_fixes = {}, {}
    for k, v in (cfg.get("hard_fixes") or {}).items():
        key = str(k).lower()
        (phrase_fixes if " " in key else token_fixes)[key] = v
    return {
        "show": cfg.get("show", ""),
        "names": list(cfg.get("names") or []),
        "phrases": list(cfg.get("phrases") or []),
        "token_fixes": token_fixes,
        "phrase_fixes": phrase_fixes,
        "initial_prompt": cfg.get("initial_prompt") or "",
        # A2: whether this show's copies lack a fansub reference track, so repair may
        # run unanchored. Normalised here because load_dict drops every key it does not
        # name, so a field absent from this dict never reaches repair.skips_unanchored.
        "unanchored_repair": bool(cfg.get("unanchored_repair")),
    }


def load(path: str) -> dict:
    """Load a glossary JSON file via load_dict. Missing/blank -> empty (no-op) glossary."""
    if path and os.path.exists(path):
        try:
            return load_dict(json.load(open(path)))
        except Exception as e:
            print("glossary load failed:", path, e, flush=True)
    return load_dict({})


def tag_names_by_arc(gloss: dict, arc: str, arc_titles: set) -> int:
    """Tag this glossary's names with an arc they belong to. Returns how many were tagged.

    S-11. The tag is a SET of arcs, not one season, and it comes from wiki MEMBERSHIP
    rather than from which season's transcript happened to produce the name. Recording a
    single "the season that acquired it" contradicts the cross-arc case the spec already
    documents: Caesar Clown is a Punk Hazard antagonist who appears in Dressrosa, so a
    single-valued tag would demote him in one of the two arcs he is genuinely in.

    Matching is on the REDUCED form, so the glossary's short name matches the wiki's full
    title -- `Doflamingo` against `Donquixote Doflamingo`, `Luffy` against
    `Monkey D. Luffy`. A name the arc does not contain is left UNTAGGED rather than tagged
    falsely: untagged defaults IN at the consumer, whereas a wrong tag actively demotes a
    name in the arcs where it belongs.

    An empty ``arc_titles`` changes nothing. That is the [S-7] path -- an arc that would
    not resolve must not be able to clear tags that other arcs established."""
    if not arc_titles:
        return 0
    # Index the whole title AND each of its words, so a glossary short name matches a
    # fuller wiki title from either end: `Caesar` -> `Caesar Clown`, `Doflamingo` ->
    # `Donquixote Doflamingo`, `Luffy` -> `Monkey D. Luffy`. Words shorter than
    # MIN_FUZZY_LEN are skipped for the same reason the fuzzy tier skips them -- `D.` in
    # `Monkey D. Luffy` would match anything.
    reduced = set()
    for t in arc_titles:
        reduced.add(re.sub(r"[^a-z0-9]", "", t.lower()))
        for word in t.split():
            w = re.sub(r"[^a-z0-9]", "", word.lower())
            if len(w) >= MIN_FUZZY_LEN:
                reduced.add(w)
    tags = gloss.setdefault("arc_tags", {})
    tagged = 0
    for name in gloss.get("names") or []:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if not key or key not in reduced:
            continue
        arcs = tags.setdefault(name.lower(), [])
        if arc not in arcs:
            arcs.append(arc)
            arcs.sort()
        tagged += 1
    return tagged


_SOURCE_EPISODES_RE = re.compile(r"Covers anime episode\(s\):\s*([^\n<]+)")


def source_episodes(nfo_path: str) -> list[int]:
    """Absolute source-episode numbers from a re-cut show's per-episode .nfo, e.g.
    "Covers anime episode(s): 628 - 631" -> [628, 629, 630, 631]. Handles the range,
    comma and single forms, and mixes of them.

    Regex-only, no XML parser and a size-capped read -- .nfo files are untrusted
    third-party input, matching arc_for's precedent below. [] on any absence or
    malformed line; never raises."""
    try:
        with open(nfo_path, encoding="utf-8", errors="replace") as f:
            text = f.read(64 * 1024)
    except OSError:
        return []
    m = _SOURCE_EPISODES_RE.search(text)
    if not m:
        return []
    out: list[int] = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        rng = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if lo <= hi:
                out.extend(range(lo, hi + 1))
            continue
        if part.isdigit():
            out.append(int(part))
    return out


def arc_for(video_path: str) -> str | None:
    """The arc name for an episode, from its season's ``season.nfo`` ``<title>``.

    Plex, Jellyfin and Sonarr already write this file, so the mapping costs nothing to
    obtain: verified 2026-08-26 across all 35 One Pace seasons, where Season 31 reads
    ``<title>Dressrosa</title>``.

    Returns None for anything it cannot answer -- no file, no title, unparseable content.
    Most of the library has no ``season.nfo`` at all, so absence is the COMMON case and not
    an error; the caller falls back to unweighted terms. A metadata file this pipeline does
    not own must never be able to fail an episode, which is why every failure returns None
    rather than raising.

    Read with a regex rather than an XML parser ON PURPOSE. `.nfo` files ship inside
    downloaded releases, so this is untrusted third-party input, and `xml.etree` is an XXE
    and entity-expansion surface (the security gate blocks it outright). The file has one
    fixed shape and one field is wanted from it, so a parser buys nothing and costs an
    attack surface plus a dependency. Size-capped for the same reason: a crafted `.nfo`
    must not be able to read a gigabyte into memory."""
    nfo = os.path.join(os.path.dirname(os.path.abspath(video_path)), "season.nfo")
    try:
        with open(nfo, encoding="utf-8", errors="ignore") as f:
            head = f.read(64 * 1024)
    except OSError:
        return None
    m = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
    return (m.group(1).strip() or None) if m else None


def prompt_for(gloss: dict, show: str = "") -> str:
    """The exact ``initial_prompt`` this glossary and show hand whisper.

    ONE derivation, used both by generate.load_glossary() when transcribing and by
    stale_tier() when deciding whether a stored transcript is still current. Two copies
    would drift, and the drift would read as "the prompt changed" on every episode of
    every show -- a permanent, silent GPU queue.

    ``show`` (generate's SHOW_NAME) wins over the glossary's own ``show`` key, matching
    load_glossary()'s precedence."""
    show = show or gloss.get("show", "")
    return gloss.get("initial_prompt") or (
        f"This is {show}, a Japanese anime (English dub). Transcribe the spoken English accurately, with natural punctuation."
        if show
        else "Japanese anime, English dub. Transcribe the spoken English accurately, with natural punctuation."
    )


def stale_tier(stored_prompt: str | None, gloss: dict, show: str = "") -> str | None:
    """``"transcribe"`` if this glossary would now hand whisper a DIFFERENT prompt than
    the one that produced the stored transcript, else ``None``.

    The glossary reaches the decoder by exactly one route -- ``initial_prompt`` -- so
    that string is the whole test. Everything else a glossary drives (``names``,
    ``hard_fixes`` -> token/phrase fixes) is consumed by correct() at card level, long
    after the words exist, and is therefore CPU work on the text tier.

    This is why the comparison is on the prompt STRING and not on a hash of the glossary
    file: mine_glossary.py appends hard_fixes on every sweep of a watched show, so a file
    hash would mark every episode of that show transcription-stale for work that changed
    nothing about audio -> words -- re-queueing a whole series for the GPU.

    No stored prompt means no evidence the transcript matches this glossary, so it counts
    as stale: unknown provenance is not evidence of freshness."""
    if not stored_prompt:
        return "transcribe"
    return "transcribe" if stored_prompt != prompt_for(gloss, show) else None


def _one_indel(a: str, b: str) -> bool:
    """True if a and b differ by exactly one inserted/deleted char (e.g. along/arlong,
    frank/franky). Such edits are too risky to auto-apply — left for the LLM."""
    if abs(len(a) - len(b)) != 1:
        return False
    short, lng = (a, b) if len(a) < len(b) else (b, a)
    return any(lng[:i] + lng[i + 1 :] == short for i in range(len(lng)))


_TOKEN_RE = re.compile(r"^([^\w']*)([\w'][\w'-]*?)([^\w']*)$")


def _phonetic_match(token: str, names: list[str]) -> str | None:
    """Tier 4 (V2 A4): match ``token`` to a glossary name by Metaphone code when the
    guarded-fuzzy tier (edit-distance based) misses -- e.g. "spondum" -> "Spandam",
    where the letters diverge enough to fail the fuzzy cutoff but the phonetics don't
    (both -> Metaphone "SPNTM"). Recall for far mishears without a curated hard_fix.

    Callers are expected to have already applied the English-word gate (``is_english``)
    to ``token`` -- this function does not re-check it, so it must never be called on a
    known English word (see ``_fix_token``, which gates before reaching any tier).

    Returns None (no-op) if ``jellyfish`` isn't installed -- the try/except ImportError
    at module load degrades this whole tier away gracefully."""
    if jellyfish is None or not names:
        return None
    code = jellyfish.metaphone(token)
    if not code:
        return None
    for nm in names:
        if jellyfish.metaphone(nm) == code:
            return nm
    return None


def _fix_token(tok: str, names: list[str], token_fixes: dict) -> tuple[str, int]:
    m = _TOKEN_RE.match(tok)
    if not m:
        return tok, 0
    pre, core, post = m.groups()
    low = core.lower()
    if low in token_fixes:
        return pre + token_fixes[low] + post, 1
    if any(low == nm.lower() for nm in names):  # already a correct name -> leave
        return tok, 0
    if len(core) < MIN_FUZZY_LEN or "'" in core or is_english(low):
        return tok, 0
    cand = difflib.get_close_matches(core.title(), names, n=1, cutoff=fuzzy_cutoff(len(core)))
    if cand and cand[0].lower() != low and not _one_indel(low, cand[0].lower()):
        return pre + cand[0] + post, 1
    phon = _phonetic_match(low, names)
    if phon and phon.lower() != low and not _one_indel(low, phon.lower()):
        # Same one-char-indel exclusion as the fuzzy tier just above: a one-char
        # insert/delete mishear (e.g. "spandm"/"Spandam") also Metaphones identically,
        # but is exactly the risky-edit case the fuzzy tier already defers to the LLM --
        # tier 4 must not undercut that guard just because it arrived via a different path.
        return pre + phon + post, 1
    return tok, 0


def correct(text: str, gloss: dict) -> tuple[str, int]:
    """Apply the tiered correction to one line; return (corrected, n_changes)."""
    n = 0
    for key in sorted(gloss["phrase_fixes"], key=len, reverse=True):  # phrases first
        text, c = re.compile(r"\b" + re.escape(key) + r"\b", re.I).subn(gloss["phrase_fixes"][key], text)
        n += c
    out = []
    for tok in text.split():
        new, ch = _fix_token(tok, gloss["names"], gloss["token_fixes"])
        out.append(new)
        n += ch
    return " ".join(out), n


def name_suspect(text: str, gloss: dict) -> bool:
    """True if the line likely contains a mis-spelled name (near a glossary name but not
    exact) or an unknown capitalized proper-noun-like token — a candidate for LLM repair."""
    names = gloss["names"]
    names_lower = {n.lower() for n in names}
    for tok in text.split():
        m = _TOKEN_RE.match(tok)
        if not m:
            continue
        core = m.group(2)
        low = core.lower()
        if len(core) < MIN_FUZZY_LEN or low in names_lower or is_english(low):
            continue
        if core[0].isupper():  # unknown proper noun
            return True
        if names and difflib.get_close_matches(core.title(), names, n=1, cutoff=0.78):
            return True  # lowercase near-name mishear
    return False
