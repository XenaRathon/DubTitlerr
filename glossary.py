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

import json
import os

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
    }


def load(path: str) -> dict:
    """Load a glossary JSON file via load_dict. Missing/blank -> empty (no-op) glossary."""
    if path and os.path.exists(path):
        try:
            return load_dict(json.load(open(path)))
        except Exception as e:
            print("glossary load failed:", path, e, flush=True)
    return load_dict({})


def correct(text: str, gloss: dict) -> tuple[str, int]:
    """Apply the tiered correction to one line; return (corrected, n_changes)."""
    raise NotImplementedError


def name_suspect(text: str, gloss: dict) -> bool:
    """True if the line likely contains a mis-spelled name (near a glossary name but not
    exact) or an unknown capitalized proper-noun-like token — a candidate for LLM repair."""
    raise NotImplementedError
