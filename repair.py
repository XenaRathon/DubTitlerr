#!/usr/bin/env python3
"""REPAIR stage (gold) — fix garbled low-confidence dub dialogue using the video's
own embedded subtitle (a *different* translation of the same scene) as a semantic
anchor, via a local LLM. Runs between generate.py and the assemble stage.

Whisper sometimes mishears hard audio (overlap, SFX, mumbling). Those segments
carry a low ``avg_logprob`` (recorded by generate.py in ``<stem>.dubtitles.conf.json``).
For each such SPEECH segment (low logprob but not music — ``no_speech_prob`` low),
we find the embedded *dialogue* line(s) overlapping that time window and ask a
local LLM to reconstruct the most likely English-DUB line: keep the transcription's
wording where it's plausible, use the subtitle only to resolve the garbled parts,
never copy the subtitle verbatim (dub != sub — localization differs).

Then the ``.srt`` is rewritten from the (possibly repaired) confidence rows and a
``<stem>.dubtitles.repair.csv`` audit (orig -> repaired) is written. Timing untouched.
A ``<stem>.dubtitles.repair-summary.json`` (targets/repaired/skipped/latency stats/model(s))
is written alongside it (V2 A10).

C1: targets are broadened to mid-confidence-AND-lower OR name-suspect lines; the show
glossary is injected into a STRICT prompt (canonical spellings, never invent/swap a name);
the LLM only runs on lines with a fansub anchor (the bake-off showed glossary-only repair
hallucinates names even on qwen3:8b, so no-anchor lines keep the deterministic text); the
LLM output is run back through the deterministic correction to enforce canon.

CPU/network only — the LLM runs on the 2070 (Ollama) or, optionally, a llama.cpp server.
Env:
  OLLAMA_URL           default http://127.0.0.1:11434/api/generate
  REPAIR_MODEL         default nanbeige4.2-3b   (see the note at MODEL: it reverses the
                         C1 bake-off's qwen3:8b on this file's own measurements)
  REPAIR_BACKEND         ollama | llamacpp  (default llamacpp; see the note at
                         REPAIR_BACKEND — V2 A1 added the dispatch, the default moved later)
  REPAIR_LLAMACPP_URL    default http://127.0.0.1:8090/v1/chat/completions
                         (chat endpoint: the raw /completion path applies no chat
                         template and yields empty output from instruct models)
  REPAIR_MODEL_SECONDARY default REPAIR_MODEL — two-pass re-check model (V2 A3; no-op if equal)
  REPAIR_TIMEOUT_CONNECT default 10   (seconds; V2 A2)
  REPAIR_TIMEOUT_READ    default 120  (seconds; V2 A2)
  MAX_REF_BORROW default 3     (reject a repair importing this many NEW words that are
                                present in the fansub reference — see accept_repair)
  LEN_RATIO_MIN default 0.6    (…and reject one whose length ratio leaves this band)
  LEN_RATIO_MAX default 1.5
                               C2/C4/C5: on top of these, a repair is rejected unless the
                               RESULT still fits the card — <=MAX_LINES lines of <=MAX_LINE
                               after reflow.wrap_balance, <=MAX_CHARS, and <=MAX_CPS at the
                               card's DISPLAY duration. Card timing is immutable in repair
                               (C1), so the repair gives way, never the timing. The
                               secondary-model pass goes through the identical gate.
  LOGPROB_MIN   default -0.4   (mid-confidence-and-lower; below this is a repair target)
  NSP_MAX       default 0.5    (…and below this no_speech_prob — i.e. it IS speech)
  GLOSSARY_DIR  default /config/glossaries   (per-show glossary, resolved from the path)
  DECISIONS_DIR default /config/decisions    (per-show human verdicts, resolved the same
                               way; absent on every install that has never reviewed
                               anything, which is an empty store and a no-op)
  DECISIONS_APPLY default 1    ([S-4]) apply stored verdicts. A reject keeps the ASR text,
                               a correct substitutes the human's wording, a force admits a
                               repair accept_repair refused, and any of the four marks the
                               line settled so it is not queued for review again. "0" is
                               suggestion-only: verdicts are still recorded by the review,
                               repair simply stops acting on them. NOTHING overrides
                               fits_card — C1 keeps card timing immutable for humans too.
  SUB_LANGS     accepted embedded-sub languages (default eng,en,und,) -- read by
                common.dialogue_intervals (T1: hoisted out of this module)
  MEDIA_UID/GID default 1000/100
Requires ffmpeg/ffprobe + pysubs2.  Built with help of Claude (Anthropic).
"""

import csv
import http.client
import json
import os
import re
import sys
import time
import urllib.parse

import decisions
import glossary
import hallucination
import qc
import reflow
import unresolved
from common import MEDIA_GID, MEDIA_UID, dialogue_intervals, find_video, out_for, ts_srt

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
# nanbeige4.2-3b, not qwen3:8b. The C1 bake-off locked qwen and this reverses that, on the
# evidence already in this file: qwen makes MORE fixes (23 safe fixes per 120 targets against
# nanbeige's 16) but imports the fansub reference verbatim into 84.1% of its repairs, 29.2%
# of them three words or more, against nanbeige's 52.5% and 17.1% -- the failure that turned
# "That's enough of that, idiots!" into "Hold it, you brats!". It also makes 14 name edits to
# nanbeige's 2. Fewer, safer repairs is the right default for a stage whose damage is
# invisible to every mechanical gate; it also happens to be the model that fits beside
# whisper on one card.
MODEL = os.environ.get("REPAIR_MODEL", "nanbeige4.2-3b")
# llamacpp, not ollama. The owner swapped to it on measurement -- it was the stronger
# performer -- and it is what both arms of the quant A/B run on, so the default matches
# what the numbers in the README will have been taken on. It costs a beta user a harder
# install than `ollama pull`; the quickstart carries that, and OLLAMA_URL still works for
# anyone who prefers it.
REPAIR_BACKEND = os.environ.get("REPAIR_BACKEND", "llamacpp")
# Loopback, not a LAN address. The previous default named a host that was DEAD, so the
# documented default could not have worked for anybody -- including the maintainer, who was
# passing this explicitly and had no reason to notice.
LLAMACPP_URL = os.environ.get("REPAIR_LLAMACPP_URL", "http://127.0.0.1:8090/v1/chat/completions")
MODEL_SECONDARY = os.environ.get("REPAIR_MODEL_SECONDARY", MODEL)
TIMEOUT_CONNECT = float(os.environ.get("REPAIR_TIMEOUT_CONNECT", "10"))
TIMEOUT_READ = float(os.environ.get("REPAIR_TIMEOUT_READ", "120"))
LOGPROB_MIN = float(os.environ.get("LOGPROB_MIN", "-0.4"))  # mid-confidence-and-lower (C1)
NSP_MAX = float(os.environ.get("NSP_MAX", "0.5"))
GLOSSARY_DIR = os.environ.get("GLOSSARY_DIR", "/config/glossaries")
ROOTS = os.environ.get("MERGE_ROOTS", "/data/Media/Anime Library").split(":")
CONF_SUFFIX = ".dubtitles.conf.json"
SRT_SUFFIX = ".eng.dubtitles.srt"


