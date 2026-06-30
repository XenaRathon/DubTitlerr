#!/usr/bin/env python3
"""Glossary wiki-verifier — make any glossary's proper-noun spellings as accurate as the
hand-tuned One Pace one, automatically.

Hybrid approach: fetch the show's wiki main-namespace page index (Fandom MediaWiki API),
pre-match each glossary term to the top-K similar titles (deterministic), then a local LLM
(qwen3:8b) picks the canonical entity and prefers the DUB spelling. High-confidence matches
are applied to the glossary; low-confidence / no-match terms are kept and flagged for review.
Incremental (a ``verified`` set skips re-checks) and cached (page index per show). Resilient:
any wiki/LLM failure is a no-op, never stalls the pipeline.

Reusable module + CLI — called by the mining hook in gen_loop, a standalone command, and
future community-repo front-ends. Source of truth = wiki/publisher (dub-preferred). See
specs/glossary-wiki-verify/spec.md.  Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import os

TOPK = 6                  # candidate titles per term handed to the LLM
CAND_CUTOFF = 0.5         # min similarity for a title to be a candidate
VERIFY_MODEL = os.environ.get("VERIFY_MODEL", "qwen3:8b")
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.local:11434/api/generate")
CACHE_DIR = os.environ.get("WIKI_CACHE_DIR", "/config/wiki_cache")
HTTP_TIMEOUT = int(os.environ.get("WIKI_HTTP_TIMEOUT", "20"))
WIKI_TTL = int(os.environ.get("WIKI_CACHE_TTL", str(30 * 24 * 3600)))   # refresh index monthly


def candidates(term: str, titles: list[str], k: int = TOPK) -> list[str]:
    """Top-k wiki titles most similar to `term` (>= CAND_CUTOFF). Pure/deterministic."""
    raise NotImplementedError


def build_adjudication_prompt(term: str, cands: list[str], show: str) -> str:
    """Prompt asking the LLM to pick the canonical (dub-preferred) spelling among candidates."""
    raise NotImplementedError


def adjudicate(term: str, cands: list[str], show: str) -> dict:
    """LLM pick -> {'canonical': str, 'confidence': 'high'|'low'|'none', 'dub_note': str}."""
    raise NotImplementedError


def apply_results(gloss: dict, results: dict) -> dict:
    """Apply per-term adjudications: write high-confidence canonical spellings into names/phrases,
    flag low/no-match, mark every processed term `verified`, regenerate `initial_prompt`. Pure;
    preserves unknown fields."""
    raise NotImplementedError


def resolve_wiki(title: str, override: str | None = None) -> str | None:
    """Resolve the show's Fandom MediaWiki API base (override wins; else search + pick)."""
    raise NotImplementedError


def fetch_titles(wiki_api: str, show_key: str) -> list[str]:
    """Cached main-namespace (ns=0) page-title list for the wiki."""
    raise NotImplementedError


def verify(gloss_path: str, override: str | None = None, force: bool = False) -> dict:
    """Orchestrate verification of one glossary file; returns a report. Resilient."""
    raise NotImplementedError
