#!/usr/bin/env python3
"""Sentence-punctuation restoration, run on whisper's WORD LIST *before* reflow splits it.

generate.py must keep ``condition_on_previous_text=False`` (a music-masked stretch
collapses into one mega-segment with True, and True also OOMs the 1060 -- both measured),
so whisper decodes every segment cold and a segment starting mid-sentence comes back
lowercase and unpunctuated. Measured on One Pace S30 (22 episodes, 9,424 cards): 27% of
cards end with no sentence-terminal punctuation, clustered into 149 runs of 5+ consecutive
cards holding 20% of the season. ``reflow._split_sentences()`` has nothing to split on
there, so the span falls through to ``_split_overflow()`` and is cut on character balance
-- mid-phrase, across speaker changes.

WHY HERE AND NOT IN repair.py: repair already edits card text, but it runs after the cards
are split and timed. Restoring there would make the text read better and leave the
boundaries exactly as wrong. The split must be DOWNSTREAM of the fix, so this runs on the
words, before reflow(). Only ``word["text"]`` is ever written; no timestamp is touched.

WHY IT IS SAFE: the guard is mechanical (R4). A restoration is accepted only when its
token sequence is identical to the original's after casefolding and stripping punctuation
-- so an accepted answer CANNOT have altered, added, dropped or reordered a word, and a
rejected one costs nothing but one run's punctuation. Every failure (unreachable model,
timeout, empty answer, rejected guard) leaves the words exactly as whisper produced them:
this is an improvement pass and must never cost an episode.

Env:
  RESTORE_PUNCTUATION   default "1"; "0" disables the pass entirely
  RESTORE_MIN_RUN       default "2" -- consecutive unpunctuated segments needed for a call
  RESTORE_BACKEND / RESTORE_MODEL / RESTORE_LLAMACPP_URL / OLLAMA_URL
                        default to the REPAIR_* values, as glossary_verify.py does
  RESTORE_MAX_TOKENS    default "2048" -- ceiling on the per-run answer budget
See docs/superpowers/specs/2026-08-20-punctuation-restoration-design.md.
Built with help of Claude (Anthropic).
"""

from __future__ import annotations

import os
import string

import reflow
import unresolved
from common import llm_chat

# The detector must ask the SAME question reflow asks when it splits, or it would "fix"
# segments reflow can already split and skip ones it cannot.
SENT_END = reflow.SENT_END

# Both apostrophes must normalise to one. A model that tidies quote style rewrites
# don't -> don<U+2019>t INSIDE the word, where .strip() would never reach it, and the guard
# would reject a restoration that changed no word at all. Built with chr() on purpose:
# a literal curly apostrophe here has already been silently normalised by an editor once,
# which disabled a guard and left a passing-looking test behind.
_FOLD = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2032: "'"}
PUNCT = string.punctuation + "".join(chr(c) for c in (0x2013, 0x2014, 0x2026, 0x00AB, 0x00BB))

RESTORE_PUNCTUATION = os.environ.get("RESTORE_PUNCTUATION", "1")
RESTORE_MIN_RUN = int(os.environ.get("RESTORE_MIN_RUN", "2"))
RESTORE_BACKEND = os.environ.get("RESTORE_BACKEND", os.environ.get("REPAIR_BACKEND", "ollama"))
RESTORE_MODEL = os.environ.get("RESTORE_MODEL", os.environ.get("REPAIR_MODEL", "qwen3:8b"))
OLLAMA = os.environ.get("OLLAMA_URL", "http://ollama.local:11434/api/generate")
RESTORE_LLAMACPP_URL = os.environ.get(
    "RESTORE_LLAMACPP_URL", os.environ.get("REPAIR_LLAMACPP_URL", "http://192.168.1.232:8080/v1/chat/completions")
)
RESTORE_MAX_TOKENS = int(os.environ.get("RESTORE_MAX_TOKENS", "2048"))
MAX_REJECT_EVENTS = 20  # a systematic rejection pattern shows in the first few; the rest
# would only crowd the shared event budget (see qc.Recorder.event)


def _norm(tok: str) -> str:
    """One token reduced to its comparable core: quote style folded, punctuation stripped
    from both ends, case dropped. ``""`` means the token was punctuation only."""
    return tok.translate(_FOLD).strip(PUNCT).casefold()


def normalise(s: str) -> list[str]:
    """The word sequence of ``s``, ignoring punctuation and case."""
    return [n for n in (_norm(t) for t in s.split()) if n]