def log(*a):
    print(*a, flush=True)


def glossary_for(path, gloss_dir=GLOSSARY_DIR):
    """Resolve the show glossary for an episode by walking up to the first ancestor
    directory that has a matching <Show>.json in the glossary dir; else a no-op glossary."""
    d = os.path.dirname(os.path.abspath(path))
    while d and d != os.path.dirname(d):
        gp = os.path.join(gloss_dir, os.path.basename(d) + ".json")
        if os.path.exists(gp):
            return glossary.load(gp)
        d = os.path.dirname(d)
    return glossary.load("")


LOW_WORD_PROB = 0.25  # V2 A7: a single word this unconfident marks the whole card a target


def has_low_prob_word(c):
    """True if any per-word linear probability in ``word_probs`` (V2 A6, generate.py) is
    below LOW_WORD_PROB -- catches a single wildly-mis-heard word hiding inside a card
    whose avg_logprob still looks fine overall. Missing/empty ``word_probs`` (older
    conf.json files predating A6, or a card generate.py couldn't join any words to) ->
    False, backward-compatible."""
    return any(p < LOW_WORD_PROB for p in c.get("word_probs", []))


def is_target(c, gloss):
    """A conf row to send to the LLM: it must be speech (low no_speech_prob) AND either
    mid-confidence-or-lower, name-suspect, OR containing a very-low-confidence word."""
    if c.get("no_speech_prob", 1.0) > NSP_MAX:
        return False
    return c.get("avg_logprob", 0.0) < LOGPROB_MIN or has_low_prob_word(c) or glossary.name_suspect(c.get("text", ""), gloss)


def _glossary_terms(gloss, arc=None):
    """The reference-spelling list for the prompt, current arc first.

    S-13: the cap below is not cosmetic -- measured 2026-08-26 on the live One Pace
    glossary, 1000 chars holds 110 of 140 terms and silently drops 30, `Nico Robin` and
    `Rob Lucci` among them. Whatever sorts last is simply never shown to the model, so the
    order decides which names it can verify against.

    Weighting REORDERS; it never filters. Dropping an out-of-arc name would make things
    worse, not better: a name absent from the list reads to the model as unrecognised, and
    the documented failure (`Oimo` -> `Zoro`) is exactly a valid name being "corrected"
    into a listed one. Every term still fitting the cap is still offered -- the arc's names
    just get first claim on the budget.

    A term in several arcs is prioritised in all of them, so a recurring character is never
    demoted in an arc he genuinely appears in. With no arc, or a glossary carrying no tags
    -- which is every glossary in the library today -- the order is exactly as before."""
    terms = list(gloss["names"]) + list(gloss["phrases"])
    terms += list(gloss["token_fixes"].values()) + list(gloss["phrase_fixes"].values())
    seen, out = set(), []
    for t in terms:  # de-dup, preserve order
        if t not in seen:
            seen.add(t)
            out.append(t)
    tags = gloss.get("arc_tags") or {}
    if arc and tags:
        # stable partition: in-arc terms keep their relative order, then the rest
        # An UNTAGGED name defaults IN. The 92 names already in the library predate
        # tagging; reading "no tags" as "not this arc" would demote the whole existing
        # glossary behind a handful of newly tagged ones, making the first weighted run a
        # strict subset of what the model already had. Only a name KNOWN to belong to other
        # arcs is demoted.
        in_arc = [t for t in out if arc in (tags.get(t.lower()) or (arc,))]
        out = in_arc + [t for t in out if t not in set(in_arc)]
    # C12: cap the prompt size on WHOLE-TERM boundaries -- a raw [:1000] slice can cut a
    # name in half mid-word, which would feed the model a garbled "canonical spelling".
    result = ""
    for t in out:
        candidate = t if not result else f"{result}, {t}"
        if len(candidate) > 1000:
            break
        result = candidate
    return result


def skips_unanchored(ref, gloss=None):
    """Whether a card with reference ``ref`` is refused before the LLM is ever called.

    S-12. Historically this was unconditional: no fansub anchor meant no repair, because
    "the bake-off showed glossary-only repair hallucinates names (Oimo->Zoro) even on
    qwen3:8b" and the deterministic layer was the safe ceiling. That ceiling leaves real
    damage on screen -- measured on One Pace S31E01, 161 targets were refused here and 0
    repaired, and the season carries 6,492 such cards. Among them was `Dothamingo`, which
    `glossary.correct()` cannot reach (difflib 0.800 against a 0.84 cutoff; metaphone T0MNK
    vs TFLMNK) and which therefore nothing in the pipeline could fix.

    Re-running those 161 with the gate open produced 21 repairs, 18 acceptable, including
    `Dothamingo` -> `Doflamingo`. But that is ONE episode of ONE show on ONE model against a
    decision taken on a measured sweep, so the gate stays CONDITIONAL and defaults CLOSED.
    Turning it on is a deliberate act, and `substitutes_a_vouched_name` guards the path it
    opens.

    A2. The gate is now declared PER SHOW, in the glossary, rather than by a global that no
    committed artifact records. The live One Pace library was produced with the env flag
    hand-set; nothing in the repo said so, so a merge pass run from the committed scripts
    skipped every card and rebuilt the srt as raw ASR OVER the shipped repairs (reproduced
    on S31E24: targets=144 repaired=0 skipped_no_ref=144). A show declares
    `unanchored_repair` when the user's copies carry no English subtitles for the Japanese
    audio -- a mainstream configuration for dub-only libraries, not a One Pace quirk.

    The global default stays CLOSED and everything above stays the authority on why: a
    show that declares nothing behaves exactly as it did before."""
    return not ref and not (REPAIR_UNANCHORED or (gloss or {}).get("unanchored_repair"))


