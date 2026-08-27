"""Tests for tools/recover_dub_srt.py — rebuilding the dub-dialogue sidecar without a GPU.

A transcribe-tier bump makes every episode regenerate. For the ~2/3 of the library
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
    p = _muxed_track(tmp_path, [_dub(0, 1000, "First line."), _sign(0, 1000), _dub(2000, 3000, "Second line.")])
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


# --- SRT-origin dubtitle tracks ----------------------------------------------
#
# An episode whose release ships no embedded signs never gets an .ass: the merge returns
# "no-signs" and mux embeds the .srt directly, so its Dubtitles track is codec subrip.
# pysubs2 loads that with every event styled "Default", so filtering on the "Dubtitles"
# style threw the whole episode away and reported no-dialogue. Those tracks hold nothing
# BUT our dialogue -- there are no signs in them to confuse with it -- so every event
# counts.


def _srt_track(tmp_path, lines):
    p = tmp_path / "ep.srt"
    body = ""
    for i, (start, end, text) in enumerate(lines, 1):
        body += f"{i}\n{start} --> {end}\n{text}\n\n"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_srt_origin_track_yields_all_its_events(tmp_path):
    p = _srt_track(tmp_path, [("00:00:01,000", "00:00:02,000", "First line."), ("00:00:03,000", "00:00:04,000", "Second line.")])
    lines = rec.dub_events(p, srt_origin=True)
    assert [e.plaintext for e in lines] == ["First line.", "Second line."]


def test_ass_track_still_ignores_everything_but_the_dubtitles_style(tmp_path):
    """The srt_origin escape hatch must not leak into the .ass path, where the non-
    Dubtitles events are the signs the rebuild is replacing."""
    p = _muxed_track(tmp_path, [_dub(0, 1000, "Dialogue."), _sign(0, 1000)])
    assert [e.plaintext for e in rec.dub_events(p, srt_origin=False)] == ["Dialogue."]


def test_recover_reads_the_codec_and_uses_it(tmp_path, monkeypatch):
    """recover() has to learn srt-ness from ffprobe: by the time pysubs2 has parsed the
    file, an SRT and a style-less ASS are indistinguishable."""
    src = _srt_track(tmp_path, [("00:00:01,000", "00:00:02,000", "Only line.")])
    monkeypatch.setattr(rec, "our_track_index", lambda v: (7, "subrip"))
    monkeypatch.setattr(rec, "extract_sub", lambda v, i, out: __import__("shutil").copy(src, out) or True)
    out = str(tmp_path / "ep.eng.dubtitles.srt")
    assert rec.recover(str(tmp_path / "ep.mkv"), out) == "recovered"
    assert "Only line." in open(out, encoding="utf-8").read()


# --- a style-less ASS track is dialogue too ------------------------------------
#
# Found by an integrity sweep: one episode's Dubtitles track is codec ASS yet every event
# is styled "Default" -- an SRT that reached the container as ASS. Keying srt-ness off the
# codec alone sent it down the ASS path, where the style filter matched nothing and the
# episode reported no-dialogue, leaving it stuck at v1 with no sidecar and no conf.json:
# invisible to merge_pass forever.
#
# Our track only ever holds our own output, and mux refuses to write one with no dialogue
# in it. So a track with ZERO "Dubtitles"-styled events cannot be signs-only -- it is
# dialogue that simply isn't carrying our style name.


def test_ass_track_with_no_dubtitles_style_falls_back_to_every_event(tmp_path):
    subs = pysubs2.SSAFile()
    subs.styles["Default"] = pysubs2.SSAStyle()
    subs.events = [
        pysubs2.SSAEvent(start=0, end=1000, style="Default", text="The name's Boxxo!"),
        pysubs2.SSAEvent(start=2000, end=3000, style="Default", text="Hello, there!"),
    ]
    p = tmp_path / "ep.ass"
    subs.save(str(p))
    got = [e.plaintext for e in rec.dub_events(str(p))]
    assert got == ["The name's Boxxo!", "Hello, there!"]


def test_fallback_does_not_fire_when_dubtitles_events_exist(tmp_path):
    """With even one Dubtitles-styled event present the track is a real merge, and the
    others are the signs being replaced -- importing them would be the original bug."""
    p = _muxed_track(tmp_path, [_dub(0, 1000, "Real dialogue."), _sign(0, 1000)])
    assert [e.plaintext for e in rec.dub_events(p)] == ["Real dialogue."]