# Dashes SEPARATE tokens; hyphens do not. A model restoring punctuation writes
# "tempo<em-dash>you" for "tempo you" -- pure punctuation, but normalise() splits on
# whitespace and would see one token where there were two. Measured: 3 of 7 live
# rejections were exactly this. Hyphen is deliberately NOT here -- it is legitimately
# word-internal ("curly-eyebrow", "District F-16") and splitting it would break real words.
_DASHES = "".join(chr(c) for c in (0x2013, 0x2014))


def _load_words(path: str = "/usr/share/dict/american-english") -> frozenset:
    """The English wordlist, for the contraction rule below. Absent (as on a dev box
    without wamerican) means the rule simply never fires -- strict, never looser."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return frozenset(w.strip().lower() for w in f if w.strip())
    except OSError:
        return frozenset()


WORDS = _load_words()


def _contraction_ok(o: str, n: str) -> bool:
    """Whether ``n`` is ``o`` with an apostrophe inserted, SAFELY.

    Restoring punctuation naturally also writes don't for dont. Allowing that in general
    is unsafe: well/we'll, shed/she'd, its/it's, lets/let's all differ in MEANING, and a
    blanket rule would let the model change the sentence and pass the guard.

    The separating property is exact and needs no curated list: an apostrophe may be
    inserted only when the bare form is NOT an English word. `dont` is not a word, so
    don't is the only reading; `well` is, so we'll is a different sentence.

    Verified against the container's 104k wordlist: allows dont/theres/youre/didnt/
    isnt/wasnt/couldnt/im/ive/thats/hed...; blocks well/shed/hell/ill/were/its/lets/wont."""
    if not WORDS:
        return False  # no wordlist -> no allowance. `o not in WORDS` would be
        # vacuously TRUE on an empty set, making a dev box without
        # wamerican LOOSER than production instead of stricter --
        # the same divergence that made a name_suspect test pass
        # here and fail in the container.
    if "'" in o or "'" not in n:
        return False
    return n.replace("'", "") == o and o not in WORDS


def _split_dashes(toks: list[str]) -> list[str]:
    out = []
    for t in toks:
        for d in _DASHES:
            t = t.replace(d, " ")
        out.extend(x for x in t.split() if x)
    return out


def accept_restoration(orig: str, new: str) -> bool:
    """R4. True only when ``new`` says the same words in the same order as ``orig``.

    Far stronger than repair's length-ratio band: there is no judgement in it, so an
    accepted restoration cannot have drifted, and a rejected one is simply not applied."""
    if not new.strip():
        return False
    a, b = _split_dashes(normalise(orig)), _split_dashes(normalise(new))
    if len(a) != len(b):
        return False
    return all(x == y or _contraction_ok(x, y) for x, y in zip(a, b))


def is_candidate(text: str) -> bool:
    """A segment reflow could not split: no sentence-terminal punctuation anywhere in it."""
    return bool(text.strip()) and not any(ch in text for ch in SENT_END)


def segment_texts(words: list[dict], n_segments: int) -> list[str]:
    """Rebuild each segment's text from the words that carry its index (generate.py's
    ``segments`` records hold timings and no_speech_prob, not text)."""
    parts: list[list[str]] = [[] for _ in range(n_segments)]
    for w in words:
        si = w.get("seg")
        if isinstance(si, int) and 0 <= si < n_segments:
            parts[si].append(w["text"].strip())
    return [" ".join(p) for p in parts]


def find_runs(texts: list[str], min_run: int | None = None) -> list[tuple[int, int]]:
    """R1. Maximal half-open ranges of consecutive candidate segments, ``min_run`` or
    longer. Two is a floor, not a default: a LONE unpunctuated segment between two
    punctuated ones is usually a real fragment ("Yeah" / "...well") and is never sent,
    however low RESTORE_MIN_RUN is set."""
    min_run = max(2, RESTORE_MIN_RUN if min_run is None else min_run)
    runs, i, n = [], 0, len(texts)
    while i < n:
        if not is_candidate(texts[i]):
            i += 1
            continue
        j = i
        while j < n and is_candidate(texts[j]):
            j += 1
        if j - i >= min_run:
            runs.append((i, j))
        i = j
    return runs


def build_prompt(lines: list[str]) -> str:
    """R2/R3. The whole run in one prompt -- where a sentence ends depends on what starts
    next, so a per-segment call could not answer the question. Only punctuation and casing
    are on the table; the guard enforces it whatever the model does."""
    body = "\n".join(lines)
    return (
        "Restore sentence punctuation and capitalisation to this transcript of spoken "
        "English dialogue from an anime dub.\n"
        "Rules:\n"
        "- Return the SAME WORDS in the SAME ORDER. Never add, remove, replace, expand or "
        "translate a word.\n"
        "- Change ONLY punctuation and capitalisation.\n"
        "- End each sentence with . ! or ? and capitalise its first word; capitalise "
        "proper nouns.\n"
        "- Keep the line breaks where they are. Output the text only, no commentary.\n\n"
        f"{body}"
    )


def _max_tokens(n_words: int) -> int:
    """Enough budget for the WHOLE run: a truncated answer loses its tail words and the
    guard then rejects the run wholesale."""
    return min(RESTORE_MAX_TOKENS, max(256, 4 * n_words + 64))


def _ask(prompt: str, n_words: int) -> str:
    """One call. ``first_line=False``: a run is multi-line and first_line would keep only
    its opening sentence. Returns "" on any failure -- llm_chat already swallows transport
    errors, and the except is the belt to that braces (R6 is absolute)."""
    try:
        return llm_chat(
            prompt,
            backend=RESTORE_BACKEND,
            ollama_url=OLLAMA,
            llamacpp_url=RESTORE_LLAMACPP_URL,
            model=RESTORE_MODEL,
            max_tokens=_max_tokens(n_words),
            first_line=False,
        )
    except Exception:
        return ""


def _apply(run_words: list[dict], new_text: str) -> int:
    """R5. Lay the restored tokens back over the word dicts in order and return how many
    changed. Past the guard the correspondence is exact, so no fuzzy alignment is needed --
    but the walk is per word DICT, not per token, because generate.py's
    no-word-timestamps fallback stores a whole segment as a single 'word'."""
    toks = [t for t in new_text.split() if _norm(t)]
    i = changed = 0
    for w in run_words:
        k = sum(1 for t in w["text"].split() if _norm(t))
        if not k:
            continue
        repl = " ".join(toks[i : i + k])
        i += k
        if repl and repl != w["text"].strip():
            w["text"] = repl
            changed += 1
    return changed


def restore(words: list[dict], segments: list[dict], rec=None, stem=None) -> None:
    """Restore sentence punctuation in place, before reflow() sees the words.

    Mutates ``word["text"]`` only, and only for runs whose restoration passed the guard.
    ``rec`` is an optional qc.Recorder. ``stem`` is optional too; when given, cases the
    model could not settle are recorded to the unresolved queue for human review -- without
    it a dead endpoint is indistinguishable from "nothing needed changing". Never raises: an
    episode that cannot reach the model is an episode that generates exactly as it did
    before this pass existed."""

    def count(name, n=1):
        if rec is not None and n:
            rec.count(name, n)

    if RESTORE_PUNCTUATION == "0" or not words or not segments:
        return
    texts = segment_texts(words, len(segments))
    sent = find_runs(texts, RESTORE_MIN_RUN)
    count("restore_runs_seen", len(find_runs(texts, 2)))  # every run; sent may be fewer
    if not sent:
        return
    by_seg: dict[int, list[dict]] = {}
    for w in words:
        si = w.get("seg")
        if isinstance(si, int):
            by_seg.setdefault(si, []).append(w)
    rejected_events = 0
    for a, b in sent:
        run_words = [w for si in range(a, b) for w in by_seg.get(si, [])]
        orig = " ".join(w["text"].strip() for w in run_words)
        n_words = len(normalise(orig))
        if not n_words:
            continue
        count("restore_runs_sent")
        new = _ask(build_prompt(texts[a:b]), n_words)
        if not new:
            count("restore_empty")
            # llm_chat() returns "" on EVERY transport failure, so a dead endpoint looks
            # exactly like "no change needed". This is what tells the two apart.
            if stem:
                unresolved.record(stem, "punctuation", "llm_empty", original_text=orig[:300], segments=[a, b], words=n_words)
            continue
        if not accept_restoration(orig, new):
            count("restore_rejected_guard")
            if stem:
                unresolved.record(
                    stem,
                    "punctuation",
                    "rejected_guard",
                    original_text=orig[:300],
                    proposed_text=new[:300],
                    segments=[a, b],
                    words=n_words,
                )
            if rec is not None and rejected_events < MAX_REJECT_EVENTS:
                rejected_events += 1
                rec.event(
                    reason="restore_rejected", segments=[a, b], words=n_words, sent=orig[:200], got=new.replace("\n", " ")[:200]
                )
            continue
        count("restore_accepted")
        count("restore_words_repunctuated", _apply(run_words, new))
