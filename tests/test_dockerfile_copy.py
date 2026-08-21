"""The container imports from /app, the test suite imports from the repo root, and
nothing in CI builds the image -- so a new top-level module can pass 987 tests and
ImportError on container start. qc.py did exactly that across 33 commits and four
review rounds. This closes the gap between the tested artifact and the shipped one."""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# modules gen_loop.sh / container_run.sh actually run inside the container
ENTRYPOINTS = ["generate.py", "repair.py", "mux.py", "mine_glossary.py",
               "glossary_verify.py", "glossary_acquire.py", "recreate_srt.py",
               "dub_signs_merge.py", "plex_refresh.py", "watch_queue.py"]


def _copied():
    with open(os.path.join(ROOT, "Dockerfile.builder")) as f:
        body = f.read().replace("\\\n", " ")
    names = set()
    for line in body.splitlines():
        if line.startswith("COPY "):
            names.update(re.findall(r"[\w./-]+\.py", line))
    return {os.path.basename(n) for n in names}


def _local_imports(path):
    tree = ast.parse(open(path).read())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return {m for m in out if os.path.exists(os.path.join(ROOT, m + ".py"))}


def test_every_module_an_entrypoint_imports_is_copied_into_the_image():
    copied = _copied()
    missing = {}
    for ep in ENTRYPOINTS:
        p = os.path.join(ROOT, ep)
        if not os.path.exists(p): continue
        for mod in _local_imports(p):
            if mod + ".py" not in copied:
                missing.setdefault(mod + ".py", []).append(ep)
    assert not missing, f"not COPY'd into the image but imported at runtime: {missing}"
