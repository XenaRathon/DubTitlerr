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

import argparse
import hashlib
import json
import math
import os
import re

import jellyfish

import acquire_cache
import glossary
import glossary_verify
import mine_glossary
from common import llm_chat, log

_DISAMBIG_RE = re.compile(r"\s*\([^)]*\)\s*$")
_REDUCE_RE = re.compile("[\\s" + chr(0x27) + chr(0x2019) + "-]")


def normalize_title(title: str) -> str:
    """A wiki article title reduced to the name itself.

    Fandom titles carry disambiguators and subpages -- 'Misty (anime)',
    'Ash Ketchum/Sun & Moon'. Both are part of the TITLE, not the name, and emitting one
    as a hard_fix canonical would rewrite dialogue to include it."""
    return _DISAMBIG_RE.sub("", str(title).split("/")[0]).strip()


def reduce_form(s: str) -> str:
    """The form both sides are compared on: lowercase, no spaces/apostrophes/hyphens.

    This is what lets the ASR token 'Vanderdecken' match the title 'Van der Decken'.
    The class is built with chr() rather than written literally: the curly apostrophe
    U+2019 gets silently normalised to U+0027 by editors in this toolchain, which
    silently disables curly-apostrophe stripping and passes a literal-looking review."""
    return _REDUCE_RE.sub("", str(s).lower())


def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """Wilson score lower bound on k/n at ~95% confidence.

    Used instead of a bare ratio because a ratio cannot tell 5-vs-1 from 56-vs-2 -- both
    look lopsided, but only one is evidence. Wilson discounts the small sample for us."""
    if n <= 0:
        return 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


EXPANSION_RATIO = 1.35


def is_expansion(variant: str, canonical: str) -> bool:
    """True if 'correcting' variant->canonical would GROW a word into a longer name.

    A canonical that merely CONTAINS the variant is not a match: the transcript says
    'Warlords', the wiki title is 'Seven Warlords of the Sea', and substituting one for the
    other rewrites the line into nonsense. Length ratio catches the rest ('Ace' ->
    'Portgas D. Ace'), while a true respelling stays about the same length."""
    v, c = reduce_form(variant), reduce_form(canonical)
    if not v or not c:
        return True
    if v == c:
        return False
    if v in c and len(c) > len(v):
        return True
    return len(c) > len(v) * EXPANSION_RATIO


MIN_SIM = float(os.environ.get("ACQUIRE_MIN_SIM", "0.72"))


def similarity(a: str, b: str) -> float:
    """Jaro-Winkler on the reduced forms, nudged when a phonetic key agrees.

    RECALL, not safety. Measured on real data the true and false pairs overlap completely
    (Syrahose/Shirahoshi 0.755 sits BELOW Warlords/Warlord 0.975), so no threshold here can
    separate them and none is asked to -- R2 and R3 do the rejecting. The phonetic key is a
    bonus signal only: exact metaphone bucketing was tried and split Shirahoshi/Syrahose
    into XRHX/SRHS, dropping the case this module exists for."""
    ra, rb = reduce_form(a), reduce_form(b)
    if not ra or not rb:
        return 0.0
    score = jellyfish.jaro_winkler_similarity(ra, rb)
    if jellyfish.metaphone(ra) == jellyfish.metaphone(rb) or jellyfish.soundex(ra) == jellyfish.soundex(rb):
        score = min(1.0, score + 0.02)
    return score


_WORD_RE = re.compile(r"[^\W_]+")


def _word_index(index: list) -> dict[str, str]:
    """word (lowercase) -> the first normalised title in `index` containing it as a whole word.

    Built from _title_index()'s already-computed normalised titles -- a cheap string split
    over data that pass already produced, not a second scan that re-runs jaro-winkler,
    metaphone or soundex per title. This is what lets 'Zoro' resolve to 'Roronoa Zoro'
    rather than to some unrelated, similarly-spelled article: this wiki titles characters by
    full name, so a bare given name in dialogue is a SHORT FORM of the full-name title, not a
    fuzzy near-match to be corrected. See _best_title_indexed."""
    out: dict = {}
    for norm, *_rest in index:
        for w in _WORD_RE.findall(norm.lower()):
            out.setdefault(w, norm)
    return out


def _title_index(titles: list) -> list[tuple[str, str, str, str]]:
    """(normalised title, reduced form, metaphone, soundex) per title, computed once.

    similarity() used to recompute a title's reduce_form/metaphone/soundex on every token
    comparison it took part in -- 8202 x 8109 times on One Pace instead of 8109. Titles
    don't change within a run; only the per-title values are safe to hoist out of the join.
    A title whose reduced form is empty can never win (similarity() returns 0.0 for it,
    same as MIN_SIM's floor), so it is dropped here exactly as it was silently ignored
    before -- fewer entries to scan, identical winners and scores. Duplicate normalised
    titles (a name appearing as several disambiguated articles) are likewise collapsed to
    one entry: every occurrence would have produced the same score, so only the first is
    kept, in title order, matching best_title's original first-wins tie-break."""
    out, seen = [], set()
    for t in titles:
        norm = normalize_title(t)
        if not norm or norm in seen:
            continue
        r = reduce_form(norm)
        if not r:
            continue
        seen.add(norm)
        out.append((norm, r, jellyfish.metaphone(r), jellyfish.soundex(r)))
    return out


