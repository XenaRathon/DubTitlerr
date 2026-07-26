"""Unit tests for tools/bakeoff.py's input loading.

The documented `--raw` path needs a `dump_whisper.py` capture that does not exist in this
repo, which made the bake-off unrunnable without re-transcribing an episode on the GPU.
`--conf` closes that: a production `<stem>.dubtitles.conf.json` already carries every
field `repair.is_target()` reads (text, avg_logprob, no_speech_prob, word_probs), and it
is the *same* file `repair.py` consumes in production -- so the bake-off judges the models
on exactly the lines the live pipeline would have sent them, with no GPU and no reflow
re-derivation. Ollama calls are not exercised here (no network in tests).
"""
import json

import pytest

import tools.bakeoff as bo


def _conf_row(text="Zolo drew his blade.", lp=-0.9, nsp=0.05, probs=None):
    row = {"start": 1.0, "end": 3.0, "avg_logprob": lp, "no_speech_prob": nsp, "text": text}
    if probs is not None:
        row["word_probs"] = probs
    return row


def _write(tmp_path, rows, name="ep.dubtitles.conf.json"):
    p = tmp_path / name
    p.write_text(json.dumps(rows))
    return str(p)


# --- conf.json loading --------------------------------------------------------

def test_load_cards_from_conf_returns_the_rows_as_cards(tmp_path):
    rows = [_conf_row("First line."), _conf_row("Second line.")]
    cards = bo.load_cards(None, _write(tmp_path, rows))
    assert [c["text"] for c in cards] == ["First line.", "Second line."]
    assert cards[0]["avg_logprob"] == -0.9 and cards[0]["no_speech_prob"] == 0.05


def test_load_cards_from_conf_preserves_word_probs(tmp_path):
    """word_probs is what repair.has_low_prob_word() reads -- dropping it would silently
    change which lines qualify as repair targets, so the bake-off would judge the models
    on a different set of lines than production sends them."""
    cards = bo.load_cards(None, _write(tmp_path, [_conf_row(probs=[0.95, 0.11])]))
    assert cards[0]["word_probs"] == [0.95, 0.11]


def test_load_cards_from_conf_tolerates_rows_without_word_probs(tmp_path):
    cards = bo.load_cards(None, _write(tmp_path, [_conf_row()]))
    assert "word_probs" not in cards[0]


def test_load_cards_from_conf_rejects_a_non_list(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(SystemExit):
        bo.load_cards(None, str(p))


def test_load_cards_from_conf_rejects_rows_missing_text(tmp_path):
    """A conf.json without `text` would produce empty prompts and a meaningless bake-off;
    fail loudly instead."""
    with pytest.raises(SystemExit):
        bo.load_cards(None, _write(tmp_path, [{"start": 0, "end": 1}]))


# --- input selection ----------------------------------------------------------

def test_load_cards_requires_one_input(tmp_path):
    with pytest.raises(SystemExit):
        bo.load_cards(None, None)


def test_load_cards_rejects_both_inputs(tmp_path):
    """--raw and --conf are different stages of the pipeline; silently preferring one
    would make the reported comparison ambiguous."""
    with pytest.raises(SystemExit):
        bo.load_cards("raw.json", _write(tmp_path, [_conf_row()]))


# --- the targets it selects are the ones production would send ----------------

def test_conf_cards_feed_the_real_is_target_predicate(tmp_path):
    """End-to-end on the selection logic: a clean high-confidence line is not a target,
    a low-logprob line is -- using repair.is_target itself, not a copy."""
    import glossary
    import repair
    gloss = glossary.load("")
    rows = [_conf_row("A perfectly clear line.", lp=-0.1, nsp=0.01),
            _conf_row("grbled nnsense here", lp=-1.4, nsp=0.02)]
    cards = bo.load_cards(None, _write(tmp_path, rows))
    targets = [c for c in cards if repair.is_target(c, gloss)]
    assert [c["text"] for c in targets] == ["grbled nnsense here"]


# --- llama.cpp candidates -----------------------------------------------------
#
# Some models can't be served by Ollama at all -- Nanbeige's GGUF needs a patched
# llama.cpp (`ollama create` fails with "failed to validate GGUF ... without
# compatibility patches"), which is why it runs in its own container. repair.py already
# supports a llama.cpp backend (REPAIR_BACKEND=llamacpp); the bake-off has to speak the
# same protocol or those models simply can't be evaluated.

def test_parse_llamacpp_specs_builds_a_name_to_url_map():
    m = bo.parse_llamacpp_specs(["nanbeige=http://host:8090/completion"])
    assert m == {"nanbeige": "http://host:8090/completion"}


def test_parse_llamacpp_specs_rejects_a_spec_without_a_url():
    with pytest.raises(SystemExit):
        bo.parse_llamacpp_specs(["nanbeige"])


def test_llamacpp_body_matches_production_repair(monkeypatch):
    """The bake-off must send what repair.llm_llamacpp sends, or it measures a different
    configuration than the one that would ship: no model selector (the server has one
    model loaded), n_predict/stop set, and the reply read from "content" not "response"."""
    seen = {}

    def fake_post(url, body, timeout=180):
        seen["url"], seen["body"] = url, body
        return {"content": ' "Zoro drew his blade." \n trailing junk'}

    monkeypatch.setattr(bo, "_post_json", fake_post)
    out, dt = bo.ask_llamacpp("http://host:8090/completion", "PROMPT")
    assert seen["url"] == "http://host:8090/completion"
    assert seen["body"]["prompt"] == "PROMPT"
    assert seen["body"]["temperature"] == 0
    assert "model" not in seen["body"]              # llama.cpp has no model selector
    assert seen["body"]["stop"] == ["\n"]
    assert out == "Zoro drew his blade."            # first line, unquoted, stripped
    assert dt >= 0


def test_ask_routes_llamacpp_models_away_from_ollama(monkeypatch):
    """A model named in --llamacpp must not be posted to the Ollama endpoint (it isn't
    there; it would come back as an <ERROR> row and read like a model failure)."""
    calls = []
    monkeypatch.setattr(bo, "ask_ollama", lambda url, m, p: (calls.append(("ollama", m)), ("o", 0.1))[1])
    monkeypatch.setattr(bo, "ask_llamacpp", lambda url, p: (calls.append(("llamacpp", url)), ("l", 0.2))[1])
    lc = {"nanbeige": "http://host:8090/completion"}
    assert bo.ask("http://ollama/api/generate", "qwen3.5:9b", "p", lc)[0] == "o"
    assert bo.ask("http://ollama/api/generate", "nanbeige", "p", lc)[0] == "l"
    assert calls == [("ollama", "qwen3.5:9b"), ("llamacpp", "http://host:8090/completion")]
