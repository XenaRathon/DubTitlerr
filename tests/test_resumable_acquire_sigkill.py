"""A REAL SIGKILL (sent by the parent, no cleanup of any kind) in the middle of glossary_acquire: tier C pairs and tier B picks.

The earlier kill test exits from inside the fake backend; this one kills the whole process from outside while it is working, at
a point chosen by how many results are already durable. Resumed output must equal an uninterrupted run's, for a dry run and for
--apply, and only the unfinished calls may be asked again."""

import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_resumable_acquire import PAIRS, build_show, last_json

import glossary_acquire as ga

ROOT = Path(__file__).resolve().parents[1]
TIER_B = ["Kasumi", "Tsunari"]
EXTRA = [f"I saw {t} {w}." for t in TIER_B for w in ("walk", "again", "thrice")] * 3
TOTAL = len(PAIRS) + len(TIER_B)  # five tier-C pairs, then two tier-B picks

RUNNER = r"""
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
import glossary_acquire as ga, glossary_verify as gv
gloss, show_dir, apply, delay = sys.argv[2], sys.argv[3], sys.argv[4] == "apply", float(sys.argv[5])
TITLES = __TITLES__
gv.VERIFY_BACKEND = "llamacpp"; gv.BACKEND_PROBLEM = ""
gv.backend_problem = lambda backend=None: ""
gv.resolve_wiki = lambda *a, **k: "https://x/api.php"
gv.fetch_titles = lambda *a, **k: TITLES
gv.candidates = lambda term, titles, k=6: ["Misty"]
n = {"calls": 0}
def answer(reply):
    def llm(prompt, **kw):
        n["calls"] += 1
        time.sleep(delay)  # work in flight: this is where the parent's SIGKILL lands
        return json.dumps(reply)
    return llm
ga.llm_chat = answer({"same_entity": True, "confidence": "high"})          # tier C: the pair merge
gv.llm_chat = answer({"canonical": "Misty", "confidence": "high"})          # tier B: the per-term pick
rep = ga.acquire(gloss, show_dir, apply=apply)
print(json.dumps({"report": rep, "calls": n["calls"]}, sort_keys=True, default=str))
""".replace("__TITLES__", repr([c for _, c in PAIRS] + ["Misty"]))


def start(d, gloss, apply, delay):
    script = d / "runner.py"
    script.write_text(RUNNER)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("ACQUIRE_NO_CACHE", None)
    return subprocess.Popen(
        [sys.executable, str(script), str(ROOT), str(gloss), str(d), "apply" if apply else "dry", str(delay)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def durable(gloss):
    p = Path(str(gloss)[:-5] + ".acquire.journal.jsonl")
    return len(p.read_text().splitlines()) if p.exists() else 0


def kill_when(proc, gloss, wanted, timeout=60):
    """SIGKILL ``proc`` from outside as soon as ``wanted`` results are durable."""
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise AssertionError(f"the run finished before the kill point: {proc.stdout.read()} {proc.stderr.read()}")
        if durable(gloss) >= wanted:
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=30)
            return
        time.sleep(0.01)
    proc.kill()
    raise AssertionError("never reached the kill point")


@pytest.mark.parametrize("apply", [False, True])
def test_a_real_sigkill_in_tier_c_and_tier_b_then_a_restart_equals_an_uninterrupted_run(tmp_path, apply):
    clean = build_show(tmp_path / "clean", extra=EXTRA)
    proc = start(clean.parent, clean, apply, 0)
    out, err = proc.communicate(timeout=120)
    assert proc.returncode == 0, err
    clean_out = last_json(type("P", (), {"stdout": out}), clean.parent)
    assert clean_out["calls"] == TOTAL
    rng = random.Random(20261011)
    # one kill inside the pairs (random), one right after the last pair, one inside tier B
    for trial, wanted in enumerate([rng.randint(1, len(PAIRS) - 1), len(PAIRS), len(PAIRS) + 1]):
        d = tmp_path / f"trial{trial}"
        gloss = build_show(d, extra=EXTRA)
        proc = start(d, gloss, apply, 0.3)
        kill_when(proc, gloss, wanted)
        assert proc.returncode == -signal.SIGKILL
        left = durable(gloss)
        assert left >= wanted and left < TOTAL, f"killed with {left} of {TOTAL} results durable"
        if wanted < len(PAIRS):  # killed inside the pairs: the end-of-run pair cache was never written, only the journal has them
            assert not Path(ga.acquire_cache.path_for(str(gloss))).exists()
        resumed = start(d, gloss, apply, 0)
        out, err = resumed.communicate(timeout=120)
        assert resumed.returncode == 0, err
        got = last_json(type("P", (), {"stdout": out}), d)
        assert got["calls"] == TOTAL - left, "only the results that were not durable are asked again"
        assert got["report"] == clean_out["report"], f"trial {trial}: report differs from an uninterrupted run"
        assert gloss.read_bytes() == clean.read_bytes(), f"trial {trial}: glossary differs from an uninterrupted run"