def build_prompt(asr, sub, gloss, prev_text="", next_text="", arc=None):
    """Build the repair prompt. Every element here is the result of a measured sweep over
    real conf.json targets (3 shows x 40 targets, temperature 0), not authorship taste.

    Two failure modes had to be balanced against each other:
      * qwen3.5:9b, told only what NOT to do, rewrote 42% of lines and pasted glossary
        names over correct text ("Border Control" -> "Cipher Pol", "Neptune" ->
        "Nefertari Vivi", "Uchihime" -> "Uchiha" -- a name from another franchise).
      * nanbeige4.2-3b, given the same prohibitions, went inert: 0 safe fixes across 120
        targets, returning the input verbatim, losing the real repairs it used to make.

    What resolved both at once:
      * the name list framed as VERIFICATION ONLY, never as material to apply;
      * an explicit POSITIVE DUTY -- rules phrased only as prohibitions produce a model
        that does nothing, which is not a repair stage;
      * NO worked example of leaving a name alone. Counter-intuitive, but it over-anchored
        inaction: removing it was the single biggest gain in the sweep (nanbeige 12 -> 16
        safe fixes, qwen 6 -> 23) *and* name edits went down for both;
      * nothing after the ASR line. An earlier version put a trailing "Remember:" reminder
        there and the model echoed that rule text into the subtitle output.

    Measured on 120 targets: qwen 6 -> 23 safe fixes (17 -> 14 name edits), nanbeige
    0 -> 16 safe fixes (1 -> 2 name edits), zero prompt leaks or length blowups for either.

    prev_text/next_text are extra context only -- never part of what gets corrected."""
    names = _glossary_terms(gloss, arc)
    head = "You fix speech-recognition errors in one English-dub subtitle line.\n"
    name_line = (f"Reference spellings (VERIFICATION ONLY - this is NOT a list of names to insert): {names}.\n") if names else ""
    ref_intro = (
        (
            "A DIFFERENT translation of this moment is quoted below; use it only to "
            "resolve garbled words and confirm names, never to copy its wording.\n"
        )
        if sub
        else ""
    )
    rules = (
        "Rules:\n"
        "- You MUST fix: run-together sentences with missing punctuation, missing "
        "capitalisation at a sentence start, and obviously garbled ordinary words.\n"
        "- You MUST NOT change any proper noun unless it is an obvious phonetic "
        "misspelling of a reference spelling above.\n"
        "- Never insert a name that is not already in the line.\n"
        "- Do NOT turn ordinary words into names. Keep the wording and length almost identical.\n\n"
        "Example -> ASR line: it worked Now we run\n"
        "Corrected line: It worked. Now we run.\n"
        "(Two sentences were run together with no punctuation. That IS damage - fix it.)\n\n"
        "Return ONLY the corrected line - no quotes, no notes, no rule text.\n\n"
    )
    # C9: the fansub reference is untrusted third-party text -- keep it wrapped in an XML
    # tag so it reads as quoted DATA, not instructions (prompt-injection guard). Context
    # and reference come BEFORE the ASR line: anything trailing it gets echoed into output.
    prev_line = f'Previous line (for context): "{prev_text}"\n' if prev_text else ""
    next_line = f'Next line (for context): "{next_text}"\n' if next_text else ""
    ref_line = f"<official_subtitle_reference>{sub}</official_subtitle_reference>\n" if sub else ""
    return f"{head}{name_line}{ref_intro}{rules}{prev_line}{next_line}{ref_line}ASR line: {asr}\nCorrected line:"


def overlap_ref(ivals, a, b):
    hits = [t for (s, e, t) in ivals if e > a and s < b]  # any time overlap
    return " ".join(hits)[:300]


def _post_json(url, body):
    """POST body (dict) as JSON to url with separate connect (TIMEOUT_CONNECT) and read
    (TIMEOUT_READ) timeouts (V2 A2). stdlib's urllib.request.urlopen only exposes a single
    timeout for the whole call (connect + every read), so we go one layer lower via
    http.client: the connect timeout is set on the connection itself (used for connect()),
    then the read timeout is set on the underlying socket right after connecting."""
    parsed = urllib.parse.urlsplit(url)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port, timeout=TIMEOUT_CONNECT)
    try:
        conn.connect()
        conn.sock.settimeout(TIMEOUT_READ)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        conn.request("POST", path, body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}: {data[:200]!r}")
        return json.loads(data)
    finally:
        conn.close()


REPAIR_UNANCHORED = os.environ.get("REPAIR_UNANCHORED", "") not in ("", "0")
# [S-4] Apply stored human verdicts. Default ON: the store is empty on every install that
# has never reviewed anything, and an empty store is a no-op, so the default costs nothing.
# "0" drops the whole path to suggestion-only -- the review still records verdicts, repair
# just stops acting on them -- which is the knob for an operator who wants the queue as a
# report rather than as an authority.
DECISIONS_APPLY = os.environ.get("DECISIONS_APPLY", "1") not in ("", "0")
# The verdicts that SHIP a repair. All three bypass accept_repair identically: its length
# band and borrow limit are heuristics standing in for a reader, and a reader has now read
# the line. They differ in what the gate said at REVIEW time -- `accept` confirms a repair
# it admitted, `force` overrides one it refused, `correct` supplies different words -- which
# is what the review UI offers and what the store counts, not how repair applies them.
#
# `accept` belongs here for a reason that is easy to miss: accept_repair's answer is not
# stable over time. LEN_RATIO_*/MAX_REF_BORROW are operator knobs, the glossary changes, and
# `ref` moves when a video is re-muxed. Re-judging an accepted line means a later glossary
# edit can silently revert a human decision AND re-queue it as a fresh guard rejection.
APPLYING = ("accept", "correct", "force")
MAX_REF_BORROW = int(os.environ.get("MAX_REF_BORROW", "3"))
LEN_RATIO_MIN = float(os.environ.get("LEN_RATIO_MIN", "0.6"))
LEN_RATIO_MAX = float(os.environ.get("LEN_RATIO_MAX", "1.5"))

_WORD = re.compile(r"[a-z']+")


def _words(s):
    return _WORD.findall((s or "").lower())


def borrowed_from_ref(orig, new, ref):
    """Words the repair ADDED that are present in the fansub reference.

    These are the signature of the model treating the reference as the answer rather than
    as a disambiguation aid. Words already in the ASR line don't count (keeping them isn't
    borrowing), and invented words absent from the reference don't either — that is
    hallucination, a different failure with its own guards."""
    had, have, in_ref = set(_words(orig)), _words(new), set(_words(ref))
    return [w for w in have if w not in had and w in in_ref]


def fits_card(text, dur, orig=None):
    """Whether ``text`` can be DISPLAYED legally on a card lasting ``dur`` seconds (C4).

    Validates the candidate as it will actually be written: through the same
    ``reflow.wrap_balance`` + flatten normalisation generate.py uses, so the thing checked
    is the thing shipped. Per line, not total only -- a total-char check passes text that
    is visually invalid (an 85-char card wraps to two legal 42-char lines but is one
    character over the card ceiling; a 49-char card whose word boundaries fall badly wraps
    to a 44-char line), and that blind spot is exactly how the library-wide wrapping defect
    survived. Line lengths are integer character counts, so only cps needs EPS."""
    wrapped = reflow.wrap_balance((text or "").replace("\n", " "))
    if not reflow.layout_faults(wrapped, dur):
        return True
    if orig is None:
        return False
    # The card ALREADY breaks the profile -- ~28% of cards are over cps, and A2
    # deliberately does not retime for cps. Refusing every repair on those would refuse
    # to fix `Zorro`->`Zoro` on a dense line, which is the exact case repair exists to
    # serve. Accept a repair that worsens NO dimension; reject one that worsens any.
    before = reflow.layout_metrics(reflow.wrap_balance((orig or "").replace("\n", " ")), dur)
    after = reflow.layout_metrics(wrapped, dur)
    return all(a <= b + reflow.EPS for a, b in zip(after, before))


PHONETIC_MIN = float(os.environ.get("REPAIR_PHONETIC_MIN", "0.75"))


