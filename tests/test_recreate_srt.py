"""recreate_srt rebuilds an srt from conf.json. conf.json stores FLATTENED text, so the
rebuild must re-wrap or the episode ships as unwrapped single lines -- the library-wide
defect this suite exists to prevent."""
import json

import recreate_srt
import reflow


def _write_conf(tmp_path, cards):
    p = tmp_path / ("ep" + recreate_srt.CONF_SUFFIX)
    p.write_text(json.dumps(cards))
    return str(p)


def _cues(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        if len(lines) >= 3: out.append(lines[2:])
    return out


def test_recreate_rewraps_flattened_conf_text(tmp_path):
    flat = "Now everybody lift your hands up Sing about what you are dreaming"
    assert len(flat) > reflow.MAX_LINE                      # the defect's precondition
    srt = recreate_srt.recreate(_write_conf(tmp_path, [{"start": 0.0, "end": 5.0, "text": flat}]))
    cue = _cues(open(srt).read())[0]
    assert len(cue) == 2
    assert all(len(ln) <= reflow.MAX_LINE for ln in cue)
    assert " ".join(cue) == flat                            # no words lost to wrapping


def test_recreate_skips_an_existing_srt(tmp_path):
    conf = _write_conf(tmp_path, [{"start": 0.0, "end": 5.0, "text": "hi"}])
    (tmp_path / "ep.eng.dubtitles.srt").write_text("existing")
    assert recreate_srt.recreate(conf) is None
    assert (tmp_path / "ep.eng.dubtitles.srt").read_text() == "existing"


def test_short_text_stays_on_one_line(tmp_path):
    srt = recreate_srt.recreate(_write_conf(tmp_path, [{"start": 0.0, "end": 2.0, "text": "Short."}]))
    assert _cues(open(srt).read())[0] == ["Short."]
