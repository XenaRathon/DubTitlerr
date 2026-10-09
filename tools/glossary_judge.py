#!/usr/bin/env python3
"""Blind judging sets for the glossary-stage bake-off: `export-judge` and `import-judge`.

`export-judge` takes the items on which the chosen arms' forward picks DISAGREE and writes DIR/items.md (what a judge
reads) and DIR/key.json (which arms gave which answer; kept apart). items.md never names a model and never carries a
confidence value or the historical verdict: the judge sees the item and the distinct answers, in a shuffled order, and
decides which is correct. Identical picks from several arms are merged into one answer. Shuffles are deterministic per
seed (a hash of seed and item id, never Python's per-process hash).

By default only items that carry a gold label are exported (so the judge can be checked against known answers);
`--include-no-gold` adds the items without one, which are where a judge's verdict matters most. Arms that failed on an
item are ignored for it. Verify items: the term, the candidate titles (neutral per-item shuffle) and the answers (a title
or none). Acquire items: the two spellings with their transcript quotes and the answers "same entity" / "different
entities" / "(unsure)"; pairs without quotes are skipped.

`import-judge` reads lines of the form `N | best=A[,B] | worst=C | note`, maps the labels back to arms through the key and
writes one row per (item, arm). Malformed lines are counted and rejected; the last verdict for an item wins."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys

sys.path.insert(0, ".")
import tools.glossary_score as glossary_score  # noqa: E402

LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
OUTSIDE = "(an answer outside the list)"
VERDICT = re.compile(
    r"^\s*(?:item\s+)?(\d+)\s*\[([0-9a-f]{4})\]\s*\|\s*best\s*=\s*([A-Za-z](?:\s*,\s*[A-Za-z])*)\s*\|\s*worst\s*=\s*((?:[A-Za-z](?:\s*,\s*[A-Za-z])*)?)\s*(?:\|(.*))?$",
    re.I,
)

INSTRUCTIONS = """# Blind judging set

For every item below, decide which answer is correct, using only what the item shows. For a wiki-title item the
correct answer is the candidate that is the same named entity as the term, or `none` if no candidate is. For a
spelling pair it is whether the two spellings are one name mis-transcribed or two different names.

Every item header carries a short check token, like `Item 12 [k3f9]`. Copy the number AND the token exactly into
each reply line; a line whose token does not match its number is rejected, so a reply that skipped or shifted an item can
never be misattributed.

Reply with one line per item:

    N [token] | best=A[,B] | worst=C | short note

`best` may list several answers when they are equally right; `worst` may be empty. Answers are labelled per item, and
their order carries no meaning.
"""


def load_all_items(path):
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                it = json.loads(line)
            except ValueError:
                continue
            if isinstance(it, dict) and it.get("stage") in ("verify", "acquire") and isinstance(it.get("id"), str):
                items.append(it)
    return items


def item_token(seed, item_id):
    """The 4-hex check token printed in an item's header and required on its verdict line."""
    return hashlib.sha256(f"{seed}|{item_id}".encode()).hexdigest()[:4]


