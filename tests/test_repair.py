"""Unit tests for repair.py pure helpers (C1) plus V2 A1/A2/A3/A10 coverage: backend
dispatch, explicit connect/read timeouts + per-call latency, two-pass repair, and the
repair-summary.json writer. The llama.cpp box and Ollama are NOT reachable from this
environment -- every HTTP-touching test here mocks repair._post_json, its underlying
http.client connection, or the llm_*/llm functions; no live LLM call is ever made. Live
llama.cpp integration is PENDING manual verification on real hardware."""

import csv
import json
import os

import common
import decisions
import glossary
import reflow
import repair
import unresolved

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
    c = {"avg_logprob": -0.05, "no_speech_prob": 0.1, "text": "hi there friend", "word_probs": [0.95, 0.91, 0.1]}
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
    c = {"avg_logprob": -0.05, "no_speech_prob": 0.1, "text": "hi there friend", "word_probs": [0.95, 0.91, 0.88]}
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
    assert all(p in names for p in parts)  # every chunk is a complete name, never a fragment
    assert len(parts) < len(names)  # confirms the cap actually engaged


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
    assert "the official sub" not in no_ref  # graceful glossary-only fallback


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
    assert explicit_empty == default_call  # backward-compat: defaults == old signature


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


def test_llm_dispatch_uses_ollama_when_that_backend_is_selected(monkeypatch):
    # REPAIR_BACKEND is read from the environment at import, and the container sets it to
    # llamacpp -- so asserting the module global here tested the dev shell, not dispatch.
    monkeypatch.setattr(repair, "REPAIR_BACKEND", "ollama")
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
    assert calls == [("llamacpp", "hi", repair.MODEL)]  # model=None -> defaults to REPAIR_MODEL


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
        captured["url"] = url
        captured["body"] = body
        return {"response": '  "fixed line"  \nignored second line'}

    monkeypatch.setattr(repair, "_post_json", fake_post)
    out = repair.llm_ollama("the prompt")
    assert captured["url"] == repair.OLLAMA
    assert captured["body"] == {
        "model": repair.MODEL,
        "prompt": "the prompt",
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    assert out == "fixed line"


def test_llm_ollama_explicit_model_overrides_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(repair, "_post_json", lambda url, body: captured.update(body) or {"response": "x"})
    repair.llm_ollama("p", model="other-model")
    assert captured["model"] == "other-model"


def test_llm_ollama_signals_a_transport_failure_rather_than_swallowing_it(monkeypatch):
    """Still fail-soft -- it must never raise into the per-episode loop -- but a dead
    endpoint is now DISTINGUISHABLE from an empty reply. Returning "" for both let a
    backend outage rebuild an episode's srt from raw ASR over its shipped repairs."""

    def boom(url, body):
        raise OSError("connection refused")

    monkeypatch.setattr(repair, "_post_json", boom)
    assert repair.llm_ollama("p") == repair.LLM_UNREACHABLE


def test_llm_llamacpp_request_shape_and_response_parsing(monkeypatch):
    """UPDATED: this used to pin the raw /completion body. That shape applies no chat
    template and returns nothing but newlines from a templated instruct model (verified
    against a live Nanbeige server), so it pinned a broken configuration. The backend now
    uses /v1/chat/completions; see
    test_llm_llamacpp_uses_chat_endpoint_with_thinking_disabled for the full contract."""
    captured = {}

    def fake_post(url, body, timeout=180):
        captured["url"] = url
        captured["body"] = body
        return {"choices": [{"message": {"content": '"quoted fix"\nsecond line'}}]}

    monkeypatch.setattr(repair, "_post_json", fake_post)
    out = repair.llm_llamacpp("the prompt", "some-model")
    assert captured["url"] == repair.LLAMACPP_URL
    assert captured["body"]["messages"] == [{"role": "user", "content": "the prompt"}]
    assert "model" not in captured["body"]  # llama.cpp serves one loaded model
    assert out == "quoted fix"


def test_llm_llamacpp_signals_a_transport_failure_rather_than_swallowing_it(monkeypatch):
    monkeypatch.setattr(repair, "_post_json", lambda url, body: (_ for _ in ()).throw(OSError("down")))
    assert repair.llm_llamacpp("p", "m") == repair.LLM_UNREACHABLE


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
    assert conn.timeout == 3.0  # connect timeout, passed at construction/connect()
    assert conn.sock.timeout == 42.0  # read timeout, set on the socket after connecting
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
        json.dump([{"start": 0.0, "end": 1.0, "text": "garbled line", "avg_logprob": -0.6, "no_speech_prob": 0.1}], f)

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
    assert int(rows[1][3]) >= 0  # latency recorded (mocked llm -> ~0ms, never negative)


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
    _write_conf(
        conf_path, srt_path, [{"start": 0.0, "end": 2.0, "text": "I saw spondum", "avg_logprob": -0.6, "no_speech_prob": 0.1}]
    )  # 2.0s: the secondary's
    # 19-char output is legal here (9.5 cps);
    # the C5 gate is tested separately below
    g = gl(names=["Spandam"])
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_2pass.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])

    def fake_llm(prompt, model=None):
        if model == "secondary-model":
            return "I saw Spandam there"  # secondary "confirms" + extends the fix
        return "I saw Spandam"  # primary already inserts the glossary name

    monkeypatch.setattr(repair, "llm", fake_llm)
    monkeypatch.setattr(repair, "MODEL_SECONDARY", "secondary-model")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2
    assert rows[1][0] == "I saw spondum"
    assert rows[1][1] == "I saw Spandam there"  # secondary's output won (name-change trigger)
    assert int(rows[1][3]) >= 0  # latency includes both calls


def test_process_two_pass_is_noop_when_secondary_equals_primary(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_noop")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "I saw spondum", "avg_logprob": -0.6, "no_speech_prob": 0.1}]
    )

    g = gl(names=["Spandam"])
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_noop.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])

    calls = []

    def fake_llm(prompt, model=None):
        calls.append(model)
        return "I saw Spandam"  # would trigger the two-pass check if secondary != primary

    monkeypatch.setattr(repair, "llm", fake_llm)
    # MODEL_SECONDARY left at its module default (== MODEL) -> two-pass must be a no-op

    assert repair.MODEL_SECONDARY == repair.MODEL
    repair.process(conf_path)
    assert calls == [None]  # only the primary call, no secondary re-check


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
    _write_conf(
        conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "garbled line", "avg_logprob": -0.6, "no_speech_prob": 0.1}]
    )

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
    assert summary["repaired_lines"] == [
        {"orig": "garbled line", "repaired": "a fixed line", "ref": "the official sub", "latency_ms": summary["mean_latency_ms"]}
    ]


def _unchanged_episode(tmp_path, monkeypatch, stem_name):
    """An episode whose single target the model returns VERBATIM -- the most common real
    outcome of the repair stage, and the one [S-4] never had a bucket for."""
    stem = str(tmp_path / stem_name)
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 1.0, "text": "garbled line", "avg_logprob": -0.6, "no_speech_prob": 0.1}],
    )
    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / (stem_name + ".mkv")))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    # Verbatim echo: accept_repair refuses it, and the `if not admitted` inner guard
    # (new.lower() != c["text"].lower()) is false by construction, so before the counter
    # existed this outcome incremented nothing and recorded nothing.
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "garbled line")
    repair.process(conf_path)
    return json.load(open(stem + ".dubtitles.repair-summary.json"))


def test_summary_counts_a_verbatim_model_response_as_unchanged(tmp_path, monkeypatch):
    """The break this catches: drop the `unchanged` increment (or put it inside the
    `new.lower() != c["text"].lower()` guard, where it can never fire) and the single most
    common repair outcome silently vanishes from the summary again."""
    summary = _unchanged_episode(tmp_path, monkeypatch, "ep_unchanged")
    assert summary["unchanged"] == 1
    assert summary["repaired"] == 0
    assert summary["rejected_guard"] == 0  # NOT the guard refusing an edit: there was no edit


def test_every_target_lands_in_exactly_one_summary_bucket(tmp_path, monkeypatch):
    """[S-4]'s invariant, corrected. It was stated as fact in a comment and was false --
    568 of 836 SAO targets were unaccounted for. The break this catches: any future outcome
    added to the repair loop without a bucket makes this arithmetic fail."""
    s = _unchanged_episode(tmp_path, monkeypatch, "ep_invariant")
    assert s["targets"] == (
        s["repaired"]
        + s["skipped_no_ref"]
        + s["llm_empty"]
        + s["rejected_guard"]
        + s["verdict_reject"]
        + s["verdict_unfittable"]
        + s["verdict_rescued"]
        + s["verdict_owed"]
        + s["unchanged"]
    )


# --- V2 C10: chown failures are logged, not silently swallowed -------------------------


def test_process_logs_chown_failure_instead_of_swallowing(tmp_path, monkeypatch, capsys):
    stem = str(tmp_path / "ep_chown")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "garbled line", "avg_logprob": -0.6, "no_speech_prob": 0.1}]
    )

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
    _write_conf(
        conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "garbled line", "avg_logprob": -0.9, "no_speech_prob": 0.1}]
    )

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_noref.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])  # no fansub anchor anywhere
    monkeypatch.setattr(
        repair,
        "llm",
        lambda prompt, model=None: (_ for _ in ()).throw(AssertionError("llm must not be called when there's no fansub anchor")),
    )

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
    _write_conf(conf_path, srt_path, [{"start": 0.0, "end": 5.0, "text": long_line, "avg_logprob": -0.9, "no_speech_prob": 0.1}])

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_rewrap_noop.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])  # no fansub anchor -> no-op
    monkeypatch.setattr(
        repair,
        "llm",
        lambda prompt, model=None: (_ for _ in ()).throw(AssertionError("llm must not be called when there's no fansub anchor")),
    )

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
    _write_conf(conf_path, srt_path, [{"start": 0.0, "end": 5.0, "text": orig_line, "avg_logprob": -0.9, "no_speech_prob": 0.1}])

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
    assert "Example" in p  # the fix-this demonstration is retained


def test_build_prompt_puts_nothing_after_the_asr_line():
    """A first cut placed a "Remember:" reminder after the ASR line and the model echoed
    that rule text straight into the subtitle output:
      "...friends in jail We're victims here, Remember: do not introduce or swap names..."
    The corrected line must be the last thing the model is asked for, with the ASR line
    and its context immediately before it."""
    g = gl(names=["Zoro"])
    p = repair.build_prompt("the asr line", "the official sub", g, prev_text="earlier", next_text="later")
    tail = p[p.index("the asr line") :]
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
    assert "model" not in seen["body"]  # llama.cpp serves one loaded model
    assert out == "Zoro drew his blade."


def test_llm_llamacpp_returns_the_unreachable_sentinel_on_failure(monkeypatch):
    """Matches llm_ollama: a backend failure must never raise into the per-episode loop.
    It returns the sentinel rather than "", so the caller can tell a dead endpoint from a
    model that had nothing to change."""

    def boom(url, body, timeout=180):
        raise OSError("connection refused")

    monkeypatch.setattr(repair, "_post_json", boom)
    assert repair.llm_llamacpp("PROMPT", None) == repair.LLM_UNREACHABLE
    assert repair.LLM_UNREACHABLE != "", "the sentinel must not be falsy-equal to an empty reply"


