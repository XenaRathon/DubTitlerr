#!/usr/bin/env python3
"""A/B whisper large-v3-turbo against NeMo parakeet/canary and Qwen3-ASR on the SAME
episodes.

Why this exists
---------------
Every candidate that beats large-v3-turbo on the Open ASR Leaderboard (parakeet v3,
canary-1b-v2, canary-qwen, Qwen3-ASR) lives in NVIDIA NeMo or Alibaba's qwen_asr
package, not faster-whisper/CTranslate2 -- so ``tools/model_bakeoff.py`` cannot judge
them: it speaks CT2 only. This tool loads all three stacks side by side and scores them
by the pipeline's own standard (same judge rules as model_bakeoff), on the pipeline's
own audio path (``generate.eng_audio_index`` and ``generate.extract_wav``).

Design constraints, inherited from model_bakeoff.py
---------------------------------------------------
* Models are loaded STRICTLY SEQUENTIALLY with a full offload between them -- the second
  entrant gets the whole card. VRAM is recorded before/after each load and per episode,
  which is what makes "it was fully offloaded" an observation rather than an assumption.
* A failed load IS the result for that entrant, not an error to retry: a smaller batch or
  compute type is a different model than the one being judged. Per-episode failures
  (no dub track, extraction error) are recorded on that episode and the entrant keeps
  going, so one bad mkv does not throw away an expensive model load.
* No reference transcript exists for dub audio, so this is a direct A/B, not a score
  against a labelled set. The pipeline's own judge -- blocklist hits, nsp/logprob where
  the stack provides them -- is applied to BOTH models, so the two are judged by the same
  bar the production gate uses.
* The report-shaping half (WER math, verdicts, defensive parsers) imports NO
  faster_whisper, NO nemo, and NO qwen_asr, so it stays importable and testable on a
  machine with no CUDA stack. GPU libs are imported lazily, inside the functions that
  need them.

The precision mismatch this cannot paper over
-----------------------------------------------
Production whisper runs int8 (``generate.py``'s default ``COMPUTE_TYPE`` -- chosen
specifically because it is Pascal-friendly and fits 6GB). Neither NeMo nor qwen_asr has
an equivalent: no ``compute_type`` flag, and no supported quantized inference path for
either -- getting int8 out of a NeMo model needs a separate TensorRT Model Optimizer PTQ
export, not a flag on ``transcribe()`` (the standard ``torch.quantization`` route is a
known-broken compatibility dead end against these architectures); qwen_asr has no such
export path documented at all. So every NeMo/Qwen entrant here runs fp16, the best
available without a multi-day export pipeline, while whisper entrants can run at
whatever ``--compute-type`` is asked for. A report mixing "large-v3-turbo (int8)"
against "nvidia/parakeet... (fp16)" or "Qwen/Qwen3-ASR... (fp16)" is comparing two
different precision floors, not just two models -- read VRAM numbers with that in mind,
not as apples-to-apples. The report's "model" label always carries the precision (see
run_entrant) so this is visible in the data, not just in this docstring.

Usage:
  python3 tools/asr_bakeoff.py /path/to/ep1.mkv /path/to/ep2.mkv \
      --models large-v3-turbo,nvidia/parakeet-tdt-0.6b-v3,Qwen/Qwen3-ASR-1.7B \
      --out asr_bakeoff.json

  python3 tools/asr_bakeoff.py --report-only --out asr_bakeoff.json   # re-print a saved run
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hallucination  # noqa: E402

# generate is imported LAZILY inside the functions that transcribe: it pulls in
# faster_whisper at module scope, and the report-shaping half of this tool must stay
# importable (and testable) on a machine with no CUDA stack. Same fencepost as
# tools/model_bakeoff.py and tools/timing_compare.py.


# The same judge thresholds model_bakeoff.py carries, kept here rather than re-adding
# them to hallucination.py (ADR 0002 removed the nsp/logprob rules from the gate; this
# tool measures whether a candidate decoder would have fired them -- exactly the
# measurement that justified the deletion, and the one to repeat per future decoder).
HIST_NSP_DROP = 0.95
HIST_LP_DROP = -2.0
HIST_NSP_FLAG = 0.5

# Turbo's known nsp collapse: verified across two CT2 conversions in the VAD design
# (§5.3, and model_bakeoff's docstring). Used as the nsp_alive_frac floor here too.
NSP_ALIVE_FLOOR = 1e-6


# ----------------------------------------------------------------------------- utils


def vram_used_mib() -> int | None:
    """Currently used VRAM, or None where nvidia-smi is unavailable (dev machines)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return int(out.stdout.strip().split("\n")[0])
    except Exception:
        return None


# ------------------------------------------------------------------- shared shaping


def normalise_words(text: str) -> list[str]:
    """Lowercase, strip punctuation, keep numeral-containing tokens ("2.5").

    The same normalisation every published WER number applies (leaderboards strip
    punctuation and case), so this tool's WERs are comparable to the leaderboard's."""
    return re.findall(r"[a-z0-9']+", text.lower(), flags=re.ASCII)