def _best_title_indexed(token: str, index: list, word_index: dict | None = None) -> tuple[str, float]:
    """(normalised title, score) of the closest entry in a precomputed _title_index().

    Token-side reduce_form/metaphone/soundex computed once here rather than once per
    title, mirroring similarity()'s formula exactly (same jaro-winkler call, same +0.02
    phonetic nudge, same score) so results are byte-identical to the unindexed path.

    `word_index`, when given, is checked first: a token that is a whole word (case-
    insensitive) of some title wins outright over any fuzzy near-match, score 1.0 -- see
    _word_index. A bare token score-losing to a wrong-but-similar-length title (a short
    given name scores higher against an unrelated short article than against its own long
    full-name title) is exactly the failure this pre-check exists to short-circuit."""
    ra = reduce_form(token)
    if not ra:
        return ("", 0.0)
    if word_index is not None:
        hit = word_index.get(token.lower())
        if hit is not None:
            return (hit, 1.0)
    ma, sa = jellyfish.metaphone(ra), jellyfish.soundex(ra)
    best, best_score = "", 0.0
    for norm, rb, mb, sb in index:
        s = jellyfish.jaro_winkler_similarity(ra, rb)
        if ma == mb or sa == sb:
            s = min(1.0, s + 0.02)
        if s > best_score:
            best, best_score = norm, s
    return (best, best_score) if best_score >= MIN_SIM else ("", 0.0)


def best_title(token: str, titles: list) -> tuple[str, float]:
    """(normalised title, score) of the closest title above MIN_SIM, else ('', 0.0).

    Not the hot path (see _resolve_tokens) -- a one-off convenience that builds its own
    title/word index per call, fine for a single token against a single title list."""
    index = _title_index(titles)
    return _best_title_indexed(token, index, _word_index(index))


CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"


def _conf_text(path: str) -> str:
    """All dialogue text from one conf.json, newline-joined, or '' if unreadable."""
    try:
        rows = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(rows, list):
        return ""
    return "\n".join(str(r.get("text", "")) for r in rows if isinstance(r, dict))


def _srt_text(path: str) -> str:
    """Dialogue lines from an SRT: drop indices and timecodes, keep the rest."""
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    out = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s or s.isdigit() or "-->" in s:
            continue
        out.append(s)
    return "\n".join(out)


def _iter_episode_texts(show_dir: str):
    """(stem, text) for each episode, conf.json preferred over the SRT fallback.

    One source per episode stem, never both: sorted(fs) puts '.dubtitles.conf.json'
    before '.eng.dubtitles.srt' for a shared stem because 'd' < 'e'."""
    stems_done = set()
    for dp, _dns, fs in os.walk(show_dir):
        for fn in sorted(fs):
            if fn.endswith(CONF_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(CONF_SUFFIX)]), _conf_text(os.path.join(dp, fn))
            elif fn.endswith(SRT_SUFFIX):
                stem, text = os.path.join(dp, fn[:-len(SRT_SUFFIX)]), _srt_text(os.path.join(dp, fn))
            else:
                continue
            if stem in stems_done or not text:
                continue
            stems_done.add(stem)
            yield stem, text


SOURCE_TRANSCRIPT = "transcript"
SOURCE_FANSUB = "fansub"


def _candidate(variant: str, source: str) -> dict:
    """The D3a candidate record, zeroed. Every field the apply rule or a reviewer needs.

    `settled_target` is filled per PROPOSAL, not here: it depends on the wiki canonical
    the token resolves to, which harvest cannot know."""
    return {"variant": variant, "source": source, "raw_forms": {}, "normalized_forms": [],
            "settled_target": None, "occurrence_count": 0, "episode_count": 0, "contexts": []}


def harvest_candidates(show_dir: str, source: str = SOURCE_TRANSCRIPT) -> tuple[dict, set, list]:
    """({variant: candidate}, midsentence, scope) across the show's own output.

    D3a: aggregate counts cannot express provenance, so the unit here is a candidate
    record, not an integer. D3b: `scope` is the list of episode stems the counts were
    taken over -- without it the recurrence floors are not the floors that were measured.

    `occurrence_count` is the BARE lane only, exactly what harvest() has always counted.
    Possessive forms appear in `raw_forms` as evidence for a reviewer but never raise a
    count: D5's rule is that possessive evidence may reinforce a candidate, never
    originate one, and lowering this module's floors with it would do the latter.

    conf.json is preferred; the SRT is the fallback for episodes whose conf is gone (104 of
    696 stamped episodes at time of writing). One source per episode stem, never both."""
    cands: dict = {}
    mid: set = set()
    scope: list = []
    for stem, text in _iter_episode_texts(show_dir):
        scope.append(stem)
        bare: dict = {}
        poss: dict = {}      # D5/task 12: counted separately, never folded into `bare`
        forms: dict = {}
        mine_glossary.mine_text(text, bare, poss, mid, forms)
        for tok in set(bare) | set(poss):
            c = cands.setdefault(tok, _candidate(tok, source))
            c["occurrence_count"] += bare.get(tok, 0)
            c["episode_count"] += 1
            for surface, n in forms.get(tok, {}).items():
                c["raw_forms"][surface] = c["raw_forms"].get(surface, 0) + n
    for c in cands.values():
        c["normalized_forms"] = sorted({reduce_form(f) for f in c["raw_forms"]})
    return cands, mid, scope


def harvest(show_dir: str) -> tuple[dict, set, int]:
    """(counts, midsentence, n_files) of capitalised tokens across the show's own output.

    The pre-D3a view of harvest_candidates, kept because the counts ARE the unit the
    scoring gates work in; numerically identical to what it returned before task 13."""
    cands, mid, scope = harvest_candidates(show_dir)
    return {t: c["occurrence_count"] for t, c in cands.items() if c["occurrence_count"]}, mid, len(scope)