def test_llm_llamacpp_treats_an_empty_reply_as_no_repair(monkeypatch):
    """Empty content with reasoning_content populated means thinking was not disabled.
    Returning "" (no repair) is correct; returning the reasoning text would write the
    model's monologue into the subtitle."""
    monkeypatch.setattr(
        repair, "_post_json", lambda u, b, timeout=180: {"choices": [{"message": {"content": "", "reasoning_content": "hmm..."}}]}
    )
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
    got = repair.borrowed_from_ref("That's enough of that, idiots!", "Hold it, you brats!", "Hold it, you brats!")
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
    assert not repair.accept_repair(
        "That's enough of that, idiots!", "Hold it, you brats!", "Hold it, you brats!", dur=6.0, gloss=gl()
    )


def test_accept_rejects_an_appended_clause_lifted_from_the_reference():
    assert not repair.accept_repair(
        "It's a bunch of baby snowbirds.",
        "It's a bunch of baby snowbirds. So, if we close the door, they'll fall.",
        "They're snowbird hatchlings.\nSo, if we close the door, they'll fall.",
        dur=6.0,
        gloss=gl(),
    )


def test_accept_keeps_a_single_word_name_fix():
    """The whole point of having a reference: one wrong proper noun, corrected from it.
    Glossary carries Spandam -- the destination of the fix is a real glossary name, so the
    phonetic-name-guard (invents_name) recognises it as a genuine correction, not a
    fabrication, and lets it through."""
    assert repair.accept_repair(
        "Spondum drew his blade.",
        "Spandam drew his blade.",
        "Spandam drew his blade, sneering.",
        dur=6.0,
        gloss=gl(names=["Spandam"]),
    )


def test_accept_keeps_a_punctuation_only_repair():
    assert repair.accept_repair(
        "He's just a reindeer with a blue nose, that's all.",
        "He's just a reindeer with a blue nose. That's all.",
        "He's just a reindeer with a blue nose. That's all.",
        dur=6.0,
        gloss=gl(),
    )


def test_accept_keeps_a_garbled_line_rebuilt_from_its_own_words():
    """The strongest kind of repair: same words, ASR mangled the punctuation/dupes."""
    assert repair.accept_repair(
        "human human fruit a Devil Fruit right that's That's right.",
        "Human human fruit, a Devil Fruit, right? That's right.",
        "The Human-Human Fruit, a Devil Fruit.",
        dur=6.0,
        gloss=gl(),
    )


def test_accept_rejects_a_line_that_more_than_doubles():
    """ "Huh?" -> "Huh? Help!" passed the old 2.5 band exactly. Adding dialogue the dub
    never spoke is the failure mode, regardless of where the word came from."""
    assert not repair.accept_repair("Huh?", "Huh? Help!", "Huh? Help!", dur=6.0, gloss=gl())


def test_accept_rejects_a_line_that_collapses():
    assert not repair.accept_repair(
        "I'll be taking fifty percent of this restaurant.", "Fifty percent.", "Fifty percent.", dur=6.0, gloss=gl()
    )


def test_accept_rejects_an_unchanged_line():
    """Nothing to write, and it must not be counted as a repair."""
    assert not repair.accept_repair("Same line.", "Same line.", "some reference", dur=6.0, gloss=gl())
    assert not repair.accept_repair("Same line.", "same LINE.", "some reference", dur=6.0, gloss=gl())


def test_accept_rejects_empty_output():
    assert not repair.accept_repair("A line.", "", "ref", dur=6.0, gloss=gl())


def test_borrow_limit_is_configurable(monkeypatch):
    """Thresholds are env-tunable so they can be tightened without rebuilding the image.

    Same-length swap, so this exercises the borrow limit alone and not the length band."""
    orig, new, ref = "the small cat sat down", "the small cat sat here", "it sat here"
    assert len(new) == len(orig)  # the length gate cannot be what fires
    monkeypatch.setattr(repair, "MAX_REF_BORROW", 1)
    assert not repair.accept_repair(orig, new, ref, dur=6.0, gloss=gl())
    monkeypatch.setattr(repair, "MAX_REF_BORROW", 99)
    assert repair.accept_repair(orig, new, ref, dur=6.0, gloss=gl())


# --- C2/C4/C5: the acceptance gate knows the card it is repairing ---------------


def test_accept_rejects_a_repair_that_breaches_cps_for_this_cards_duration():
    """C2. The length band alone allows +50%; readability is a function of the card's
    DURATION, which the ratio cannot see. Same repair, same reference -- only the card
    the text has to fit in decides."""
    orig, new = "We need to get back to the ship.", "We really need to get back to the ship now."
    assert repair.LEN_RATIO_MIN <= len(new) / len(orig) <= repair.LEN_RATIO_MAX  # ratio 1.34: in band
    assert reflow.card_cps(new, 2.0) > reflow.MAX_CPS  # 21.5 cps -- unreadable
    assert not repair.accept_repair(orig, new, "", dur=2.0, gloss=gl())
    assert reflow.card_cps(new, 3.0) < reflow.MAX_CPS  # 14.3 cps -- fine
    assert repair.accept_repair(orig, new, "", dur=3.0, gloss=gl())


def test_accept_rejects_the_fifty_percent_growth_the_ratio_band_allows():
    """The brief's worked example: 40 chars at 3.0s is 13 cps, 58 chars is 19.3."""
    assert not repair.accept_repair("a" * 40, "b" * 58, ref="", dur=3.0, gloss=gl())


def test_accept_rejects_a_repair_valid_in_total_but_unwrappable_per_line():
    """C4. A total-char check says nothing about whether the text can be DISPLAYED as
    <=MAX_LINES lines of <=MAX_LINE chars -- that depends on where the word boundaries
    fall. Passing text that is visually invalid is exactly how the wrapping defect
    survived, so validate the candidate AS WRAPPED."""
    orig, new = "a" * 40, "b" * 44 + " tail"
    assert len(new) <= reflow.MAX_CHARS  # total is legal ...
    assert reflow.card_cps(new, 6.0) < reflow.MAX_CPS  # ... and so is the density
    assert max(len(ln) for ln in reflow.wrap_balance(new).split("\n")) > reflow.MAX_LINE
    assert not repair.accept_repair(orig, new, "", dur=6.0, gloss=gl())


def test_accept_rejects_a_repair_over_max_chars_even_when_every_line_fits():
    """MAX_CHARS is not implied by the per-line check: two full 42-char lines flatten to
    85 visible characters (the break counts as the space it replaces), one over the
    card ceiling."""
    orig, new = "z" * 60, "x" * 42 + " " + "y" * 42
    lines = reflow.wrap_balance(new).split("\n")
    assert len(lines) == reflow.MAX_LINES and max(len(ln) for ln in lines) <= reflow.MAX_LINE
    assert len(new) > reflow.MAX_CHARS
    assert not repair.accept_repair(orig, new, "", dur=10.0, gloss=gl())


def test_accept_keeps_a_name_only_repair_at_its_cards_duration():
    """The case repair exists to serve. If the card-aware gate rejects this it is wrong.
    Glossary carries Zoro -- the destination is a real glossary name, so the
    phonetic-name-guard recognises this as a genuine correction rather than a fabrication."""
    assert repair.accept_repair("Hi Zorro", "Hi Zoro", ref="", dur=2.0, gloss=gl(names=["Zoro"]))


def test_accept_keeps_a_name_only_repair_on_a_dense_but_legal_card():
    """Permissiveness has to survive a tight card, not just a roomy one: 40 chars at
    2.5s is 16 cps -- under the ceiling, and the repair does not move it. Glossary carries
    Spandam -- the destination is a real glossary name, so the phonetic-name-guard lets
    this through as a genuine correction."""
    orig = "Spondum drew his blade and stepped back."
    new = "Spandam drew his blade and stepped back."
    assert len(new) == len(orig) and reflow.card_cps(new, 2.5) < reflow.MAX_CPS
    assert repair.accept_repair(orig, new, "Spandam drew his blade, sneering.", dur=2.5, gloss=gl(names=["Spandam"]))


def test_accept_still_rejects_reference_borrowing_on_a_card_with_room():
    """The C2/C4 additions must not become an escape hatch: a long card cannot buy a
    wholesale lift from the reference."""
    assert not repair.accept_repair(
        "That's enough of that, idiots!", "Hold it, you brats!", "Hold it, you brats!", dur=7.0, gloss=gl()
    )


def _conf_row(start, end, text, **extra):
    row = {"start": start, "end": end, "text": text, "avg_logprob": -0.6, "no_speech_prob": 0.1}
    row.update(extra)
    return row


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
    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 1.0, "garbled line here")], "a garbled line here")
    assert repair.process(conf_path) == "repaired"  # the srt is always rewritten
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 0 and summary["rejected_guard"] == 1
    srt = open(stem + repair.SRT_SUFFIX).read()
    assert "a garbled line here" not in srt and "garbled line here" in srt  # the card kept its text
    with open(stem + ".dubtitles.repair.csv") as f:
        assert len(list(csv.reader(f))) == 1  # header only: nothing written


def test_process_accepts_the_same_repair_on_a_card_with_room(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_roomy")
    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 2.0, "garbled line here")], "a garbled line here")
    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 1 and summary["rejected_guard"] == 0


def test_process_gates_on_display_duration_not_source_duration(tmp_path, monkeypatch):
    """The viewer reads the card for as long as it is ON SCREEN. A card whose audio ran
    for 5s but which displays for 1.0s gets 1.0s worth of characters."""
    stem = str(tmp_path / "ep_src")
    conf_path = _repair_env(
        tmp_path,
        monkeypatch,
        stem,
        [_conf_row(0.0, 1.0, "garbled line here", source_start=0.0, source_end=5.0)],
        "a garbled line here",
    )
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

    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 1.0, "I saw spondum")], fake_llm, g=g)
    monkeypatch.setattr(repair, "MODEL_SECONDARY", "secondary-model")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert rows[1][1] == "I saw Spandam"  # 19 chars at 1.0s is 19 cps -- refused
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 1 and summary["rejected_secondary"] == 1


def test_process_secondary_output_that_borrows_the_reference_is_refused(tmp_path, monkeypatch):
    """The borrow guard applies to the second pass too, not just the length profile."""
    stem = str(tmp_path / "ep_sec_borrow")
    g = gl(names=["Spandam"])

    def fake_llm(prompt, model=None):
        return "the official sub" if model == "secondary-model" else "I saw Spandam"

    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 3.0, "I saw spondum")], fake_llm, g=g)
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
    ref = repair.overlap_ref(ivals, card.get("source_start", card["start"]), card.get("source_end", card["end"]))
    assert ref == "the neighbour's line"


def test_process_selects_the_reference_by_the_source_window(tmp_path, monkeypatch):
    """End-to-end: the audited ref is the cue the card's AUDIO overlaps, not the one
    its displaced display window overlaps."""
    stem = str(tmp_path / "ep_src")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [
            {
                "start": 12.0,
                "end": 12.9,
                "source_start": 10.0,
                "source_end": 10.9,
                "text": "garbled line",
                "avg_logprob": -0.6,
                "no_speech_prob": 0.1,
            }
        ],
    )

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_src.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(
        repair, "dialogue_intervals", lambda video: [(10.0, 10.9, "the right line"), (11.9, 13.0, "the neighbour's line")]
    )
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

    assert repair.process(conf_path) == "repaired"
    with open(stem + ".dubtitles.repair.csv") as f:
        rows = list(csv.reader(f))
    assert rows[1][2] == "the right line"


