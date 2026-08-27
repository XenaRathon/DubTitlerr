"""Every writer of glossaries/*.json must end the file with a newline.

json.dump writes no trailing newline, so prettier reports a freshly written
glossary as unformatted and the commit gate blocks -- at the moment a glossary
legitimately changes, which is the worst time to find out. Each of the four
writers now adds the newline explicitly; these pin that down.

Only writers that can be called without standing up the pipeline are exercised
directly. The rest are covered by the source check and by the committed-state
check, which is the condition the gate actually reads.
"""

import ast
import json
import pathlib

import glossary_acquire

ROOT = pathlib.Path(__file__).resolve().parent.parent

# path -> name of the function whose json.dump must be followed by a newline write
WRITERS = {
    "glossary_acquire.py": "_write_json",
    "glossary_verify.py": "verify",
    "mine_glossary.py": "main",
    "tools/glossary_doctor.py": "main",
}


def test_acquire_write_json_ends_with_newline(tmp_path):
    """The one glossary writer callable in isolation -- exercised for real."""
    p = tmp_path / "Show.json"
    glossary_acquire._write_json(str(p), {"names": ["Luffy"], "phrases": {}})
    text = p.read_text(encoding="utf-8")
    assert text.endswith("\n"), "_write_json left no trailing newline"
    assert json.loads(text)["names"] == ["Luffy"], "the newline broke the JSON"


def test_every_committed_glossary_ends_with_newline():
    """The condition the commit gate reads: no committed glossary may lack one."""
    missing = [p.name for p in sorted((ROOT / "glossaries").glob("*.json")) if not p.read_text(encoding="utf-8").endswith("\n")]
    assert missing == [], f"glossaries without a trailing newline: {missing}"


def test_no_glossary_writer_dumps_without_a_newline():
    """Catches a fifth writer being added, or one of the four losing its newline.

    Walks each writer's AST for a `json.dump(...)` and requires a `.write("\\n")`
    on the same file handle in the same block.
    """
    offenders = []
    for rel, fname in WRITERS.items():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        scopes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fname]
        assert scopes, f"{rel}: no function named {fname!r} -- the writer was renamed"
        for node in ast.walk(scopes[0]):
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            fn = node.value.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "dump" and getattr(fn.value, "id", "") == "json"):
                continue
            if len(node.value.args) < 2:
                continue
            handle = node.value.args[1]
            if not isinstance(handle, ast.Name):  # json.dump(x, open(...)) -- no handle to follow
                offenders.append(f"{rel}:{node.lineno} dumps straight into an unnamed handle")
                continue
            siblings = _block_containing(scopes[0], node)
            if not any(_is_newline_write(s, handle.id) for s in siblings):
                offenders.append(f"{rel}:{node.lineno} json.dump with no f.write('\\n') after it")
    assert offenders == [], "glossary writers missing a trailing newline:\n  " + "\n  ".join(offenders)


def _block_containing(tree, target):
    for parent in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(parent, field, None)
            if isinstance(block, list) and target in block:
                return block
    return []


def _is_newline_write(stmt, handle_name):
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    fn = stmt.value.func
    return (
        isinstance(fn, ast.Attribute)
        and fn.attr == "write"
        and getattr(fn.value, "id", "") == handle_name
        and stmt.value.args
        and isinstance(stmt.value.args[0], ast.Constant)
        and stmt.value.args[0].value == "\n"
    )
