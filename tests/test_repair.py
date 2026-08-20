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
import reflow
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
    """UPDATED: this used to pin the raw /completion body. That shape applies no chat
    template and returns nothing but newlines from a templated instruct model (verified
    against a live Nanbeige server), so it pinned a broken configuration. The backend now
    uses /v1/chat/completions; see
    test_llm_llamacpp_uses_chat_endpoint_with_thinking_disabled for the full contract."""
    captured = {}

    def fake_post(url, body, timeout=180):
        captured["url"] = url; captured["body"] = body
        return {"choices": [{"message": {"content": '"quoted fix"\nsecond line'}}]}
    monkeypatch.setattr(repair, "_post_json", fake_post)
    out = repair.llm_llamacpp("the prompt", "some-model")
    assert captured["url"] == repair.LLAMACPP_URL
    assert captured["body"]["messages"] == [{"role": "user", "content": "the prompt"}]
    assert "model" not in captured["body"]     # llama.cpp serves one loaded model
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
                [{"start": 0.0, "end": 2.0, "text": "I saw spondum",
                  "avg_logprob": -0.6, "no_speech_prob": 0.1}])   # 2.0s: the secondary's
                                                    # 19-char output is legal here (9.5 cps);
                                                    # the C5 gate is tested separately below
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


# --- srt rewrap on write: conf.json stores flattened text (generate.py strips the
# newline), so repair must re-wrap when it rewrites the srt -- even on a total no-op.
# This is the live defect: verified against shipped, muxed tracks, zero multi-line
# cues exist anywhere in the library. -------------------------------------------

def _parse_srt(path):
    """Minimal SRT reader for these tests: returns [{"lines": [str, ...]}, ...]."""
    blocks = open(path, encoding="utf-8").read().strip().split("\n\n")
    return [{"lines": b.split("\n")[2:]} for b in blocks]


def test_repair_rewraps_even_when_it_changes_nothing(tmp_path, monkeypatch):
    """A no-op repair must still write a wrapped srt. This is the live defect:
    conf.json holds flattened text and repair passed it straight through."""
    stem = str(tmp_path / "ep_rewrap_noop")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    long_line = "Now everybody lift your hands up Sing about what you are dreaming"
    _write_conf(conf_path, srt_path,
                [{"start": 0.0, "end": 5.0, "text": long_line,
                  "avg_logprob": -0.9, "no_speech_prob": 0.1}])

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_rewrap_noop.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])   # no fansub anchor -> no-op
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: (_ for _ in ()).throw(
        AssertionError("llm must not be called when there's no fansub anchor")))

    assert repair.process(conf_path) == "repaired"
    cues = _parse_srt(srt_path)
    assert len(cues[0]["lines"]) == 2
    assert all(len(ln) <= reflow.MAX_LINE for ln in cues[0]["lines"])


def test_repair_rewraps_a_repaired_line_too(tmp_path, monkeypatch):
    """Same requirement when the LLM DID change the line -- the rewrap must not be
    something that only happens to survive on the no-op path."""
    stem = str(tmp_path / "ep_rewrap_fixed")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    orig_line = "The garbled short version of a dreamy lyric line right here"
    _write_conf(conf_path, srt_path,
                [{"start": 0.0, "end": 5.0, "text": orig_line,
                  "avg_logprob": -0.9, "no_speech_prob": 0.1}])

    g = gl()
    long_fix = "The fixed longer version of a dreamy lyric line right there tonight"
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_rewrap_fixed.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 5.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: long_fix)

    assert repair.process(conf_path) == "repaired"
    cues = _parse_srt(srt_path)
    assert len(cues[0]["lines"]) == 2
    assert all(len(ln) <= reflow.MAX_LINE for ln in cues[0]["lines"])