def test_process_still_uses_display_timing_for_a_pre_c6_sidecar(tmp_path, monkeypatch):
    stem = str(tmp_path / "ep_old")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 12.0, "end": 12.9, "text": "garbled line", "avg_logprob": -0.6, "no_speech_prob": 0.1}],
    )

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_old.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(
        repair, "dialogue_intervals", lambda video: [(10.0, 10.9, "the right line"), (11.9, 13.0, "the neighbour's line")]
    )
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
    orig, new = "Zorro " * 6, "Zoro " * 6  # shorter, still over cps
    assert reflow.card_cps(orig, dur) > reflow.MAX_CPS
    assert reflow.card_cps(new, dur) > reflow.MAX_CPS
    assert repair.fits_card(new, dur, orig) is True


def test_repair_that_worsens_an_already_over_cps_card_is_rejected():
    dur = 1.0
    orig, new = "Zoro " * 6, "Zorro " * 6  # longer, and already over
    assert repair.fits_card(new, dur, orig) is False


def test_a_clean_card_is_still_gated_absolutely():
    """Non-worsening applies only when the card was ALREADY invalid. A repair may not
    push a valid card over the ceiling just because it is an improvement elsewhere."""
    dur = 3.0
    orig, new = "a" * 40, "b" * 58  # 13 cps -> 19.3 cps
    assert reflow.card_cps(orig, dur) <= reflow.MAX_CPS
    assert repair.fits_card(new, dur, orig) is False


def test_fits_card_without_orig_stays_absolute():
    assert repair.fits_card("z" * 60, 1.0) is False


def test_repair_backend_defaults_to_llamacpp_when_unset(monkeypatch):
    """Asserted independently of whatever the ambient environment sets.

    This used to pin `ollama` as a backward-compat default while, as its own docstring
    recorded, "the production container sets REPAIR_BACKEND=llamacpp" -- the shipped default
    and the only real deployment disagreeing, with the repo documenting the one nobody ran.
    That is the same shape as REPAIR_UNANCHORED: a hand-set variable doing load-bearing work
    no committed file records. llama.cpp is also the stronger performer on the owner's
    measurement and what both arms of the quant A/B run on, so the default now matches the
    configuration the published numbers were taken on.

    Ollama is still fully supported; it is a value, not a removal."""
    import importlib

    monkeypatch.delenv("REPAIR_BACKEND", raising=False)
    assert importlib.reload(repair).REPAIR_BACKEND == "llamacpp"
    importlib.reload(repair)  # restore ambient config for the rest of the session


def test_repair_model_defaults_to_qwen3_4b_instruct_when_unset(monkeypatch):
    """Asserted independently of whatever the ambient environment sets.

    This used to pin `nanbeige4.2-3b` -- the C1 bake-off's own choice, reversing the
    original C1 bake-off's qwen3.5:9b lock on the evidence that qwen3.5:9b imported the
    fansub reference verbatim into 84.1% of its repairs. A live anchored bake-off run
    2026-09-01 against real production data (Trigun, MARRIAGETOXIN, Serial Experiments
    Lain) on a DIFFERENT, newer qwen candidate -- qwen3-4b-instruct, not qwen3.5:9b, and
    not the same model the original C1 bake-off rejected -- found it the only one of four
    real candidates (nanbeige4.2-3b, gemma3n-e2b, phi4-mini, qwen3-4b-instruct) with zero
    hallucinations, zero severe content drops, and zero verbatim-reference-copy instances
    across all three shows; the others each exhibited at least one of those failure modes,
    including one outright fabricated line from phi4-mini. qwen3-4b-instruct is also the
    model recorded as the unanchored verdict-bake-off leader on exact-match count in the
    2026-08-31 handoff (59/90 vs nanbeige's 43/90)."""
    import importlib

    monkeypatch.delenv("REPAIR_MODEL", raising=False)
    assert importlib.reload(repair).MODEL == "qwen3-4b-instruct"
    importlib.reload(repair)  # restore ambient config for the rest of the session


# --- implausible source window (VAD design S6; spec v5, S-6) -------------------


def test_process_takes_no_reference_from_an_implausible_source_window(tmp_path, monkeypatch):
    """A 7s source span on a one-word card selects whatever fansub line falls inside it --
    possibly a different line entirely. The guard must yield NO reference, not the display
    window: on 99% of gated cards display == source, so a fallback reproduces the very
    window just declared implausible."""
    stem = str(tmp_path / "ep_badwin")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [
            {
                "start": 12.0,
                "end": 12.9,
                "source_start": 6.0,
                "source_end": 14.0,  # 8.0s > MAX_DUR on a one-word card
                "text": "it",
                "avg_logprob": -0.6,
                "no_speech_prob": 0.1,
            }
        ],
    )

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_badwin.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(6.5, 7.5, "a neighbour's line")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "should never be called")

    repair.process(conf_path)

    with open(stem + ".dubtitles.repair-summary.json") as f:
        summary = json.load(f)
    assert summary["skipped_no_ref"] == 1, "the bad window must yield no anchor"
    assert summary["rules"]["rule_source_window_activated"] == 1
    assert summary["rules"]["rule_source_window_evaluated"] == 1


def test_process_still_anchors_a_plausible_window(tmp_path, monkeypatch):
    """The guard is scoped: an ordinary card keeps its reference and the rule reports
    evaluated-but-not-activated, which is what makes a dead rule visible."""
    stem = str(tmp_path / "ep_okwin")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [
            {
                "start": 12.0,
                "end": 12.9,
                "source_start": 12.0,
                "source_end": 12.9,
                "text": "garbled line",
                "avg_logprob": -0.6,
                "no_speech_prob": 0.1,
            }
        ],
    )

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_okwin.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(12.0, 12.9, "the right line")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "a fixed line")

    repair.process(conf_path)

    with open(stem + ".dubtitles.repair-summary.json") as f:
        summary = json.load(f)
    assert summary["skipped_no_ref"] == 0
    assert summary["rules"]["rule_source_window_activated"] == 0
    assert summary["rules"]["rule_source_window_evaluated"] == 1


# --- phonetic name guard (ISSUE-phonetic-name-guard.md) -------------------------
#
# glossary.correct(new, gloss) already ran on every LLM output before accept_repair sees
# it (repair.py:449), snapping any token the deterministic tiers can match to a glossary
# name -- exact, hard-fix, or guarded-fuzzy/metaphone. invents_name() judges only the
# residue: tokens matching no glossary name by any tier. Measured on One Pace S29E08 (40
# targets, temperature 0), prompt tuning could not close this -- see the file above.


def _pin_words(monkeypatch, words=()):
    """Pin glossary._WORDS so is_english is deterministic regardless of the host's
    wordlist (see tests/test_glossary.py:112) -- this dev box falls back to a 233-word
    bundle when /usr/share/dict/american-english is absent, production has wamerican, and
    either could accidentally contain one of the invented tokens below."""
    monkeypatch.setattr(glossary, "_WORDS", set(words))


def test_invents_name_sees_a_substitution_masked_by_a_repeated_name(monkeypatch):
    """Garnus appears twice in orig (vocative, then reference) and only the first occurrence
    is mangled to the invented Garnel; the second survives untouched -- ordinary dialogue,
    not evidence of anything. A SET-based comparison of lowercase cores still finds 'garnus'
    present somewhere in new_lower and concludes nothing was lost, so it never inspects the
    invented Garnel at all -- exactly the case this guard exists to catch. Multiset (Counter)
    semantics see that one occurrence of Garnus went missing regardless of the other
    surviving."""
    _pin_words(monkeypatch)
    g = gl()
    assert repair.invents_name("Garnus fought Garnus again", "Garnel fought Garnus again", g)


def test_invents_name_rejects_an_unknown_phonetic_substitute(monkeypatch):
    """Syrahose -> Shyarros: Shyarros matches no glossary name by any tier, so this is the
    invented-name failure the guard exists to catch."""
    _pin_words(monkeypatch)
    g = gl(names=["Shirahoshi"])
    assert repair.invents_name(
        "You're about to be a big, beautiful corpse, Syrahose!",
        "You're about to be a big, beautiful corpse, Shyarros!",
        g,
    )


def test_invents_name_accepts_a_known_glossary_correction(monkeypatch):
    """Syrahose -> Shirahoshi: the SAME original token as the test above, but this time
    the substitute IS a glossary name (glossary.correct() already made this exact swap
    upstream) -- the guard must not undo a correct repair."""
    _pin_words(monkeypatch)
    g = gl(names=["Shirahoshi"])
    assert not repair.invents_name(
        "Van Der Decken is going to capture my precious Syrahose!",
        "Van Der Decken is going to capture my precious Shirahoshi!",
        g,
    )


def test_invents_name_rejects_deccan_to_decman(monkeypatch):
    """A two-character substitution is still a fabrication. Decman is close enough to
    Deccan that any edit-distance escape hatch would wave it through -- which is exactly
    why the guard has none, and why breaking that rule would break this test."""
    _pin_words(monkeypatch)
    g = gl()
    assert repair.invents_name("Just let me go after Deccan.", "Just let me go after Decman.", g)


def test_invents_name_rejects_hirohoshi_mangled_to_hihohi(monkeypatch):
    """The worst observed case: a name already close to correct was destroyed into a
    non-word."""
    _pin_words(monkeypatch)
    g = gl()
    assert repair.invents_name("I can't let that beast catch Hirohoshi.", "I can't let that beast catch Hihohi.", g)


def test_invents_name_rejects_garnus_to_garnel(monkeypatch):
    """The name-only half of the mixed card below, isolated: with no genuine fix riding
    along, the substitution alone must still be refused."""
    _pin_words(monkeypatch)
    g = gl()
    assert repair.invents_name("Garnus charged forward.", "Garnel charged forward.", g)


def test_invents_name_accepts_zolo_to_zoro(monkeypatch):
    """zolo -> Zoro: the lowercase original is not itself proper-noun-ish (it never had a
    capitalised core to lose), and the gained Zoro IS a known glossary name -- both halves
    of the guard have to agree for this to pass."""
    _pin_words(monkeypatch)
    g = gl(names=["Zoro"])
    assert not repair.invents_name("zolo drew his blade", "Zoro drew his blade", g)


def test_invents_name_polices_a_four_char_core_at_the_min_fuzzy_len_floor(monkeypatch):
    """MIN_FUZZY_LEN is 4, and the guard requires len(core) >= MIN_FUZZY_LEN -- so a
    4-character invented substitution sits exactly on the boundary and must still be
    caught. No shipped glossary fixture exercises this: the only 4-char name in the
    fixtures (Zoro) is always KNOWN, so its classification never turns on this floor."""
    _pin_words(monkeypatch)
    g = gl()
    assert repair.invents_name("Nami waited.", "Nima waited.", g)


def test_invents_name_does_not_police_a_three_char_core_below_the_floor(monkeypatch):
    """The mirror of the test above: a 3-character core sits just under MIN_FUZZY_LEN and
    must NOT be policed -- too short for the fuzzy/metaphone tiers upstream to have judged
    with any precision either, so this guard doesn't try."""
    _pin_words(monkeypatch)
    g = gl()
    assert not repair.invents_name("Nam waited.", "Nim waited.", g)


def test_invents_name_ignores_punctuation_only_change(monkeypatch):
    """human -centric -> human-centric: no capitalised token is gained at all, so this
    must not be policed as a name change."""
    _pin_words(monkeypatch)
    g = gl()
    assert not repair.invents_name("a human -centric approach", "a human-centric approach", g)


