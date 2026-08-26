#!/usr/bin/env python3
"""Per-episode UNRESOLVED queue — the human rung of the deterministic → LLM → human ladder,
for the subtitle path.

`glossary_acquire.py` already implements that ladder properly: candidates the deterministic
gates cannot settle become `flagged`, and `--review` walks them with their evidence attached.
The subtitle path had no equivalent. Repair increments `skipped_no_ref` and `rejected` and
continues; punctuation restoration records `restore_empty` and leaves the old text in place.
Each is a *safe* fallback, and each is invisible: `common.llm_chat()` returns "" on every
transport failure, so a dead endpoint produces a clean-looking run with a slightly higher
counter. The actual ladder was:

    rules -> bounded LLM -> keep old text / increment a counter

This module supplies the missing arrow. It records WHAT could not be settled, WHY, and the
evidence a human needs to settle it — so a model refusal, a dead endpoint and a missing
reference stop being the same silent no-op.

PER-STAGE, not one flat queue: the triage action differs by stage. A repair rejection needs
the fansub reference checked; a punctuation failure needs the run read; they are not
interchangeable, and a flat queue destroys the signal that says which to do.

Deliberately NOT covered yet: the hallucination `flag`. `maybe_silence` fires on 67% of real
cards (measured over 20,292), so queuing it would bury the operator in ~13,000 entries per
20,000 cards. A queue nobody can face is worse than no queue.

That deferral is tied to a specific future item: the liveness counters showed `music` AND
`repetition` both activate ZERO times, while `maybe_silence` activates on two thirds of
everything. All three are hallucination-gate rules that need re-thresholding together, and
the queue's hallucination stage should be added in that same pass — the right threshold is
what decides whether the entries are worth a human's attention at all.

Contract, mirroring qc.write: this is OBSERVABILITY. It must never raise and never fail an
episode that otherwise generated correctly. Every entry point returns a bool.
"""

import json
import os
import tempfile

from common import SIDECAR_MODE, out_for

SUFFIX = ".dubtitles.unresolved.jsonl"

# Reasons, per stage. Kept as a module constant so the --review CLI and the call sites cannot
# drift apart, and so a typo'd reason is visible rather than silently creating a new bucket.
REASONS = {
    "repair": (
        "no_reference",  # no fansub anchor overlapped this card's source window
        "rejected_guard",  # the model proposed an edit; accept_repair() refused it
        "rejected_name_invented",  # the model substituted a proper noun that is in
        # neither the glossary nor the original -- the phonetic name guard refused it
        "llm_empty",
    ),  # the backend returned nothing (transport failure or timeout)
    "punctuation": (
        "llm_empty",  # ditto -- a dead endpoint looks exactly like "no change"
        "rejected_guard",
    ),  # accept_restoration() found the model rewrote words
}


def path_for(stem: str) -> str:
    return out_for(stem + SUFFIX)


def items(stem: str) -> list:
    """Every entry, resolved and pending. Returns [] rather than raising.

    JSONL, one entry per line. A trailing partial line -- the only thing a crash mid-append
    can produce -- is skipped, so a torn write costs the last entry rather than the file."""
    out = []
    try:
        with open(path_for(stem), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue  # torn final line; everything before it is intact
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        return []
    return out


def pending(stem: str) -> list:
    return [e for e in items(stem) if not e.get("resolved")]


def _rewrite(stem: str, doc: list) -> bool:
    """Whole-file replace, used only by resolve(). Atomic via temp + os.replace."""
    path = path_for(stem)
    d = os.path.dirname(path) or "."
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for e in doc:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.chmod(tmp, SIDECAR_MODE)
        os.replace(tmp, path)
        return True
    except (OSError, ValueError):
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def record(stem: str, stage: str, reason: str, **fields) -> bool:
    """Append one unresolved case. Extra fields are the evidence for triage — for repair that
    is original_text/proposed_text/source_start/source_end/avg_logprob; for punctuation the
    run's text. `proposed_text` matters most: today a rejected repair discards what the model
    said, which is exactly what a human needs to judge whether the guard was right."""
    entry = {"stage": stage, "reason": reason, "resolved": False}
    entry.update({k: v for k, v in fields.items() if v is not None})
    path = path_for(stem)
    try:
        # O(1) append. The array version re-read and re-wrote the whole file per card --
        # O(n^2) I/O, and one CIFS round-trip each, on a path that fires ~86x per episode.
        exists = os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if not exists:
            os.chmod(path, SIDECAR_MODE)  # only the creator sets the mode
        return True
    except (OSError, ValueError):
        return False


def resolve(stem: str, index: int, accept: bool, note: str = "") -> bool:
    """Mark one entry reviewed. The entry KEEPS its evidence: this file is the audit trail,
    not a worklist that shrinks. Mirrors glossary_acquire.record_decision, where a human
    rejection is itself durable information (it stops the next sweep re-proposing it)."""
    doc = items(stem)
    if not (0 <= index < len(doc)):
        return False
    doc[index]["resolved"] = True
    doc[index]["accepted"] = bool(accept)
    if note:
        doc[index]["note"] = note
    return _rewrite(stem, doc)


# --- review CLI ---------------------------------------------------------------------------
# Mirrors glossary_acquire.py's --review: walk what the automation could not settle, show the
# evidence that stage's triage actually needs, record the decision. Unified walk, stage-keyed
# storage -- one pass for the operator, but a repair entry still arrives with its reference
# and a punctuation entry with its run.

_EVIDENCE = {
    # what a human needs to see to settle each reason, in the order it helps
    "no_reference": ("original_text", "source_start", "source_end", "avg_logprob"),
    "rejected_guard": ("original_text", "proposed_text", "reference", "avg_logprob", "words"),
    "rejected_name_invented": ("original_text", "proposed_text", "reference", "avg_logprob", "words"),
    "llm_empty": ("original_text", "segments", "words"),
}


def _render(i: int, e: dict) -> str:
    head = f"[{i}] {e['stage']}/{e['reason']}"
    lines = [head, "-" * len(head)]
    for k in _EVIDENCE.get(e["reason"], ()):
        if k in e:
            lines.append(f"  {k:14} {e[k]}")
    for k, v in e.items():  # anything not in the template, so nothing hides
        if k not in ("stage", "reason", "resolved", "accepted", "note") and k not in _EVIDENCE.get(e["reason"], ()):
            lines.append(f"  {k:14} {v}")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    import glob as _glob

    ap = argparse.ArgumentParser(description="Review subtitle-quality cases the pipeline could not settle.")
    ap.add_argument("target", help="an episode stem, or a directory to walk")
    ap.add_argument("--review", action="store_true", help="interactive walk (default: list pending and exit)")
    a = ap.parse_args(argv)

    stems = (
        [a.target]
        if os.path.exists(a.target + SUFFIX)
        else [p[: -len(SUFFIX)] for p in sorted(_glob.glob(os.path.join(a.target, "**", "*" + SUFFIX), recursive=True))]
    )
    total = 0
    for stem in stems:
        todo = pending(stem)
        if not todo:
            continue
        print(f"\n=== {os.path.basename(stem)}  ({len(todo)} pending) ===")
        for e in todo:
            idx = items(stem).index(e)
            print(_render(idx, e))
            total += 1
            if not a.review:
                continue
            try:
                ans = input("  keep as-is [k] / needs fixing [f] / skip [s] ? ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  stopped.")
                return 0
            if ans in ("k", "f"):
                note = input("  note (optional): ").strip()
                resolve(stem, idx, accept=(ans == "k"), note=note)
    print(f"\n{total} pending across {len(stems)} episode(s)." if total else "\nNothing pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