def _proper_cores(text):
    """Capitalised, non-English, glossary-shaped bare cores -- the tokens both name guards
    reason about. Shared so the two cannot drift apart on what counts as a proper noun."""
    out = []
    for tok in (text or "").split():
        m = glossary._TOKEN_RE.match(tok)
        if not m:
            continue
        core = m.group(2)
        if core[:1].isupper() and len(core) >= glossary.MIN_FUZZY_LEN and not glossary.is_english(core):
            out.append(core)
    return out


def invents_name(orig, new, gloss):
    """True if ``new`` substitutes an INVENTED proper noun for one that was in ``orig``.

    By the time this runs, ``glossary.correct(new, gloss)`` has already executed (see the
    call site in process(), repair.py:513): any token the deterministic tiers can match to
    a glossary name -- exact, hard-fix, or guarded-fuzzy/metaphone -- is already snapped to
    its canonical spelling. So ``Syrahose -> Shirahoshi`` is handled upstream and never
    reaches here. What this function judges is the residue prompt tuning could not close
    (ISSUE-phonetic-name-guard.md, measured on One Pace S29E08, 40 targets, temperature 0):

        Syrahose  -> Shyarros    (the SAME token got the right answer elsewhere in the
                                   same episode -- the model is guessing phonetically
                                   per-call, not recalling a name it recognises)
        Deccan    -> Decman
        Hirohoshi -> Hihohi      (a name already close to correct, destroyed into a
                                   non-word)
        Garnus    -> Garnel

    None of these are reachable from the glossary by any tier the deterministic corrector
    runs, so they ship as fabricated proper nouns. There is deliberately no edit-distance
    or phonetic comparison here -- that is what the fuzzy and metaphone tiers upstream
    already tried, and it is exactly what let a wrong guess through as "close enough" in
    the failures above. The only signal left that is both cheap and precise: did a
    capitalised, non-English, glossary-shaped token DISAPPEAR, and did a token no tier
    recognises take its place. Comparison is on the bare core (glossary._TOKEN_RE, which
    strips leading/trailing punctuation) and case-insensitive -- that is the whole
    casing/punctuation escape hatch, on purpose: ``Garnus,`` -> ``Garnus`` or ``Garnus`` ->
    ``garnus`` reads as the same token, not a substitution.

    Judged on what is GAINED, whether or not anything was lost. A card that conjures a
    capitalised non-English token the glossary does not know is refused even if it replaced
    nothing: `jester` -> `Dester` is a fabrication exactly as much as `Deccan` -> `Decman`,
    and the lowercase original meant the substitution rule could not see it. The cost of
    this width is a repair that legitimately ADDS an unknown name is refused too; that is
    accepted deliberately, because an added name has no original to fall back on and a
    wrong one is indistinguishable from a right one once written.
    """

    # Scope widened 2026-08-26: a gained name is judged on its own, whether or not one was
    # LOST. The original rule required a SUBSTITUTION, which made a name conjured from
    # nothing invisible -- measured on the hotwords spike, where `jester` became `Dester`
    # and neither direction fired, because a lowercase word is not a proper noun to lose.
    #
    # GAINED is measured against every core in ORIG, not only its capitalised ones. A word
    # merely RE-CAPITALISED was not conjured, and punctuation restoration re-capitalises
    # constantly: `that's` -> `That's` after a new sentence boundary, `human` -> `Human`
    # rebuilding a garbled line. Comparing against the capitalised cores alone reported both
    # as fabricated names -- two real repairs refused, caught by the existing suite.
    # (`that's` is doubly exposed: _read_words drops every wordlist entry containing an
    # apostrophe, so is_english() can never be True for a contraction.)
    proper_cores = _proper_cores
    orig_all = {m.group(2).lower() for m in (glossary._TOKEN_RE.match(t) for t in (orig or "").split()) if m}
    known = {n.lower() for n in gloss["names"]} | {v.lower() for v in gloss["token_fixes"].values()}
    return any(c.lower() not in orig_all and c.lower() not in known for c in proper_cores(new))


def substitutes_a_vouched_name(orig, new, gloss):
    """True if ``new`` overrules a name the glossary already vouched for, or reaches for a
    known name that sounds nothing like what it replaced.

    Applied ONLY where there is no fansub reference. `repair.py`'s no-reference skip records
    why: "the bake-off showed glossary-only repair hallucinates names (Oimo->Zoro) even on
    qwen3:8b". Both failures in that shape need the model to be guessing from the glossary
    rather than reading evidence, so with a reference in hand these must NOT fire -- a
    reference-backed `Oimo` -> `Zoro` is exactly the correction repair exists to make, and
    refusing it everywhere would lose real anchored repairs across the library.

    Two rules, both measured 2026-08-26:

    * KNOWN -> KNOWN is refused outright. The glossary vouched for the original; a model
      with no reference has no standing to overrule it.
    * UNKNOWN -> KNOWN must be phonetically close. jaro_winkler admits the genuine fixes --
      dothamingo->doflamingo 0.893, zolo->zoro 0.867, syrahose->shirahoshi 0.755 -- and
      blocks oimo->zoro at 0.667. The threshold is 0.75 and it is KNOWINGLY imperfect:
      vivra->vivi scores 0.848 and gets through. No threshold separates that case, because
      the genuine syrahose->shirahoshi fix scores LOWER than it. That one is a glossary
      COVERAGE gap ("Vivre Card" is a real term absent from the names), not a distance
      problem, and metaphone cannot help either -- it is False for every pair here."""
    known = {n.lower() for n in gloss["names"]} | {v.lower() for v in gloss["token_fixes"].values()}
    orig_cores = _proper_cores(orig)
    new_cores = _proper_cores(new)
    orig_all = {c.lower() for c in orig_cores}
    new_all = {c.lower() for c in new_cores}
    lost = [c for c in orig_cores if c.lower() not in new_all]
    gained = [c for c in new_cores if c.lower() not in orig_all]
    if not (lost and gained):
        return False
    if any(c.lower() in known for c in lost):
        return True  # the glossary already vouched for what was replaced
    # Only the PHONETIC half needs jellyfish; the vouched-name rule above does not, and
    # must keep working when the optional dependency is absent. Degrading both would let
    # the exact bake-off failure through on a box without it.
    gained_known = [c for c in gained if c.lower() in known]
    if gained_known and glossary.jellyfish is not None:
        best = max(glossary.jellyfish.jaro_winkler_similarity(a.lower(), b.lower()) for a in lost for b in gained_known)
        if best < PHONETIC_MIN:
            return True
    return False