def test_invents_name_rejects_the_mixed_card_even_with_a_genuine_fix_inside(monkeypatch):
    """Garnel is invented AND `Is -> if` is a genuine punctuation/casing fix in the SAME
    line. Owner's decision: the whole card is rejected regardless -- assert that
    explicitly so a future change that tries to salvage the genuine fix has to notice it
    is reversing this call."""
    _pin_words(monkeypatch)
    g = gl()
    assert repair.invents_name(
        "Garnus, too far away to tell Is something wrong?",
        "Garnel, too far away to tell if something wrong?",
        g,
    )


def test_invents_name_rejects_a_bare_addition_that_loses_nothing(monkeypatch):
    """NEW conjures a capitalised, non-glossary token while ORIG loses none of its own.

    Scope widened 2026-08-26: the guard originally policed substitutions only, so a name
    invented from nothing was invisible to it. The hotwords spike produced exactly that
    shape -- `jester` -> `Dester`, a correct English word turned into a capitalised
    non-word -- and the substitution rule could not see it in either direction, because
    the lowercase `jester` was never a proper noun to lose."""
    _pin_words(monkeypatch)
    g = gl()
    assert repair.invents_name("He looked around.", "He looked around, Garnus.", g)


def test_invents_name_rejects_the_dester_shape_from_the_hotwords_spike(monkeypatch):
    """The measured regression: a real English word decoded as a capitalised non-word.

    `jester` is lowercase so nothing is LOST; only `Dester` is gained. Under the original
    substitutions-only rule this returned False and the fabrication shipped."""
    _pin_words(monkeypatch, words=("the", "genius", "jester"))
    g = gl(names=["Buggy"])
    assert repair.invents_name("the genius jester, Buggy", "The Genius Dester, Buggy", g)


def test_invents_name_accepts_an_addition_that_is_a_known_name(monkeypatch):
    """Widening to additions must not refuse a name the glossary already knows: the
    reference-anchored repair that ADDS `Zoro` is the case repair exists to serve."""
    _pin_words(monkeypatch)
    g = gl(names=["Zoro"])
    assert not repair.invents_name("He looked around.", "He looked around, Zoro.", g)


def test_invents_name_ignores_a_token_reached_only_via_trailing_punctuation(monkeypatch):
    """Garnus, -> Garnus: the bare core is identical once trailing punctuation is
    stripped, so this is not a substitution -- proves the punctuation escape is
    deliberate, not a gap."""
    _pin_words(monkeypatch)
    g = gl()
    assert not repair.invents_name("Garnus, look out!", "Garnus look out!", g)


def test_process_records_rejected_name_invented_reason(tmp_path, monkeypatch):
    """The unresolved reason string must switch to "rejected_name_invented" specifically
    when the guard rejected because a name was invented -- not for e.g. a length/cps
    failure -- or the guard's hit rate is unmeasurable. (unresolved.record is monkeypatched
    only to capture its call; unresolved.py's REASONS table is owned by another agent and
    not touched here.)"""
    stem = str(tmp_path / "ep_invented")
    g = gl(names=["Shirahoshi"])
    conf_path = _repair_env(
        tmp_path,
        monkeypatch,
        stem,
        [_conf_row(0.0, 6.0, "You're about to be a big, beautiful corpse, Syrahose!")],
        "You're about to be a big, beautiful corpse, Shyarros!",
        g=g,
    )
    _pin_words(monkeypatch)
    captured = []
    monkeypatch.setattr(unresolved, "record", lambda *a, **kw: captured.append((a, kw)))
    assert repair.process(conf_path) == "repaired"
    reasons = [a[2] for a, kw in captured]
    assert "rejected_name_invented" in reasons


def _tagged_gloss():
    """A glossary with arc tags, shaped as [S-11] stores them: term -> the arcs it is in."""
    g = gl(names=["Doflamingo", "Rebecca", "Oimo", "Spandam", "Zoro"])
    g["arc_tags"] = {
        "doflamingo": ["Dressrosa"],
        "rebecca": ["Dressrosa"],
        "oimo": ["Enies Lobby"],
        "spandam": ["Enies Lobby"],
        "zoro": ["Dressrosa", "Enies Lobby"],  # recurring: belongs to both
    }
    return g


def test_glossary_terms_puts_the_current_arcs_names_first(monkeypatch):
    """[S-13] The prompt term list is capped at 1000 chars on whole-term boundaries, and
    that cap BITES: measured 2026-08-26 on the live One Pace glossary, 30 of 140 terms were
    dropped, including `Nico Robin` and `Rob Lucci`. Ordering therefore decides which names
    the model is told about at all, so the current arc's names must come first."""
    terms = repair._glossary_terms(_tagged_gloss(), arc="Dressrosa").split(", ")
    assert terms.index("Doflamingo") < terms.index("Oimo")
    assert terms.index("Rebecca") < terms.index("Spandam")


def test_glossary_terms_keeps_a_recurring_name_in_every_arc(monkeypatch):
    """A character in two arcs must be prioritised in BOTH. Caesar Clown is a Punk Hazard
    antagonist present in Dressrosa; filtering him out of either would be wrong."""
    for arc in ("Dressrosa", "Enies Lobby"):
        terms = repair._glossary_terms(_tagged_gloss(), arc=arc).split(", ")
        assert terms.index("Zoro") < terms.index("Spandam" if arc == "Dressrosa" else "Rebecca")


def test_glossary_terms_never_drops_an_out_of_arc_name_that_fits(monkeypatch):
    """Weighting REORDERS, it does not filter. An out-of-arc name the model might need is
    still offered -- dropping it would make the model MORE likely to 'correct' a valid name
    into a listed one, which is the failure this is supposed to prevent."""
    terms = repair._glossary_terms(_tagged_gloss(), arc="Dressrosa").split(", ")
    assert set(terms) >= {"Doflamingo", "Rebecca", "Oimo", "Spandam", "Zoro"}


def test_glossary_terms_unchanged_when_the_arc_is_unknown(monkeypatch):
    """No season.nfo, or a show with no tags, must behave exactly as before -- the common
    case in this library, and the one that must not regress."""
    g = _tagged_gloss()
    assert repair._glossary_terms(g, arc=None) == repair._glossary_terms(g)


def test_glossary_terms_unchanged_when_the_glossary_has_no_tags(monkeypatch):
    """Every glossary in the library today has no arc_tags key at all."""
    g = gl(names=["Doflamingo", "Oimo"])
    assert repair._glossary_terms(g, arc="Dressrosa") == repair._glossary_terms(g)


def test_build_prompt_threads_the_arc_into_the_reference_spellings(monkeypatch):
    """[S-13] end to end: the arc reaches the prompt text, not just the term helper."""
    g = _tagged_gloss()
    p = repair.build_prompt("some line", "", g, arc="Dressrosa")
    names = p.split("VERIFICATION ONLY - this is NOT a list of names to insert): ")[1].split(".\n")[0]
    terms = names.split(", ")
    assert terms.index("Doflamingo") < terms.index("Spandam")


def _episode_tagged_gloss():
    """A glossary with both arc_tags (Dressrosa/Enies Lobby) and episode_tags (Rebecca
    tagged to S31E01 specifically), shaped as [S-9] stores them."""
    g = _tagged_gloss()
    g["episode_tags"] = {"rebecca": ["S31E01"]}
    return g


def test_glossary_terms_episode_tag_outranks_arc_tag():
    g = _episode_tagged_gloss()
    terms = repair._glossary_terms(g, arc="Dressrosa", episode="S31E01").split(", ")
    # Rebecca is BOTH arc- and episode-tagged for S31E01; Doflamingo is arc-tagged only.
    # The episode tier must rank Rebecca ahead of Doflamingo.
    assert terms.index("Rebecca") < terms.index("Doflamingo")


def test_glossary_terms_episode_untagged_falls_through_to_arc_tier():
    """An episode-untagged term is NOT defaulted into the episode-first tier the way an
    arc-untagged term defaults into the arc tier -- it falls through to the (unchanged)
    arc-tier logic, which still applies. Doflamingo (arc-tagged, not episode-tagged)
    must still outrank Oimo (a different arc) for this episode."""
    g = _episode_tagged_gloss()
    terms = repair._glossary_terms(g, arc="Dressrosa", episode="S31E01").split(", ")
    assert terms.index("Doflamingo") < terms.index("Oimo")


def test_glossary_terms_untagged_term_still_appears():
    g = _episode_tagged_gloss()
    terms = repair._glossary_terms(g, arc="Dressrosa", episode="S99E99").split(", ")
    assert "Oimo" in terms  # untagged for both dimensions, still included


def test_glossary_terms_episode_none_matches_today_2tier_behavior():
    g = _tagged_gloss()
    with_episode_none = repair._glossary_terms(g, arc="Dressrosa", episode=None)
    # Must be byte-identical to calling with no episode kwarg at all, for every
    # existing caller that doesn't pass one.
    assert with_episode_none == repair._glossary_terms(g, arc="Dressrosa")


def test_build_prompt_without_an_arc_is_byte_identical_to_before(monkeypatch):
    """The no-arc path is the whole library today; it must not shift by a single byte."""
    g = _tagged_gloss()
    assert repair.build_prompt("l", "r", g, "p", "n", arc=None) == repair.build_prompt("l", "r", g, "p", "n")


def _known_gloss():
    return gl(names=["Zoro", "Oimo", "Doflamingo", "Shirahoshi"])


def test_unanchored_repair_refuses_swapping_one_known_name_for_another(monkeypatch):
    """[S-14] The documented reason unanchored repair was disabled: repair.py:512 records
    that glossary-only repair hallucinated `Oimo` -> `Zoro`. The glossary vouched for the
    ORIGINAL, and a model with no reference has no standing to overrule it."""
    _pin_words(monkeypatch, words=("get", "him"))
    assert not repair.accept_repair("Get him, Oimo!", "Get him, Zoro!", ref="", dur=6.0, gloss=_known_gloss())


def test_anchored_repair_still_allows_a_known_to_known_swap(monkeypatch):
    """The same swap WITH a fansub reference is evidence-backed, so it must still pass.
    Applying the strict guard everywhere would refuse real anchored repairs library-wide,
    and the bake-off failure this guards against was the glossary-ONLY case."""
    _pin_words(monkeypatch, words=("get", "him"))
    assert repair.accept_repair("Get him, Oimo!", "Get him, Zoro!", ref="Get him, Zoro!", dur=6.0, gloss=_known_gloss())


def test_unanchored_repair_refuses_a_phonetically_distant_name(monkeypatch):
    """[S-14b] On the unknown -> known path, require the names to actually sound alike.
    Measured 2026-08-26: jaro_winkler admits dothamingo->doflamingo 0.893 and
    syrahose->shirahoshi 0.755, and blocks oimo->zoro 0.667."""
    _pin_words(monkeypatch, words=("it", "is", "a", "card"))
    assert not repair.accept_repair("It is a Kavendish card", "It is a Zoro card", ref="", dur=6.0, gloss=_known_gloss())


def test_unanchored_repair_allows_the_phonetic_name_fix_it_exists_for(monkeypatch):
    """The whole point: Dothamingo -> Doflamingo on a card with no reference. Neither
    glossary tier can reach it (difflib 0.800 vs a 0.84 cutoff, metaphone T0MNK vs TFLMNK)
    and it is one of S31's 6,492 unanchored cards, so nothing else can fix it either."""
    _pin_words(monkeypatch, words=("the", "heavenly", "demon", "don"))
    assert repair.accept_repair(
        "The heavenly demon, Don Dothamingo.", "The heavenly demon, Don Doflamingo.", ref="", dur=6.0, gloss=_known_gloss()
    )


