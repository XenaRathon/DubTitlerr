"""The adjudication journals are sidecars: glossary_acquire writes one beside each (tracked) glossary, verify one under the cache
dir. They must be ignored by git, with their lock and compaction temp files, and nothing real may be hidden by the patterns."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="needs a git checkout")


def ignored(path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "glossaries/One Pace.acquire.journal.jsonl",
        "glossaries/One Pace.acquire.journal.jsonl.lock",
        "glossaries/One Pace.acquire.journal.jsonl.k3j2h1.tmp",
        "wiki_cache/One_Pace.verify.journal.jsonl",
        "wiki_cache/One_Pace.verify.journal.jsonl.lock",
    ],
)
def test_the_journal_sidecars_are_ignored(path):
    assert ignored(path), path


@pytest.mark.parametrize("path", ["glossaries/One Pace.json", "adjudication_journal.py", "tests/test_adjudication_journal.py"])
def test_real_files_are_not_hidden(path):
    assert not ignored(path), path
