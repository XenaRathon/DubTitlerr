"""Checks that hold for a repository about to be published.

The tree is going public. Nothing here is a security boundary -- RFC1918 addresses are not
routable from outside -- but a default pointing at somebody's LAN is a default that cannot
work for anyone who installs this, and it publishes the maintainer's network layout for no
benefit. Decision 15 of the public-beta spec: scrub the tree, leave the history alone.
"""

import re
import subprocess
from pathlib import Path

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


def _top_level_field(text, field):
    """Return (line, following_body_lines) for a key declared at column 0.

    The indentation is what makes it the workflow-level field: a `concurrency:` inside a job,
    or a line inside a `run:` script, is not this field. The body therefore stops at the
    first following line that is neither blank nor indented."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"{field}:"):
            end = index + 1
            while end < len(lines) and (not lines[end].strip() or lines[end].startswith((" ", "\t"))):
                end += 1
            return line, lines[index + 1 : end]
    raise AssertionError(f"missing top-level {field!r} field")


def _block_mapping(lines, field, indent):
    """Parse a block mapping whose key starts at `indent` spaces.

    Both explicit and flow (`{contents: read}`) forms are supported. A block with a
    non-empty value is returned under `_scalar` so callers can distinguish a shorthand
    such as `read-all` from an absent declaration."""
    prefix = " " * indent + field + ":"
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        rest = line[len(prefix) :].split("#", 1)[0].strip()
        if rest.startswith("{") and rest.endswith("}"):
            return index, {
                key.strip().strip("\"'"): value.strip().strip("\"'")
                for key, _, value in (item.partition(":") for item in rest[1:-1].split(","))
                if key.strip() and value.strip()
            }
        if rest:
            return index, {"_scalar": rest.strip("\"'")}
        mapping = {}
        for child in lines[index + 1 :]:
            if not child.strip():
                continue
            if not child.startswith(" " * (indent + 2)):
                break
            key, separator, value = child.strip().partition(":")
            value = value.split("#", 1)[0].strip().strip("\"'")
            if separator and value:
                mapping[key.strip()] = value
        return index, mapping
    return None, None


def _scope_value(mapping, scope):
    """The value a permissions mapping grants `scope`, or None when it grants nothing."""
    if mapping is None:
        return None
    shorthand = mapping.get("_scalar")
    if shorthand == "read-all":
        return "read"
    if shorthand == "write-all":
        return "write"
    if shorthand == "none":
        return "none"
    return mapping.get(scope)


def _workflow_jobs(text):
    """Return {job_name: its body lines} for the top-level `jobs:` mapping."""
    _, body = _top_level_field(text, "jobs")
    starts = [
        (line.split(":", 1)[0].strip(), index)
        for index, line in enumerate(body)
        if re.match(r"^  [A-Za-z0-9_-]+:\s*(?:#.*)?$", line)
    ]
    jobs = {}
    for position, (name, start) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else len(body)
        jobs[name] = body[start:end]
    return jobs


def _job_field(job, field):
    """Return (index, value) for a `field:` on the job itself -- 4 spaces, never deeper."""
    prefix = f"    {field}:"
    for index, line in enumerate(job):
        if line.startswith(prefix):
            return index, line[len(prefix) :].split("#", 1)[0].strip()
    return None, ""


def _job_needs(job):
    index, value = _job_field(job, "needs")
    if value:
        flow = value[1:-1] if value.startswith("[") and value.endswith("]") else value
        return {item.strip().strip("\"'") for item in flow.split(",") if item.strip()}
    if index is None:
        return set()
    needs = set()
    for line in job[index + 1 :]:
        if not line.strip():
            continue
        if not line.startswith("      - "):
            break
        needs.add(line.removeprefix("      - ").strip().strip("\"'"))
    return needs


def test_release_image_job_is_gated_by_reusable_ci():
    """The release image may publish only after the same reusable CI contract passes."""
    root = Path(__file__).resolve().parents[1]

    ci_text = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    on_line, on_body = _top_level_field(ci_text, "on")
    inline_triggers = on_line.split(":", 1)[1].split("#", 1)[0].strip()
    if inline_triggers:
        assert inline_triggers.startswith("[") and inline_triggers.endswith("]"), (
            "ci.yml on must be a flow sequence or block mapping"
        )
        triggers = {item.strip().strip("\"'") for item in inline_triggers[1:-1].split(",") if item.strip()}
    else:
        triggers = {line.split(":", 1)[0].strip() for line in on_body if re.match(r"^  [A-Za-z0-9_-]+:", line)}
    assert {"push", "pull_request", "workflow_call"} <= triggers, (
        f"ci.yml must declare workflow_call alongside push and pull_request; found {sorted(triggers)}"
    )

    release_text = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    release_jobs = _workflow_jobs(release_text)
    ci_callers = {name for name, job in release_jobs.items() if _job_field(job, "uses")[1] == "./.github/workflows/ci.yml"}
    assert ci_callers, "release.yml must define a reusable CI caller job with uses: ./.github/workflows/ci.yml"
    assert "image" in release_jobs, "release.yml must define the image job"
    image_needs = _job_needs(release_jobs["image"])
    assert ci_callers <= image_needs, (
        f"release image job must need reusable CI caller(s) {sorted(ci_callers)}; found {sorted(image_needs)}"
    )


def test_reusable_ci_concurrency_isolated_from_direct_trigger():
    """A tag push runs ci.yml twice: once directly on `push`, once through release.yml.

    A group built only from the shared ref makes those two runs mutually cancel, so a
    release's own CI gate can disappear under the direct tag-triggered run (or the reverse).
    The group therefore has to name the trigger/caller as well as the ref."""
    root = Path(__file__).resolve().parents[1]
    ci_text = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    _, concurrency_body = _top_level_field(ci_text, "concurrency")
    _, group = _block_mapping(concurrency_body, "group", 2)
    assert group is not None, "ci.yml concurrency must declare a group"
    group_value = group.get("_scalar", "")
    assert "${{ github.workflow }}" in group_value, (
        "ci.yml concurrency group must use ${{ github.workflow }} to identify the caller; "
        f"found {group_value!r}; github.event_name is 'push' for both direct and reusable runs"
    )


def test_reusable_ci_uses_least_privilege_permissions():
    """The called workflow gets the release caller's broad `packages: write` token.

    A called workflow cannot elevate what the caller grants, so ci.yml must pin its own
    token to `contents: read` and must not inherit package publishing. A job-level
    `permissions:` block replaces the workflow-level one, so any override is checked too."""
    root = Path(__file__).resolve().parents[1]
    ci_text = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    _, workflow_permissions = _block_mapping(ci_text.splitlines(), "permissions", 0)
    ci_jobs = _workflow_jobs(ci_text)
    assert workflow_permissions is not None or any(
        _block_mapping(job, "permissions", 4)[1] is not None for job in ci_jobs.values()
    ), (
        "ci.yml must declare least-privilege permissions: workflow-level, or on every job "
        "when the reusable call inherits the release caller's token"
    )

    offenders = {}
    for name, job in ci_jobs.items():
        _, job_permissions = _block_mapping(job, "permissions", 4)
        effective = workflow_permissions if job_permissions is None else job_permissions
        contents = _scope_value(effective, "contents")
        packages = _scope_value(effective, "packages")
        if contents != "read" or packages == "write":
            offenders[name] = {
                "contents": contents,
                "packages": packages,
                "source": "job" if job_permissions is not None else "workflow",
            }
    assert not offenders, (
        f"every ci.yml job must run with contents: read and without packages: write; offending jobs: {offenders}"
    )