# --- v1b prompt: measured anti-fabrication structure --------------------------
#
# A 40-target bake-off on real conf.json data showed the old prompt let qwen3.5:9b rewrite
# 42% of lines, pasting glossary names over correct text (Border Control -> "Cipher Pol",
# Sonny -> "Shanks", Neptune -> "Nefertari Vivi", and on another show Uchihime -> "Uchiha",
# a name from a different franchise entirely). The old prompt already SAID "NEVER replace a
# name"; restating it was not enough. Dropping the glossary from the prompt did NOT help
# (still 38%), so the name list is not the trigger. What cut it to 18% with zero glossary-
# name fabrications was structure: verification-only framing, worked examples, and nothing
# after the ASR line.

def test_build_prompt_frames_names_as_verification_not_insertion():
    """The list must not read as a menu of names to apply."""
    g = gl(names=["Zoro"])
    p = repair.build_prompt("zolo drew", "", g)
    assert "VERIFICATION ONLY" in p
    assert "not a list of names to insert" in p.lower()


def test_build_prompt_states_a_positive_duty_to_fix_damage():
    """Rules phrased purely as prohibitions produced an inert model: nanbeige4.2-3b made
    0 safe fixes across 120 targets, returning the input verbatim. Adding an explicit MUST
    FIX for run-together sentences and missing punctuation took it to 16, and qwen3.5:9b
    from 6 to 23 -- with FEWER name edits for both. The duty has to be stated, not implied
    by the absence of a prohibition."""
    g = gl(names=["Zoro"])
    p = repair.build_prompt("asr line", "", g)
    assert "MUST fix" in p
    assert "run-together" in p.lower() or "run together" in p.lower()


def test_build_prompt_omits_the_leave_alone_example():
    """Counter-intuitive but measured: a worked example showing an unlisted name being left
    alone over-anchored inaction. Removing it (keeping the prohibition in prose) was the
    single biggest gain in the sweep -- nanbeige 12 -> 16 safe fixes, qwen 6 -> 23 -- while
    name edits went DOWN. The only worked example kept is one that demonstrates fixing."""
    g = gl(names=["Zoro"])
    p = repair.build_prompt("asr line", "", g)
    assert "Sonny" not in p
    assert "Example" in p                    # the fix-this demonstration is retained


def test_build_prompt_puts_nothing_after_the_asr_line():
    """A first cut placed a "Remember:" reminder after the ASR line and the model echoed
    that rule text straight into the subtitle output:
      "...friends in jail We're victims here, Remember: do not introduce or swap names..."
    The corrected line must be the last thing the model is asked for, with the ASR line
    and its context immediately before it."""
    g = gl(names=["Zoro"])
    p = repair.build_prompt("the asr line", "the official sub", g,
                            prev_text="earlier", next_text="later")
    tail = p[p.index("the asr line"):]
    assert "Remember" not in tail
    assert "Rules:" not in tail
    assert tail.rstrip().endswith("Corrected line:")


def test_build_prompt_context_and_reference_precede_the_asr_line():
    """Context/reference are inputs, so they belong before the line being corrected --
    trailing blocks are what invited the echo above."""
    g = gl()
    p = repair.build_prompt("THE_ASR", "THE_REF", g, prev_text="PREV", next_text="NEXT")
    assert p.index("PREV") < p.index("THE_ASR")
    assert p.index("NEXT") < p.index("THE_ASR")
    assert p.index("THE_REF") < p.index("THE_ASR")


def test_build_prompt_carries_restraint_on_names_not_a_blanket_unsure_escape():
    """The old "if you are unsure, return it UNCHANGED" clause was removed deliberately: it
    is the escape hatch a cautious model takes on every line. Restraint now attaches
    specifically to proper nouns, which is where the damage was, leaving ordinary-word and
    punctuation repair unblocked. Measured: dropping the blanket escape RAISED safe fixes
    for both models and LOWERED name edits for both."""
    g = gl()
    p = repair.build_prompt("asr", "", g)
    assert "MUST NOT change any proper noun" in p
    assert "Never insert a name that is not already in the line." in p
    assert "unsure" not in p.lower()


