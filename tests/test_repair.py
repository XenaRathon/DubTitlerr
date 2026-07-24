"""Unit tests for repair.py pure helpers (C1) plus V2 A1 backend-dispatch coverage. The
llama.cpp box and Ollama are NOT reachable from this environment -- every HTTP-touching
test here mocks urllib.request.urlopen or the llm_* functions; no live LLM call is ever
made. Live llama.cpp integration is PENDING manual verification on real hardware."""
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


# --- A1: llm() backend dispatch ----------------------------------------------

def test_llm_dispatch_default_is_ollama(monkeypatch):
    assert repair.REPAIR_BACKEND == "ollama"           # default, backward-compat
    calls = []
    monkeypatch.setattr(repair, "llm_ollama", lambda prompt, model=None: calls.append(("ollama", prompt, model)) or "ok")
    monkeypatch.setattr(repair, "llm_llamacpp", lambda prompt, model: calls.append(("llamacpp", prompt, model)) or "bad")
    assert repair.llm("hi") == "ok"
    assert calls == [("ollama", "hi", None)]


def test_llm_dispatch_routes_to_llamacpp_when_configured(monkeypatch):
    calls = []
    monkeypatch.setattr(repair, "REPAIR_BACKEND", "llamacpp")
    monkeypatch.setattr(repair, "llm_ollama", lambda prompt, model=None: calls.append(("ollama", prompt, model)) or "bad")
    monkeypatch.setattr(repair, "llm_llamacpp", lambda prompt, model: calls.append(("llamacpp", prompt, model)) or "ok")
    assert repair.llm("hi") == "ok"
    assert calls == [("llamacpp", "hi", repair.MODEL)]   # model=None -> defaults to REPAIR_MODEL


def test_llm_dispatch_passes_explicit_model_through(monkeypatch):
    calls = []
    monkeypatch.setattr(repair, "REPAIR_BACKEND", "llamacpp")
    monkeypatch.setattr(repair, "llm_llamacpp", lambda prompt, model: calls.append(model) or "ok")
    repair.llm("hi", model="secondary-model")
    assert calls == ["secondary-model"]


class _FakeHTTPResponse:
    """Minimal context-manager stand-in for urllib.request.urlopen()'s return value."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_llm_ollama_request_shape_and_response_parsing(monkeypatch):
    """Byte-for-byte the pre-A1 request body + response parsing (first line, unquoted)."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        captured["timeout"] = timeout
        return _FakeHTTPResponse({"response": '  "fixed line"  \nignored second line'})
    monkeypatch.setattr(repair.urllib.request, "urlopen", fake_urlopen)
    out = repair.llm_ollama("the prompt")
    assert captured["url"] == repair.OLLAMA
    assert captured["body"] == {"model": repair.MODEL, "prompt": "the prompt", "stream": False,
                                 "think": False, "options": {"temperature": 0}}
    assert out == "fixed line"


def test_llm_ollama_explicit_model_overrides_default(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return _FakeHTTPResponse({"response": "x"})
    monkeypatch.setattr(repair.urllib.request, "urlopen", fake_urlopen)
    repair.llm_ollama("p", model="other-model")
    assert captured["body"]["model"] == "other-model"


def test_llm_ollama_swallows_transport_failure(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("connection refused")
    monkeypatch.setattr(repair.urllib.request, "urlopen", boom)
    assert repair.llm_ollama("p") == ""      # same fail-soft behavior as before A1


def test_llm_llamacpp_request_shape_and_response_parsing(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return _FakeHTTPResponse({"content": '"quoted fix"\nsecond line'})
    monkeypatch.setattr(repair.urllib.request, "urlopen", fake_urlopen)
    out = repair.llm_llamacpp("the prompt", "some-model")
    assert captured["url"] == repair.LLAMACPP_URL
    assert captured["body"] == {"prompt": "the prompt", "temperature": 0, "n_predict": 50, "stop": ["\n"]}
    assert "model" not in captured["body"]     # llama.cpp /completion has no model selector
    assert out == "quoted fix"


def test_llm_llamacpp_swallows_transport_failure(monkeypatch):
    monkeypatch.setattr(repair.urllib.request, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(OSError("down")))
    assert repair.llm_llamacpp("p", "m") == ""