CONTEXT_LINES = int(os.environ.get("ACQUIRE_CONTEXT_LINES", "4"))


def context_lines(show_dir: str, tokens: list, limit: int = CONTEXT_LINES) -> dict:
    """Up to `limit` real transcript lines containing each token, whole-word matched.

    Whole-word is required: 'Hoshi' must not match inside 'Shirahoshi', or the evidence
    shown to the model (and to the human) would be about a different name."""
    pats = {t: re.compile(r"\b" + re.escape(t) + r"\b") for t in tokens}
    out: dict = {t: [] for t in tokens}
    for _stem, text in _iter_episode_texts(show_dir):
        for ln in text.splitlines():
            for t, pat in pats.items():
                if len(out[t]) < limit and pat.search(ln):
                    out[t].append(ln.strip())
        if all(len(v) >= limit for v in out.values()):
            return out
    return out


def build_merge_prompt(variant: str, canonical: str, ctx_v: list, ctx_c: list, show: str) -> str:
    """Ask whether two spellings are one entity mis-transcribed or two legitimate forms.

    The model never supplies a spelling -- it answers yes/no about merging. The canonical
    string is already fixed by the wiki, which is what keeps R1 intact at this tier."""
    lines_v = "\n".join(f"  - {ln}" for ln in ctx_v) or "  (none)"
    lines_c = "\n".join(f"  - {ln}" for ln in ctx_c) or "  (none)"
    return (
        f"Two spellings appear in the English dub of {show}. Decide whether they are the SAME "
        f"name mis-transcribed, or two DIFFERENT legitimate forms (a nickname, a title, or a "
        f"separate character).\n\n"
        f'Spelling A: "{variant}"\n{lines_v}\n\n'
        f'Spelling B: "{canonical}"\n{lines_c}\n\n'
        f"A nickname the characters actually use is NOT a mis-transcription.\n"
        f'Answer with JSON only: {{"same_entity": true|false, "confidence": "high"|"low"}}\n')


def adjudicate_merge(variant: str, canonical: str, ctx_v: list, ctx_c: list, show: str) -> dict:
    """LLM merge decision -> {'same_entity': bool, 'confidence': 'high'|'low'|'none'}."""
    none = {"same_entity": False, "confidence": "none"}
    try:
        out = llm_chat(build_merge_prompt(variant, canonical, ctx_v, ctx_c, show),
                       backend=glossary_verify.VERIFY_BACKEND, ollama_url=glossary_verify.OLLAMA,
                       llamacpp_url=glossary_verify.VERIFY_LLAMACPP_URL,
                       model=glossary_verify.VERIFY_MODEL,
                       max_tokens=glossary_verify.VERIFY_MAX_TOKENS, first_line=False)
    except Exception as e:
        log("acquire: merge adjudication failed:", variant, e); return none
    if not out:
        return none
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return none
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return none
    conf = str(d.get("confidence", "none")).lower()
    return {"same_entity": d.get("same_entity") is True,
            "confidence": conf if conf in ("high", "low", "none") else "low"}


def escalate(proposals: list, ctx: dict, show: str) -> list:
    """Re-decide share-too-close proposals with context. Other verdicts pass through.

    ONLY share-too-close escalates. below-floor, sentence-initial-only, already-canonical,
    english-word, unseen-needs-evidence and short-form never do: none of those verdicts is
    evidence-shaped, and short-form (an expansion) is structurally wrong -- no amount of
    context evidence redeems it. unseen-needs-evidence specifically has no `canonical`
    context to escalate WITH -- canonical_count is 0 by definition of the branch that
    produced it, so there is nothing on the canonical side for tier-C to compare against."""
    out = []
    for p in proposals:
        if p.get("reason") != "share-too-close":
            out.append(p); continue
        adj = adjudicate_merge(p["variant"], p["canonical"],
                               ctx.get(p["variant"], []), ctx.get(p["canonical"], []), show)
        if adj["same_entity"] and adj["confidence"] == "high":
            out.append({**p, "verdict": "apply", "reason": "context-merged"})
        elif not adj["same_entity"] and adj["confidence"] == "high":
            out.append({**p, "verdict": "known", "reason": "context-distinct"})
        else:
            out.append(p)
    return out


MIN_COUNT = int(os.environ.get("ACQUIRE_MIN_COUNT", "3"))
MIN_SHARE = float(os.environ.get("ACQUIRE_MIN_SHARE", "0.80"))
UNSEEN_SIM = float(os.environ.get("ACQUIRE_UNSEEN_SIM", "0.98"))
# D4: split recurrence floors. The distribution runs opposite to intuition -- high counts
# are CORRECT names missing from the glossary (Momonosuke 21x, Brownbeard 16x, Vegapunk
# 14x), because Whisper hears a clear name consistently; the ERRORS live in the tail
# (Kinamon 2x, Whitestrom 2x, Hazzard 4x). So a near-miss of a settled term needs less
# recurrence to be worth looking at than a brand-new term does.
NEAR_MISS_MIN_COUNT = int(os.environ.get("ACQUIRE_NEAR_MISS_MIN_COUNT", "2"))
# C7: a candidate-admission throttle on D auto-applies, guarding against large wiki
# expansions like the rejected Zunesha -> "Zou Elephant (Zunisha)" (+16). It is explicitly
# NOT a layout-safety proof -- wrapping depends on where word boundaries fall, not on total
# length, and C7's measured post-glossary validation in generate.py owns that question.
GROWTH_MAX = int(os.environ.get("ACQUIRE_GROWTH_MAX", "2"))


