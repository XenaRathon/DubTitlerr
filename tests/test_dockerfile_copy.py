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
    # [S-8]: the review server is a third container loop, so everything it imports has to
    # be in the image. qc.py passed 987 tests and ImportError'd on container start for
    # exactly this reason.
    "review_server.py",
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


def test_every_entrypoint_is_itself_copied_into_the_image():
    """The gap the import check leaves. It walks what each entrypoint IMPORTS and never asks
    whether the entrypoint itself is in the COPY line -- so a new entrypoint could be added
    to ENTRYPOINTS, have all its dependencies satisfied, pass, and not exist in the image.
    Found by a mutation: removing review_server.py from the COPY line broke nothing.

    That is the qc.py failure exactly -- 987 tests green, ImportError on container start."""
    copied = _copied()
    absent = [ep for ep in ENTRYPOINTS if os.path.exists(os.path.join(ROOT, ep)) and ep not in copied]

    assert not absent, f"entrypoints missing from the image: {absent}"


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


def _container_run():
    return open(os.path.join(ROOT, "container_run.sh")).read()


def test_container_run_starts_the_review_server_as_a_background_loop():
    """[S-8]. The generate loop is the container's FOREGROUND process -- `exec` replaces the
    shell, so it IS the payload keeping the container alive. The review server must never
    occupy that position: launched in the exec slot it would end the GPU sweep, and a sweep
    killed mid-episode leaves a .dubtitles.fail poison marker that must be removed by hand
    before the episode can be retried."""
    body = _container_run()
    # Executable lines only. Matching the whole file would be satisfied by the word
    # appearing in a COMMENT -- the guard would pass while nothing started the server.
    code = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    launches = [i for i, ln in enumerate(code) if "review_server.py" in ln]
    execs = [i for i, ln in enumerate(code) if ln.startswith("exec ")]

    assert launches, "the server has to actually be started, not just mentioned"
    assert code[launches[0]].startswith("python3 "), "started as a process, not assigned to a variable"
    assert execs and code[execs[0]] == "exec sh /app/gen_loop.sh", "the generate loop keeps its foreground slot"
    assert launches[0] < execs[0], "started BEFORE the exec, or it never starts at all"
    assert not any(i > execs[0] for i in launches), "nothing after exec ever runs"


def test_the_review_server_loop_cannot_end_the_container():
    """A crashed or unstartable server -- port in use, unwritable token dir -- is a logged
    annoyance, not an outage. It is wrapped in a restart loop inside a background subshell,
    so a non-zero exit is retried rather than propagating."""
    body = _container_run()
    code = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    at = next(i for i, ln in enumerate(code) if "review_server.py" in ln)
    before, after = code[:at], code[at:]

    assert before[-1].startswith("while"), "the launch sits inside a restart loop, not a bare call"
    assert before[-2] == "(", "and that loop is inside a subshell"
    assert ") &" in after, "which is backgrounded, so a hang cannot block the exec below"
    assert any(ln.startswith("sleep") for ln in after[:4]), "with a delay, or a crash-loop spins the CPU"
    assert "||" in code[at], "a non-zero exit is logged and retried rather than propagating"


def test_container_run_is_valid_posix_shell():
    """A syntax error here does not fail a test, it fails the container at boot. `sh -n`
    parses without executing, which is the whole check: nothing in this file may run in the
    suite -- it launches GPU sweeps."""
    import subprocess

    r = subprocess.run(["sh", "-n", os.path.join(ROOT, "container_run.sh")], capture_output=True, text=True)

    assert r.returncode == 0, r.stderr
