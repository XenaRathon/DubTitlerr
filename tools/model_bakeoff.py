#!/usr/bin/env python3
"""A/B two whisper models on the SAME episodes, with the pipeline's own audio path.

Why this is an A/B and not a score against a stored labelled set
---------------------------------------------------------------
The "labelled set" cited in the 2026-08-21 review (207 certain hallucinations against
57,572 real cards) is not an artifact on disk. Its positives are blocklist-defined hits
found in existing ``conf.json`` sidecars, and those sidecars were produced BY the model
currently in production. Scoring a candidate model against them would be scoring it
against its rival's output. So each model transcribes the same episodes here and the two
runs are compared directly.

What it measures, and why each one
----------------------------------
``no_speech_prob`` distribution
    The decisive number. §5.3 of the VAD design established that ``large-v3-turbo``
    collapses nsp to ~1e-10 on every card, verified across two independent CT2
    conversions -- which makes the ``music`` drop rule and the ``maybe_silence`` flag
    STRUCTURALLY INERT: 2 of the 5 gated rules cannot fire at all. If large-v3 returns a
    real distribution, it buys back two rules; if it does not, the honest response is to
    delete those rules rather than keep shipping them.
``avg_logprob`` distribution
    §5.4 measured this as the second-best discriminator (0.913 separation).
blocklist hits
    A proxy for "certain hallucination" using the same rule the gate uses, so the two
    models are judged by the pipeline's own standard.
wall clock and peak VRAM
    A model that does not fit is a FINDING, not an error: an OOM is recorded as that
    entrant's result rather than retried at a smaller beam, because a smaller beam is a
    different model than the one being judged.

Models are loaded STRICTLY SEQUENTIALLY with a full offload between them, so the second
entrant gets the whole card. Free VRAM is recorded before and after each load, which is
what makes "it was fully offloaded" an observation rather than an assumption.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hallucination  # noqa: E402

# generate is imported LAZILY inside the functions that transcribe: it pulls in
# faster_whisper at module scope, and the report-shaping half of this tool must stay
# importable (and testable) on a machine with no CUDA stack.


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


def summarise(nsps: list[float], lps: list[float], texts: list[str]) -> dict:
    """Collapse one model's per-segment output into the numbers the decision needs.

    ``nsp_alive`` is the whole point: the fraction of segments whose no_speech_prob is
    above a floor a collapsed model can never clear. With turbo it is expected to be 0.0,
    which is what makes two of the gate's five rules dead code."""

    def q(v, p):
        return round(statistics.quantiles(v, n=100)[p - 1], 6) if len(v) > 1 else (round(v[0], 6) if v else None)

    blocklist_hits = sum(1 for t in texts if hallucination.BLOCKLIST.search(t))
    return {
        "segments": len(nsps),
        "nsp_min": round(min(nsps), 12) if nsps else None,
        "nsp_median": q(nsps, 50),
        "nsp_max": round(max(nsps), 6) if nsps else None,
        # A collapsed decoder pins every segment at ~1e-10; anything above 1e-6 means the
        # signal is real and the nsp-based rules can actually fire.
        "nsp_alive_frac": round(sum(1 for n in nsps if n > 1e-6) / len(nsps), 4) if nsps else None,
        "nsp_over_0_5": sum(1 for n in nsps if n > 0.5),
        "nsp_over_0_95": sum(1 for n in nsps if n > 0.95),
        "logprob_median": q(lps, 50),
        "logprob_p05": q(lps, 5),
        "blocklist_hits": blocklist_hits,
    }


def run_model(model_name: str, videos: list[str], compute_type: str, model_dir: str) -> dict:
    """Transcribe every episode with one model, then unload it completely."""
    from faster_whisper import WhisperModel

    import generate

    before = vram_used_mib()
    result: dict = {"model": model_name, "vram_before_load_mib": before, "episodes": []}
    t_load = time.monotonic()
    try:
        wm = WhisperModel(model_name, device="cuda", compute_type=compute_type, download_root=model_dir)
    except Exception as e:  # OOM or missing model IS the result for this entrant
        result["error"] = f"{type(e).__name__}: {e}"
        result["verdict"] = "did not load"
        return result
    result["load_s"] = round(time.monotonic() - t_load, 1)

    peak = vram_used_mib() or 0
    nsps: list[float] = []
    lps: list[float] = []
    texts: list[str] = []
    beam = int(os.environ.get("WHISPER_BEAM_SIZE", "7"))

    for v in videos:
        ep = {"episode": os.path.basename(v)}
        t0 = time.monotonic()
        try:
            idx = generate.eng_audio_index(v)
            if idx is None:
                ep["error"] = "no-eng-dub"
                result["episodes"].append(ep)
                continue
            with tempfile.TemporaryDirectory() as td:
                wav = os.path.join(td, "a.wav")
                if not generate.extract_wav(v, idx, wav):
                    ep["error"] = "extract-failed"
                    result["episodes"].append(ep)
                    continue
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
                for s in segs:  # the generator is lazy: consume it while the wav lives
                    nsps.append(float(s.no_speech_prob))
                    lps.append(float(s.avg_logprob))
                    texts.append(s.text)
                    n += 1
                ep["segments"] = n
        except Exception as e:
            ep["error"] = f"{type(e).__name__}: {e}"
        ep["wall_s"] = round(time.monotonic() - t0, 1)
        peak = max(peak, vram_used_mib() or 0)
        result["episodes"].append(ep)
        print(f"  {model_name}: {ep['episode'][:50]} {ep['wall_s']}s", flush=True)

    result["peak_vram_mib"] = peak
    result.update(summarise(nsps, lps, texts))
    done = [e for e in result["episodes"] if "wall_s" in e and "error" not in e]
    if done:
        result["mean_minutes_per_episode"] = round(sum(e["wall_s"] for e in done) / len(done) / 60, 2)

    # Full offload, then PROVE it: the next entrant must get the whole card.
    del wm
    gc.collect()
    time.sleep(3)
    result["vram_after_unload_mib"] = vram_used_mib()
    result["verdict"] = "ok"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("videos", nargs="+", help="episodes to transcribe with BOTH models")
    ap.add_argument("--models", default="large-v3-turbo,large-v3")
    ap.add_argument("--compute-type", default=os.environ.get("COMPUTE_TYPE", "int8"))
    ap.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", "/models"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    import generate

    generate.load_glossary()
    report = {
        "videos": [os.path.basename(v) for v in args.videos],
        "compute_type": args.compute_type,
        "beam_size": int(os.environ.get("WHISPER_BEAM_SIZE", "7")),
        "entrants": [],
    }
    for name in args.models.split(","):
        print(f"== {name} ==", flush=True)
        report["entrants"].append(run_model(name.strip(), args.videos, args.compute_type, args.model_dir))

    print("\n" + "=" * 72)
    for e in report["entrants"]:
        if e.get("verdict") != "ok":
            print(f"{e['model']:<20} {e['verdict']}: {e.get('error', '')[:60]}")
            continue
        print(
            f"{e['model']:<20} {e.get('mean_minutes_per_episode', '?'):>6} min/ep   "
            f"peak {e['peak_vram_mib']:>5} MiB   segs {e['segments']:>5}   "
            f"nsp_alive {e['nsp_alive_frac']}   nsp_max {e['nsp_max']}   "
            f"blocklist {e['blocklist_hits']}"
        )
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
        print("report ->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
