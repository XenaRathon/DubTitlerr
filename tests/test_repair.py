"""Unit tests for repair.py pure helpers (C1). The LLM call itself is integration."""
import json

import glossary
import repair


def gl(names=None, hard_fixes=None):
    return glossary.load_dict({"names": names or [], "hard_fixes": hard_fixes or {}})


# --- target selection --------------------------------------------------------

def test_is_target_picks_mid_confidence_speech():
    g = gl()
    assert repair.is_target({"avg_logprob": -0.6, "no_speech_prob": 0.1, "text": "hi"}, g)


def test_is_target_picks_name_suspect_even_if_confident():
    g = gl(names=["Luffy"])
    c = {"avg_logprob": -0.05, "no_speech_prob": 0.1, "text": "I saw Krieg there"}
    assert repair.is_target(c, g)


def test_is_target_skips_clean_confident_line():
    g = gl(names=["Luffy"])
    c = {"avg_logprob": -0.05, "no_speech_prob": 0.1, "text": "Luffy hit the pirates"}
    assert not repair.is_target(c, g)


def test_is_target_skips_music_silence():
    g = gl()
    assert not repair.is_target({"avg_logprob": -2.0, "no_speech_prob": 0.9, "text": "la la"}, g)


def test_is_target_fencepost():
    # a card at exactly NSP_MAX (0.5) is speech, not silence — was excluded by the old >= check
    g = gl()
    c = {"avg_logprob": -0.6, "no_speech_prob": 0.5, "text": "hi"}
    assert repair.is_target(c, g)


# --- prompt building ---------------------------------------------------------

def test_build_prompt_includes_glossary_names():
    g = gl(names=["Spandam"], hard_fixes={"eddie's lobby": "Enies Lobby"})
    p = repair.build_prompt("the cheef spondum", "", g)
    assert "Spandam" in p and "Enies Lobby" in p
    assert "the cheef spondum" in p


def test_build_prompt_uses_reference_when_present_else_glossary_only():
    g = gl(names=["Spandam"])
    with_ref = repair.build_prompt("asr line", "the official sub", g)
    no_ref = repair.build_prompt("asr line", "", g)
    assert "the official sub" in with_ref
    assert "the official sub" not in no_ref          # graceful glossary-only fallback


def test_build_prompt_no_prev_next_matches_old_prompt():
    g = gl(names=["Spandam"])
    explicit_empty = repair.build_prompt("asr line", "the official sub", g, "", "")
    default_call = repair.build_prompt("asr line", "the official sub", g)
    assert explicit_empty == default_call            # backward-compat: defaults == old signature


def test_build_prompt_includes_context():
    g = gl()
    p = repair.build_prompt("asr line", "", g, prev_text="earlier line", next_text="later line")
    assert '"earlier line"' in p
    assert '"later line"' in p
    # context lines absent when not provided
    no_ctx = repair.build_prompt("asr line", "", g)
    assert "earlier line" not in no_ctx and "later line" not in no_ctx


# --- per-episode glossary resolution ----------------------------------------

def test_glossary_for_finds_show_glossary_by_walking_up(tmp_path):
    gdir = tmp_path / "glossaries"
    gdir.mkdir()
    (gdir / "One Pace.json").write_text(json.dumps({"names": ["Luffy"], "show": "One Pace"}))
    ep = tmp_path / "Anime Library" / "One Pace" / "Season 19" / "ep.mkv"
    ep.parent.mkdir(parents=True)
    ep.write_text("x")
    g = repair.glossary_for(str(ep), str(gdir))
    assert g["names"] == ["Luffy"]


def test_glossary_for_missing_is_noop(tmp_path):
    g = repair.glossary_for(str(tmp_path / "Show" / "ep.mkv"), str(tmp_path / "glossaries"))
    assert g["names"] == [] and g["token_fixes"] == {}