def anchor_terms(gloss: dict) -> set:
    """Terms a transcript candidate may anchor itself to: `names` plus every hard_fix
    canonical (which is where `acquired` canonicals live too).

    `known` is deliberately excluded. Those are spellings a human REJECTED via --review;
    anchoring a new candidate to one would make a rejected misspelling the corroborating
    evidence for the next correction."""
    return ({str(n) for n in gloss.get("names") or []}
            | {str(v) for v in (gloss.get("hard_fixes") or {}).values() if v})


def settled_target(variant: str, canonical: str, anchors: set | None) -> str | None:
    """The already-settled term `variant` is a near-miss of, or None.

    Two conditions, both required, and the second is the one that is easy to lose:

    1. `variant` is a near-miss of the term -- reduced-form equality (Kaido/Kaidou) or
       similarity >= MIN_SIM (Kinamon/Kin'emon).
    2. the term IS the canonical the wiki proposed, reduced-form equal.

    Without (2) the anchor corroborates nothing about the string being written into
    hard_fixes: `Zunesha` sits close to a settled `Zunisha`, but the canonical on the
    proposal is "Zou Elephant", and applying it because some OTHER term is nearby is
    precisely the failure D3 exists to prevent. An exact match is not a near-miss --
    the token IS the settled term, and there is nothing to correct."""
    if not anchors or not canonical:
        return None
    rc = reduce_form(canonical)
    best, best_score = None, 0.0
    for term in sorted(anchors):
        if reduce_form(term) != rc or variant == term:
            continue
        if reduce_form(variant) == reduce_form(term):
            return term
        s = similarity(variant, term)
        if s >= MIN_SIM and s > best_score:
            best, best_score = term, s
    return best


def source_gate(proposals: list) -> list:
    """D3, the source-asymmetry APPLY rule. Runs AFTER the tier logic and AFTER escalate().

    A fansub candidate was written by a human who knew the show; a transcript candidate is
    Whisper guessing at audio, so a wiki title match means something weaker -- it may
    confirm the wiki's word while the audio said something else.

        fansub                            -> existing miner policy, untouched
        transcript + settled_target set   -> may auto-apply (the wiki corroborates an anchor)
        transcript + settled_target None  -> review, regardless of tier, count, or LLM
                                             adjudication confidence

    The last line is why this is a separate pass over finished proposals rather than
    another branch in decide(): escalate() can promote a high-confidence context
    adjudication straight to an apply, and for a new transcript term that must be
    impossible. A proposal carrying no `source` is treated as transcript -- missing
    provenance takes the safe branch, never the permissive one.

    The floor is re-checked here because D4's near-miss floor is on the candidate's OWN
    recurrence, while decide()'s gate deliberately weighs variant + canonical together."""
    out = []
    for p in proposals:
        if p.get("verdict") != "apply" or p.get("source", SOURCE_TRANSCRIPT) != SOURCE_TRANSCRIPT:
            out.append(p); continue
        target, grew = p.get("settled_target"), len(p["canonical"]) - len(p["variant"])
        if not target:
            out.append({**p, "verdict": "flag", "reason": "transcript-new-term"})
        elif p.get("variant_count", 0) < NEAR_MISS_MIN_COUNT:
            out.append({**p, "verdict": "flag", "reason": "below-floor"})
        elif grew > GROWTH_MAX:
            out.append({**p, "verdict": "flag", "reason": "growth-over-cap"})
        else:
            out.append(p)
    return out


def decide(variant: str, variant_count: int, canonical: str, canonical_count: int,
           score: float, midsentence: bool, floor: int | None = None) -> dict:
    """Run the four gates over one variant->canonical proposal.

    `floor` is D4's split recurrence floor, defaulting to MIN_COUNT (a brand-new term).
    propose() passes NEAR_MISS_MIN_COUNT for a candidate anchored to a settled term.

    Order matters: the cheap structural rejections come first so the report's reason is the
    most specific true one. R2 (expansion) and R3 (dominance) are the only gates carrying
    real safety -- `score` is a recall floor that has already been applied upstream.

    canonical-unseen means there is NO competing evidence: the canonical spelling never
    appears, so Wilson has nothing to weigh. With no evidence the only safe correction is one
    that is not really a phonetic judgement -- an apostrophe, spacing, a doubled letter --
    which is what reduce_form(variant) == reduce_form(canonical) or score >= UNSEEN_SIM
    tests for. A genuine phonetic leap ('Zoro'->'Zoryu', 0.87) is a CLAIM about what was
    actually said, and a claim needs evidence: either R3 dominance or tier-C context. Absent
    that bar every one of 8109 wiki titles finds SOME obscure article within MIN_SIM of any
    correctly-spelled name, which never appears in dialogue for the excellent reason that it
    is not in the show -- and canonical_count==0 would read that silence as proof."""
    floor = MIN_COUNT if floor is None else floor
    if variant_count + canonical_count < floor:
        return {"verdict": "flag", "reason": "below-floor", "bound": 0.0}
    if not midsentence:
        return {"verdict": "flag", "reason": "sentence-initial-only", "bound": 0.0}
    if is_expansion(variant, canonical):
        return {"verdict": "known", "reason": "short-form", "bound": 0.0}
    if variant == canonical:
        return {"verdict": "flag", "reason": "already-canonical", "bound": 0.0}
    if canonical_count == 0:
        if reduce_form(variant) == reduce_form(canonical) or score >= UNSEEN_SIM:
            return {"verdict": "apply", "reason": "canonical-unseen", "bound": 0.0}
        return {"verdict": "flag", "reason": "unseen-needs-evidence", "bound": 0.0}
    bound = wilson_lower(canonical_count, canonical_count + variant_count)
    if bound > MIN_SHARE:
        return {"verdict": "apply", "reason": "dominant", "bound": bound}
    return {"verdict": "flag", "reason": "share-too-close", "bound": bound}


