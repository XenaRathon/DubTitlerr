"""Tests for tools/recover_dub_srt.py — rebuilding the dub-dialogue sidecar without a GPU.

A PIPELINE_VERSION bump makes every episode regenerate. For the ~2/3 of the library
that still has its ``<stem>.dubtitles.conf.json``, recreate_srt.py rebuilds the sidecar
and repair.py re-runs normally. The rest have nothing left on disk — their only surviving
copy of the dub dialogue is the muxed "Dubtitles" track itself, whose Dubtitles-styled
events ARE the finished dialogue (the sign events beside them are the ones we're
regenerating). Lifting those events back out is what makes a full-library rebuild cost
hours of remuxing instead of days of Whisper on a 6 GB 1060.

This is the one place the pipeline reads its own output on purpose. It is not a context
leak: the recovered lines go straight back out as dialogue, and repair.py skips an
episode with no conf.json, so nothing re-repairs text that was already repaired.
"""
import pysubs2
import pytest

from tools import recover_dub_srt as rec


def _muxed_track(tmp_path, events, name="ep.ass"):
    subs = pysubs2.SSAFile()
    subs.styles["Dubtitles"] = pysubs2.SSAStyle()
    subs.styles["Credits"] = pysubs2.SSAStyle()
    subs.events = events
    p = tmp_path / name
    subs.save(str(p))
    return str(p)


def _dub(start, end, text):
    return pysubs2.SSAEvent(start=start, end=end, style="Dubtitles", text=text)


def _sign(start, end, text=r"{\pos(10,20)}a sign"):
    return pysubs2.SSAEvent(start=start, end=end, style="Credits", text=text, layer=1)


# --- extracting the dialogue back out ----------------------------------------

def test_extracts_only_the_dubtitles_styled_events(tmp_path):
    """The signs sitting in the same track are exactly what the rebuild replaces —
    carrying them into the new sidecar would re-merge last version's broken signs."""
    p = _muxed_track(tmp_path, [_dub(0, 1000, "First line."),
                                _sign(0, 1000),
                                _dub(2000, 3000, "Second line.")])
    lines = rec.dub_events(p)
    assert [e.plaintext for e in lines] == ["First line.", "Second line."]


def test_keeps_timings_intact(tmp_path):
    p = _muxed_track(tmp_path, [_dub(1500, 4250, "Timed line.")])
    e = rec.dub_events(p)[0]
    assert (e.start, e.end) == (1500, 4250)


def test_strips_override_tags_from_the_recovered_text(tmp_path):
    """The sidecar is an SRT. A stray override tag would be rendered literally when the
    merge re-imports it under the Dubtitles style."""
    p = _muxed_track(tmp_path, [_dub(0, 1000, r"{\i1}Whispered.{\i0}")])
    assert rec.dub_events(p)[0].plaintext == "Whispered."


def test_returns_nothing_when_the_track_has_no_dubtitles_events(tmp_path):
    """A track of ours that somehow holds only signs must not yield an empty sidecar that
    the merge would then treat as a finished episode."""
    p = _muxed_track(tmp_path, [_sign(0, 1000)])
    assert rec.dub_events(p) == []


# --- writing the sidecar ------------------------------------------------------

def test_writes_a_well_formed_srt(tmp_path):
    p = _muxed_track(tmp_path, [_dub(0, 1500, "Hello."), _dub(2000, 3000, "Goodbye.")])
    out = str(tmp_path / "ep.eng.dubtitles.srt")
    assert rec.write_srt(rec.dub_events(p), out) == 2
    body = open(out, encoding="utf-8").read()
    assert body.startswith("1\n00:00:00,000 --> 00:00:01,500\nHello.\n\n")
    assert "2\n00:00:02,000 --> 00:00:03,000\nGoodbye." in body


def test_refuses_to_write_an_empty_sidecar(tmp_path):
    """An empty .srt would make merge_pass assemble an empty .ass and mux a dubtitle
    track with no dialogue in it — silently destroying the episode's dubtitles."""
    out = str(tmp_path / "ep.eng.dubtitles.srt")
    with pytest.raises(ValueError):
        rec.write_srt([], out)
    assert not __import__("os").path.exists(out)


def test_never_overwrites_an_existing_sidecar(tmp_path):
    """If a sidecar is already on disk it is either this rebuild's fresh work or a
    conf.json-derived one, both of which are better than a recovered copy."""
    out = tmp_path / "ep.eng.dubtitles.srt"
    out.write_text("existing", encoding="utf-8")
    p = _muxed_track(tmp_path, [_dub(0, 1000, "New.")])
    assert rec.recover(p, str(out)) == "exists"
    assert out.read_text(encoding="utf-8") == "existing"
