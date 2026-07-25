"""Unit tests for repair.py pure helpers (C1) plus V2 A1/A2/A3/A10 coverage: backend
dispatch, explicit connect/read timeouts + per-call latency, two-pass repair, and the
repair-summary.json writer. The llama.cpp box and Ollama are NOT reachable from this
environment -- every HTTP-touching test here mocks repair._post_json, its underlying
http.client connection, or the llm_*/llm functions; no live LLM call is ever made. Live
llama.cpp integration is PENDING manual verification on real hardware."""
import csv
import json

import common
import glossary
import repair

# --- T1 hoist: dialogue_intervals now lives in common.py --------------------

def test_dialogue_intervals_is_the_hoisted_common_function():
    """repair.dialogue_intervals must be common.dialogue_intervals itself (a plain
    re-export), not a local reimplementation -- pins the T1 hoist's import wiring.
    (process()'s use of it is still exercised end-to-end via monkeypatch below, same
    as before the hoist.)"""
    assert repair.dialogue_intervals is common.dialogue_intervals


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


# --- V2 A7: per-word confidence gate ------------------------------------------

def test_is_target_by_word_prob():
    # avg_logprob and name_suspect both look fine -- only a single low word_probs
    # entry (one badly-mis-heard word buried in an otherwise-clean line) makes it a
    # repair target.
    g = gl()
    c = {"avg_logprob": -0.05, "no_speech_prob": 0.1, "text": "hi there friend",
         "word_probs": [0.95, 0.91, 0.1]}
    assert repair.has_low_prob_word(c)
    assert repair.is_target(c, g)


def test_is_target_no_word_probs_field():
    # older conf.json (pre-A6) has no word_probs key at all -- must not be treated as
    # "has a low-prob word"; is_target falls back to avg_logprob/name_suspect exactly
    # as before A7.
    g = gl()
    c = {"avg_logprob": -0.05, "no_speech_prob": 0.1, "text": "hi there friend"}
    assert not repair.has_low_prob_word(c)
    assert not repair.is_target(c, g)


def test_is_target_word_probs_all_confident_no_gate():
    g = gl()
    c = {"avg_logprob": -0.05, "no_speech_prob": 0.1, "text": "hi there friend",
         "word_probs": [0.95, 0.91, 0.88]}
    assert not repair.has_low_prob_word(c)
    assert not repair.is_target(c, g)


# --- C12: glossary term string cap boundary ----------------------------------

def test_glossary_terms_no_truncation_mid_name():
    # Long enough names that a naive [:1000] slice would land mid-name; the fix must
    # only ever emit WHOLE terms, never a dangling fragment.
    names = [f"Character{i:02d}WithAVeryLongNameToForceTheCapBoundary" for i in range(50)]
    g = gl(names=names)
    terms = repair._glossary_terms(g)
    assert terms and len(terms) <= 1000
    parts = terms.split(", ")
    assert all(p in names for p in parts)     # every chunk is a complete name, never a fragment
    assert len(parts) < len(names)             # confirms the cap actually engaged


def test_glossary_terms_under_cap_unchanged():
    g = gl(names=["Luffy", "Zoro", "Nami"])
    assert repair._glossary_terms(g) == "Luffy, Zoro, Nami"


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


def test_build_prompt_wraps_reference_in_xml_tag():
    # C9: prompt-injection guard -- the fansub reference (untrusted third-party text) is
    # wrapped in an XML tag so the model reads it as quoted data, not instructions.
    g = gl()
    p = repair.build_prompt("asr line", "the official sub", g)
    assert "<official_subtitle_reference>the official sub</official_subtitle_reference>" in p
    no_ref = repair.build_prompt("asr line", "", g)
    assert "<official_subtitle_reference>" not in no_ref


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


def test_llm_ollama_request_shape_and_response_parsing(monkeypatch):
    """Byte-for-byte the pre-A1 request body + response parsing (first line, unquoted)."""
    captured = {}

    def fake_post(url, body):
        captured["url"] = url; captured["body"] = body
        return {"response": '  "fixed line"  \nignored second line'}
    monkeypatch.setattr(repair, "_post_json", fake_post)
    out = repair.llm_ollama("the prompt")
    assert captured["url"] == repair.OLLAMA
    assert captured["body"] == {"model": repair.MODEL, "prompt": "the prompt", "stream": False,
                                 "think": False, "options": {"temperature": 0}}
    assert out == "fixed line"


def test_llm_ollama_explicit_model_overrides_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(repair, "_post_json", lambda url, body: captured.update(body) or {"response": "x"})
    repair.llm_ollama("p", model="other-model")
    assert captured["model"] == "other-model"