def _resolve_tokens(counts: dict, titles: list) -> dict:
    """token -> (canonical, score) for every harvested token that resolves to a wiki title.

    This is the module's dominant cost -- 8202 tokens x 8109 titles on One Pace -- so it is
    computed once per acquire() run and shared: propose() and unmatched() both need it, and
    used to each run best_title() over every token independently, doubling the join for no
    reason (unmatched's tokens are a subset of counts, already resolved or not by propose's
    pass). No count/mid-sentence pre-filtering happens here: R6's floor gate compares
    variant_count + canonical_count, not variant_count alone (see
    test_propose_emits_one_proposal_per_variant_with_the_canonical_count's
    Hirohoshi/Shirahoshi cluster), so a token's own low count never proves in advance that
    its match would be discarded -- the canonical it turns out to match could itself be a
    high-count token. Measured on One Pace, the tightest count-only bound that IS always
    safe (skip a token only if even its best possible booster couldn't clear the floor)
    prunes zero of 8202 tokens, so no such pre-filter is applied."""
    index = _title_index(titles)
    word_index = _word_index(index)
    resolved = {}
    for tok in counts:
        name, score = _best_title_indexed(tok, index, word_index)
        if name:
            resolved[tok] = (name, score)
    return resolved


def propose(counts: dict, midsentence: set, titles: list, settled: set | None = None,
            resolved: dict | None = None, candidates: dict | None = None,
            anchors: set | None = None) -> list:
    """One proposal per harvested token that resolves to a wiki title.

    A token matching no title yields nothing here -- it is the tier-B queue's business
    (see acquire()), not a silent drop. An ordinary English variant is flagged rather than
    applied or dropped: dialogue words like 'name' can score deceptively close to a real
    name (JW('name','nami') = 0.90), but real characters ARE English words too (Brook, Law),
    so a human reviewer -- not a silent drop -- gets the final call. The canonical itself is
    exempt: it comes from the wiki and is authoritative.

    `settled` (already `known` or `acquired`) is skipped entirely -- C2: without this, an
    unattended sweep re-proposes a term a human already rejected via --review, and
    apply_proposals happily re-applies it, silently overriding the human decision.

    `resolved` lets a caller that already ran _resolve_tokens() (acquire(), sharing it with
    unmatched()) pass the result straight in instead of paying for the join twice.

    `candidates` (D3a) carries each token's provenance onto its proposal, so the apply rule
    downstream can see WHERE the token came from; `anchors` (D3) is the settled-term set a
    transcript candidate may be a near-miss OF, which also picks D4's floor. Both are
    optional: without them every token is treated as an unanchored transcript token, which
    is the safe reading."""
    settled = settled or set()
    candidates = candidates or {}
    if resolved is None:
        resolved = _resolve_tokens(counts, titles)
    out = []
    for tok, (canon, score) in sorted(resolved.items()):
        if tok in settled:
            continue
        canon_count = counts.get(canon, 0)
        cand = candidates.get(tok) or _candidate(tok, SOURCE_TRANSCRIPT)
        target = settled_target(tok, canon, anchors)
        floor = NEAR_MISS_MIN_COUNT if (target and cand["source"] == SOURCE_TRANSCRIPT) else MIN_COUNT
        d = decide(tok, counts[tok], canon, canon_count, score, tok in midsentence, floor)
        if d["reason"] == "already-canonical":
            continue
        # R6e: the english-word gate must never touch a 'known'/'short-form' verdict --
        # that is a structural "leave dialogue alone" call, not a confidence judgement, and
        # real characters are English words too (Brook, Law). Every other verdict (apply,
        # or an already-flagged reason) is still eligible to be (re)labelled english-word.
        if d["verdict"] != "known" and glossary.is_english(tok.lower()):
            d = {"verdict": "flag", "reason": "english-word", "bound": 0.0}
        out.append({"variant": tok, "canonical": canon, "variant_count": counts[tok],
                    "canonical_count": canon_count, "score": round(score, 3),
                    "source": cand["source"], "settled_target": target,
                    "occurrence_count": counts[tok], "episode_count": cand["episode_count"],
                    "raw_forms": cand["raw_forms"], **d})
    return out


def unmatched(counts: dict, midsentence: set, titles: list, resolved: dict | None = None) -> list:
    """Frequent, mid-sentence tokens that resolved to no wiki title at all.

    This is the dub-only-name queue: a character the dub renamed outright ('Ash' where the
    wiki is titled in romaji) matches nothing phonetically, which is a MISS, never a
    corruption. Tier B asks the wiki's full-text search about these.

    `resolved` lets a caller share one _resolve_tokens() pass with propose() instead of
    the join running twice (see propose's docstring)."""
    if resolved is None:
        resolved = _resolve_tokens(counts, titles)
    return sorted(t for t, c in counts.items()
                  if c >= MIN_COUNT and t in midsentence and t not in resolved)


def _provenance(p: dict, scope: int) -> dict:
    """D3a/D3b: the source, the anchor, and the episode set the counts were taken over.

    Recorded on BOTH lanes. On `acquired` it is the justification for an unattended write;
    on `flagged` it is the evidence a reviewer needs -- a review queue whose entries arrive
    without the reason they escalated defeats the point of escalating."""
    return {"source": p.get("source", SOURCE_TRANSCRIPT), "settled_target": p.get("settled_target"),
            "episode_count": p.get("episode_count", 0), "scope": scope}