def test_vouched_name_guard_survives_a_missing_jellyfish(monkeypatch):
    """Only the phonetic half needs the optional dependency. Degrading the vouched-name
    rule with it would let the exact bake-off failure (`Oimo` -> `Zoro`) through on any box
    where jellyfish is absent -- and glossary.py already ships that degradation path."""
    _pin_words(monkeypatch, words=("get", "him"))
    monkeypatch.setattr(glossary, "jellyfish", None)
    assert not repair.accept_repair("Get him, Oimo!", "Get him, Zoro!", ref="", dur=6.0, gloss=_known_gloss())


def test_unanchored_cards_are_skipped_by_default(monkeypatch, tmp_path):
    """[S-12] The gate is CONDITIONAL, not deleted. Default-off means production behaves
    exactly as it does today -- measured on S31E01: targets=161, repaired=0, every one
    refused for want of a fansub anchor."""
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    assert repair.skips_unanchored("") is True
    assert repair.skips_unanchored("some fansub line") is False


def test_unanchored_cards_reach_the_llm_when_enabled(monkeypatch):
    """With the flag on, a card with no reference is no longer refused outright. The 161
    targets on S31E01 produced 21 repairs this way, 18 acceptable."""
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", True)
    assert repair.skips_unanchored("") is False
    assert repair.skips_unanchored("some fansub line") is False


def test_an_untagged_legacy_name_is_never_demoted(monkeypatch):
    """[S-11] The 92 names already in the library predate tagging. Treating "no tags" as
    "not in this arc" would demote the entire existing glossary behind a handful of newly
    tagged names -- making the first weighted run a strict SUBSET of what the model already
    had. Untagged means unknown, and unknown defaults IN."""
    g = gl(names=["Doflamingo", "Luffy", "Zoro"])
    g["arc_tags"] = {"doflamingo": ["Dressrosa"]}  # only one name tagged
    terms = repair._glossary_terms(g, arc="Dressrosa").split(", ")
    assert set(terms[:3]) == {"Doflamingo", "Luffy", "Zoro"}


def test_a_name_tagged_to_another_arc_sorts_after_the_current_one(monkeypatch):
    """A name KNOWN to belong elsewhere is the only thing weighting demotes."""
    g = gl(names=["Doflamingo", "Spandam", "Luffy"])
    g["arc_tags"] = {"doflamingo": ["Dressrosa"], "spandam": ["Enies Lobby"]}
    terms = repair._glossary_terms(g, arc="Dressrosa").split(", ")
    assert terms.index("Doflamingo") < terms.index("Spandam")
    assert terms.index("Luffy") < terms.index("Spandam")


def test_an_accepted_repair_is_queued_with_the_text_before_and_after(tmp_path, monkeypatch):
    """Breaks if the accept path stops queueing, or queues the wrong side of the swap.

    `accept_repair` admitted this line; nothing below it checked the meaning, and its own
    docstring says so. The reviewer is the check, and they need BOTH texts to be one.

    Asserted on the fields, not the count: two empty strings satisfy a count. The ordering
    is the trap -- `c["text"] = new` (repair.py:683) runs AFTER `audit.append`
    (repair.py:681), so a record call placed below the assignment would report the
    repaired text as the original and the entry would compare a line against itself."""
    stem = str(tmp_path / "ep_queued")
    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 2.0, "garbled line here")], "a garbled line here")
    assert repair.process(conf_path) == "repaired"

    entries = [e for e in unresolved.items(stem) if e["stage"] == "repair_applied"]
    assert len(entries) == 1
    assert entries[0]["reason"] == "accepted"
    assert entries[0]["original_text"] == "garbled line here"
    assert entries[0]["proposed_text"] == "a garbled line here"

    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert len(entries) == summary["repaired"]


def test_a_rejected_repair_is_not_queued_as_accepted(tmp_path, monkeypatch):
    """Breaks if the record call lands outside the accept branch. A repair the gate REFUSED
    must never appear in the accepted queue -- it is already recorded as rejected_guard, and
    counting it twice would tell the reviewer a line shipped that never did."""
    stem = str(tmp_path / "ep_tight_q")
    conf_path = _repair_env(tmp_path, monkeypatch, stem, [_conf_row(0.0, 1.0, "garbled line here")], "a garbled line here")
    assert repair.process(conf_path) == "repaired"

    stages = [e["stage"] for e in unresolved.items(stem)]
    assert "repair_applied" not in stages
    assert json.load(open(stem + ".dubtitles.repair-summary.json"))["repaired"] == 0


def test_the_queue_records_the_secondary_models_text_not_the_first_passes(tmp_path, monkeypatch):
    """Breaks if the queue write moves ABOVE the secondary-model block (repair.py:667-680).

    The gap this closes: the record call's own comment claims it sits below that block so
    `proposed_text` is the text actually applied, and NO test held it there. Moving the call
    to just after `else:` left the whole suite green while queueing "I saw Spandam" -- the
    discarded first pass -- for a card that shipped "I saw Spandam there".

    That is the worst possible failure for this queue: a reviewer approving text the viewer
    never saw, on precisely the name-change-then-re-verified case the two-pass gate exists
    for. Mirrors test_process_two_pass_reverifies_name_change, which asserts the same
    override on the CSV and never looks at the queue."""
    stem = str(tmp_path / "ep_2pass_q")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 2.0, "text": "I saw spondum", "avg_logprob": -0.6, "no_speech_prob": 0.1}],
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_2pass_q.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(
        repair, "llm", lambda prompt, model=None: "I saw Spandam there" if model == "secondary-model" else "I saw Spandam"
    )
    monkeypatch.setattr(repair, "MODEL_SECONDARY", "secondary-model")

    assert repair.process(conf_path) == "repaired"
    queued = [e for e in unresolved.items(stem) if e["stage"] == "repair_applied"]
    assert len(queued) == 1
    assert queued[0]["original_text"] == "I saw spondum"
    assert queued[0]["proposed_text"] == "I saw Spandam there", "the queue must show what SHIPPED"
    # ...and it agrees with the audit trail the same run wrote.
    with open(stem + ".dubtitles.repair.csv") as f:
        assert list(csv.reader(f))[1][1] == queued[0]["proposed_text"]


# --- [S-4] the decision-store consult ----------------------------------------
# The store has been write-only until now: sprint 002 built it, sprint 003 filled its
# queue, and nothing read either back. These pin the read side.


def _store(orig, proposed, verdict, text=""):
    """A one-decision store, built through decisions.record so the keys are the real ones."""
    return decisions.record({}, orig, proposed, verdict, text=text)


def _one_target(tmp_path, name, text="I saw spondum"):
    """One mid-confidence card on a 2.0s display window -- is_target() picks it up."""
    stem = str(tmp_path / name)
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 2.0, "text": text, "avg_logprob": -0.6, "no_speech_prob": 0.1}],
    )
    return stem, conf_path


def test_a_reject_verdict_keeps_the_post_correction_asr_text(tmp_path, monkeypatch):
    """A stored `reject` for this exact pair means the repair is not applied.

    Pins the consult BETWEEN glossary.correct() (repair.py:634) and accept_repair
    (repair.py:649). The llm proposes "I saw Spandom"; hard_fixes rewrites it to
    "I saw Spandam"; the verdict is stored against the CORRECTED text. A consult placed
    above line 634 would look up "I saw Spandom", miss, fall through to accept_repair --
    which accepts this pair (test_process_two_pass_reverifies_name_change relies on it) --
    and the card would ship repaired. The miss is silent, which is why this is asserted on
    the card text rather than on the lookup being called."""
    stem, conf_path = _one_target(tmp_path, "ep_reject")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_reject.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (_store("I saw spondum", "I saw Spandam", "reject"), "Show"))

    repair.process(conf_path)

    # The SRT, not conf.json: repair.py mutates the conf rows in memory and never writes
    # that file back (repair.py:703 vs the rebuild at :709-713). Asserting on conf.json
    # passes whether or not the repair was applied -- it is the vacuous version of this test.
    assert "I saw spondum" in open(stem + repair.SRT_SUFFIX).read(), "a rejected repair must not be applied"
    assert [e for e in unresolved.items(stem) if e["stage"] == "repair_applied"] == [], "a settled line must not be re-queued"


def test_a_correct_verdict_applies_the_humans_text(tmp_path, monkeypatch):
    """A stored `correct` ships the human's wording, not the model's, and is not re-judged.

    The human's text is deliberately one accept_repair REFUSES: 24 chars against a 13-char
    original is a 1.85 length ratio, outside the 0.6-1.5 band. It still renders inside the
    2.0s card (12 cps). So this fails both without the branch (the model's text ships) and
    with a branch that leaves the human's text subject to accept_repair (nothing ships).
    A `correct` verdict is a human overriding the gate's judgement; only fits_card, which
    is timing and not judgement, still governs it."""
    stem, conf_path = _one_target(tmp_path, "ep_correct")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_correct.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    store = _store("I saw spondum", "I saw Spandam", "correct", text="I saw Spandam over there")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))

    repair.process(conf_path)

    assert "I saw Spandam over there" in open(stem + repair.SRT_SUFFIX).read(), "the human's text must win over the model's"


def test_a_correct_that_does_not_fit_the_card_is_refused_and_recorded(tmp_path, monkeypatch):
    """C1: timing is immutable, so even a human cannot widen a card.

    `correct` overrules accept_repair's JUDGEMENT, never fits_card. A verdict that cannot
    be rendered leaves the ASR text standing -- and says so in the queue, because the whole
    point of the review loop is that a decision never disappears silently. The reviewer
    supplied 57 characters for a 2.0s card (28.5 cps against a 17 cps profile)."""
    stem, conf_path = _one_target(tmp_path, "ep_unfit")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_unfit.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    too_long = "I saw Spandam standing over there beside the harbour gate"
    monkeypatch.setattr(
        decisions, "decisions_for", lambda *a, **k: (_store("I saw spondum", "I saw Spandam", "correct", text=too_long), "Show")
    )

    repair.process(conf_path)

    srt = open(stem + repair.SRT_SUFFIX).read()
    # A token, not the whole string: wrap_balance inserts a newline, so the full 57-char
    # text never appears verbatim even when it HAS shipped -- that form of the assertion
    # passes unconditionally.
    assert "harbour" not in srt, "a card cannot be widened to fit the human's text"
    assert "I saw spondum" in srt, "the ASR text stands when the verdict cannot be rendered"
    refusals = [e for e in unresolved.items(stem) if e["reason"] == "decision_unfittable"]
    assert len(refusals) == 1, "the human must be told their decision was refused, not silently dropped"
    assert refusals[0]["proposed_text"] == too_long


def test_accept_repair_never_splits_a_machine_proposal():
    """Scope boundary, settled 2026-09-02: card_split applies to human correct/force
    verdicts only. A machine repair proposal that would need a split to fit is still
    refused outright -- accept_repair's own fits_card call never routes through
    card_split, and C1 stays absolute for this path. Same fixture the human-verdict split
    tests use, verified independently to be splittable, so a False here can only mean the
    machine path really never tries."""
    orig = "The captain gave an order and everyone listened closely today."
    new = "The captain ordered everyone to abandon ship at once. Nobody thought twice about it."
    assert repair.accept_repair(orig, new, "", 10.0, gl()) is False