# --- llama.cpp backend: chat endpoint, template applied ------------------------
#
# llm_llamacpp posted a RAW prompt to /completion, which applies no chat template. Verified
# against a live Nanbeige 4.2-3B server: that path returns nothing but newlines (200 tokens
# of "\n"), because the instruct model never sees its template. It can only ever have
# worked for a base/completion model. /v1/chat/completions applies the template; this fork
# additionally needs enable_thinking=false or it fills reasoning_content and returns an
# empty message (measured: empty after 114s at max_tokens=512; correct output in 4.3s with
# thinking off).

def test_llm_llamacpp_uses_chat_endpoint_with_thinking_disabled(monkeypatch):
    seen = {}

    def fake_post(url, body, timeout=180):
        seen["url"], seen["body"] = url, body
        return {"choices": [{"message": {"content": ' "Zoro drew his blade."\nnoise'}}]}

    monkeypatch.setattr(repair, "_post_json", fake_post)
    monkeypatch.setattr(repair, "LLAMACPP_URL", "http://host:8090/v1/chat/completions")
    out = repair.llm_llamacpp("PROMPT", None)
    assert seen["body"]["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["body"]["temperature"] == 0
    assert "model" not in seen["body"]          # llama.cpp serves one loaded model
    assert out == "Zoro drew his blade."


def test_llm_llamacpp_returns_empty_string_on_failure(monkeypatch):
    """Matches llm_ollama: a backend failure must degrade to "no repair", never raise into
    the per-episode loop."""
    def boom(url, body, timeout=180):
        raise OSError("connection refused")

    monkeypatch.setattr(repair, "_post_json", boom)
    assert repair.llm_llamacpp("PROMPT", None) == ""


def test_llm_llamacpp_treats_an_empty_reply_as_no_repair(monkeypatch):
    """Empty content with reasoning_content populated means thinking was not disabled.
    Returning "" (no repair) is correct; returning the reasoning text would write the
    model's monologue into the subtitle."""
    monkeypatch.setattr(repair, "_post_json", lambda u, b, timeout=180: {
        "choices": [{"message": {"content": "", "reasoning_content": "hmm..."}}]})
    assert repair.llm_llamacpp("PROMPT", None) == ""


# --- a recovered episode has no conf.json -------------------------------------
#
# tools/recover_dub_srt.py rebuilds the dub sidecar out of the already-muxed track for
# episodes whose conf.json is long gone. merge_pass.sh calls repair.py unconditionally
# before assembling, so process() has to treat a missing conf.json as "nothing to
# repair" rather than raising FileNotFoundError -- the guard above it checks the video
# and the srt but never the conf itself.

def test_process_skips_cleanly_when_the_conf_json_is_missing(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep")
    open(stem + repair.SRT_SUFFIX, "w").close()
    monkeypatch.setattr(repair, "find_video", lambda s: stem + ".mkv")
    assert repair.process(stem + repair.CONF_SUFFIX) == "skip"


# --- reference-leak guard -----------------------------------------------------
#
# The fansub reference exists to DISAMBIGUATE a garbled ASR line, not to supply its text.
# A dubtitle has to match the spoken dub, so a "repair" that swaps the dub's wording for
# the fansub's makes the subtitle wrong against the audio it accompanies.
#
# Measured across every repair summary in the library before this guard existed:
#   qwen3:8b   2520 repairs -- 84.1% imported words from the reference, 29.2% imported 3+
#   nanbeige   8456 repairs -- 52.5% imported words from the reference, 17.1% imported 3+
# i.e. both models did it, qwen far worse. Real examples that shipped:
#   "That's enough of that, idiots!" -> "Hold it, you brats!"   (the reference, verbatim)
#   "Let's go, Chopper."            -> "Well then, shall we go, Chopper?"
#
# The only gate was a 0.4-2.5 length band, far too loose to catch a same-length rewrite.

def test_borrowed_from_ref_lists_words_taken_from_the_reference():
    got = repair.borrowed_from_ref("That's enough of that, idiots!", "Hold it, you brats!",
                                   "Hold it, you brats!")
    assert set(got) == {"hold", "it", "you", "brats"}


def test_borrowed_from_ref_ignores_words_already_in_the_asr_line():
    """Keeping a word the ASR already had is not borrowing -- only NEW words count."""
    assert repair.borrowed_from_ref("the cat sat", "the cat sat down", "the cat sat down") == ["down"]


def test_borrowed_from_ref_ignores_new_words_absent_from_the_reference():
    """A word the model invented is a different failure (hallucination), not leak."""
    assert repair.borrowed_from_ref("the cat sat", "the cat waited", "the dog ran") == []


# dur=6.0 throughout the block below: a roomy card, so the C2/C4 card-profile gate is
# never what fires and each test still exercises the guard it was written for.

def test_accept_rejects_a_wholesale_substitution_from_the_reference():
    assert not repair.accept_repair("That's enough of that, idiots!", "Hold it, you brats!",
                                    "Hold it, you brats!", dur=6.0)


def test_accept_rejects_an_appended_clause_lifted_from_the_reference():
    assert not repair.accept_repair(
        "It's a bunch of baby snowbirds.",
        "It's a bunch of baby snowbirds. So, if we close the door, they'll fall.",
        "They're snowbird hatchlings.\nSo, if we close the door, they'll fall.", dur=6.0)


def test_accept_keeps_a_single_word_name_fix():
    """The whole point of having a reference: one wrong proper noun, corrected from it."""
    assert repair.accept_repair("Spondum drew his blade.", "Spandam drew his blade.",
                                "Spandam drew his blade, sneering.", dur=6.0)


def test_accept_keeps_a_punctuation_only_repair():
    assert repair.accept_repair(
        "He's just a reindeer with a blue nose, that's all.",
        "He's just a reindeer with a blue nose. That's all.",
        "He's just a reindeer with a blue nose. That's all.", dur=6.0)


def test_accept_keeps_a_garbled_line_rebuilt_from_its_own_words():
    """The strongest kind of repair: same words, ASR mangled the punctuation/dupes."""
    assert repair.accept_repair(
        "human human fruit a Devil Fruit right that's That's right.",
        "Human human fruit, a Devil Fruit, right? That's right.",
        "The Human-Human Fruit, a Devil Fruit.", dur=6.0)


def test_accept_rejects_a_line_that_more_than_doubles():
    """"Huh?" -> "Huh? Help!" passed the old 2.5 band exactly. Adding dialogue the dub
    never spoke is the failure mode, regardless of where the word came from."""
    assert not repair.accept_repair("Huh?", "Huh? Help!", "Huh? Help!", dur=6.0)


def test_accept_rejects_a_line_that_collapses():
    assert not repair.accept_repair("I'll be taking fifty percent of this restaurant.",
                                    "Fifty percent.", "Fifty percent.", dur=6.0)


def test_accept_rejects_an_unchanged_line():
    """Nothing to write, and it must not be counted as a repair."""
    assert not repair.accept_repair("Same line.", "Same line.", "some reference", dur=6.0)
    assert not repair.accept_repair("Same line.", "same LINE.", "some reference", dur=6.0)


def test_accept_rejects_empty_output():
    assert not repair.accept_repair("A line.", "", "ref", dur=6.0)


def test_borrow_limit_is_configurable(monkeypatch):
    """Thresholds are env-tunable so they can be tightened without rebuilding the image.

    Same-length swap, so this exercises the borrow limit alone and not the length band."""
    orig, new, ref = "the small cat sat down", "the small cat sat here", "it sat here"
    assert len(new) == len(orig)                  # the length gate cannot be what fires
    monkeypatch.setattr(repair, "MAX_REF_BORROW", 1)
    assert not repair.accept_repair(orig, new, ref, dur=6.0)
    monkeypatch.setattr(repair, "MAX_REF_BORROW", 99)
    assert repair.accept_repair(orig, new, ref, dur=6.0)


# --- C2/C4/C5: the acceptance gate knows the card it is repairing ---------------

def test_accept_rejects_a_repair_that_breaches_cps_for_this_cards_duration():
    """C2. The length band alone allows +50%; readability is a function of the card's
    DURATION, which the ratio cannot see. Same repair, same reference -- only the card
    the text has to fit in decides."""
    orig, new = "We need to get back to the ship.", "We really need to get back to the ship now."
    assert repair.LEN_RATIO_MIN <= len(new) / len(orig) <= repair.LEN_RATIO_MAX    # ratio 1.34: in band
    assert reflow.card_cps(new, 2.0) > reflow.MAX_CPS                   # 21.5 cps -- unreadable
    assert not repair.accept_repair(orig, new, "", dur=2.0)
    assert reflow.card_cps(new, 3.0) < reflow.MAX_CPS                   # 14.3 cps -- fine
    assert repair.accept_repair(orig, new, "", dur=3.0)


def test_accept_rejects_the_fifty_percent_growth_the_ratio_band_allows():
    """The brief's worked example: 40 chars at 3.0s is 13 cps, 58 chars is 19.3."""
    assert not repair.accept_repair("a" * 40, "b" * 58, ref="", dur=3.0)


def test_accept_rejects_a_repair_valid_in_total_but_unwrappable_per_line():
    """C4. A total-char check says nothing about whether the text can be DISPLAYED as
    <=MAX_LINES lines of <=MAX_LINE chars -- that depends on where the word boundaries
    fall. Passing text that is visually invalid is exactly how the wrapping defect
    survived, so validate the candidate AS WRAPPED."""
    orig, new = "a" * 40, "b" * 44 + " tail"
    assert len(new) <= reflow.MAX_CHARS                                 # total is legal ...
    assert reflow.card_cps(new, 6.0) < reflow.MAX_CPS                   # ... and so is the density
    assert max(len(ln) for ln in reflow.wrap_balance(new).split("\n")) > reflow.MAX_LINE
    assert not repair.accept_repair(orig, new, "", dur=6.0)


def test_accept_rejects_a_repair_over_max_chars_even_when_every_line_fits():
    """MAX_CHARS is not implied by the per-line check: two full 42-char lines flatten to
    85 visible characters (the break counts as the space it replaces), one over the
    card ceiling."""
    orig, new = "z" * 60, "x" * 42 + " " + "y" * 42
    lines = reflow.wrap_balance(new).split("\n")
    assert len(lines) == reflow.MAX_LINES and max(len(ln) for ln in lines) <= reflow.MAX_LINE
    assert len(new) > reflow.MAX_CHARS
    assert not repair.accept_repair(orig, new, "", dur=10.0)


def test_accept_keeps_a_name_only_repair_at_its_cards_duration():
    """The case repair exists to serve. If the card-aware gate rejects this it is wrong."""
    assert repair.accept_repair("Hi Zorro", "Hi Zoro", ref="", dur=2.0)


def test_accept_keeps_a_name_only_repair_on_a_dense_but_legal_card():
    """Permissiveness has to survive a tight card, not just a roomy one: 40 chars at
    2.5s is 16 cps -- under the ceiling, and the repair does not move it."""
    orig = "Spondum drew his blade and stepped back."
    new = "Spandam drew his blade and stepped back."
    assert len(new) == len(orig) and reflow.card_cps(new, 2.5) < reflow.MAX_CPS
    assert repair.accept_repair(orig, new, "Spandam drew his blade, sneering.", dur=2.5)


def test_accept_still_rejects_reference_borrowing_on_a_card_with_room():
    """The C2/C4 additions must not become an escape hatch: a long card cannot buy a
    wholesale lift from the reference."""
    assert not repair.accept_repair("That's enough of that, idiots!", "Hold it, you brats!",
                                    "Hold it, you brats!", dur=7.0)


def _conf_row(start, end, text, **extra):
    row = {"start": start, "end": end, "text": text, "avg_logprob": -0.6, "no_speech_prob": 0.1}
    row.update(extra); return row


def _repair_env(tmp_path, monkeypatch, stem, rows, out, g=None):
    """Drive process() over one hand-built conf.json with a canned LLM reply."""
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(conf_path, stem + repair.SRT_SUFFIX, rows)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g or gl())
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 30.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", out if callable(out) else (lambda prompt, model=None: out))
    return conf_path


def test_process_rejects_a_repair_that_does_not_fit_the_cards_duration(tmp_path, monkeypatch):
    """C2 wiring: the call site passes the card's duration, so the same model output is
    refused on a 1.0s card and accepted on a 2.0s one. Timing is never touched to make
    a repair fit (C1) -- the repair is what gives way."""
    stem = str(tmp_path / "ep_tight")
    conf_path = _repair_env(tmp_path, monkeypatch, stem,
                            [_conf_row(0.0, 1.0, "garbled line here")], "a garbled line here")
    assert repair.process(conf_path) == "repaired"          # the srt is always rewritten
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 0 and summary["rejected_guard"] == 1
    srt = open(stem + repair.SRT_SUFFIX).read()
    assert "a garbled line here" not in srt and "garbled line here" in srt    # the card kept its text
    with open(stem + ".dubtitles.repair.csv") as f:
        assert len(list(csv.reader(f))) == 1                # header only: nothing written


def test_process_accepts_the_same_repair_on_a_card_with_room(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_roomy")
    conf_path = _repair_env(tmp_path, monkeypatch, stem,
                            [_conf_row(0.0, 2.0, "garbled line here")], "a garbled line here")
    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 1 and summary["rejected_guard"] == 0


def test_process_gates_on_display_duration_not_source_duration(tmp_path, monkeypatch):
    """The viewer reads the card for as long as it is ON SCREEN. A card whose audio ran
    for 5s but which displays for 1.0s gets 1.0s worth of characters."""
    stem = str(tmp_path / "ep_src")
    conf_path = _repair_env(tmp_path, monkeypatch, stem,
                            [_conf_row(0.0, 1.0, "garbled line here", source_start=0.0, source_end=5.0)],
                            "a garbled line here")
    repair.process(conf_path)
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 0 and summary["rejected_guard"] == 1


def test_process_secondary_output_goes_through_the_same_gate(tmp_path, monkeypatch):
    """C5. The secondary model's output was written straight over the first pass with no
    validation at all -- a stronger model is still a model. When it fails the gate the
    already-validated first-pass repair stands; the card is not left garbled."""
    stem = str(tmp_path / "ep_sec")
    g = gl(names=["Spandam"])

    def fake_llm(prompt, model=None):
        return "I saw Spandam there" if model == "secondary-model" else "I saw Spandam"
    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 1.0, "I saw spondum")],
                            fake_llm, g=g)
    monkeypatch.setattr(repair, "MODEL_SECONDARY", "secondary-model")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert rows[1][1] == "I saw Spandam"            # 19 chars at 1.0s is 19 cps -- refused
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 1 and summary["rejected_secondary"] == 1