def edit_distance(a: list[str], b: list[str]) -> int:
    """Word-level edit distance -- the edit count WER is defined over.

    difflib's block-matching, not a Levenshtein DP: a full 24-min episode's word list
    is thousands of tokens, and cross_wer joins a whole episode SET (a movie included
    pushed one entrant past 19,000 words) -- an O(n*m) pure-Python DP over that is
    ~350M cells, a multi-minute hang per pair, times 6 pairs for 4 entrants. difflib's
    matcher is C-accelerated and near-linear in practice; verified against this file's
    hand-checked cases below, it matches exact Levenshtein on every one of them, but is
    not guaranteed identical on arbitrary realignments -- an approximation, not the
    definition, which is the right trade for an agreement SIGNAL over exact distance."""
    import difflib

    dist = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            dist += max(i2 - i1, j2 - j1)
    return dist


def wer(ref: str, hyp: str) -> float | None:
    """Word error rate between a reference and a hypothesis, or None for empty refs."""
    r, h = normalise_words(ref), normalise_words(hyp)
    if not r:
        return None
    return edit_distance(r, h) / len(r)


def load_srt_reference(srt_path: str) -> str:
    """A cue-track's spoken text, joined into one string -- for real WER, not agreement.

    Most dub audio has no ground truth (see cross_wer), but an SRT sometimes IS one: a
    track mislabelled "SDH" that is actually the professional dub script rather than
    sound-only captions. SDH mixes real dialogue with bracketed sound cues
    ("[dramatic music plays]") and speaker tags ("[narrator] text") -- bracket content
    is stripped from every cue (dropping cue-level, not the whole file: a cue that is
    pure sound-effect vanishes, one with a speaker tag keeps its dialogue)."""
    import pysubs2

    lines = []
    for ev in pysubs2.load(srt_path):
        t = re.sub(r"\[[^\]]*\]", "", ev.plaintext).strip()
        if t:
            lines.append(t)
    return " ".join(lines)


def cross_wer(a_texts: list[str], b_texts: list[str]) -> float | None:
    """WER of one model's transcript against the other's, joined over the episode set.

    A "reference" does not exist for dub audio; the honest substitute is agreement --
    the WER of model B read against model A on the same audio. Low means the two stacks
    heard the same thing. Pairs with the per-entrant blocklist/nsp judge below: agreement
    tells you they match each other, the judge tells you whether what they agree on is
    sane. Only meaningful when BOTH entrants transcribed the same episode set without
    per-episode errors; the caller passes ``agreement_eligible`` accordingly."""
    if not a_texts or not b_texts:
        return None
    return wer(" ".join(a_texts), " ".join(b_texts))


def pairwise_agreement(entries: list[dict]) -> dict:
    """Agreement WER for every pair of entrants that loaded and share an episode set.

    With N entrants (this tool now routes 4: turbo, large-v3, parakeet, canary) a single
    "agreement_wer" scalar can only describe one pair; a doc comparing them all needs
    every pair, keyed "model-a|model-b" so each cell in a results table has a source."""
    oks = [e for e in entries if e.get("verdict") == "ok"]
    out: dict[str, float | None] = {}
    for i, a in enumerate(oks):
        for b in oks[i + 1 :]:
            a_eps = {ep["episode"] for ep in a["episodes"] if "error" not in ep}
            b_eps = {ep["episode"] for ep in b["episodes"] if "error" not in ep}
            key = f"{a['model']}|{b['model']}"
            if a_eps and a_eps == b_eps:
                out[key] = cross_wer(a["texts"], b["texts"])
            else:
                out[key] = None
    return out


def summarise(nsps: list[float], lps: list[float], texts: list[str]) -> dict:
    """Collapse one model's per-segment output into the numbers the decision needs.

    Same contract as model_bakeoff.summarise -- and nsp_alive_frac is the whole point
    there: the fraction of segments whose no_speech_prob clears the floor a collapsed
    decoder can never clear. Parakeet/canary expose no nsp/logprob at all (CTC/transducer
    decoders), so for NeMo entrants the acoustic-confidence half of this judge is empty
    and only blocklist hits remain."""
    blocklist_hits = sum(1 for t in texts if hallucination.BLOCKLIST.search(t))
    both = sum(1 for nsp, lp in zip(nsps, lps) if nsp > HIST_NSP_DROP and lp < HIST_LP_DROP)
    silence = sum(1 for n in nsps if n > HIST_NSP_FLAG)

    def median(v: list[float]) -> float | None:
        return round(statistics.median(v), 6) if v else None

    def p05(v: list[float]) -> float | None:
        if not v:
            return None
        return round(statistics.quantiles(v, n=100)[4], 6) if len(v) > 1 else round(v[0], 6)

    return {
        "music_rule_would_fire": both,
        "maybe_silence_would_fire": silence,
        "segments": len(texts),
        "nsp_min": round(min(nsps), 12) if nsps else None,
        "nsp_median": median(nsps),
        "nsp_max": round(max(nsps), 6) if nsps else None,
        "nsp_alive_frac": round(sum(1 for n in nsps if n > NSP_ALIVE_FLOOR) / len(nsps), 4) if nsps else None,
        "nsp_over_0_5": sum(1 for n in nsps if n > 0.5),
        "nsp_over_0_95": sum(1 for n in nsps if n > 0.95),
        "logprob_median": median(lps),
        "logprob_p05": p05(lps),
        "blocklist_hits": blocklist_hits,
    }