def test_a_correct_too_wide_for_one_line_but_splittable_ships_as_two_cues(tmp_path, monkeypatch):
    """.procoder/todo/20260829-split-a-card-so-a-human-correction-fits.md: an over_line_len
    refusal (NOT over_cps -- that stays out of scope and unsplittable, see
    test_a_correct_that_does_not_fit_the_card_is_refused_and_recorded) now ships as two
    cues instead of being thrown away. Fixture verified directly against reflow: at 10.0s
    the 84-char correction wraps to a 44-char second line (over_line_len only), and the
    sentence-boundary split gives two individually legal single-line halves."""
    half1 = "The captain ordered everyone to abandon ship at once."
    half2 = "Nobody thought twice about it."
    full_text = f"{half1} {half2}"
    stem = str(tmp_path / "ep_split")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 100.0, "end": 110.0, "text": "I saw spondum", "avg_logprob": -0.6, "no_speech_prob": 0.1}],
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_split.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    monkeypatch.setattr(
        decisions,
        "decisions_for",
        lambda *a, **k: (_store("I saw spondum", "I saw Spandam", "correct", text=full_text), "Show"),
    )

    repair.process(conf_path)

    srt = open(stem + repair.SRT_SUFFIX).read()
    # Tokens, not the whole strings: wrap_balance inserts a newline in half1 (2 lines), so
    # the space-joined half1 never appears verbatim even when it HAS shipped correctly.
    assert "abandon ship at once" in srt and "Nobody thought twice" in srt, "both halves must ship, not raw ASR"
    assert srt.count(" --> ") == 2, "two cues, not one -- a single cue could never legally hold this text"
    assert not [e for e in unresolved.items(stem) if e["reason"] == "decision_unfittable"], "a legal split is not a refusal"


def _run_force_case(tmp_path, monkeypatch, name, store):
    """One episode whose proposal accept_repair REFUSES (30 chars against 13 is a 2.3 length
    ratio, outside the 0.6-1.5 band) but which renders fine in the 2.0s card (15 cps)."""
    stem, conf_path = _one_target(tmp_path, name)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / (name + ".mkv")))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom by the gate here")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    repair.process(conf_path)
    return open(stem + repair.SRT_SUFFIX).read()


def test_a_force_verdict_admits_a_repair_the_gate_refused(tmp_path, monkeypatch):
    """`force` is the human overruling accept_repair -- the verdict that exists because the
    gate is a heuristic and a reader is not. The control half is what makes it mean
    anything: the SAME pair with an empty store must still be refused, or the test would
    pass on a proposal the gate was going to accept anyway."""
    forced = _store("I saw spondum", "I saw Spandam by the gate here", "force")
    assert "by the gate here" in _run_force_case(tmp_path, monkeypatch, "ep_force", forced), "force must admit it"
    assert "by the gate here" not in _run_force_case(tmp_path, monkeypatch, "ep_force_ctl", {}), "the gate still refuses it"


def test_a_forced_repair_that_cannot_be_rendered_is_still_refused(tmp_path, monkeypatch):
    """The boundary of `force`: it overrules judgement, never timing.

    accept_repair is a heuristic and a human may overrule it. fits_card is not a heuristic
    -- it is whether the line can be put on screen for the seconds the card lasts. C1 holds
    timing immutable, so there is no verdict that admits an unrenderable line, and the
    reviewer is told rather than having their force silently ignored."""
    stem, conf_path = _one_target(tmp_path, "ep_force_unfit")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_force_unfit.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    unrenderable = "I saw Spandam standing over there beside the harbour gate"
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: unrenderable)
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (_store("I saw spondum", unrenderable, "force"), "Show"))

    repair.process(conf_path)

    srt = open(stem + repair.SRT_SUFFIX).read()
    assert "harbour" not in srt, "force must not be able to widen a card"
    assert "I saw spondum" in srt
    assert [e for e in unresolved.items(stem) if e["reason"] == "decision_unfittable"], "the forcer must be told"


def _run_accept_case(tmp_path, monkeypatch, name, store):
    """One episode whose proposal accept_repair ACCEPTS, so applying it proves nothing on
    its own -- the queue entry is the whole observable difference a verdict makes."""
    stem, conf_path = _one_target(tmp_path, name)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / (name + ".mkv")))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    repair.process(conf_path)
    return open(stem + repair.SRT_SUFFIX).read(), [e for e in unresolved.items(stem) if e["stage"] == "repair_applied"]


def test_an_accept_verdict_applies_the_repair_and_stops_re_queueing_it(tmp_path, monkeypatch):
    """The verdict the plan omitted, and the one that closes re-run amplification.

    APPLYING is not the observable part: with no verdict at all accept_repair already
    accepts this pair, so a branch that only applies is indistinguishable from no branch.
    What `accept` changes is that the line stops coming back -- the control half below
    shows the same episode queueing it when nothing is stored. Without this, every re-run
    hands the reviewer a line they already approved, forever."""
    srt, queued = _run_accept_case(tmp_path, monkeypatch, "ep_accept", _store("I saw spondum", "I saw Spandam", "accept"))
    assert "I saw Spandam" in srt, "an accepted repair is still applied"
    assert queued == [], "a line the human approved must not be queued again"

    _, control = _run_accept_case(tmp_path, monkeypatch, "ep_accept_ctl", {})
    assert len(control) == 1, "with no verdict the same episode DOES queue it -- else the test above is vacuous"


def test_correct_and_force_verdicts_are_not_re_queued_either(tmp_path, monkeypatch):
    """Same rule, other two applying verdicts: a human has ruled, so the line is settled.
    `reject` is settled by never reaching the queue write at all."""
    _, corrected = _run_accept_case(
        tmp_path, monkeypatch, "ep_c_qs", _store("I saw spondum", "I saw Spandam", "correct", text="I saw Spandam there")
    )
    assert corrected == [], "a corrected line is settled"
    _, forced = _run_accept_case(tmp_path, monkeypatch, "ep_f_qs", _store("I saw spondum", "I saw Spandam", "force"))
    assert forced == [], "a forced line is settled"


def test_an_empty_store_is_byte_identical_and_still_reaches_the_lookup(tmp_path, monkeypatch):
    """The no-op case -- every install that has never reviewed anything.

    Byte-identity alone is a weak claim: a `return` placed above the consult satisfies it
    while the whole feature is dead. So this also spies on decisions.lookup and requires it
    to have been reached for the targeted card. Expected values are written literally, not
    computed from a second run, so a change that breaks BOTH runs the same way still fails."""
    stem, conf_path = _one_target(tmp_path, "ep_empty")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_empty.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: ({}, "Show"))
    seen = []
    real = decisions.lookup
    monkeypatch.setattr(decisions, "lookup", lambda store, o, p: seen.append((o, p)) or real(store, o, p))

    repair.process(conf_path)

    assert seen == [("I saw spondum", "I saw Spandam")], "the consult must be reached even with nothing stored"
    assert open(stem + repair.SRT_SUFFIX).read() == "1\n00:00:00,000 --> 00:00:02,000\nI saw Spandam\n\n"
    assert len([e for e in unresolved.items(stem) if e["stage"] == "repair_applied"]) == 1


def test_decisions_apply_0_applies_no_verdict(tmp_path, monkeypatch):
    """Suggestion-only: the review still records verdicts, repair stops acting on them.

    Written AFTER the flag existed (it went in with the first consult), so it never went
    red on its own -- it is held by the mutation check instead: deleting the DECISIONS_APPLY
    guard makes the stored `reject` take effect and fails this.

    Asserted on the APPLICATION, not the bytes. A stored `reject` would suppress the
    repair_applied entry, so that entry's presence is what proves the verdict was never
    consulted -- byte-identity alone would pass on a flag read after the verdict took
    effect."""
    store = _store("I saw spondum", "I saw Spandam", "reject")
    monkeypatch.setattr(repair, "DECISIONS_APPLY", False)
    srt, queued = _run_accept_case(tmp_path, monkeypatch, "ep_noapply", store)

    assert "I saw Spandam" in srt, "the reject must NOT take effect"
    assert len(queued) == 1, "the line is unsettled again, so it is queued -- the verdict was not read"
    assert srt == "1\n00:00:00,000 --> 00:00:02,000\nI saw Spandam\n\n"


def test_a_human_verdict_is_not_overridden_by_the_secondary_model(tmp_path, monkeypatch):
    """The secondary-model pass must not re-open a line a human has closed.

    The two-pass block (repair.py, the `else:` branch) reassigns `new` AFTER the consult
    has run, so without a guard a stored verdict is admitted and then quietly replaced by
    the second model's wording. The suppression rule makes it worse rather than better: no
    `repair_applied` entry is written for a settled line, so the substituted text reaches
    the viewer with nothing in the queue to show it ever happened.

    C5 says "a stronger model is still a model". A human is not, and outranks both."""
    stem, conf_path = _one_target(tmp_path, "ep_verdict_2pass")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_verdict_2pass.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(
        repair, "llm", lambda prompt, model=None: "I saw Spandam there" if model == "secondary-model" else "I saw Spandom"
    )
    monkeypatch.setattr(repair, "MODEL_SECONDARY", "secondary-model")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (_store("I saw spondum", "I saw Spandam", "accept"), "Show"))

    repair.process(conf_path)

    srt = open(stem + repair.SRT_SUFFIX).read()
    assert "I saw Spandam\n" in srt, "the shipped text must be the one the human approved"
    assert "there" not in srt, "the secondary model must not overwrite a human verdict"


def test_an_accept_verdict_survives_later_drift_in_the_gate(tmp_path, monkeypatch):
    """An `accept` must not be re-judged by accept_repair on every subsequent run.

    accept_repair's answer is not stable across time: LEN_RATIO_MIN/MAX and MAX_REF_BORROW
    are documented operator knobs (repair.py Env), the glossary changes, and `ref` moves if
    the video is re-muxed. When it flips to False for a line a human already approved, two
    things went wrong at once -- the approved text did not ship, AND the line was written
    back to the queue as an ordinary `rejected_guard`, handing the reviewer a decision they
    had already made.

    Simulated here by tightening LEN_RATIO_MAX to 0.9 after the verdict was recorded, which
    refuses the 1.0-ratio pair the human accepted."""
    monkeypatch.setattr(repair, "LEN_RATIO_MAX", 0.9)
    srt, _ = _run_accept_case(tmp_path, monkeypatch, "ep_drift", _store("I saw spondum", "I saw Spandam", "accept"))
    stem = str(tmp_path / "ep_drift")

    assert "I saw Spandam" in srt, "the human's accept outranks a gate that has since drifted"
    requeued = [e for e in unresolved.items(stem) if e["reason"] in ("rejected_guard", "rejected_name_invented")]
    assert requeued == [], "a settled line must never come back as a fresh guard rejection"