def accept_repair(orig, new, ref, dur, gloss):
    """Whether to write ``new`` over ``orig`` on a card lasting ``dur`` seconds.

    A dubtitle must carry what the DUB AUDIO says. The reference is a different translation
    of the same scene, so lifting its phrasing produces a subtitle that reads well and is
    wrong against the sound — the worst kind of error here, because it looks correct.

    The standard is REFERENT AND SENSE, not word-for-word fidelity (owner's bar,
    2026-08-26). A deviation carrying the same meaning is acceptable -- `Hawkeye Dracule
    Mihawk` shortened to `Mihawk` was ruled acceptable explicitly, being the same character
    and the same information. A deviation changing the meaning is not: `factory` -> `needle`
    destroys it, `VIVRA card` -> `Vivi card` swaps an item for a character.

    NOTHING BELOW ENFORCES THAT. The checks here are mechanical -- length ratio, card fit,
    reference borrowing, invented names -- and none can tell "same meaning" from "meaning
    destroyed"; both examples above pass this function today, verified 2026-08-26. The bar
    is enforced by human review of the repaired lines, which is why the spec makes that
    review a required step of accepting a measured episode rather than an optional one.

    Measured over every repair the library had accumulated before this guard: qwen3:8b
    imported reference words in 84.1% of its repairs (29.2% imported three or more),
    nanbeige in 52.5% (17.1%). Lines like "That's enough of that, idiots!" became "Hold
    it, you brats!" — the reference, verbatim. The old gate was a 0.4–2.5 length band,
    which a same-length rewrite sails straight through.

    C2: the length ratio cannot see readability. LEN_RATIO_MAX is 1.5, so 40 chars on a
    3.0s card (13 cps) may become 58 (19.3 cps) with nothing re-checking it. The card's
    timing is immutable here (C1) -- a repair that does not fit the card it is repairing
    is rejected, never accommodated by moving the card -- so ``dur`` is required, not
    optional: a caller that does not know the card cannot be allowed to skip the check.

    Kept deliberately permissive for the case the reference exists to serve: a single
    misheard proper noun corrected from it.

    ``gloss`` is required for the same reason ``dur`` is: the phonetic-name-guard
    (``invents_name``, below) needs to know what the show's names ARE to tell a real
    correction from a fabricated one, so a caller that cannot say what those names are
    must not be allowed to silently skip the check by omitting the argument."""
    if not new:
        return False
    if new.lower() == (orig or "").lower():
        return False  # nothing changed
    if invents_name(orig, new, gloss):
        return False  # phonetic-name-guard: fabricated proper noun, not a real correction
    if not ref and substitutes_a_vouched_name(orig, new, gloss):
        return False  # S-14: no reference, so no standing to overrule a vouched name
    ratio = len(new) / max(1, len(orig))
    if not (LEN_RATIO_MIN <= ratio <= LEN_RATIO_MAX):
        return False  # added or dropped a clause
    if not fits_card(new, dur, orig):
        return False  # unreadable/undisplayable on THIS card
    return len(borrowed_from_ref(orig, new, ref)) < MAX_REF_BORROW


def llm_ollama(prompt, model=None):
    """Ollama /api/generate backend (the original/default path — byte-for-byte the same
    request shape and response parsing as before A1's dispatch refactor)."""
    # think=False keeps qwen3/qwen3.5 from emitting <think> blocks (ignored by qwen2.5)
    body = {"model": model or MODEL, "prompt": prompt, "stream": False, "think": False, "options": {"temperature": 0}}
    try:
        out = _post_json(OLLAMA, body).get("response", "").strip()
        return out.splitlines()[0].strip().strip('"').strip() if out else ""
    except Exception as e:
        log("  llm fail:", e)
        return ""


def llm_llamacpp(prompt, model):
    """llama.cpp backend, via the OpenAI-compatible /v1/chat/completions endpoint.

    This previously posted a RAW prompt to /completion, which applies NO chat template.
    Verified against a live Nanbeige 4.2-3B server, that path returns nothing but newlines
    -- 200 tokens of "\n" -- because a templated instruct model never sees its template.
    It could only ever have worked for a base/completion model, so REPAIR_BACKEND=llamacpp
    was effectively broken for the models anyone would actually use.

    ``chat_template_kwargs.enable_thinking=false`` is required by this fork: with the
    template applied but thinking still on, the model spends its whole budget on
    reasoning_content and returns an empty message (measured empty after 114s at
    max_tokens=512; correct output in 4.3s with thinking off). An empty reply is treated as
    "no repair" -- never as text to embed, which would put the model's monologue in a
    subtitle.

    No "model" selector is sent (the server has exactly one model loaded); ``model`` is
    accepted for signature parity with llm_ollama and the two-pass dispatch."""
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 80,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        msg = _post_json(LLAMACPP_URL, body)["choices"][0]["message"]
        out = (msg.get("content") or "").strip()
        return out.splitlines()[0].strip().strip('"').strip() if out else ""
    except Exception as e:
        log("  llm fail:", e)
        return ""


def llm(prompt, model=None):
    """Dispatch to the backend configured by REPAIR_BACKEND (ollama|llamacpp, default
    ollama — matches pre-A1 behavior exactly). model=None uses the backend's default
    (REPAIR_MODEL); pass it explicitly for the two-pass secondary-model re-check (A3)."""
    if REPAIR_BACKEND == "llamacpp":
        return llm_llamacpp(prompt, model or MODEL)
    return llm_ollama(prompt, model)


def _needs_secondary_check(orig, new, gloss):
    """A3 two-pass trigger: the first-pass repair looks divergent enough to re-verify with
    the (usually stronger/slower) secondary model — either the length changed a lot, or a
    glossary name showed up in the output that wasn't in the original line. NOTE (spec
    correction): the name-appeared condition fires on ~every successful name repair by
    design — inserting the correct name IS the point of repair — so this is "re-verify all
    name-changing repairs," not a rare-case optimization."""
    ratio = len(new) / max(1, len(orig))
    if ratio < 0.6 or ratio > 1.5:
        return True
    for name in gloss["names"]:
        pat = r"\b" + re.escape(name) + r"\b"
        if re.search(pat, new, re.I) and not re.search(pat, orig, re.I):
            return True
    return False


def _p95(values):
    """Nearest-rank 95th percentile; no numpy dependency for one summary stat (A10)."""
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]


def apply_human_text(c, store, stem):
    """A card the repair loop is about to SKIP: ship the human's wording if one is stored.

    `decisions.lookup` sits further down the loop and needs both sides of the pair, so a card
    that skips -- no fansub anchor, or `llm()` returned "" on a transport failure -- never
    reaches it. `process` then rebuilds the srt from conf.json, replacing a reviewer's typed
    correction with raw ASR. `decisions.corrected_text` answers on the orig alone, which is
    safe for `correct` and only for it.

    Returns the summary bucket this card belongs in, or None when nothing was stored and the
    caller keeps its own. "owed" is the outcome that must never be silent again: a human had
    ruled on the line, and this path could not act on it.

    fits_card is NOT bypassed. C1 keeps card timing immutable for humans too, exactly as it
    does for the verdict path below."""
    if not DECISIONS_APPLY:
        return None
    text = decisions.corrected_text(store, c["text"])
    if text:
        if not fits_card(text, c["end"] - c["start"], c["text"]):
            unresolved.record(stem, "repair", "verdict_unfittable", original_text=c["text"], proposed_text=text)
            return "unfittable"
        c["text"] = text
        return "rescued"
    if decisions.for_orig(store, c["text"]):
        unresolved.record(stem, "repair", "verdict_owed", original_text=c["text"])
        return "owed"
    return None