# --------------------------------------------------------------- results containers


class WhisperRun:
    """Result record for one faster-whisper entrant.

    ``segments`` is the raw per-segment list (the judge's input shape, with the
    no_speech_prob / avg_logprob parakeet-and-friends do not produce); ``words`` is the
    flat word list, the shape production's reflow consumes."""

    family = "faster-whisper"

    def __init__(self, name: str):
        self.name = name
        self.segments: list[dict] = []  # {start, end, text, no_speech_prob, avg_logprob}
        self.words: list[dict] = []  # {text, start, end, prob}
        self.episodes: list[dict] = []  # {episode, wall_s} or {episode, error}
        self.peak_vram_mib: int | None = None
        self.load_s: float | None = None
        self.error: str | None = None  # load failure only; episode errors live in episodes

    @property
    def ok(self) -> bool:
        return self.error is None

    def texts(self) -> list[str]:
        return [s["text"] for s in self.segments]

    def clean_episodes(self) -> list[dict]:
        return [e for e in self.episodes if "error" not in e]


class NemoRun:
    """Result record for one NeMo entrant.

    NeMo returns Hypothesis objects whose shape moves between versions (single, list, or
    a (hypotheses, alignment) tuple; word- or token-level ``timestamp`` dicts), so
    parse_transcript() accepts whatever arrives and records what it got. Parakeet TDT
    emits word timestamps natively; canary models may need their decoding strategy
    restored on load before timestamps appear."""

    family = "nemo"

    def __init__(self, name: str):
        self.name = name
        self.words: list[dict] = []  # {text, start, end} -- empty when no timestamps
        self.segments: list[dict] = []  # text-only; NeMo gives no per-segment confidences
        self.episodes: list[dict] = []
        self.has_timestamps: bool = False
        self.peak_vram_mib: int | None = None
        self.load_s: float | None = None
        self.error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def texts(self) -> list[str]:
        return [s["text"] for s in self.segments]

    def clean_episodes(self) -> list[dict]:
        return [e for e in self.episodes if "error" not in e]


def parse_transcript(raw: object) -> tuple[list[str], list[dict]]:
    """One NeMo transcribe() return -> ([segment texts], [word dicts with start/end]).

    Defensive on purpose: NeMo's return type moves between versions, so accept any of
    the observed shapes and degrade gracefully. Timestamps land in the word list only
    when the model actually produced them; a shape this tool does not know yields an
    empty result that the run records as an explicit finding, not a guess."""

    def flatten(x: object) -> list[object]:
        # Unwrap (hypotheses, alignment) tuples and nested per-file lists down to a
        # flat sequence of hypothesis-like objects.
        if isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], (list, tuple)):
            return flatten(x[0])
        if isinstance(x, (list, tuple)):
            out: list[object] = []
            for item in x:
                out.extend(flatten(item))
            return out
        return [x]

    def take_text(hyp: object) -> str:
        t = getattr(hyp, "text", None)
        return t.strip() if isinstance(t, str) else ""

    def take_words(hyp: object) -> list:
        ts = getattr(hyp, "timestamp", None)
        if not isinstance(ts, dict):
            return []
        for key in ("word", "token", "segment"):
            segs = ts.get(key)
            if isinstance(segs, list) and segs:
                return segs
        return []

    texts: list[str] = []
    words: list[dict] = []
    for h in flatten(raw):
        txt = take_text(h)
        if txt:
            texts.append(txt)
        for w in take_words(h):
            get = w.get if isinstance(w, dict) else (lambda k, _w=w: getattr(_w, k, None))
            # token-level timestamp entries carry the text under "token"; word-level
            # under "word". A missing text key yields None and the entry is dropped.
            wt = get("word") or get("token")
            start, end = get("start"), get("end")
            if wt and start is not None and end is not None:
                words.append({"text": str(wt), "start": float(start), "end": float(end)})

    if words:
        words.sort(key=lambda d: (d["start"], d["end"]))
    return texts, words


