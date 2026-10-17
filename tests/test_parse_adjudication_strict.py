"""Phase 29 F5: the text-response parser must not turn a malformed canonical into a trusted spelling.

Sol's probe: the reply {"canonical": ["Zoro", "Bogus"], "confidence": "high"} was coerced with str() to the string
"['Zoro', 'Bogus']", which then passed clean_adjudication, qualified as an expansion of Zoro and was saved to `phrases`."""

import json

import pytest

import glossary_verify as gv


@pytest.mark.parametrize(
    "reply",
    [
        '{"canonical": ["Zoro", "Bogus"], "confidence": "high"}',
        '{"canonical": {"x": 1}, "confidence": "high"}',
        '{"canonical": 5, "confidence": "high"}',
        '{"canonical": "Roronoa Zoro", "confidence": ["high"]}',
        '{"canonical": "Roronoa Zoro", "confidence": {"x": 1}}',
    ],
)
def test_a_non_string_field_is_malformed_not_coerced(reply):
    cleaned, bad = gv.clean_adjudication(gv.parse_adjudication_checked(reply)[0])
    assert bad is True
    assert cleaned["confidence"] in ("none", "low") and cleaned["canonical"] in ("", "Roronoa Zoro")
    assert "[" not in cleaned["canonical"] and "{" not in cleaned["canonical"]


def test_a_well_formed_reply_is_unchanged():
    got = gv.parse_adjudication_checked('prose {"canonical": "Roronoa Zoro", "confidence": "HIGH", "dub_note": "dub"} more')[0]
    assert got == {"canonical": "Roronoa Zoro", "confidence": "high", "dub_note": "dub"}
    assert gv.clean_adjudication(got) == ({"canonical": "Roronoa Zoro", "confidence": "high"}, False)


def test_the_real_verify_run_counts_it_malformed_and_writes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"show": "S", "names": ["Zoro"], "phrases": [], "wiki": "https://example.fandom.com/api.php"}))
    raw = '{"canonical":["Zoro","Bogus"],"confidence":"high"}'
    monkeypatch.setattr(gv, "VERIFY_BACKEND", "llamacpp")
    monkeypatch.setattr(gv, "BACKEND_PROBLEM", "")
    monkeypatch.setattr(gv, "backend_problem", lambda backend=None: "")
    monkeypatch.setattr(gv, "resolve_wiki", lambda *a, **k: "https://example.fandom.com/api.php")
    monkeypatch.setattr(gv, "fetch_titles", lambda *a, **k: ["Zoro"])
    monkeypatch.setattr(gv, "llm_chat", lambda *a, **k: raw)
    report = gv.verify(str(path))
    saved = json.loads(path.read_text())
    assert saved["phrases"] == [] and report["applied"] == 0 and report["malformed"] == 1