def test_the_summary_still_accounts_for_every_target_once_verdicts_fire(tmp_path, monkeypatch):
    """Every targeted card must land in exactly one counted bucket.

    Before [S-4] the summary's buckets covered every target. The two new terminal paths --
    a `reject` verdict, and an applying verdict refused by fits_card -- both `continue`
    without incrementing anything, so `targets` would silently exceed the sum and any
    dashboard treating the buckets as exhaustive would under-count with no field explaining
    the residual. Three cards here: one settled by a reject, one whose `correct` cannot be
    rendered, one ordinary repair."""
    stem = str(tmp_path / "ep_acct")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [
            {"start": 0.0, "end": 2.0, "text": "I saw spondum", "avg_logprob": -0.6, "no_speech_prob": 0.1},
            {"start": 2.0, "end": 4.0, "text": "he went thataway", "avg_logprob": -0.6, "no_speech_prob": 0.1},
            {"start": 4.0, "end": 6.0, "text": "the ship sailed", "avg_logprob": -0.6, "no_speech_prob": 0.1},
        ],
    )

    # By call order, NOT by sniffing the prompt: build_prompt embeds the previous and next
    # card as context, so every card's prompt contains its neighbours' text and a substring
    # match returns card 1's proposal for card 2. Targets are walked in index order.
    outputs = iter(["I saw Spandom", "he went that way", "the ship has sailed"])

    def fake_llm(prompt, model=None):
        return next(outputs)

    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_acct.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 6.0, "the official sub line")])
    monkeypatch.setattr(repair, "llm", fake_llm)
    store = decisions.record({}, "I saw spondum", "I saw Spandam", "reject")
    store = decisions.record(
        store, "he went thataway", "he went that way", "correct", text="he went off along that road over there somewhere"
    )
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))

    repair.process(conf_path)
    s = json.load(open(stem + ".dubtitles.repair-summary.json"))

    assert s["verdict_reject"] == 1, "a reject verdict must be counted, not silently dropped from the accounting"
    assert s["verdict_unfittable"] == 1, "a verdict refused on timing must be counted too"
    counted = (
        s["repaired"] + s["skipped_no_ref"] + s["llm_empty"] + s["rejected_guard"] + s["verdict_reject"] + s["verdict_unfittable"]
    )
    assert counted == s["targets"], f"targets {s['targets']} != sum of buckets {counted}"


def test_a_second_repair_pass_does_not_re_queue_a_line_already_in_the_queue(tmp_path, monkeypatch):
    """merge_pass.sh runs repair on EVERY sweep for an episode that still has an srt.

    An episode held by the [S-6] review gate never gets muxed, so its srt is never removed;
    and `dub_signs_merge.build()` returns "no-signs" before writing any .ass for a
    dialogue-only episode (dub_signs_merge.py:126-127), so merge_pass's
    `! -f .ass && -f .srt` assemble condition stays true forever. repair.py therefore
    re-runs every MERGE_INTERVAL (default 600s) and, without this, appends another
    `repair_applied` row for the same line each time: ~144 copies a day, growing without
    bound, and the reviewer sees one line over and over.

    It also disarms the gate's own stall alert. That alert reads the queue file's mtime,
    and an append refreshes it, so `STALLED` could never fire for exactly the episodes that
    are stuck. Keyed on the (original, proposed) PAIR against every entry in the file,
    resolved or not: keying on pending-only would re-append the moment a human resolved one
    through the --review CLI, which is the deadlock inverted."""
    stem, conf_path = _one_target(tmp_path, "ep_twice")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_twice.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: ({}, "Show"))

    repair.process(conf_path)
    first = os.path.getmtime(unresolved.path_for(stem))
    repair.process(conf_path)

    queued = [e for e in unresolved.items(stem) if e["stage"] == "repair_applied"]
    assert len(queued) == 1, "a second sweep must not re-queue a line the reviewer already has"
    assert os.path.getmtime(unresolved.path_for(stem)) == first, "and must not refresh the staleness clock"


def test_a_changed_proposal_supersedes_the_pending_one_for_that_line(tmp_path, monkeypatch):
    """[F-2]. The re-queue suppression keys on the (original, proposed) PAIR, which is right
    for an identical re-run and wrong for a proposal that changes.

    Change the model, the glossary or the reference and the same ASR line yields Y where it
    yielded X. `(orig, X)` is queued, so `(orig, Y)` is appended alongside it: the reviewer
    sees one card twice with two different proposals, and a verdict on either leaves the
    other pending -- which for a gated show keeps the episode held on a proposal nobody is
    going to ship.

    The superseded entry is RESOLVED rather than deleted. The queue is the audit trail, not
    a worklist that shrinks (`unresolved.resolve`'s docstring), and what the model proposed
    before is exactly the evidence for whether the gate is drifting."""
    stem, conf_path = _one_target(tmp_path, "ep_superseded")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_superseded.mkv"))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 1.0, "the official sub")])
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: ({}, "Show"))

    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam"}))
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    repair.process(conf_path)

    # the glossary changes, so the same line now yields a different proposal
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"], hard_fixes={"Spandom": "Spandam there"}))
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandom")
    repair.process(conf_path)

    applied = [e for e in unresolved.items(stem) if e["stage"] == "repair_applied"]
    pending_now = [e for e in applied if not e.get("resolved")]
    assert len(applied) == 2, "both proposals stay in the audit trail"
    assert len(pending_now) == 1, "but the reviewer is asked about the card ONCE"
    assert pending_now[0]["proposed_text"] == "I saw Spandam there", "and about the proposal that would ship"
    superseded = [e for e in applied if e.get("resolved")]
    assert superseded[0]["note"].startswith("superseded"), "the older one says why it left the queue"


def test_a_show_can_declare_unanchored_repair_in_its_glossary(monkeypatch):
    """A2. Many users hold dub-only copies of shows the maintainer holds in dual audio, so
    the unanchored path is a mainstream configuration, not a One Pace quirk. The declaration
    therefore belongs to the SHOW, in the artifact the repo can commit and reproduce, rather
    than to a hand-set global that no committed file records.

    This drives the whole route on purpose: `glossary.load_dict` normalises a raw glossary
    to an explicit key list and drops everything else, so a field it does not carry never
    reaches the gate however correct the gate is."""
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    gloss = glossary.load_dict({"show": "One Pace", "unanchored_repair": True})
    assert repair.skips_unanchored("", gloss) is False


def test_a_show_that_declares_nothing_keeps_the_closed_default(monkeypatch):
    """The global default stays CLOSED and `skips_unanchored`'s docstring stays the
    authority on why. A show that says nothing must behave exactly as it does today --
    otherwise adding the per-show field would silently open the gate library-wide, which is
    the opposite of what it is for."""
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    gloss = glossary.load_dict({"show": "Sword Art Online"})
    assert repair.skips_unanchored("", gloss) is True
    assert repair.skips_unanchored("some fansub line", gloss) is False


def test_process_honours_the_shows_declaration_not_just_the_global(tmp_path, monkeypatch):
    """A2 wiring. `skips_unanchored` accepting a glossary is inert unless `process` hands it
    one -- and the whole defect this fixes is a gate that was correct in isolation while the
    committed scripts skipped every card and rebuilt raw ASR over the shipped repairs.

    Breaks if `process` calls `skips_unanchored(ref)` without the glossary: the card is
    refused, the LLM is never reached, and skipped_no_ref goes back to 1."""
    stem = str(tmp_path / "ep_declared")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path, srt_path, [{"start": 0.0, "end": 1.0, "text": "garbled line", "avg_logprob": -0.9, "no_speech_prob": 0.1}]
    )

    g = glossary.load_dict({"show": "One Pace", "unanchored_repair": True})
    calls = []
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)  # the global stays shut
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_declared.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])  # no fansub anchor anywhere
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: calls.append(prompt) or "garbled line")

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["skipped_no_ref"] == 0
    assert calls, "the declared show must reach the LLM"


def test_a_pass_that_would_skip_every_target_refuses_to_overwrite_prior_repairs(tmp_path, monkeypatch):
    """A2 guard (c). `repair.process` REBUILDS the srt from conf.json on every run, so when
    the gate is shut and every card is skipped the rebuild is raw ASR -- and it lands ON TOP
    of repairs already shipped. Reproduced on One Pace S31E24: targets=144 repaired=0
    skipped_no_ref=144, and the sidecar came back as `our mods will never give up There's a`
    where the shipped track had `Our mods will never give up. There's a fire...`.

    The episode must abort instead, leaving both the srt and the prior summary untouched, so
    a misconfigured pass is loud rather than quietly destructive.

    Breaks if the guard is removed, if it fires on `repaired > 0`, or if it runs after the
    srt is rewritten rather than before."""
    stem = str(tmp_path / "ep_prior")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 2.0, "text": "our mods will never give up", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    shipped = "1\n00:00:00,000 --> 00:00:02,000\nOur mods will never give up.\n\n"
    open(srt_path, "w").write(shipped)
    prior = {"targets": 144, "repaired": 3, "skipped_no_ref": 0}
    summary_path = stem + ".dubtitles.repair-summary.json"
    json.dump(prior, open(summary_path, "w"))

    g = glossary.load_dict({"show": "One Pace"})  # declares nothing -> gate shut
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_prior.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])  # no fansub anchor anywhere

    assert repair.process(conf_path) == "refused"
    assert open(srt_path).read() == shipped, "the shipped repairs were overwritten with raw ASR"
    assert json.load(open(summary_path))["repaired"] == 3, "the prior summary was clobbered"


def test_the_refusal_is_narrow_and_a_quiet_episode_still_rewrites(tmp_path, monkeypatch):
    """A2 guard (c), mutation check. The guard must fire only when EVERY target was skipped
    for want of an anchor. Loosened to `skipped_no_ref > 0` it would refuse any episode that
    happened to repair nothing while one card lacked a reference -- a normal, harmless
    outcome -- and stall the pipeline on it.

    Here card 1 is anchored and the model proposes nothing; card 2 is unanchored and skipped.
    fixed == 0 and prior repairs exist, so only the `== len(targets)` clause holds it back."""
    stem = str(tmp_path / "ep_quiet")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [
            {"start": 0.0, "end": 2.0, "text": "anchored line", "avg_logprob": -0.9, "no_speech_prob": 0.1},
            {"start": 10.0, "end": 12.0, "text": "unanchored line", "avg_logprob": -0.9, "no_speech_prob": 0.1},
        ],
    )
    json.dump({"targets": 2, "repaired": 3}, open(stem + ".dubtitles.repair-summary.json", "w"))

    g = glossary.load_dict({"show": "One Pace"})
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_quiet.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 2.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "anchored line")  # nothing to fix

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["repaired"] == 0 and summary["skipped_no_ref"] == 1


def test_an_llm_empty_card_still_ships_a_stored_human_correction(tmp_path, monkeypatch):
    """A4. `llm()` returns "" on any transport failure or timeout, and the backend being
    briefly unreachable during a merge pass is an ordinary operational event. Today that
    card `continue`s before the store is consulted, and `process` then rebuilds the whole srt
    from conf.json -- so the reviewer's typed text is replaced by raw ASR while the summary
    records only `llm_empty`, a number that reads as "the model had nothing to say".

    Breaks if the consult stays below the skip branches, or if the rescue does not run when
    the LLM is silent."""
    stem = str(tmp_path / "ep_rescue_empty")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    store = _store("I saw spondum", "I saw Spandam", "correct", text="I saw Spandam.")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_rescue_empty.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 4.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "")  # transport failure

    assert repair.process(conf_path) == "repaired"
    assert "I saw Spandam." in open(srt_path).read(), "the human's text was replaced by raw ASR"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_rescued"] == 1
    assert summary["llm_empty"] == 0, "a rescued card must land in exactly one bucket"


def test_an_unanchored_card_still_ships_a_stored_human_correction(tmp_path, monkeypatch):
    """The same rescue on the other skip branch. One guard where both paths converge, not a
    patch on the one the defect was found in."""
    stem = str(tmp_path / "ep_rescue_noref")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    store = _store("I saw spondum", "I saw Spandam", "correct", text="I saw Spandam.")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_rescue_noref.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])  # no anchor at all
    monkeypatch.setattr(
        repair, "llm", lambda prompt, model=None: (_ for _ in ()).throw(AssertionError("no anchor -> the LLM must not be called"))
    )

    assert repair.process(conf_path) == "repaired"
    assert "I saw Spandam." in open(srt_path).read()
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_rescued"] == 1
    assert summary["skipped_no_ref"] == 0


