"""Checks that hold for a repository about to be published.

The tree is going public. Nothing here is a security boundary -- RFC1918 addresses are not
routable from outside -- but a default pointing at somebody's LAN is a default that cannot
work for anyone who installs this, and it publishes the maintainer's network layout for no
benefit. Decision 15 of the public-beta spec: scrub the tree, leave the history alone.
"""

import re
import subprocess

# 10/8, 172.16/12 and 192.168/16. Loopback is deliberately NOT here: 127.0.0.1 is a correct
# default for a service the user runs beside the pipeline, and is the fix for the rest.
PRIVATE = re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")


def _tracked(*globs):
    out = subprocess.run(["git", "ls-files", *globs], capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines() if p]


def test_no_shipped_source_file_defaults_to_a_private_address():
    """Breaks the moment a LAN address is committed into code that runs on someone else's
    machine. It has happened three times -- repair.py's REPAIR_LLAMACPP_URL pointed at a host
    that was DEAD, so the documented default could not have worked for anybody, including the
    maintainer.

    Scoped to code and shell, not docs: `docs/` records measurements taken on real hosts and
    naming them there is what makes those records reproducible."""
    offenders = {}
    for path in _tracked("*.py", "*.sh", "Dockerfile*"):
        if path.startswith("tests/"):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if PRIVATE.search(line):
                    offenders.setdefault(path, []).append(n)
    assert not offenders, f"private addresses in shipped source: {offenders}"


# A .local name is mDNS: it resolves only on the network that publishes it, so as a shipped
# default it is the same defect as a LAN address wearing a friendlier face.
MDNS = re.compile(r"https?://[A-Za-z0-9._-]+\.local\b")


def test_no_shipped_source_file_defaults_to_an_mdns_hostname():
    """Breaks on the OLLAMA_URL shape: `http://ollama.local:11434/api/generate` was the
    default for every install, and `ollama.local` resolves for nobody who has not published
    that name themselves -- so the out-of-the-box repair backend was unreachable and the
    failure surfaced as `llm_empty`, which reads as "the model had nothing to say"."""
    offenders = {}
    for path in _tracked("*.py", "*.sh", "Dockerfile*"):
        if path.startswith("tests/"):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if MDNS.search(line):
                    offenders.setdefault(path, []).append(n)
    assert not offenders, f"mDNS hostnames in shipped source: {offenders}"