def apply_proposals(gloss: dict, proposals: list, run_id: str, scope: int = 0) -> dict:
    """Write applied proposals into hard_fixes + acquired; record the rest in flagged.

    Pure: deep-copies its input the way glossary_verify.apply_results does, so curated
    hard_fixes, names and initial_prompt survive untouched.

    Acquired canonicals deliberately do NOT join `names`, and therefore never reach the
    regenerated initial_prompt. That is the cut that keeps a wrong entry from biasing the
    next transcription into producing more of the same spelling -- which would raise its
    count and reinforce the dominance test that let it in.

    C2/I3: every verdict clears whatever a PRIOR run -- automated or human -- left behind
    for the same term, mirroring record_decision. Without this a term can end up both
    `known` (a human said no) and freshly hard-fixed (a later sweep said yes), which is
    exactly the both-states bug this module exists to avoid reintroducing."""
    g = json.loads(json.dumps(gloss))
    fixes = g.setdefault("hard_fixes", {})
    acquired = g.setdefault("acquired", {})
    flagged = g.setdefault("flagged", {})
    known = set(g.get("known", []))
    for p in proposals:
        term = p["variant"]
        flagged.pop(term, None)                     # I3: never stays queued once decided
        if p["verdict"] == "known":
            known.add(term); continue
        if p["verdict"] != "apply":
            fixes.pop(term, None); acquired.pop(term, None)
            flagged[term] = {"reason": p["reason"], "canonical": p["canonical"],
                             "variant_count": p["variant_count"], "canonical_count": p["canonical_count"],
                             "score": p["score"], "bound": round(p.get("bound", 0.0), 3),
                             "context": p.get("context", []), **_provenance(p, scope)}
            continue
        known.discard(term)                          # C2: an apply verdict wins over a stale known
        fixes[term] = p["canonical"]
        acquired[term] = {"canonical": p["canonical"], "count": p["variant_count"],
                          "canonical_count": p["canonical_count"],
                          "score": p["score"], "bound": round(p.get("bound", 0.0), 3),
                          "reason": p["reason"], "run": run_id, **_provenance(p, scope)}
    if not flagged:
        g.pop("flagged", None)
    if known:
        g["known"] = sorted(known)
    else:
        g.pop("known", None)
    return g


def revert(gloss: dict, run_id: str | None = None) -> dict:
    """Remove hard_fixes this module wrote, restoring the pre-acquisition glossary.

    A fix whose current value no longer matches what we recorded has been edited by hand
    since; leave it alone and drop only our provenance for it.

    R4: an entry with run == "review" is a human's decision (record_decision), not this
    module's automated guess. A blanket --revert must never delete one, regardless of
    `run_id` -- reverting an automated sweep must not also undo what a person approved."""
    g = json.loads(json.dumps(gloss))
    fixes, acquired = g.get("hard_fixes", {}), g.get("acquired", {})
    for variant, meta in list(acquired.items()):
        if meta.get("run") == "review":
            continue
        if run_id is not None and meta.get("run") != run_id:
            continue
        if fixes.get(variant) == meta.get("canonical"):
            fixes.pop(variant, None)
        acquired.pop(variant, None)
    return g


def review_items(gloss: dict) -> list:
    """The pending review queue, normalised.

    glossary_verify writes bare strings; this module writes objects. Both load, so the
    queue that has been accumulating unread since the verifier shipped is reviewable too.

    Normalisation FILLS the fixed key set; it does not restrict the entry to it. Producers
    attach the evidence they escalated on -- mine_glossary's possessive_floor_crossing
    carries `bare`/`possessive`, this module's entries carry `source`/`settled_target`/
    `scope` -- and a queue whose entries arrive stripped of the reason they escalated
    cannot be reviewed, which is the whole point of escalating."""
    out = []
    for term, meta in sorted((gloss.get("flagged") or {}).items()):
        if isinstance(meta, str):
            meta = {"reason": meta}
        item = {"term": term, "reason": meta.get("reason", ""),
                "canonical": meta.get("canonical", ""),
                "variant_count": meta.get("variant_count", 0),
                "canonical_count": meta.get("canonical_count", 0),
                "bound": meta.get("bound", 0.0), "context": meta.get("context", [])}
        for k, v in meta.items():
            if k not in item:
                item[k] = v
        out.append(item)
    return out


def record_decision(gloss: dict, term: str, accept: bool) -> dict:
    """Apply one human decision and drop the term from the queue for good, in exactly one state.

    accept and reject are mutually exclusive: each clears whatever the other branch -- or a
    stale prior decision from an earlier run -- may have left behind, so a term is never both
    known and hard-fixed at once.

    C1 defence in depth: this cannot see `titles` (best_title's normalised set), so it
    cannot repeat R1's membership check. It CAN repeat the other two structural checks --
    not an expansion, and the canonical is already in normalised form -- and does, before
    ever writing to hard_fixes. A canonical failing either is free-form model/human-typo
    text, not a wiki spelling, and must not become a hard_fix even on a human 'y'."""
    g = json.loads(json.dumps(gloss))
    meta = (g.get("flagged") or {}).get(term)
    if isinstance(meta, str):
        meta = {"reason": meta}
    meta = meta or {}
    canon = meta.get("canonical", "")
    if accept and canon and not is_expansion(term, canon) and normalize_title(canon) == canon:
        g.setdefault("hard_fixes", {})[term] = canon
        g.setdefault("acquired", {})[term] = {"canonical": canon, "count": meta.get("variant_count", 0),
                                              "canonical_count": meta.get("canonical_count", 0),
                                              "score": meta.get("score", 0.0), "bound": meta.get("bound", 0.0),
                                              "reason": "human-approved", "run": "review"}
        g["known"] = sorted(set(g.get("known", [])) - {term})
        g.get("flagged", {}).pop(term, None)
    elif accept and canon:
        g.setdefault("flagged", {})[term] = {**meta, "reason": "unsafe-canonical-rejected"}
    else:
        g["known"] = sorted(set(g.get("known", [])) | {term})
        g.get("hard_fixes", {}).pop(term, None)
        g.get("acquired", {}).pop(term, None)
        g.get("flagged", {}).pop(term, None)
    for k in ("flagged", "known", "hard_fixes", "acquired"):
        if not g.get(k):
            g.pop(k, None)
    return g


