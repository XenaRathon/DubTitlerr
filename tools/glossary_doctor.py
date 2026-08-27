#!/usr/bin/env python3
"""Check -- and repair -- the invariant that a verified glossary term stays IN SERVICE.

`glossary_verify.apply_results()` used to overwrite a term with its wiki canonical form
(`lst[i] = canon`). The overwritten term survived only in `verified`, a bookkeeping key that
`glossary.load_dict()` never reads, so the runtime silently lost it. The code path is fixed
(see 7aef5b6); this module handles the data already damaged, and leaves behind a test that
fails if it ever happens again.

THE INVARIANT
    Every term in `verified` is reachable at runtime -- present in `names`, in `phrases`, or
    as a `hard_fixes` VALUE -- or is explicitly parked in `flagged`.

"Or flagged" matters: a term a human rejected is legitimately out of service, and an
invariant that cannot express that would force the operator to choose between a false alarm
and deleting the audit trail.

SHAPE
    `names` feeds `glossary.correct()`'s per-token tiers, whose `_TOKEN_RE` matches exactly
    one token, so a multi-word entry there can never fire. Multi-word terms belong in
    `phrases`, which feeds `repair._glossary_terms()`. A multi-word string in `names` is
    therefore a defect in its own right, and the doctor reports and repairs it.

Read-only by default. `--fix` writes, and only then.
"""

from __future__ import annotations

import argparse
import glob
import json
import os


def _runtime_terms(g: dict) -> set:
    """Everything `glossary.load_dict()` actually puts in front of the pipeline."""
    return set(g.get("names") or []) | set(g.get("phrases") or []) | set((g.get("hard_fixes") or {}).values())


def diagnose(g: dict) -> dict:
    """Findings for one glossary. Pure -- takes a dict, returns a report, touches nothing."""
    live = _runtime_terms(g)
    flagged = set(g.get("flagged") or {})
    stranded = sorted(t for t in (g.get("verified") or []) if t not in live and t not in flagged)
    misshaped = sorted(t for t in (g.get("names") or []) if " " in t.strip())
    return {"stranded": stranded, "misshaped": misshaped, "ok": not stranded and not misshaped}


def repair(g: dict) -> tuple[dict, dict]:
    """Return (repaired copy, report). Deep-copies; never mutates the input.

    Every list edit is ADD-THEN-REMOVE. A move done the other way round loses the term
    outright if the process dies between the two steps -- strictly worse than the bug being
    repaired, and on a 924 MB-adjacent CIFS write that window is not theoretical."""
    out = json.loads(json.dumps(g))
    rep = diagnose(out)
    names = out.setdefault("names", [])
    phrases = out.setdefault("phrases", [])

    for t in rep["stranded"]:  # restore to the list its SHAPE implies
        dest = phrases if " " in t.strip() else names
        if t not in dest:
            dest.append(t)

    for t in rep["misshaped"]:  # multi-word in names -> phrases
        if t not in phrases:
            phrases.append(t)  # ADD first...
        while t in names:
            names.remove(t)  # ...only then REMOVE

    out["names"] = sorted(set(names))
    out["phrases"] = sorted(set(phrases))
    return out, rep


def drop_prompt_terms(g: dict, terms: list, reason: str) -> tuple[dict, list]:
    """Remove unverified strings from `initial_prompt` AND `phrases`, recording each in
    `flagged` so the next sweep does not re-propose it.

    `initial_prompt` is one comma-joined string, so this splits on commas and drops whole
    fields rather than doing substring surgery -- a `replace()` would happily cut a name in
    half or take a prefix of a longer one."""
    out = json.loads(json.dumps(g))
    want = {t.strip().lower() for t in terms}
    dropped = []

    prompt = out.get("initial_prompt", "")
    if prompt:
        # keep the sentence structure: split on commas, drop matching fields, rejoin
        head, sep, tail = prompt.partition("Attack names:")
        target = tail if sep else prompt
        fields = [f.strip() for f in target.replace(".", ",").split(",")]
        kept = [f for f in fields if f and f.lower() not in want]
        for f in fields:
            if f and f.lower() in want:
                dropped.append(f)
        if sep:
            out["initial_prompt"] = (head + (sep + " " + ", ".join(kept) + "." if kept else "")).strip()
        else:
            out["initial_prompt"] = ", ".join(kept)

    out["phrases"] = [p for p in (out.get("phrases") or []) if p.strip().lower() not in want]
    flagged = dict(out.get("flagged") or {})
    for t in terms:
        flagged.setdefault(t, {"reason": reason})
    if flagged:
        out["flagged"] = flagged
    return out, dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="a glossary .json, or a directory of them")
    ap.add_argument("--fix", action="store_true", help="write repairs (default: report only)")
    a = ap.parse_args(argv)

    paths = [a.target] if a.target.endswith(".json") else sorted(glob.glob(os.path.join(a.target, "*.json")))
    paths = [p for p in paths if not p.endswith((".lastrun.json", ".bak"))]
    bad = 0
    for p in paths:
        try:
            g = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"  SKIP {os.path.basename(p)}: {e}")
            continue
        rep = diagnose(g)
        if rep["ok"]:
            print(f"  ok   {os.path.basename(p)}")
            continue
        bad += 1
        print(f"  BAD  {os.path.basename(p)}")
        if rep["stranded"]:
            print(
                f"         {len(rep['stranded'])} verified but unreachable: "
                f"{', '.join(rep['stranded'][:8])}" + (" …" if len(rep["stranded"]) > 8 else "")
            )
        if rep["misshaped"]:
            print(
                f"         {len(rep['misshaped'])} multi-word in names: "
                f"{', '.join(rep['misshaped'][:5])}" + (" …" if len(rep["misshaped"]) > 5 else "")
            )
        if a.fix:
            fixed, _ = repair(g)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(fixed, f, indent=2, ensure_ascii=False)
                f.write("\n")  # POSIX line: prettier flags a glossary without it
            print("         repaired.")
    print(f"\n{bad} of {len(paths)} glossaries need repair." if bad else f"\nAll {len(paths)} glossaries hold the invariant.")
    return 1 if (bad and not a.fix) else 0


if __name__ == "__main__":
    raise SystemExit(main())
