#!/usr/bin/env python3
"""Acquire proper nouns for a show whose releases carry no mineable subtitle track.

mine_glossary.py can only learn names from an embedded fansub track. Where a release
ships none, the glossary for that stretch of the show stays empty and every name is left
to Whisper's guessing. This module fills that gap from the opposite direction: the show's
wiki owns the candidate list AND every canonical spelling, and the show's own transcripts
only decide which wiki entities are worth asking about. Our errors can raise a question;
they can never become an answer.

See docs/superpowers/specs/2026-08-19-glossary-name-acquisition-design.md.
Built with help of Claude (Anthropic).
"""
from __future__ import annotations

import re

_DISAMBIG_RE = re.compile(r"\s*\([^)]*\)\s*$")


def normalize_title(title: str) -> str:
    """A wiki article title reduced to the name itself.

    Fandom titles carry disambiguators and subpages -- 'Misty (anime)',
    'Ash Ketchum/Sun & Moon'. Both are part of the TITLE, not the name, and emitting one
    as a hard_fix canonical would rewrite dialogue to include it."""
    return _DISAMBIG_RE.sub("", str(title).split("/")[0]).strip()


def reduce_form(s: str) -> str:
    """The form both sides are compared on: lowercase, no spaces/apostrophes/hyphens.

    This is what lets the ASR token 'Vanderdecken' match the title 'Van der Decken'."""
    return re.sub(r"[\s''-]", "", str(s).lower())