def _write_json(path: str, obj) -> None:
    """Atomic, UTF-8-safe glossary write: tmp file + os.replace, handle always closed.

    C3: `open(path, 'w')` truncates the file immediately and, with ensure_ascii=False over
    Japanese names, can raise mid-write under a locale-derived encoding -- either way the
    curated glossary is gone. The tmp+replace dance means a failed write leaves the
    original untouched; explicit encoding='utf-8' removes the locale dependency."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def acquire(gloss_path: str, show_dir: str, apply: bool = False, override: str | None = None) -> dict:
    """Harvest -> score -> gate -> (optionally) write. Returns a report; never raises.

    Resilient by the same contract as glossary_verify.verify(): any wiki, LLM or IO failure
    leaves the glossary untouched and is reported, not raised."""
    try:
        gloss = json.load(open(gloss_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"note": f"load-failed: {e}"}
    show = gloss.get("show") or os.path.basename(gloss_path)[:-5]
    # Harvest-first: nothing to score means no reason to spend a wiki round-trip.
    cands, mid, scope = harvest_candidates(show_dir)
    counts = {t: c["occurrence_count"] for t, c in cands.items() if c["occurrence_count"]}
    files = len(scope)
    if not counts:
        return {"show": show, "note": "nothing harvested", "files": files}
    api = glossary_verify.resolve_wiki(show, override or gloss.get("wiki"))
    if not api:
        return {"show": show, "note": "wiki unresolved", "files": files}
    try:
        titles = glossary_verify.fetch_titles(api, show)
    except Exception as e:
        return {"show": show, "wiki": api, "note": f"titles-failed: {e}", "files": files}
    if not titles:
        return {"show": show, "wiki": api, "note": "no titles fetched", "files": files}
    norm_titles = {normalize_title(t) for t in titles if normalize_title(t)}
    # C2: skip anything a human or an earlier sweep already settled, so an unattended
    # rerun can never re-propose (and re-apply) a term someone already rejected.
    settled = set(gloss.get("known", [])) | set(gloss.get("acquired", {}))
    # I6/perf: the token x title join is the module's dominant cost -- resolve every
    # harvested token against the wiki exactly once and hand the same result to propose()
    # and unmatched(), instead of each independently re-running it (was ~1.5x the work).
    resolved = _resolve_tokens(counts, titles)
    anchors = anchor_terms(gloss)
    # Per-token decision cache. `settled` alone was 107 terms against 8,199 harvested, so
    # ~99% of the work -- including 371 LLM calls in escalate, 71% of this stage's runtime --
    # was re-derived every sweep, and the stage exceeded its timeout three sweeps running
    # without ever completing. A cached verdict folds into the same skip `settled` uses, so
    # nothing downstream needs to know the cache exists.
    #
    # ACQUIRE_NO_CACHE=1 forces a full run without editing the file, for the case where an
    # operator wants to re-derive everything after changing a threshold.
    cache = {} if os.environ.get("ACQUIRE_NO_CACHE") else acquire_cache.load(gloss_path)
    cached = acquire_cache.skippable(
        cache, counts, lambda t: settled_target(t, resolved.get(t, ("", 0))[0], anchors),
        norm_titles, normalize_title) if cache else set()
    settled = settled | cached
    proposals = propose(counts, mid, titles, settled, resolved=resolved,
                        candidates=cands, anchors=anchors)
    close = [p for p in proposals if p.get("reason") == "share-too-close"]
    if close:
        toks = sorted({p["variant"] for p in close} | {p["canonical"] for p in close})
        proposals = escalate(proposals, context_lines(show_dir, toks), show)
    # D3: the source-aware apply rule runs LAST, over finished proposals -- after the tier
    # logic and after escalate(), which can otherwise promote a confident context
    # adjudication for a brand-new transcript term straight into the glossary.
    proposals = source_gate(proposals)
    # Remember what this run decided, AFTER source_gate -- what gets stored is the verdict
    # the pipeline actually reached, including the post-escalate outcome, which is the LLM
    # cost this cache exists to stop repaying. Never fatal: a cache that cannot be written
    # is a slow next run, not a failed this one.
    #
    # DELIBERATELY NOT gated on `apply`. The cache is a memo of computed verdicts, not a
    # glossary mutation -- the dry-run safety convention does not apply to it, and gating it
    # was a real bug: gen_loop.sh only passes --apply when ACQUIRE_APPLY is set, which it is
    # not, so acquire runs dry every sweep. The cache would therefore never have been written
    # at all, and the 25-minute run that finally completed on 2026-08-21 banked nothing.
    # A dry run computes the same verdicts; `apply` only controls whether apply_proposals
    # writes them into the glossary.
    acquire_cache.save(gloss_path, acquire_cache.remember(cache, proposals, counts))
    # I4: attach real transcript evidence to every flagged proposal so the review queue
    # (and --review's CLI) has something to show a human, instead of an empty context: [].
    flag_terms = sorted({p["variant"] for p in proposals if p["verdict"] == "flag"})
    if flag_terms:
        fctx = context_lines(show_dir, flag_terms)
        for p in proposals:
            if p["verdict"] == "flag":
                p["context"] = fctx.get(p["variant"], [])
    tier_b = {}
    for term in unmatched(counts, mid, titles, resolved=resolved):
        try:
            adj = glossary_verify.adjudicate(term, glossary_verify.candidates(term, titles), show)
        except Exception as e:
            log("acquire: adjudicate failed:", term, e); continue
        if adj.get("confidence") != "high" or not adj.get("canonical"):
            continue
        # C1: tier B's canonical is free-form LLM text -- re-run R1 (wiki membership) and
        # R2 (expansion) on it exactly like tier A, or it becomes the module's only path
        # for un-vetted model text to reach hard_fixes. A failing canonical is recorded
        # empty: still reviewable, but nothing left for a human to accept-and-auto-apply.
        canon = normalize_title(adj["canonical"])
        tier_b[term] = canon if (canon in norm_titles and not is_expansion(term, canon)) else ""
    applied = [p for p in proposals if p["verdict"] == "apply"]
    known = [p for p in proposals if p["verdict"] == "known"]
    flag_props = [p for p in proposals if p["verdict"] == "flag"]     # I5: was shadowed below
    digest = hashlib.sha1("|".join(f"{p['variant']}>{p['canonical']}" for p in sorted(
        proposals, key=lambda p: p["variant"])).encode()).hexdigest()[:8]
    run_id = f"{show}:{len(titles)}:{files}:{digest}"
    if apply and (proposals or tier_b):
        try:
            out = apply_proposals(gloss, proposals, run_id, files)
            if tier_b:
                tctx = context_lines(show_dir, list(tier_b))
                flagged = out.setdefault("flagged", {})
                for term, canon in tier_b.items():
                    flagged[term] = {"reason": "no-wiki-match", "canonical": canon,
                                     "variant_count": counts.get(term, 0), "canonical_count": 0,
                                     "bound": 0.0, "context": tctx.get(term, []),
                                     **_provenance(cands.get(term, {}), files)}
            _write_json(gloss_path, out)
        except Exception as e:
            try: os.remove(gloss_path + ".tmp")
            except OSError: pass
            return {"show": show, "wiki": api, "note": f"write-failed: {e}", "files": files}
    return {"show": show, "wiki": api, "files": files, "titles": len(titles),
            "proposed": len(proposals), "applied": len(applied), "known": len(known),
            "flagged": len(flag_props), "dry_run": not apply, "scope": len(scope),
            "scope_episodes": [os.path.basename(s) for s in scope],
            "proposals": proposals, "tier_b": tier_b}


def main():
    ap = argparse.ArgumentParser(description="Acquire proper nouns from a show's own output + its wiki.")
    ap.add_argument("glossary", help="path to <show>.json")
    ap.add_argument("show_dir", help="the show's media directory")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--wiki", default=None, help="override the wiki API base")
    ap.add_argument("--revert", action="store_true", help="undo previously acquired fixes and exit")
    ap.add_argument("--review", action="store_true", help="walk the pending queue interactively")
    a = ap.parse_args()
    if a.review:
        g = json.load(open(a.glossary, encoding="utf-8"))
        for item in review_items(g):
            log(f"\n{item['term']}  ->  {item['canonical'] or '(no canonical)'}   [{item['reason']}]")
            log(f"  seen {item['variant_count']}x vs canonical {item['canonical_count']}x, bound {item['bound']:.3f}")
            for ln in item["context"]:
                log(f"    | {ln}")
            if item["canonical"]:
                ans = input("  accept this fix? [y/N/q] ").strip().lower()
                if ans == "q":
                    break
                g = record_decision(g, item["term"], accept=(ans == "y"))
            else:
                ans = input("  no fix proposed - mark this spelling correct as-is? [y/N/q] ").strip().lower()
                if ans == "q":
                    break
                if ans == "y":
                    g = record_decision(g, item["term"], accept=False)
                # 'n' (or anything else): leave it pending in flagged, untouched
        if a.apply:
            _write_json(a.glossary, g)
        log(json.dumps({"reviewed": True, "written": a.apply, "pending": len(g.get("flagged", {}))}))
        return
    if a.revert:
        try:
            g = json.load(open(a.glossary, encoding="utf-8"))
        except (OSError, ValueError) as e:
            log(json.dumps({"note": f"load-failed: {e}"}))
            return
        out = revert(g)
        if a.apply:
            _write_json(a.glossary, out)
        log(json.dumps({"reverted": len(g.get("acquired", {})), "written": a.apply}))
        return
    rep = acquire(a.glossary, a.show_dir, apply=a.apply, override=a.wiki)
    for p in rep.get("proposals", []):
        log(f"{p['verdict']:5} {p['variant']:18} -> {p['canonical']:22} "
            f"seen {p['variant_count']:4}/{p['canonical_count']:<4} sim {p['score']:.3f} "
            f"bound {p.get('bound', 0.0):.3f}  {p['reason']}")
    log(json.dumps({k: v for k, v in rep.items() if k != "proposals"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