def prior_repairs(stem):
    """How many repairs the LAST run of this episode shipped, from the summary it left.

    The summary survives the mux (mux.py removes the srt/ass sidecars, not this), so it is
    the durable record of whether an episode already carries repaired text."""
    try:
        with open(stem + ".dubtitles.repair-summary.json") as f:
            return int(json.load(f).get("repaired", 0))
    except Exception:
        return 0


def process(conf_path):
    stem = conf_path[: -len(CONF_SUFFIX)]
    srt = stem + SRT_SUFFIX
    video = find_video(stem)
    # No conf.json is a normal state, not an error: tools/recover_dub_srt.py rebuilds the
    # sidecar straight out of the already-muxed track for episodes whose conf was long
    # since cleaned up, and merge_pass.sh calls repair.py unconditionally. That dialogue
    # was already repaired when it was first built, so there is nothing to redo.
    if not video or not os.path.exists(srt) or not os.path.exists(conf_path):
        return "skip"
    conf = json.load(open(conf_path))
    gloss = glossary_for(video)
    # A3. glossary_for falls back to a no-op glossary when no <Show>.json resolves, which is
    # the right behaviour -- a missing glossary must never fail an episode. Doing it SILENTLY
    # is what is wrong: a misconfigured GLOSSARY_DIR repairs a whole library with no names at
    # all and nothing anywhere says why. load_dict leaves `show` empty when nothing resolved.
    if not gloss.get("show"):
        log(
            f"  WARNING no glossary resolved for {os.path.basename(stem)} — names will not be corrected."
            " Check GLOSSARY_DIR and that a <Show>.json matches the show directory."
        )
    # S-13: the episode's arc, for weighting the reference spellings. None for most
    # of the library (no season.nfo), which leaves the term order exactly as before.
    arc = glossary.arc_for(video)
    # [S-4] The human rung, read back. Resolved ONCE per episode rather than per card: it is
    # a file read, and the per-card path already pays a network round-trip per LLM call.
    # An absent or unreadable store is {} -- every install that has never reviewed anything.
    store, _ = decisions.decisions_for(video)
    # Pairs this episode's queue ALREADY holds. merge_pass.sh re-runs repair on every sweep
    # while an srt exists, and an episode held by the [S-6] gate never loses its srt (mux
    # stops before removing sidecars, and dub_signs_merge writes no .ass for a dialogue-only
    # episode -- dub_signs_merge.py:126-127). Without this the queue gains another copy of
    # every unreviewed line every MERGE_INTERVAL, and the gate's stall alert -- which reads
    # this file's mtime -- can never fire, because each append refreshes it.
    #
    # ONE read for the whole episode, not a scan per card: unresolved.record is an O(1)
    # append precisely because the array version was O(n^2) I/O over ~86 calls an episode.
    # Matched against EVERY entry, resolved or not -- keying on pending-only would re-append
    # the moment a human resolved one through the --review CLI, which is the same deadlock
    # inverted.
    _queued = unresolved.items(stem)
    queued_pairs = {
        (decisions.key(e.get("original_text", "")), decisions.key(e.get("proposed_text", "")))
        for e in _queued
        if e.get("stage") == "repair_applied"
    }
    # [F-2] Pending entries by ORIGINAL line, so a changed proposal can supersede the one it
    # replaces instead of queueing beside it. The pair is right as the DECISION key -- keying
    # a verdict on `orig` alone would let one rejection suppress the proposal that fixes the
    # line -- but the reviewer's PENDING set is a different question: two live proposals for
    # one card are two questions about a card that will only ever ship one answer, and a
    # verdict on either leaves a gated episode held on the other.
    pending_by_orig: dict = {}
    for i, e in enumerate(_queued):
        if e.get("stage") == "repair_applied" and not e.get("resolved"):
            pending_by_orig.setdefault(decisions.key(e.get("original_text", "")), []).append(
                (i, decisions.key(e.get("proposed_text", "")))
            )
    targets = [(i, c) for i, c in enumerate(conf) if is_target(c, gloss)]
    if not targets:
        return "clean"  # nothing to repair (e.g. S15E01)
    ivals = dialogue_intervals(video)
    audit, fixed, skipped_no_ref, rejected = [], 0, 0, 0
    rec = qc.Recorder()  # S-6 liveness counters, merged into the summary below
    llm_empty = 0
    rejected_secondary = 0  # C5: second-pass output refused by the gate
    # The model returned the line verbatim -- the single most common outcome of this stage
    # (568 of 836 targets on the SAO pass). accept_repair refuses it and the `not admitted`
    # inner guard is false by construction, so before this counter it incremented nothing
    # and recorded nothing: the [S-4] invariant below was stated as fact and was false.
    unchanged = 0
    # [S-4]. Both are terminal `continue` paths, so without their own buckets `targets`
    # would quietly exceed the sum of the others and the residual would be unexplained.
    verdict_reject = 0  # a stored `reject`: settled by a human, nothing shipped
    verdict_rescued = 0  # a SKIPPED card whose stored human text was shipped anyway (A4)
    verdict_owed = 0  # skipped, a human had ruled, and this path could not act on it (A4)
    verdict_unfittable = 0  # an applying verdict refused by fits_card (C1)
    repaired_lines = []  # A10: per-line detail for the summary
    for i, c in targets:
        # C6: select the reference on the SOURCE window -- where the audio actually was --
        # not the display window, which the timing layer may have stolen forward onto the
        # NEIGHBOUR's cue. The .get fallback keeps every pre-C6 sidecar working unchanged.
        #
        # S-6: unless that window is one whisper got wrong. A 7-second span on a one-word
        # card selects whatever fansub line happens to fall inside it -- possibly a
        # different line entirely -- and the guard then rejects the repair and counts a
        # rejection, recording nothing about the REFERENCE having been wrong. The guard
        # fires BEFORE the .get() below, or it reads the very default it exists to doubt.
        # No reference, not the display window: on 99% of gated cards display == source,
        # so falling back reproduces the window just declared implausible.
        if hallucination.bad_source_window(c, rec=rec):
            ref = ""
        else:
            ref = overlap_ref(ivals, c.get("source_start", c["start"]), c.get("source_end", c["end"]))
        if skips_unanchored(ref, gloss):
            bucket = apply_human_text(c, store, stem)
            if bucket == "rescued":
                verdict_rescued += 1
                continue
            if bucket == "unfittable":
                verdict_unfittable += 1
                continue
            if bucket == "owed":
                verdict_owed += 1
                continue
            skipped_no_ref += 1
            # The counter alone made this indistinguishable from "repair ran and found
            # nothing wrong". Record the card so a human can see WHICH lines went unrepaired
            # and judge whether the release simply has no fansub or the anchor logic missed.
            unresolved.record(
                stem,
                "repair",
                "no_reference",
                original_text=c["text"],
                source_start=c.get("source_start", c["start"]),
                source_end=c.get("source_end", c["end"]),
                avg_logprob=c.get("avg_logprob"),
            )
            continue  # see skips_unanchored() for why, and for what opens this path
        prev_text = conf[i - 1]["text"] if i > 0 else ""
        next_text = conf[i + 1]["text"] if i + 1 < len(conf) else ""
        prompt = build_prompt(c["text"], ref, gloss, prev_text, next_text, arc)
        t0 = time.monotonic()  # V2 A2: per-call latency
        new = llm(prompt)
        latency_ms = round((time.monotonic() - t0) * 1000)
        if new:
            new = glossary.correct(new, gloss)[0]  # enforce canonical spelling on output
        # C2: the card's DISPLAY duration -- how long the viewer actually has to read it.
        # (source_start/source_end anchor the EVIDENCE window above; they are not what is
        # on screen.) Timing stays immutable: a repair that does not fit is rejected.
        dur = c["end"] - c["start"]
        if not new:
            # llm() returns "" on any transport failure or timeout. The guard below is
            # `if new and ...`, so an empty result incremented NOTHING and recorded nothing:
            # a dead endpoint was indistinguishable from a card that needed no repair. With
            # the backend down this is every targeted card in the episode.
            bucket = apply_human_text(c, store, stem)
            if bucket == "rescued":
                verdict_rescued += 1
                continue
            if bucket == "unfittable":
                verdict_unfittable += 1
                continue
            if bucket == "owed":
                verdict_owed += 1
                continue
            llm_empty += 1
            unresolved.record(
                stem, "repair", "llm_empty", original_text=c["text"], reference=ref[:120], avg_logprob=c.get("avg_logprob")
            )
            continue
        # [S-4] A human already ruled on this exact (original, proposal) pair. Consulted
        # HERE -- after glossary.correct() has canonicalised `new`, before accept_repair
        # judges it -- because the verdict was recorded against the corrected proposal.
        # Placed above the correction it would key on raw model output and miss silently.
        # No `and store` short-circuit: the consult runs whether or not anything is stored,
        # so the path cannot quietly become dead code on the installs where it matters least
        # to test and most to keep working. lookup() on {} returns None off an empty list.
        verdict = decisions.lookup(store, c["text"], new) if DECISIONS_APPLY else None
        ruling = verdict.get("verdict") if verdict else None
        human_text = verdict.get("text", "") if verdict else ""
        if ruling == "reject":
            # Settled: not applied, and NOT re-queued. Re-queueing it would show the
            # reviewer a line they have already ruled on, every run, forever.
            verdict_reject += 1
            continue
        if ruling == "correct":
            new = human_text or new
        # C1, and the exact boundary of what a human verdict may overrule. Every verdict in
        # APPLYING bypasses accept_repair -- its length band and borrow limit are
        # heuristics standing in for a reader who is now present -- but NONE bypasses
        # fits_card, which is not judgement: it is whether the line can be on screen for
        # the seconds the card lasts. There is no verdict that admits an unrenderable line.
        # `c["text"]` as `orig` keeps the existing already-over-cps allowance, so a human
        # editing a card that was always too fast is not what this refuses.
        if ruling in APPLYING and not fits_card(new, dur, c["text"]):
            # Refused, and SAID SO. A verdict that vanishes silently is the failure this
            # whole loop exists to prevent -- the reviewer would believe the line settled.
            unresolved.record(
                stem,
                "repair",
                "decision_unfittable",
                original_text=c["text"],
                proposed_text=new,
                avg_logprob=c.get("avg_logprob"),
            )
            verdict_unfittable += 1
            continue
        # Every applying verdict is admitted here, so `not admitted` below can only be
        # reached with no ruling at all -- which is why that branch needs no ruling guard of
        # its own to avoid re-queueing a settled line.
        admitted = ruling in APPLYING or accept_repair(c["text"], new, ref, dur, gloss)
        if not admitted:
            if new and new.lower() != c["text"].lower():
                rejected += 1  # surfaced in the summary so the guard stays visible
                # ...but the PROPOSAL was discarded, and it is the whole evidence a human
                # needs to judge whether the guard was right or overzealous.
                reason = "rejected_name_invented" if invents_name(c["text"], new, gloss) else "rejected_guard"
                unresolved.record(
                    stem,
                    "repair",
                    reason,
                    original_text=c["text"],
                    proposed_text=new,
                    reference=ref[:120],
                    avg_logprob=c.get("avg_logprob"),
                )
            else:
                # `new` is non-empty (the `if not new` above returned), so this is exactly
                # the verbatim echo. NOT queued: there is no proposal for a human to judge,
                # and queueing every unrepaired line would flood the review page.
                unchanged += 1
        else:
            # A3: re-verify divergent-looking repairs (esp. name changes) with the secondary
            # model. No-op by default (REPAIR_MODEL_SECONDARY == REPAIR_MODEL).
            #
            # NOT when a human has ruled. C5 says "a stronger model is still a model"; a
            # human is not, and outranks both passes. Without `not ruling` this block
            # reassigns `new` AFTER the consult, so an accept/correct/force would be
            # admitted and then quietly replaced by the second model's wording -- and the
            # suppression below would write no queue entry, because the line counts as
            # settled. The substitution would reach the viewer with nothing recording it.
            if not ruling and MODEL_SECONDARY != MODEL and _needs_secondary_check(c["text"], new, gloss):
                t1 = time.monotonic()
                new2 = llm(prompt, model=MODEL_SECONDARY)
                latency_ms += round((time.monotonic() - t1) * 1000)
                if new2:
                    new2 = glossary.correct(new2, gloss)[0]
                    # C5: a stronger model is still a model. Its output went straight over
                    # the first pass with no validation at all -- same gate, same card. When
                    # it fails, the already-accepted first-pass repair stands rather than the
                    # card being left garbled.
                    if new2 and accept_repair(c["text"], new2, ref, dur, gloss):
                        new = new2
                    elif new2 and new2.lower() != new.lower():
                        rejected_secondary += 1
            audit.append((c["text"], new, ref[:80], latency_ms))
            repaired_lines.append({"orig": c["text"], "repaired": new, "ref": ref[:80], "latency_ms": latency_ms})
            # The human rung of the ladder, for the branch that had none. accept_repair
            # ADMITTED this repair and its own docstring says nothing below it checked the
            # meaning -- `factory -> needle` passes every gate. So the admitted line is
            # queued for the one reviewer who can judge it.
            #
            # MUST stay above `c["text"] = new`. Below the assignment, `original_text` would
            # be the REPAIRED text and every entry would compare a line against itself --
            # a queue that always looks unanimous.
            #
            # Also below the secondary-model block above, so `new` is the text actually
            # applied rather than the first pass's proposal.
            # ...unless a human already ruled on it. [S-4]: an accept/correct/force verdict
            # means this line is SETTLED, and re-queueing a settled line would hand the
            # reviewer their own decision back on every subsequent run. That is the re-run
            # amplification the spec records under Edge cases, and the pair being the
            # store's key is what lets it be suppressed here rather than deduplicated in
            # unresolved.record(), whose O(1) append is deliberate.
            pair = (decisions.key(c["text"]), decisions.key(new))
            if not ruling and pair not in queued_pairs:
                # Retire any live entry for this same line whose proposal has changed. Marked
                # RESOLVED, never deleted: the queue is the audit trail, and what the model
                # proposed before is the evidence for whether the gate is drifting.
                # No "is it different?" check: an IDENTICAL pair never reaches here, because
                # `pair not in queued_pairs` above already skipped it, and queued_pairs is
                # built from every entry including the pending ones. Any live entry for this
                # original therefore carries a different proposal by construction.
                for idx_old, _ in pending_by_orig.get(pair[0], []):
                    unresolved.resolve(stem, idx_old, accept=False, note=f"superseded by a newer proposal: {new}")
                pending_by_orig[pair[0]] = [(len(_queued), pair[1])]
                _queued.append({})  # keep index accounting honest for a second supersession
                queued_pairs.add(pair)
                unresolved.record(
                    stem,
                    "repair_applied",
                    "accepted",
                    original_text=c["text"],
                    proposed_text=new,
                    reference=ref[:120] or None,
                    avg_logprob=c.get("avg_logprob"),
                )
            c["text"] = new
            fixed += 1
    # A2 guard (c). This function REBUILDS the srt from conf.json unconditionally, so a run
    # that repaired nothing because every target was refused for want of an anchor writes RAW
    # ASR over whatever was already shipped. Reproduced on One Pace S31E24 (targets=144
    # repaired=0 skipped_no_ref=144), which came back as `our mods will never give up There's
    # a` where the shipped track had `Our mods will never give up. There's a fire...`.
    #
    # Refusing is deliberately narrow: it fires only when EVERY target was skipped for want of
    # a reference AND the last run shipped repairs. An episode that genuinely has nothing to
    # fix still rewrites normally, and the first run of a new episode has no prior summary.
    if targets and fixed == 0 and skipped_no_ref == len(targets) and prior_repairs(stem) > 0:
        log(
            f"  REFUSED {os.path.basename(stem)}: every one of {len(targets)} targets was skipped for want of a"
            f" fansub anchor, but the last run shipped {prior_repairs(stem)} repairs. Rebuilding the srt would"
            " overwrite them with raw ASR. Declare `unanchored_repair` in this show's glossary if its copies"
            " carry no English subtitles for the Japanese audio."
        )
        return "refused"
    # rewrite srt from (possibly repaired) conf rows. conf.json stores text FLATTENED
    # (generate.py replaces '\n' with ' '), so re-wrap here or every episode that
    # passes through repair ships as unwrapped single lines -- which is exactly what
    # the library did until this fix.
    srt_out = out_for(srt)
    rep_out = out_for(stem + ".dubtitles.repair.csv")
    with open(srt_out, "w") as f:
        for i, c in enumerate(conf, 1):
            f.write(f"{i}\n{ts_srt(c['start'])} --> {ts_srt(c['end'])}\n{reflow.wrap_balance(c['text'])}\n\n")
    with open(rep_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["orig", "repaired", "ref", "latency_ms"])
        w.writerows(audit)
    # A10: per-show repair summary, written alongside the srt/csv
    lat_values = [r["latency_ms"] for r in repaired_lines]
    summary = {
        "targets": len(targets),
        "repaired": fixed,
        "skipped_no_ref": skipped_no_ref,
        "llm_empty": llm_empty,
        "rejected_guard": rejected,  # model proposed an edit, accept_repair() refused it
        "rejected_secondary": rejected_secondary,  # C5: second pass refused, first pass kept
        "unchanged": unchanged,  # model echoed the line back; nothing proposed, nothing shipped
        # [S-4]. targets == repaired + skipped_no_ref + llm_empty + rejected_guard +
        # verdict_reject + verdict_unfittable + verdict_rescued + verdict_owed + unchanged,
        # for every episode. `unchanged`
        # was missing until 2026-08-29 and it is the LARGEST bucket, so the identity this
        # comment asserts was false everywhere it was read. Pinned by
        # test_every_target_lands_in_exactly_one_summary_bucket -- add an outcome to the
        # loop without a bucket here and that test fails.
        "verdict_reject": verdict_reject,  # human said no; ASR text stands
        "verdict_rescued": verdict_rescued,  # skipped, but the human's stored text shipped (A4)
        "verdict_owed": verdict_owed,  # skipped while a human verdict existed and could not be applied (A4)
        "verdict_unfittable": verdict_unfittable,  # human's text cannot be rendered (C1)
        "mean_latency_ms": round(sum(lat_values) / len(lat_values)) if lat_values else 0,
        "p95_latency_ms": round(_p95(lat_values)) if lat_values else 0,
        "model": MODEL,
        "model_secondary": MODEL_SECONDARY,
        # evaluated>0 with activated==0 across a season is the dead-rule signal. Carried
        # here because repair writes its own summary rather than a qc sidecar.
        "rules": dict(rec.counters),
        "repaired_lines": repaired_lines,
    }
    summary_out = out_for(stem + ".dubtitles.repair-summary.json")
    with open(summary_out, "w") as f:
        json.dump(summary, f, indent=2)
    for p in (srt_out, rep_out, summary_out):
        try:
            os.chown(p, MEDIA_UID, MEDIA_GID)
        except OSError as e:
            log(f"chown failed for {p}: {e}")
    # A3. The beta-user shape: dub-only copies, `unanchored_repair` never declared, and no
    # prior repairs -- so guard (c) above cannot fire, since it only protects work that
    # already exists. Every card is skipped and, until this line, the only trace was a
    # skipped_no_ref count inside a JSON sidecar nobody opens. The message names the remedy:
    # a user who does not know the setting exists cannot act on "144 targets skipped".
    if targets and fixed == 0 and skipped_no_ref == len(targets):
        log(
            f"  WARNING every one of {len(targets)} targets on {os.path.basename(stem)} was skipped for want of a"
            " reference — this release has no English subtitles for the Japanese audio, so there is nothing to"
            ' anchor a repair on. Set "unanchored_repair": true in this show\'s glossary to repair from the'
            " glossary alone (wider guesses, fewer missed names), or leave it off to ship the ASR text as-is."
        )
    log(f"  targets={len(targets)} repaired={fixed}")
    return "repaired"


def main():
    args = sys.argv[1:]
    confs = list(args) if args else []  # explicit .conf.json paths, else walk roots
    if not confs:
        for root in ROOTS:
            if not os.path.isdir(root):
                continue
            for dp, _, files in os.walk(root):
                for f in files:
                    if f.endswith(CONF_SUFFIX):
                        confs.append(os.path.join(dp, f))
    counts = {}
    for cp in sorted(confs):
        res = process(cp)
        counts[res] = counts.get(res, 0) + 1
        log(f"{res}: {os.path.basename(cp)}")
    log("SUMMARY", counts)


if __name__ == "__main__":
    main()