def test_llm_ollama_swallows_transport_failure(monkeypatch):
    def boom(url, body):
        raise OSError("connection refused")
    monkeypatch.setattr(repair, "_post_json", boom)
    assert repair.llm_ollama("p") == ""      # same fail-soft behavior as before A1


def test_llm_llamacpp_request_shape_and_response_parsing(monkeypatch):
    captured = {}

    def fake_post(url, body):
        captured["url"] = url; captured["body"] = body
        return {"content": '"quoted fix"\nsecond line'}
    monkeypatch.setattr(repair, "_post_json", fake_post)
    out = repair.llm_llamacpp("the prompt", "some-model")
    assert captured["url"] == repair.LLAMACPP_URL
    assert captured["body"] == {"prompt": "the prompt", "temperature": 0, "n_predict": 50, "stop": ["\n"]}
    assert "model" not in captured["body"]     # llama.cpp /completion has no model selector
    assert out == "quoted fix"


def test_llm_llamacpp_swallows_transport_failure(monkeypatch):
    monkeypatch.setattr(repair, "_post_json", lambda url, body: (_ for _ in ()).throw(OSError("down")))
    assert repair.llm_llamacpp("p", "m") == ""


# --- A2: explicit connect/read timeouts + latency ----------------------------

def test_timeout_env_defaults():
    assert repair.TIMEOUT_CONNECT == 10.0
    assert repair.TIMEOUT_READ == 120.0


class _FakeSock:
    def __init__(self):
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def read(self):
        return json.dumps(self._payload).encode()


class _FakeConn:
    instances = []

    def __init__(self, host, port=None, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = _FakeSock()
        self.requested = None
        _FakeConn.instances.append(self)

    def connect(self):
        pass

    def request(self, method, path, body=None, headers=None):
        self.requested = (method, path, body, headers)

    def getresponse(self):
        return _FakeResponse({"response": "ok"})

    def close(self):
        pass


def test_post_json_uses_explicit_connect_and_read_timeouts(monkeypatch):
    _FakeConn.instances.clear()
    monkeypatch.setattr(repair.http.client, "HTTPConnection", _FakeConn)
    monkeypatch.setattr(repair, "TIMEOUT_CONNECT", 3.0)
    monkeypatch.setattr(repair, "TIMEOUT_READ", 42.0)
    out = repair._post_json("http://example.local:1234/x", {"a": 1})
    assert out == {"response": "ok"}
    conn = _FakeConn.instances[0]
    assert conn.host == "example.local" and conn.port == 1234
    assert conn.timeout == 3.0            # connect timeout, passed at construction/connect()
    assert conn.sock.timeout == 42.0      # read timeout, set on the socket after connecting
    assert conn.requested[0] == "POST"
    assert conn.requested[1] == "/x"


def test_post_json_raises_on_http_error_status(monkeypatch):
    class ErrConn(_FakeConn):
        def getresponse(self):
            return _FakeResponse({"error": "boom"}, status=500)
    monkeypatch.setattr(repair.http.client, "HTTPConnection", ErrConn)
    try:
        repair._post_json("http://example.local/x", {})
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_process_writes_latency_ms_column(tmp_path, monkeypatch):
    """process() is exercised end-to-end with find_video/glossary_for/dialogue_intervals/llm
    all monkeypatched -- no ffmpeg/ffprobe/pysubs2/network touched, matching the pattern
    used for generate.process() in test_generate.py."""
    stem = str(tmp_path / "ep")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    open(srt_path, "w").close()
    with open(conf_path, "w") as f:
        json.dump([{"start": 0.0, "end": 1.0, "text": "garbled line",
                    "avg_logprob": -0.6, "no_speech_prob": 0.1}], f)

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["orig", "repaired", "ref", "latency_ms"]
    assert len(rows) == 2
    assert rows[1][0] == "garbled line" and rows[1][1] == "a fixed line"
    assert int(rows[1][3]) >= 0        # latency recorded (mocked llm -> ~0ms, never negative)


# --- A3: two-pass repair ------------------------------------------------------

def test_needs_secondary_check_true_on_length_ratio_shrink():
    g = gl()
    assert repair._needs_secondary_check("a reasonably long original line here", "short", g) is True


def test_needs_secondary_check_true_on_length_ratio_grow():
    g = gl()
    assert repair._needs_secondary_check("short", "a much much much longer replacement line", g) is True


def test_needs_secondary_check_true_on_new_glossary_name():
    g = gl(names=["Spandam"])
    # similar length, no ratio trigger -- only the new-name condition should fire
    assert repair._needs_secondary_check("I saw spondum there", "I saw Spandam there", g) is True


def test_needs_secondary_check_false_when_name_already_in_orig():
    g = gl(names=["Spandam"])
    assert repair._needs_secondary_check("I saw Spandam already", "I saw Spandam again", g) is False


def test_needs_secondary_check_false_on_stable_similar_line():
    g = gl(names=["Spandam"])
    assert repair._needs_secondary_check("a clean line here", "a clean line there", g) is False


def _write_conf(conf_path, srt_path, conf_rows):
    open(srt_path, "w").close()
    with open(conf_path, "w") as f:
        json.dump(conf_rows, f)


def test_process_two_pass_reverifies_name_change(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_2pass")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(conf_path, srt_path,
                [{"start": 0.0, "end": 1.0, "text": "I saw spondum",
                  "avg_logprob": -0.6, "no_speech_prob": 0.1}])

    g = gl(names=["Spandam"])
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_2pass.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])

    def fake_llm(prompt, model=None):
        if model == "secondary-model":
            return "I saw Spandam there"        # secondary "confirms" + extends the fix
        return "I saw Spandam"                  # primary already inserts the glossary name
    monkeypatch.setattr(repair, "llm", fake_llm)
    monkeypatch.setattr(repair, "MODEL_SECONDARY", "secondary-model")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2
    assert rows[1][0] == "I saw spondum"
    assert rows[1][1] == "I saw Spandam there"        # secondary's output won (name-change trigger)
    assert int(rows[1][3]) >= 0                       # latency includes both calls


