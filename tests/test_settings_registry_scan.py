"""[S-1] Every environment variable the pipeline reads is in the settings registry, first wave or not.

The scan reads the code, not a list: it walks the top-level modules and tools/ (Python: os.environ.get / os.getenv /
os.environ[...] and the small env helpers; shell: ${VAR} and $VAR), so a new read that nobody registered fails here.
"""

import ast
import os
import re

import settings_registry as reg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
SKIP_DIRS = {
    "tests",
    "web",
    "node_modules",
    "skills",
    "scripts",
    "specs",
    "deploy",
    "docs",
    "Docs",
    "glossaries",
    "data",
    "__pycache__",
}
CALLS = {"get", "getenv", "env_int", "env_float", "_env_num", "_fraction", "_count", "pop", "setdefault"}
# Names the scan sees that are not settings: shell locals, and the per-show inputs the loops set for each child.
NON_SETTINGS = {
    "DT_CONTAINER_BOOT_ID": "exported by container_run.sh at start, read by common.boot_id()",
    "ACQ_FLAGS": "gen_loop.sh local",
    "ANIME": "gen_loop.sh local",
    "APP": "merge_pass.sh and publish tool local",
    "DURATION": "mux.py local constant",
    "GLOSS": "gen_loop.sh local",
    "GLOSS_DIR": "gen_loop.sh local",
    "ORDER": "gen_loop.sh local",
    "PATTERN": "merge_pass.sh local",
    "PUSH": "sync_wiki.sh local",
    "ROOT": "merge_pass.sh local",
    "SRC": "sync_wiki.sh local",
    "UTC": "review_requests.py time zone name",
    "SHOW_NAME": "set per show by the loops",
    "GLOSSARY_FILE": "set per show by the loops",
    "GENERATE_ONLY_RE": "set per request by the loops",
}


def _walk():
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".") and "venv" not in d]
        yield directory, files


def _python_reads(path):
    out = set()
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in CALLS:
                for arg in node.args[:2]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and NAME.match(arg.value):
                        out.add(arg.value)
                        break
        elif isinstance(node, ast.Subscript):
            target = node.value
            if isinstance(target, ast.Attribute) and target.attr == "environ":
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    out.add(node.slice.value)
    return out


def _shell_reads(path):
    text = open(path, encoding="utf-8").read()
    return set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)[:}+=\-]", text)) | set(re.findall(r"\$([A-Z][A-Z0-9_]{2,})\b", text))


def scan():
    reads = set()
    for directory, files in _walk():
        for name in files:
            path = os.path.join(directory, name)
            if name.endswith(".py"):
                reads |= _python_reads(path)
            elif name.endswith(".sh") and (directory == ROOT or os.path.basename(directory) in ("shell", "tools")):
                reads |= _shell_reads(path)
    return reads


def test_every_env_read_is_in_the_registry():
    missing = sorted(n for n in scan() if n not in reg.REGISTRY and n not in NON_SETTINGS)
    assert not missing, f"read by the pipeline but missing from settings_registry.REGISTRY: {missing}"


def test_the_scan_finds_reads_in_python_and_shell():
    reads = scan()
    assert {"WHISPER_BEAM_SIZE", "MINE_MIN_COUNT", "ACQUIRE_TIMEOUT", "REVIEW_PORT", "MERGE_INTERVAL"} <= reads


def test_non_settings_are_not_also_registry_keys():
    assert not set(NON_SETTINGS) & set(reg.REGISTRY)
