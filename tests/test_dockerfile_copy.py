"""The container imports from /app, the test suite imports from the repo root, and
nothing in CI builds the image -- so a new top-level module can pass 987 tests and
ImportError on container start. qc.py did exactly that across 33 commits and four
review rounds. This closes the gap between the tested artifact and the shipped one."""

import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# modules gen_loop.sh / container_run.sh actually run inside the container
ENTRYPOINTS = [
    "generate.py",
    "repair.py",
    "mux.py",
    "mine_glossary.py",
    "glossary_verify.py",
    "glossary_acquire.py",
    "recreate_srt.py",
    "dub_signs_merge.py",
    "plex_refresh.py",
    "watch_queue.py",
]


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
        if not os.path.exists(p):
            continue
        for mod in _local_imports(p):
            if mod + ".py" not in copied:
                missing.setdefault(mod + ".py", []).append(ep)
    assert not missing, f"not COPY'd into the image but imported at runtime: {missing}"


def _dockerfile_arg_default(name):
    """The ARG default Dockerfile.builder bakes for ``name``."""
    with open(os.path.join(ROOT, "Dockerfile.builder")) as f:
        body = f.read().replace("\\\n", " ")
    m = re.search(rf"^ARG\s+{re.escape(name)}=(\S+)\s*$", body, re.M)
    return m.group(1) if m else None


def _module_env_default(module, var, env_key):
    """The fallback ``module`` passes to os.environ.get(env_key) when assigning ``var``.

    Parsed, never imported: generate.py loads faster_whisper at module level."""
    tree = ast.parse(open(os.path.join(ROOT, module)).read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == var for t in node.targets):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and len(call.args) == 2):
            continue
        key = call.args[0]
        if isinstance(key, ast.Constant) and key.value == env_key:
            fallback = call.args[1]
            if isinstance(fallback, ast.Constant):
                return fallback.value
    return None


def test_the_baked_model_and_generates_fallback_cannot_drift():
    """Dockerfile.builder bakes the model its ARG names and exports the same value as the
    container ENV; generate.py's fallback decides what a bare checkout loads. When the two
    disagree, a plain `docker build` produces an image whose baked model is not the one
    generate.py asks for -- and faster-whisper does not error on that, it silently
    re-downloads the missing model into /models on every container start (Dockerfile.builder
    says so in its own comment). Nothing else in the suite compares these two files."""
    baked = _dockerfile_arg_default("WHISPER_MODEL")
    fallback = _module_env_default("generate.py", "MODEL", "WHISPER_MODEL")
    assert baked, "Dockerfile.builder has no ARG WHISPER_MODEL=<default>"
    assert fallback, "generate.py does not default MODEL from WHISPER_MODEL"
    assert baked == fallback, f"baked model {baked!r} != generate.py fallback {fallback!r}"