def test_process_two_pass_is_noop_when_secondary_equals_primary(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_noop")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(conf_path, srt_path,
                [{"start": 0.0, "end": 1.0, "text": "I saw spondum",
                  "avg_logprob": -0.6, "no_speech_prob": 0.1}])

    g = gl(names=["Spandam"])
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_noop.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])

    calls = []

    def fake_llm(prompt, model=None):
        calls.append(model)
        return "I saw Spandam"       # would trigger the two-pass check if secondary != primary
    monkeypatch.setattr(repair, "llm", fake_llm)
    # MODEL_SECONDARY left at its module default (== MODEL) -> two-pass must be a no-op

    assert repair.MODEL_SECONDARY == repair.MODEL
    repair.process(conf_path)
    assert calls == [None]           # only the primary call, no secondary re-check


# --- A10: repair-summary.json -------------------------------------------------

def test_p95_empty_is_zero():
    assert repair._p95([]) == 0.0


def test_p95_nearest_rank_on_small_set():
    # 5 values -> rank index round(0.95*4)=4 -> the max
    assert repair._p95([10, 20, 30, 40, 100]) == 100


def test_process_writes_repair_summary_json(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_summary")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(conf_path, srt_path,
                [{"start": 0.0, "end": 1.0, "text": "garbled line",
                  "avg_logprob": -0.6, "no_speech_prob": 0.1}])

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_summary.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["targets"] == 1
    assert summary["repaired"] == 1
    assert summary["skipped_no_ref"] == 0
    assert summary["model"] == repair.MODEL
    assert summary["model_secondary"] == repair.MODEL_SECONDARY
    assert summary["mean_latency_ms"] >= 0 and summary["p95_latency_ms"] >= 0
    assert summary["repaired_lines"] == [{"orig": "garbled line", "repaired": "a fixed line",
                                           "ref": "the official sub", "latency_ms": summary["mean_latency_ms"]}]


# --- V2 C10: chown failures are logged, not silently swallowed -------------------------

def test_process_logs_chown_failure_instead_of_swallowing(tmp_path, monkeypatch, capsys):
    stem = str(tmp_path / "ep_chown")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(conf_path, srt_path,
                [{"start": 0.0, "end": 1.0, "text": "garbled line",
                  "avg_logprob": -0.6, "no_speech_prob": 0.1}])

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_chown.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

    def _boom(*a, **kw):
        raise OSError("Operation not permitted")
    monkeypatch.setattr(repair.os, "chown", _boom)

    assert repair.process(conf_path) == "repaired"  # chown failure must not abort the show
    out = capsys.readouterr().out
    assert out.count("chown failed for") == 3  # srt_out, rep_out, summary_out


def test_process_counts_skipped_no_ref_and_never_calls_llm(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_noref")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(conf_path, srt_path,
                [{"start": 0.0, "end": 1.0, "text": "garbled line",
                  "avg_logprob": -0.9, "no_speech_prob": 0.1}])

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_noref.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])   # no fansub anchor anywhere
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: (_ for _ in ()).throw(
        AssertionError("llm must not be called when there's no fansub anchor")))

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["targets"] == 1
    assert summary["repaired"] == 0
    assert summary["skipped_no_ref"] == 1
    assert summary["repaired_lines"] == []
    assert summary["mean_latency_ms"] == 0 and summary["p95_latency_ms"] == 0
