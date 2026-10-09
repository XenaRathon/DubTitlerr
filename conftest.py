"""Put the repo root and tools/ on sys.path so tests can `import reflow`, `import
ordering`, `import sns_extract`, etc. regardless of pytest's import mode / invocation
directory."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_word_list_cache(monkeypatch):
    """The common-word guard is on by default, so many tests reach glossary.ordinary_words(), which caches the list and whether
    the configured file was readable. Start every test with that cache empty so one test's status never leaks into the next."""
    import glossary

    monkeypatch.setattr(glossary, "_ORDINARY", None)
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", None)