def _rng(seed, *parts):
    digest = hashlib.sha256("|".join([str(seed), *map(str, parts)]).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _acquire_answer(row):
    """'same entity' | 'different entities' | '(unsure)' from an acquire result row, or None for a failure."""
    if row.get("error") or not isinstance(row.get("parsed"), dict):
        return None
    p = row["parsed"]
    if "same_entity" in p:
        if str(p.get("confidence", "")).lower() == "none":
            return "(unsure)"
        return "same entity" if p["same_entity"] is True else "different entities"
    if "noul" in p:
        v = p["noul"].get("probability", p["noul"].get("score")) if isinstance(p["noul"], dict) else p["noul"]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return "same entity" if v > 0.5 else ("different entities" if v < 0.5 else "(unsure)")
    return None


def _verify_answer(row):
    pick = glossary_score.row_pick(row)
    return None if pick is None else (pick.title or "none")


def export_judge(items, rows, arms, stage, seed=0, sample=None, include_no_gold=False):
    """(markdown, key dict) for the items on which the arms' forward picks disagree."""
    eligible = []
    for it in items:
        if it["stage"] != stage:
            continue
        if stage == "verify":
            if it.get("no_call") or not it.get("candidates") or (it.get("gold") is None and not include_no_gold):
                continue
        elif not (isinstance(it.get("quotes"), dict) and it["quotes"].get("variant") and it["quotes"].get("canonical")):
            continue
        answers = {}  # normalised answer -> {"pick": shown, "arms": [...]}
        for arm in arms:
            row = rows.get((it["id"], arm, "fwd"))
            shown = None if row is None else (_verify_answer(row) if stage == "verify" else _acquire_answer(row))
            if shown is None:
                continue
            if stage == "verify" and shown != "none":
                listed = {c["title"].casefold() for c in it["candidates"]}
                if shown.casefold() not in listed:
                    # A free-form text answer: the judge must not be able to tell a text arm from a decision arm.
                    slot = answers.setdefault(OUTSIDE.casefold(), {"pick": OUTSIDE, "arms": [], "raw": []})
                    slot["arms"].append(arm)
                    slot["raw"].append(shown)
                    continue
            slot = answers.setdefault(shown.casefold(), {"pick": shown, "arms": []})
            slot["arms"].append(arm)
        if len(answers) >= 2:
            eligible.append((it, answers))
    if sample is not None and sample < len(eligible):
        keep = set(random.Random(seed).sample(range(len(eligible)), sample))
        eligible = [e for i, e in enumerate(eligible) if i in keep]
    md = [INSTRUCTIONS]
    key = {"version": 1, "stage": stage, "seed": seed, "arms": list(arms), "items": []}
    for n, (it, answers) in enumerate(eligible, 1):
        shuffled = list(answers.values())
        _rng(seed, it["id"], "answers").shuffle(shuffled)
        labelled = {}
        for i, a in enumerate(shuffled):
            labelled[LABELS[i]] = {
                "pick": a["pick"],
                "arms": sorted(a["arms"]),
                **({"raw": sorted(a["raw"])} if "raw" in a else {}),
            }
        token = item_token(seed, it["id"])
        md += [f"### Item {n} [{token}]", f"- show: {it['show']}"]
        if stage == "verify":
            titles = [c["title"] for c in it["candidates"]]
            _rng(seed, it["id"], "candidates").shuffle(titles)
            md += [f"- term (as heard in the dub): {it['term']}", "- wiki titles (candidates):"]
            md += [f"  {i}. {t}" for i, t in enumerate(titles, 1)]
        else:
            q = it["quotes"]
            md += [f'- first spelling: "{it["variant"]}"', *[f"  - {line}" for line in q["variant"]]]
            md += [f'- second spelling: "{it["canonical"]}"', *[f"  - {line}" for line in q["canonical"]]]
        md += [f"- answer {label}: {a['pick']}" for label, a in labelled.items()]
        md.append("")
        key["items"].append({"n": n, "token": token, "id": it["id"], "answers": labelled})
    return "\n".join(md) + "\n", key


def write_export(out_dir, markdown, key):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "items.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(markdown)
    with open(os.path.join(out_dir, "key.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, ensure_ascii=False, indent=1)


def _labels(text):
    return [x.strip().upper() for x in text.split(",") if x.strip()]


def import_judge(key, text):
    """(rows, stats) from a key and the judge's verdict text. The last verdict for an item wins."""
    by_n = {k["n"]: k for k in key["items"]}
    verdicts, malformed, duplicates = {}, 0, 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = VERDICT.match(line)
        if not m:
            malformed += 1
            continue
        n, token = int(m.group(1)), m.group(2).lower()
        best, worst, note = _labels(m.group(3)), _labels(m.group(4) or ""), (m.group(5) or "").strip()
        item = by_n.get(n)
        if item is None or item.get("token") != token:
            malformed += 1  # unknown number, or a token that does not belong to it: never misattribute
            continue
        if not all(x in item["answers"] for x in [*best, *worst]) or set(best) & set(worst):
            malformed += 1
            continue
        if n in verdicts:
            duplicates += 1
        verdicts[n] = (best, worst, note)
    rows = []
    for n, (best, worst, note) in sorted(verdicts.items()):
        item = by_n[n]
        for label, ans in item["answers"].items():
            for arm in ans["arms"]:
                rows.append(
                    {
                        "item": item["id"],
                        "n": n,
                        "stage": key["stage"],
                        "arm": arm,
                        "pick": ans["pick"],
                        "best": label in best,
                        "worst": label in worst,
                        "sole_best": best == [label] and ans["arms"] == [arm],
                        "note": note,
                    }
                )
    return rows, {"used": len(verdicts), "malformed": malformed, "duplicates": duplicates, "unjudged": len(by_n) - len(verdicts)}