def test_process_secondary_output_that_borrows_the_reference_is_refused(tmp_path, monkeypatch):
    """The borrow guard applies to the second pass too, not just the length profile."""
    stem = str(tmp_path / "ep_sec_borrow")
    g = gl(names=["Spandam"])

    def fake_llm(prompt, model=None):
        return "the official sub" if model == "secondary-model" else "I saw Spandam"
    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 3.0, "I saw spondum")],
                            fake_llm, g=g)
    monkeypatch.setattr(repair, "MODEL_SECONDARY", "secondary-model")
    repair.process(conf_path)
    with open(stem + ".dubtitles.repair.csv") as f:
        assert list(csv.reader(f))[1][1] == "I saw Spandam"


# --- C6: reference selection anchors on SOURCE timing, not display timing -----

def test_overlap_ref_uses_the_source_window_not_the_displaced_one():
    """A card whose display start was stolen forward (Task 7) can land on its
    NEIGHBOUR's cue. Selecting on the source window keeps the evidence honest."""
    card = {"start": 12.0, "end": 12.9, "source_start": 10.0, "source_end": 10.9}
    ivals = [(10.0, 10.9, "the right line"), (11.9, 13.0, "the neighbour's line")]
    assert repair.overlap_ref(ivals, card["source_start"], card["source_end"]) == "the right line"
    assert repair.overlap_ref(ivals, card["start"], card["end"]) == "the neighbour's line"


