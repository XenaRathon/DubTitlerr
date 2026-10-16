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


@pytest.fixture(autouse=True)
def _isolated_wiki_cache(monkeypatch, tmp_path):
    """glossary_verify keeps its adjudication journal and wiki title cache under CACHE_DIR; no test may touch a real one."""
    import glossary_verify

    monkeypatch.setattr(glossary_verify, "CACHE_DIR", str(tmp_path / "wiki_cache"))


@pytest.fixture(autouse=True)
def _accounts_are_installed_by_default(request, monkeypatch, tmp_path_factory):
    """Suites that predate accounts assert 401 for a missing token, which is the behaviour of an instance that has accounts.
    First run (409 setup required) is exercised only by files marked real_accounts, which get the real functions."""
    if request.node.get_closest_marker("real_accounts"):
        return
    import review_auth

    monkeypatch.setattr(review_auth, "setup_required", lambda: False)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path_factory.mktemp("auth_config")))  # even when the shell or CI already set one