def test_a_rescued_correction_too_wide_for_one_line_ships_as_two_cues(tmp_path, monkeypatch):
    """The split path applies here too -- apply_human_text is the OTHER writer of a human
    correction (repair.process's own main loop is the first), and the two must not drift
    on what counts as fittable. Same verified fixture as the main-loop split test."""
    half1 = "The captain ordered everyone to abandon ship at once."
    half2 = "Nobody thought twice about it."
    full_text = f"{half1} {half2}"
    stem = str(tmp_path / "ep_rescue_split")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 100.0, "end": 110.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    store = _store("I saw spondum", "I saw Spandam", "correct", text=full_text)
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_rescue_split.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])  # no anchor -> the skip branch

    assert repair.process(conf_path) == "repaired"
    srt = open(srt_path).read()
    assert "abandon ship at once" in srt and "Nobody thought twice" in srt
    assert srt.count(" --> ") == 2
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_rescued"] == 1
    assert summary["verdict_unfittable"] == 0


def test_a_rescued_correction_that_cannot_be_rendered_is_still_refused(tmp_path, monkeypatch):
    """C1 is not relaxed for this path. Card timing is immutable for humans too, so a stored
    correction that cannot be displayed in the card's own duration is refused and counted --
    exactly as `fits_card` refuses one on the ordinary verdict path.

    Breaks if the rescue writes c["text"] before consulting fits_card."""
    stem = str(tmp_path / "ep_rescue_unfit")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 1.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    too_long = "I saw Spandam standing right over there by the gate and he was not alone at all."
    store = _store("I saw spondum", "I saw Spandam", "correct", text=too_long)
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_rescue_unfit.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

    assert repair.process(conf_path) == "repaired"
    shipped = open(srt_path).read()
    assert too_long not in shipped, "an unrenderable human line must not be forced onto the card"
    assert "I saw spondum" in shipped
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_unfittable"] == 1
    assert summary["verdict_rescued"] == 0


def test_a_skipped_card_a_human_ruled_on_is_never_silent(tmp_path, monkeypatch):
    """The acceptance criterion the defect turns on: the summary must distinguish "skipped
    and nothing was owed" from "skipped while a verdict existed". Here the human rejected the
    proposal, so there is no text to ship -- but a reviewer HAD ruled on the line, and a run
    that drops that fact is how the loss went unnoticed for eleven corrections.

    Breaks if the rescue returns None whenever there is no `correct` text, collapsing this
    back into the plain skip bucket."""
    stem = str(tmp_path / "ep_owed")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    store = _store("I saw spondum", "I saw Spandam", "reject")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_owed.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_owed"] == 1
    assert summary["skipped_no_ref"] == 0
    assert "I saw spondum" in open(srt_path).read(), "a rejection leaves the ASR text standing"


def test_a_forced_verdict_on_a_skipped_card_still_ships(tmp_path, monkeypatch):
    """R-force, measured on MARRIAGETOXIN S01E10. `force` is the verdict a reviewer escalates
    to when the automated checks would refuse the line -- so losing it is the worst version
    of the skipped-card bug, not a lesser one. The rescue answered only `correct`, so every
    forced verdict on a card the repair stage skipped shipped raw ASR while the store said
    the line was settled.

    Breaks if apply_human_text drops the forced_text fallback, or if forced_text reads the
    folded `proposed` key instead of the verbatim `text` (which would ship the line
    lowercased -- assert the casing here, not just the presence)."""
    stem = str(tmp_path / "ep_forced")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 4.0, "text": "Hammy Rat Network is online!", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    store = _store("Hammy Rat Network is online!", "Hammy-Rat Network is online!", "force")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_forced.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=[]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

    assert repair.process(conf_path) == "repaired"
    shipped = open(srt_path).read()
    assert "Hammy-Rat Network is online!" in shipped, "the forced wording must reach the srt"
    assert "hammy-rat network" not in shipped, "and must not arrive as the folded match key"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_rescued"] == 1 and summary["verdict_owed"] == 0


def test_an_accept_verdict_on_a_skipped_card_is_owed_not_guessed(tmp_path, monkeypatch):
    """The boundary of the rescue. `accept` endorses the MODEL's wording for a proposal this
    card no longer has -- answering it on the original alone would ship text the reviewer
    approved in a context that no longer exists. It stays owed, and stays visible."""
    stem = str(tmp_path / "ep_accept")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    store = _store("I saw spondum", "I saw Spandam", "accept")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_accept.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_owed"] == 1, "owed, so the reviewer is told rather than guessed for"
    assert "I saw spondum" in open(srt_path).read()


def test_an_approval_orphaned_by_a_new_proposal_is_queued_not_silent(tmp_path, monkeypatch):
    """R-model-change, measured on MARRIAGETOXIN S01E10 when REPAIR_MODEL moved from
    nanbeige4.2-3b to qwen3-4b-instruct.

    A verdict keys on (orig, proposed), and the proposed side is MODEL OUTPUT -- so changing
    the model rewrites the key for every line in the library at once. `lookup` then misses,
    `accept_repair` judges the new wording on its own merits and may ship it, and the store
    still shows the line as settled. The reviewer is never told that what shipped is not
    what they approved; the log even reads `repair_applied / accepted`.

    Breaks if the stale-approval check is dropped, or narrowed to fire only when the new
    proposal is rejected."""
    stem = str(tmp_path / "ep_stale")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    # The human approved the OLD model's wording; the new model proposes something else.
    store = _store("I saw spondum", "I saw Spandam", "accept")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", True)
    monkeypatch.setattr(repair, "llm", lambda *a, **k: "I saw Spandine")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_stale.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam", "Spandine"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_stale_proposal"] == 1, "the orphaned approval must be counted"
    queued = [json.loads(x) for x in open(stem + ".dubtitles.unresolved.jsonl") if x.strip()]
    stale = [q for q in queued if q.get("reason") == "verdict_stale_proposal"]
    assert stale, "and queued, so the reviewer can rule on the new wording"
    assert stale[0]["approved_text"] == "I saw Spandam", "what they had approved"
    assert stale[0]["proposed_text"] == "I saw Spandine", "against what the model now says"
    assert stale[0]["model"] == repair.MODEL, "and which model moved the goalposts"


def test_a_superseded_rejection_is_not_flagged_as_stale(tmp_path, monkeypatch):
    """The boundary, and the reason this is narrowed to APPROVALS. `lookup`'s docstring
    exists to stop one rejection suppressing the proposal that fixes the line -- a new
    proposal arriving after a rejection is the DESIGNED flow, not drift. Flagging those
    would bury the real signal in noise."""
    stem = str(tmp_path / "ep_superseded")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path,
        srt_path,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    store = _store("I saw spondum", "I saw Spandam", "reject")
    monkeypatch.setattr(decisions, "decisions_for", lambda *a, **k: (store, "Show"))
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", True)
    monkeypatch.setattr(repair, "llm", lambda *a, **k: "I saw Spandine")
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_superseded.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam", "Spandine"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

    assert repair.process(conf_path) == "repaired"
    summary = json.load(open(stem + ".dubtitles.repair-summary.json"))
    assert summary["verdict_stale_proposal"] == 0


def test_a_first_run_with_no_anchor_says_so_loudly(tmp_path, monkeypatch, capsys):
    """A3. The beta-user case: dub-only copies, `unanchored_repair` never declared, and no
    prior repairs -- so guard (c) cannot fire, because it only protects work that already
    exists. Every card is skipped, nothing is repaired, and until now the only trace was a
    `skipped_no_ref` count inside a JSON sidecar nobody opens.

    The message has to name the remedy, not just the symptom: a user who does not know the
    setting exists cannot act on "144 targets skipped".

    Breaks if the warning is dropped, or if it fires on an episode that DID repair something
    -- which would train the reader to ignore it."""
    stem = str(tmp_path / "ep_first_run")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 2.0, "text": "garbled line", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    monkeypatch.setattr(repair, "REPAIR_UNANCHORED", False)
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_first_run.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl())
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [])

    assert repair.process(conf_path) == "repaired"
    out = capsys.readouterr().out
    assert "reference" in out.lower(), "the reason must be stated, not just the count"
    assert "skipped" in out.lower()
    assert "unanchored_repair" in out, "the remedy must be named, not just the symptom"


def test_an_episode_that_repaired_something_does_not_get_the_no_anchor_warning(tmp_path, monkeypatch, capsys):
    """The other half of the pair. A warning that fires on healthy episodes is noise, and
    noise is how the real one gets missed."""
    stem = str(tmp_path / "ep_healthy")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_healthy.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: gl(names=["Spandam"]))
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 4.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandam")

    assert repair.process(conf_path) == "repaired"
    assert "unanchored_repair" not in capsys.readouterr().out


def test_a_show_with_no_glossary_is_reported_not_silently_no_opped(tmp_path, monkeypatch, capsys):
    """`glossary_for` falls back to a no-op glossary when no <Show>.json resolves. That is
    the right behaviour -- a missing glossary must never fail an episode -- but doing it
    silently means a user whose GLOSSARY_DIR is misconfigured gets a whole library repaired
    with no names at all and nothing anywhere says why.

    Breaks if the fallback goes back to being silent."""
    stem = str(tmp_path / "ep_nogloss")
    conf_path = stem + repair.CONF_SUFFIX
    _write_conf(
        conf_path,
        stem + repair.SRT_SUFFIX,
        [{"start": 0.0, "end": 4.0, "text": "I saw spondum", "avg_logprob": -0.9, "no_speech_prob": 0.1}],
    )
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_nogloss.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: glossary.load_dict({}))  # nothing resolved
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 4.0, "the official sub")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: "I saw Spandam")

    assert repair.process(conf_path) == "repaired"
    out = capsys.readouterr().out
    assert "glossary" in out.lower() and "GLOSSARY_DIR" in out


def test_a_dead_backend_refuses_the_episode_instead_of_rebuilding_raw_asr(tmp_path, monkeypatch):
    """A transport failure is not "the model left the line alone".

    `llm_llamacpp` returns "" for BOTH a dead endpoint and an empty reply, so with the
    backend down every target lands in `llm_empty`, `fixed` stays 0, and process() rewrites
    the srt from conf.json -- raw ASR over whatever the last run shipped. This is guard
    (c)'s failure mode reached by a different road. Measured 2026-08-31: an accidental
    merge pass with no reachable LLM queued 1,299 llm_empty entries across 11 episodes.
    """
    stem = str(tmp_path / "ep_deadbackend")
    conf_path = stem + repair.CONF_SUFFIX
    srt_path = stem + repair.SRT_SUFFIX
    _write_conf(
        conf_path, srt_path, [{"start": 0.0, "end": 2.0, "text": "garbled line", "avg_logprob": -0.9, "no_speech_prob": 0.1}]
    )
    shipped = open(srt_path, encoding="utf-8").read()

    g = gl()
    monkeypatch.setattr(repair, "find_video", lambda s: str(tmp_path / "ep_deadbackend.mkv"))
    monkeypatch.setattr(repair, "glossary_for", lambda video: g)
    monkeypatch.setattr(repair, "dialogue_intervals", lambda video: [(0.0, 2.0, "a reference line")])
    monkeypatch.setattr(repair, "llm", lambda prompt, model=None: repair.LLM_UNREACHABLE)

    assert repair.process(conf_path) == "refused"
    assert open(srt_path, encoding="utf-8").read() == shipped, "the shipped srt must not be rewritten"
    assert not os.path.exists(stem + ".dubtitles.unresolved.jsonl"), "a dead endpoint is not a review item"