def segment_from_words(words: list[dict], max_gap: float = 2.0) -> list[dict]:
    """Group a flat word list into pseudo-segments split on implausible gaps.

    Only relevant if a NeMo entrant yields words but no usable per-hypothesis text
    chunks: the blocklist rule consumes per-card text, and a 24-minute wall of one
    string is a worse blocklist target than sentence-ish chunks. 2.0s matches the gap
    reflow treats as implausible within an utterance."""
    segments: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if cur and w["start"] - cur[-1]["end"] > max_gap:
            segments.append({"text": " ".join(x["text"] for x in cur), "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur = []
        cur.append(w)
    if cur:
        segments.append({"text": " ".join(x["text"] for x in cur), "start": cur[0]["start"], "end": cur[-1]["end"]})
    return segments


# ------------------------------------------------------------------- transcribers

# NeMo's transcribe() runs full (non-windowed) self-attention over the WHOLE clip in
# one pass -- unlike faster-whisper, which windows internally. On a 6GB Pascal card
# even a single 24-minute episode OOMs (observed: a ~2GB single allocation fails with
# under 2GB free after the model's own weights+activations). Chunking bounds peak VRAM
# to one chunk's worth regardless of episode/movie length, at the cost of losing any
# cross-chunk context the decoder might have used (irrelevant here: these are direct
# ASR entrants, not judged on continuity, and faster-whisper's own condition_on_previous
# _text is already off for the same reason -- see generate.py).
NEMO_CHUNK_S = 300.0

# Canary (EncDecMultiTaskModel) is a different decoder family from parakeet (RNNT/TDT):
# it generates autoregressively up to a fixed token budget (~512 tokens) per transcribe()
# call, not a streaming decode. A 300s chunk of dense dialogue needs well over that many
# tokens -- observed as repetition-collapse ("itsssss...", "It's awesome." x40), not a
# clean truncation, which is the classic failure mode of an AED decoder run past its
# generation-length cap. NeMo's own chunked-inference script for canary defaults to
# chunk_len_in_secs=40.0; matching that here instead of NEMO_CHUNK_S is the fix, not a
# guess -- https://github.com/NVIDIA-NeMo/NeMo/blob/main/examples/asr/
# asr_chunked_inference/aed/speech_to_text_aed_chunked_infer.py
NEMO_CANARY_CHUNK_S = 40.0


def chunk_wav(wav_path: str, chunk_s: float, out_dir: str) -> list[tuple[float, str]]:
    """Split a wav into fixed-length pieces, returning (offset_s, chunk_path) pairs.

    stdlib ``wave``, not ffmpeg: the input is always this pipeline's own 16k mono PCM
    extraction, so a chunk is a frame-range copy that needs no decoder and no subprocess.
    That also retires an ffmpeg trap this function was first written around -- with
    ``-c copy``, input seeking (``-ss`` before ``-i``) silently produced a 0-byte file with
    rc=0 at every offset tried, so the arguments had to be ordered for output seeking."""
    import wave

    chunks: list[tuple[float, str]] = []
    with wave.open(wav_path, "rb") as src:
        rate = src.getframerate()
        per_chunk = max(1, int(round(chunk_s * rate)))
        i = 0
        while True:
            frames = src.readframes(per_chunk)
            if not frames:
                break
            out_path = os.path.join(out_dir, f"chunk_{i:03d}.wav")
            with wave.open(out_path, "wb") as dst:
                dst.setnchannels(src.getnchannels())
                dst.setsampwidth(src.getsampwidth())
                dst.setframerate(rate)
                dst.writeframes(frames)
            chunks.append((i * per_chunk / rate, out_path))
            i += 1
    return chunks


def _extract_dub_wav(video: str, td: str) -> str | None:
    """The pipeline's own audio path: pick the eng dub track, extract 16k mono wav.

    Returns the wav path, or None with the reason recorded by the caller's ep dict."""
    import generate  # lazy: pulls faster_whisper at module scope

    idx = generate.eng_audio_index(video)
    if idx is None:
        return None
    wav = os.path.join(td, "a.wav")
    return wav if generate.extract_wav(video, idx, wav) else None


def run_whisper(name: str, videos: list[str], compute_type: str, model_dir: str) -> WhisperRun:
    """Transcribe every episode with one faster-whisper model, then unload it completely."""
    from faster_whisper import WhisperModel  # lazy: GPU stack

    import generate  # lazy: for INITIAL_PROMPT (and the audio path above)

    run = WhisperRun(name)
    t_load = time.monotonic()
    try:
        wm = WhisperModel(name, device="cuda", compute_type=compute_type, download_root=model_dir)
    except Exception as e:  # OOM or missing model IS the result for this entrant
        run.error = f"{type(e).__name__}: {e}"
        print(f"  {name}: LOAD FAILED: {run.error[:150]}", flush=True)
        return run
    run.load_s = round(time.monotonic() - t_load, 1)

    peak = vram_used_mib() or 0
    beam = int(os.environ.get("WHISPER_BEAM_SIZE", "7"))

    for v in videos:
        ep: dict = {"episode": os.path.basename(v)}
        t0 = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as td:
                wav = _extract_dub_wav(v, td)
                if wav is None:
                    ep["error"] = "no-eng-dub-or-extract-failed"
                else:
                    segs, _info = wm.transcribe(
                        wav,
                        language="en",
                        task="transcribe",
                        beam_size=beam,
                        best_of=beam,
                        word_timestamps=True,
                        vad_filter=False,
                        condition_on_previous_text=False,
                        no_speech_threshold=0.9,
                        log_prob_threshold=-2.0,
                        initial_prompt=generate.INITIAL_PROMPT,
                    )
                    n = 0
                    ep_texts: list[str] = []
                    for s in segs:  # the generator is lazy: consume it while the wav lives
                        run.segments.append(
                            {
                                "start": float(s.start),
                                "end": float(s.end),
                                "text": s.text,
                                "no_speech_prob": float(s.no_speech_prob),
                                "avg_logprob": float(s.avg_logprob),
                            }
                        )
                        ep_texts.append(s.text)
                        for w in s.words or []:
                            run.words.append(
                                {
                                    "text": w.word,
                                    "start": float(w.start),
                                    "end": float(w.end),
                                    "prob": float(w.probability or 1.0),
                                }
                            )
                        n += 1
                    ep["segments"] = n
                    # kept per episode (not just accumulated into run.segments) so a
                    # single-episode reference (e.g. a mislabelled-SDH dub script) can
                    # be scored against exactly the audio it actually covers.
                    ep["text"] = " ".join(ep_texts)
        except Exception as e:
            ep["error"] = f"{type(e).__name__}: {e}"
        ep["wall_s"] = round(time.monotonic() - t0, 1)
        peak = max(peak, vram_used_mib() or 0)
        run.episodes.append(ep)
        status = f"ERROR: {ep['error'][:80]}" if "error" in ep else "ok"
        print(f"  {name}: {ep['episode'][:50]} {ep['wall_s']}s [{status}]", flush=True)

    run.peak_vram_mib = peak
    # Full offload, then PROVE it: the next entrant must get the whole card.
    del wm
    gc.collect()
    time.sleep(3)
    run.peak_vram_mib = max(run.peak_vram_mib or 0, peak)
    return run


def run_nemo(model_name: str, videos: list[str], device: str) -> NemoRun:
    """Transcribe every episode with one NeMo model, then unload it completely.

    batch_size=1: a 24-minute episode must be bounded by GPU RAM alone, not multiplied
    by a batch of 24-minute clips."""
    import nemo.collections.asr as nemo_asr  # lazy: heavy, pulls torch/cuda
    import torch  # lazy: arrives with nemo

    run = NemoRun(model_name)
    t_load = time.monotonic()
    try:
        model = nemo_asr.models.ASRModel.from_pretrained(model_name, map_location=device)
        if device == "cuda":
            # from_pretrained defaults to fp32 -- faster-whisper gets an explicit
            # compute_type, so NeMo entrants need the same explicit precision choice
            # rather than silently taking 2x the VRAM of every other entrant here.
            model = model.half()
    except Exception as e:  # OOM, offline, or missing model IS the result for this entrant
        run.error = f"{type(e).__name__}: {e}"
        print(f"  {model_name}: LOAD FAILED: {run.error[:150]}", flush=True)
        return run
    run.load_s = round(time.monotonic() - t_load, 1)

    is_canary = "canary" in model_name.lower()
    chunk_s = NEMO_CANARY_CHUNK_S if is_canary else NEMO_CHUNK_S

    peak = vram_used_mib() or 0
    for v in videos:
        ep: dict = {"episode": os.path.basename(v)}
        t0 = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as td:
                wav = _extract_dub_wav(v, td)
                if wav is None:
                    ep["error"] = "no-eng-dub-or-extract-failed"
                else:
                    kwargs: dict = {"batch_size": 1, "timestamps": True}
                    if device == "cuda":
                        kwargs["num_workers"] = 0
                    if is_canary:
                        # EncDecMultiTaskModel needs its task specified explicitly --
                        # without it there is no guarantee it even runs plain ASR.
                        kwargs["source_lang"] = "en"
                        kwargs["target_lang"] = "en"
                        kwargs["pnc"] = "yes"  # NeMo's Modality check wants a string, not a bool
                    ep_texts: list[str] = []
                    ep_words: list[dict] = []
                    for offset, chunk_path in chunk_wav(wav, chunk_s, td):
                        out = model.transcribe([chunk_path], **kwargs)
                        c_texts, c_words = parse_transcript(out)
                        ep_texts.extend(c_texts)
                        for w in c_words:
                            ep_words.append({**w, "start": w["start"] + offset, "end": w["end"] + offset})
                        if device == "cuda":
                            # bound peak VRAM to one chunk's worth, not the whole episode.
                            # gc.collect() deliberately NOT called here: forcing a
                            # synchronous Python GC sweep right after CUDA async ops is a
                            # known race with pinned-memory deallocation -- reproduced as
                            # a fatal "illegal memory access" in the pinned allocator's
                            # free() on an 8GB Turing card (torch 2.14+cu130), always on
                            # the second transcribe() call. Not observed on the 6GB
                            # Pascal card (torch 2.6+cu124) this was written against.
                            torch.cuda.empty_cache()
                    run.has_timestamps = run.has_timestamps or bool(ep_words)
                    if ep_words and not ep_texts:
                        # shape this NeMo version only reaches via timestamps
                        ep_texts = [s["text"] for s in segment_from_words(ep_words)]
                    run.words.extend(ep_words)
                    for t in ep_texts:
                        run.segments.append({"text": t})
                    ep["segments"] = len(ep_texts)
                    ep["text"] = " ".join(ep_texts)
                    if not ep_texts:
                        ep["error"] = "empty-transcript"
        except Exception as e:
            ep["error"] = f"{type(e).__name__}: {e}"
        ep["wall_s"] = round(time.monotonic() - t0, 1)
        if device == "cuda":
            # A failed (OOM'd) call can leave tensors pinned until the next allocation
            # forces a collect; clearing here, not just at entrant teardown, is what
            # stops one bad episode from starving every episode after it. No explicit
            # gc.collect() -- see the per-chunk clear above for why.
            torch.cuda.empty_cache()
        peak = max(peak, vram_used_mib() or 0)
        run.episodes.append(ep)
        status = f"ERROR: {ep['error'][:80]}" if "error" in ep else "ok"
        print(f"  {model_name}: {ep['episode'][:50]} {ep['wall_s']}s [{status}]", flush=True)

    run.peak_vram_mib = peak
    # Full offload, then PROVE it: the next entrant must get the whole card.
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    time.sleep(3)
    return run


class QwenRun(NemoRun):
    """Result record for one Qwen3-ASR entrant -- identical shape to NemoRun (a
    non-whisper decoder with no per-segment nsp/logprob and word-level timestamps
    merged from a separate forced-aligner pass), so only the family label differs."""

    family = "qwen3-asr"


# Qwen3-ASR's own package DOES chunk internally (up to 20min per plain-ASR pass, 3min
# per forced-align pass -- qwen_asr.inference.utils.MAX_ASR_INPUT_SECONDS /
# MAX_FORCE_ALIGN_INPUT_SECONDS, read from the package source), but that 20-minute cap
# is still one non-windowed attention pass over the whole chunk -- reproduced as a real
# OOM on a 6GB card (model load: 1.9GB; a single transcribe() call on a ~24min episode
# then tried to allocate another 5.4GB). The library's internal chunking bounds RAM for
# a big card, not a 6GB one; pre-chunking externally with chunk_wav() (like run_nemo
# does for canary) is the fix an earlier version of this comment assumed was
# unnecessary -- corrected here against that OOM, not left as a stale claim.
QWEN_CHUNK_S = 60.0

QWEN_FORCED_ALIGNER = "Qwen/Qwen3-ForcedAligner-0.6B"

# qwen_asr.Qwen3ASRModel.from_pretrained() defaults max_new_tokens to 512, applied as a
# hard per-generate() cap regardless of chunk length -- and an ASR chunk can run up to
# 1200s (20 minutes) of dense dialogue. That is the exact failure shape that broke NeMo
# canary here (repetition-collapse past a fixed generation cap -- see NEMO_CANARY_CHUNK_S
# above): verified by reading qwen_asr's own source (qwen3_asr.py, from_pretrained's
# signature and the model.generate() call), not assumed. Override explicitly.
QWEN_MAX_NEW_TOKENS = 4096

# Qwen3-ASR is genuinely multilingual and, left unconstrained, drifts into transcribing
# background music/vocals in Chinese mid-episode -- reproduced directly: an English dub
# episode came back with a long run of Chinese-language hallucinated lyrics during a
# song, dragging the word count to ~1/7th of turbo's on the same audio. Passing
# language="English" (an exact SUPPORTED_LANGUAGES value, not a locale code -- see
# qwen_asr.inference.utils) forces text-only English output per the package's own
# transcribe() docstring. Pinned here since production is English-dub-only; a future
# non-English use of this harness would need this constant configurable.
QWEN_LANGUAGE = "English"


def run_qwen(model_name: str, videos: list[str], device: str) -> QwenRun:
    """Transcribe every episode with one Qwen3-ASR model + its forced aligner, then unload.

    Pre-chunked with chunk_wav() at QWEN_CHUNK_S (see its comment for why) -- one
    ASRTranscription per chunk, merged into one segment/word list per episode, offsets
    added back onto word timestamps the same way run_nemo does."""
    import torch  # lazy: arrives with qwen_asr
    from qwen_asr import Qwen3ASRModel  # lazy: heavy, pulls torch/transformers

    run = QwenRun(model_name)
    t_load = time.monotonic()
    try:
        model = Qwen3ASRModel.from_pretrained(
            model_name,
            forced_aligner=QWEN_FORCED_ALIGNER,
            device_map=device,
            dtype=torch.float16 if device == "cuda" else torch.float32,
            max_new_tokens=QWEN_MAX_NEW_TOKENS,
        )
    except Exception as e:  # OOM, offline, or missing model IS the result for this entrant
        run.error = f"{type(e).__name__}: {e}"
        print(f"  {model_name}: LOAD FAILED: {run.error[:150]}", flush=True)
        return run
    run.load_s = round(time.monotonic() - t_load, 1)

    peak = vram_used_mib() or 0
    for v in videos:
        ep: dict = {"episode": os.path.basename(v)}
        t0 = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as td:
                wav = _extract_dub_wav(v, td)
                if wav is None:
                    ep["error"] = "no-eng-dub-or-extract-failed"
                else:
                    ep_texts: list[str] = []
                    ep_words: list[dict] = []
                    for offset, chunk_path in chunk_wav(wav, QWEN_CHUNK_S, td):
                        result = model.transcribe(chunk_path, language=QWEN_LANGUAGE, return_time_stamps=True)[0]
                        text = result.text or ""
                        if text:
                            ep_texts.append(text)
                        if result.time_stamps is not None:
                            for item in result.time_stamps:
                                ep_words.append(
                                    {
                                        "text": item.text,
                                        "start": float(item.start_time) + offset,
                                        "end": float(item.end_time) + offset,
                                    }
                                )
                        if device == "cuda":
                            torch.cuda.empty_cache()
                    run.has_timestamps = run.has_timestamps or bool(ep_words)
                    run.words.extend(ep_words)
                    for t in ep_texts:
                        run.segments.append({"text": t})
                    ep["segments"] = len(ep_texts)
                    ep["text"] = " ".join(ep_texts)
                    if not ep_texts:
                        ep["error"] = "empty-transcript"
        except Exception as e:
            ep["error"] = f"{type(e).__name__}: {e}"
        ep["wall_s"] = round(time.monotonic() - t0, 1)
        if device == "cuda":
            torch.cuda.empty_cache()
        peak = max(peak, vram_used_mib() or 0)
        run.episodes.append(ep)
        status = f"ERROR: {ep['error'][:80]}" if "error" in ep else "ok"
        print(f"  {model_name}: {ep['episode'][:50]} {ep['wall_s']}s [{status}]", flush=True)

    run.peak_vram_mib = peak
    # Full offload, then PROVE it: the next entrant must get the whole card.
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    time.sleep(3)
    return run


# --------------------------------------------------------------------- entrant list


WHISPER_FAMILY = ("whisper", "large-v3", "large-v2", "distil", "medium", "small", "base", "tiny")


def is_whisper_name(name: str) -> bool:
    """Route an --models entry to the faster-whisper runner.

    Anything that looks like a HF NeMo id (org/name) whose model name does NOT contain a
    whisper-family token is NeMo (or Qwen -- see is_qwen_name, checked first in
    run_entrant). ``nvidia/parakeet-tdt-0.6b-v3``, ``nvidia/canary-1b-v2`` -> NeMo;
    ``large-v3-turbo``, ``deepdml/faster-distil-whisper-large-v3`` -> faster-whisper."""
    stem = name.rsplit("/", 1)[-1].lower()
    return any(tok in stem for tok in WHISPER_FAMILY)


def is_qwen_name(name: str) -> bool:
    """Route an --models entry to the Qwen3-ASR runner.

    Checked on the HF org prefix ("qwen/...") rather than a substring match on the
    model name: NeMo's own ``nvidia/canary-qwen-2.5b`` contains "qwen" in its name (it
    uses a Qwen LLM as its decoder) but needs the NeMo backend, not this one -- an "in"
    check would misroute it."""
    return name.lower().startswith("qwen/")


def run_entrant(name: str, videos: list[str], compute_type: str, model_dir: str, device: str) -> dict:
    """Dispatch one --models entry to its runner, then shape its report entry.

    The report's "model" label carries the precision alongside the name: whisper
    entrants can run at any --compute-type, NeMo/Qwen entrants are always cast to fp16
    on cuda (neither has an int8 inference path -- see the module docstring), so two
    runs of the "same" model at different precision need distinct labels or they
    collide as one entrant in the pairwise-agreement table."""
    run: WhisperRun | NemoRun | QwenRun
    if is_whisper_name(name):
        run = run_whisper(name, videos, compute_type, model_dir)
        label = f"{name} ({compute_type})"
    elif is_qwen_name(name):
        run = run_qwen(name, videos, device)
        label = f"{name} (fp16)" if device == "cuda" else name
    else:
        run = run_nemo(name, videos, device)
        label = f"{name} (fp16)" if device == "cuda" else name

    entry: dict = {
        "model": label,
        "family": run.family,
        "load_s": run.load_s,
        "peak_vram_mib": run.peak_vram_mib,
        "has_word_timestamps": bool(run.words),
        "episodes": run.episodes,
    }
    if not run.ok:
        entry["error"] = run.error
        entry["verdict"] = "did not load"
        return entry

    entry.update(
        summarise(
            [s["no_speech_prob"] for s in run.segments if "no_speech_prob" in s],
            [s["avg_logprob"] for s in run.segments if "avg_logprob" in s],
            run.texts(),
        )
    )
    entry["word_count"] = len(run.words)
    # Full transcripts stay in the report on purpose: the verdict line tells you to
    # hand-read them, and the noisiest episode is exactly where blocklist/agreement
    # metrics cannot see wrong-but-plausible words.
    entry["texts"] = run.texts()
    entry["words"] = run.words
    entry["verdict"] = "ok"
    return entry


def score_against_references(entries: list[dict], refs: dict[str, str]) -> None:
    """Attach wer_vs_ref to every episode whose basename has a loaded reference.

    Mutates entries in place: run_whisper/run_nemo already keep per-episode text
    (``ep["text"]``), so this is a pure post-pass over already-collected data -- no
    re-transcription, and it runs the same whether refs came from --report-only's saved
    JSON or a live run."""
    for e in entries:
        for ep in e.get("episodes", []):
            ref = refs.get(ep["episode"])
            if ref and "text" in ep:
                ep["wer_vs_ref"] = wer(ref, ep["text"])


def shape_report(entries: list[dict], agreement: dict) -> dict:
    """Assemble the JSON report dict the CLI writes (also the unit-test target)."""
    return {"entrants": entries, "agreement_wer": agreement}


def print_verdict(report: dict) -> None:
    """Print the human-readable verdict table to stdout."""
    print("\n" + "=" * 72)
    for e in report["entrants"]:
        name = e["model"]
        if e.get("verdict") != "ok":
            print(f"{name:<36} {e.get('verdict', '?')}: {str(e.get('error', ''))[:60]}")
            continue
        failed = [ep for ep in e["episodes"] if "error" in ep]
        ts = "words" if e.get("has_word_timestamps") else "NO word timestamps"
        mins = sum(ep["wall_s"] for ep in e["episodes"]) / 60
        print(
            f"{name:<36} load {e.get('load_s') or '?':>6}s   peak {e.get('peak_vram_mib') or '?':>6} MiB   "
            f"segs {e.get('segments', '?'):>5}   words {e.get('word_count', '?'):>6}   "
            f"{ts:<20} blocklist {e.get('blocklist_hits', '?')}   {mins:.1f} min total"
            + (f"   EPISODE ERRORS: {len(failed)}" if failed else "")
        )
        for ep in failed:
            print(f"    {ep['episode'][:60]}: {ep['error']}")
        for ep in e["episodes"]:
            if ep.get("wer_vs_ref") is not None:
                print(f"    {ep['episode'][:50]}: WER vs reference = {ep['wer_vs_ref']:.2%}")
    agreement = report.get("agreement_wer") or {}
    if agreement:
        print("\nagreement WER (low = the two stacks heard the same thing):")
        for pair, w in agreement.items():
            a, b = pair.split("|", 1)
            print(f"  {a} <-> {b}: {'n/a (different episode sets)' if w is None else f'{w:.2%}'}")
    models = [e["model"] for e in report["entrants"]]
    if any("(fp16)" in m for m in models) and any("(int8)" in m for m in models):
        print(
            "\nCAVEAT: this report mixes int8 whisper entrants with fp16 NeMo entrants -- "
            "NeMo has no supported int8 inference path (see this file's module docstring). "
            "VRAM/speed comparisons across that boundary are not apples-to-apples."
        )
    print("\nNext: hand-read the transcripts on your noisiest episode. Blocklist and")
    print("agreement numbers cannot see wrong-but-plausible words.")


# ------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("videos", nargs="*", help="episodes to transcribe with every --models entry")
    ap.add_argument(
        "--models",
        default="large-v3-turbo,nvidia/parakeet-tdt-0.6b-v3",
        help="comma-separated; whisper-family names -> faster-whisper, everything else -> NeMo",
    )
    ap.add_argument("--compute-type", default=os.environ.get("COMPUTE_TYPE", "int8"))
    ap.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", "/models"))
    ap.add_argument("--device", default=os.environ.get("ASR_DEVICE", "cuda"), help="device for the NeMo side")
    ap.add_argument("--out", default="", help="write the JSON report here")
    ap.add_argument("--report-only", action="store_true", help="re-print a saved --out report, no GPU")
    ap.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="EPISODE_BASENAME=SRT_PATH",
        help="score one episode against a real reference transcript (e.g. a mislabelled-SDH dub script); repeatable",
    )
    args = ap.parse_args(argv)
    refs = {base: load_srt_reference(path) for base, _, path in (item.partition("=") for item in args.ref)}

    if args.report_only:
        if not args.out:
            ap.error("--report-only needs --out")
        with open(args.out) as f:
            report = json.load(f)
        score_against_references(report["entrants"], refs)
        print_verdict(report)
        return 0

    if not args.videos:
        ap.error("give at least one episode (or --report-only)")

    import generate  # lazy: pulls faster_whisper at module scope

    generate.load_glossary()
    names = [n.strip() for n in args.models.split(",") if n.strip()]

    # Transcribe ALL videos per entrant (not one video per pair of loads): model loads
    # are the expensive part, and sequential-per-model is what lets the second entrant
    # start from a proven-empty card.
    entries: list[dict] = []
    for name in names:
        print(f"== {name} ==", flush=True)
        entries.append(run_entrant(name, args.videos, args.compute_type, args.model_dir, args.device))

    score_against_references(entries, refs)

    # Agreement WER for every pair of entrants that completed the same episode set -- a
    # one-sided or error-punctuated join would score a mismatch the models never both saw.
    report = shape_report(entries, pairwise_agreement(entries))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
        print("report ->", args.out)
    print_verdict(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
