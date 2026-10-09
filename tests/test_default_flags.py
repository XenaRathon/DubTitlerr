"""Phase 27: the defaults the maintainer decided on (2026-10-09). 'Unset' now means the new default; the old value restores the
legacy behaviour. One place per flag, read per call."""

import glossary
import glossary_verify as gv
import repair
import unresolved


def test_whole_word_guard_is_on_unless_set_to_0(monkeypatch):
    monkeypatch.delenv("VERIFY_WRITE_WHOLE_WORD", raising=False)
    assert gv.auto_writes("Usop", "Usopp") is False  # a respelling is flagged, not written
    assert gv.auto_writes("Luffy", "Monkey D. Luffy") is True
    monkeypatch.setenv("VERIFY_WRITE_WHOLE_WORD", "0")
    assert gv.auto_writes("Usop", "Usopp") is True  # legacy


def test_common_word_guard_is_on_unless_set_to_0(monkeypatch):
    monkeypatch.setattr(glossary, "is_ordinary_word", lambda t: t.lower() == "castle")
    for var in ("VERIFY_COMMON_WORD_ARC_RESCUE", "VERIFY_ARC_GATE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("VERIFY_SKIP_COMMON_WORDS", raising=False)
    assert gv.skip_common_words() is True
    assert gv.write_decision("castle", "Castle Rock", None) == "common-word"
    monkeypatch.setenv("VERIFY_SKIP_COMMON_WORDS", "0")
    assert gv.skip_common_words() is False
    assert gv.write_decision("castle", "Castle Rock", None) == "write"  # legacy


def test_no_match_terms_are_not_queued_unless_set_to_1(monkeypatch):
    monkeypatch.delenv("VERIFY_QUEUE_NO_MATCH", raising=False)
    assert gv.queue_no_match() is False
    monkeypatch.setenv("VERIFY_QUEUE_NO_MATCH", "1")
    assert gv.queue_no_match() is True  # legacy


def test_blocked_expansions_still_queue_by_default(monkeypatch):
    """UNCHANGED by phase 27: guard against flipping it with the rest."""
    monkeypatch.delenv("VERIFY_QUEUE_BLOCKED_EXPANSIONS", raising=False)
    assert gv.queue_blocked_expansions() is True


def test_auto_dismiss_defaults_to_6_and_off_disables_it(monkeypatch):
    monkeypatch.delenv("REPAIR_AUTO_DISMISS_WORDS", raising=False)
    assert unresolved.auto_dismiss_threshold() == 6
    for raw, expect in (("", 6), ("  ", 6), ("off", None), ("OFF", None), ("0", 0), ("3", 3)):
        monkeypatch.setenv("REPAIR_AUTO_DISMISS_WORDS", raw)
        assert unresolved.auto_dismiss_threshold() == expect, raw


def test_transport_retries_default_to_2_and_0_restores_one_attempt(monkeypatch):
    monkeypatch.delenv("REPAIR_TRANSPORT_RETRIES", raising=False)
    assert repair._transport_retries() == 2
    monkeypatch.setenv("REPAIR_TRANSPORT_RETRIES", "0")
    assert repair._transport_retries() == 0  # legacy


def test_name_parts_check_is_on_unless_set_to_0(monkeypatch):
    monkeypatch.delenv("REPAIR_KEEP_NAME_PARTS", raising=False)
    assert repair.KEEP_NAME_PARTS_DEFAULT == "1"
    assert repair._keep_name_parts() is True
    monkeypatch.setenv("REPAIR_KEEP_NAME_PARTS", "0")
    assert repair._keep_name_parts() is False  # legacy


def test_the_flags_that_stay_off_are_still_off(monkeypatch):
    for var in ("REPAIR_ACCEPT_PUNCT_CASE_ONLY", "REPAIR_GUARD_TERMINAL_PUNCT", "VERIFY_ARC_GATE"):
        monkeypatch.delenv(var, raising=False)
    assert repair._accept_punct_case_only() is False
    assert repair._guard_terminal_punct() is False


def test_the_default_on_common_word_guard_survives_a_missing_word_list_and_says_so_once(monkeypatch, capsys, tmp_path):
    """An image without wamerican: verify must not break, the guard runs on the bundled list, and the line is printed once."""
    monkeypatch.delenv("VERIFY_SKIP_COMMON_WORDS", raising=False)
    monkeypatch.setattr(glossary, "WORDLIST_PATH", str(tmp_path / "no-such-list"))
    monkeypatch.setattr(glossary, "_ORDINARY", None)
    monkeypatch.setattr(glossary, "_ORDINARY_STATUS", None)
    g = {"show": "S", "names": ["Nami", "Zoro"], "phrases": [], "hard_fixes": {}}
    out = gv.apply_results(
        g, {"Nami": {"canonical": "Nami Two", "confidence": "high"}, "Zoro": {"canonical": "Roronoa Zoro", "confidence": "high"}}
    )
    assert "Roronoa Zoro" in out["phrases"]
    assert gv._common_word_block(0) == {"blocked": 0, "wordlist": "missing"}
    assert capsys.readouterr().out.count("unreadable") == 1
