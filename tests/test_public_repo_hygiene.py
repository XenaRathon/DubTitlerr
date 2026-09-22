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


def test_the_wiki_discloses_when_repair_unanchored_was_deployed():
    """The wiki used to say 'do not use REPAIR_UNANCHORED' / 'unset -- closed' while the
    reference install had quietly turned it on months earlier (common.py's v10 note,
    2026-09-06) -- exactly the silent-drift failure this suite exists to catch, just in
    prose instead of code."""
    for path in _tracked("docs/wiki/How-To-Guides.md", "docs/wiki/Reference.md"):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "2026-09-06" in text, f"{path} does not disclose the REPAIR_UNANCHORED deploy date"


def test_repair_backend_secondary_is_retired_not_referenced_outside_history():
    """REPAIR_BACKEND_SECONDARY was proposed in IMPROVEMENTS.md, never implemented,
    and retired 2026-09-22 (REVIEW.md's outstanding-issues list, `.procoder/specs/
    v0-2-0-hardening.md`'s S-13). A name that keeps reappearing in ACTIVE docs after
    retirement is exactly the kind of drift IMPROVEMENTS.md and REVIEW.md used to
    carry themselves."""
    allowed_prefixes = (
        "docs/Adversarial Reviews/",
        "docs/superpowers/plans/2026-08-22-observability-and-dead-path-cleanup.md",
        ".procoder/specs/v0-2-0-hardening.md",
        ".procoder/plans/v0-2-0-hardening.md",
        ".procoder/backlog/",
        "CHANGELOG.md",
    )
    offenders = []
    for path in _tracked("*.md"):
        if any(path.startswith(p) for p in allowed_prefixes):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            if "REPAIR_BACKEND_SECONDARY" in f.read():
                offenders.append(path)
    assert not offenders, f"REPAIR_BACKEND_SECONDARY referenced outside history: {offenders}"