def test_missing_source_window_falls_back_to_display():
    """Every conf.json already in the library predates C6 and must keep working."""
    card = {"start": 12.0, "end": 12.9}
    ivals = [(10.0, 10.9, "the right line"), (11.9, 13.0, "the neighbour's line")]
    ref = repair.overlap_ref(ivals, card.get("source_start", card["start"]),
                             card.get("source_end", card["end"]))
    assert ref == "the neighbour's line"


def test_process_selects_the_reference_by_the_source_window(tmp_path, monkeypatch):
    """End-to-end: the audited ref is the cue the card's AUDIO overlaps, not the one
    its displaced display window overlaps."""
    stem = str(tmp_path / "ep_src")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(conf_path, stem + repair.SRT_SUFFIX,
                [{"start": 12.0, "end": 12.9, "source_start": 10.0, "source_end": 10.9,
                  "text": "garbled line", "avg_logprob": -0.6, "no_speech_prob": 0.1}])

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_src.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals",
                        lambda video: [(10.0, 10.9, "the right line"),
                                       (11.9, 13.0, "the neighbour's line")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert rows[1][2] == "the right line"


def test_process_still_uses_display_timing_for_a_pre_c6_sidecar(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_old")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(conf_path, stem + repair.SRT_SUFFIX,
                [{"start": 12.0, "end": 12.9, "text": "garbled line",
                  "avg_logprob": -0.6, "no_speech_prob": 0.1}])

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_old.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals",
                        lambda video: [(10.0, 10.9, "the right line"),
                                       (11.9, 13.0, "the neighbour's line")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert rows[1][2] == "the neighbour's line"


# --- non-worsening gate on an already-invalid card (C2 refinement) --------------
# ~28% of cards are over cps and A2 deliberately does not retime for cps, so an
# absolute gate would refuse to fix a misheard name on any dense line -- the exact
# case repair exists to serve.

def _dense(n):
    return "word " * n


def test_repair_that_improves_an_already_over_cps_card_is_accepted():
    dur = 1.0
    orig, new = "Zorro " * 6, "Zoro " * 6          # shorter, still over cps
    assert reflow.card_cps(orig, dur) > reflow.MAX_CPS
    assert reflow.card_cps(new, dur) > reflow.MAX_CPS
    assert repair.fits_card(new, dur, orig) is True


def test_repair_that_worsens_an_already_over_cps_card_is_rejected():
    dur = 1.0
    orig, new = "Zoro " * 6, "Zorro " * 6          # longer, and already over
    assert repair.fits_card(new, dur, orig) is False


def test_a_clean_card_is_still_gated_absolutely():
    """Non-worsening applies only when the card was ALREADY invalid. A repair may not
    push a valid card over the ceiling just because it is an improvement elsewhere."""
    dur = 3.0
    orig, new = "a" * 40, "b" * 58                 # 13 cps -> 19.3 cps
    assert reflow.card_cps(orig, dur) <= reflow.MAX_CPS
    assert repair.fits_card(new, dur, orig) is False


def test_fits_card_without_orig_stays_absolute():
    assert repair.fits_card("z" * 60, 1.0) is False
