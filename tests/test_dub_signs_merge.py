"""Unit tests for dub_signs_merge.py: keep_event() classifier + build() layer ordering."""
import pysubs2

import dub_signs_merge as dsm


def ev(text="hello", style="Default"):
    return pysubs2.SSAEvent(text=text, style=style)


# --- keep_event() matrix -----------------------------------------------------

def test_keep_event_drops_plain_dialogue():
    assert not dsm.keep_event(ev(text="Just talking.", style="Main"))


def test_keep_event_keeps_karaoke():
    # neutral style ("Text") so only the \k tag drives the keep decision
    assert dsm.keep_event(ev(text=r"{\k30}ka{\k30}ra{\k30}o{\k30}ke", style="Text"))


def test_keep_event_keeps_positioned():
    # neutral style ("Text") so only the \pos tag drives the keep decision
    assert dsm.keep_event(ev(text=r"{\pos(100,200)}Sign text", style="Text"))


def test_keep_event_keeps_drawing_p1():
    assert dsm.keep_event(ev(text=r"{\p1}m 0 0 l 100 0 100 100 0 100{\p0}", style="Text"))


def test_keep_event_keeps_drawing_clip():
    assert dsm.keep_event(ev(text=r"{\clip(0,0,100,100)}clipped sign", style="Text"))


def test_keep_event_keeps_animated_transform():
    assert dsm.keep_event(ev(text=r"{\t(0,500,\fscx120\fscy120)}growing sign", style="Text"))


def test_keep_event_keeps_animated_fade():
    assert dsm.keep_event(ev(text=r"{\fade(255,0,0,0,500,1000,1500)}fading sign", style="Text"))


def test_keep_event_drops_translation_style_despite_karaoke():
    # DROP_STYLE precedence: even with karaoke tags, a Translation-style event is dropped
    # because it's the fansub's English song translation, replaced by whisper's Dubtitles.
    assert not dsm.keep_event(ev(text=r"{\k30}some{\k30}translated{\k30}lyrics", style="Song Translation"))


# --- layer ordering in build() -----------------------------------------------

def test_layer_ordering_dub_below_signs(tmp_path, monkeypatch):
    base = pysubs2.SSAFile()
    base.styles["Sign"] = pysubs2.SSAStyle()
    base.styles["Song"] = pysubs2.SSAStyle()

    sign_low = pysubs2.SSAEvent(start=0, end=1000, style="Sign", text="low sign", layer=0)
    sign_high = pysubs2.SSAEvent(start=0, end=1000, style="Song", text="high sign", layer=1)
    base.events = [sign_low, sign_high]

    dub_srt = tmp_path / "dub.srt"
    dub_srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nDub line\n\n",
        encoding="utf-8",
    )

    def fake_eng_sub_streams(video, langs):
        return [0]

    def fake_extract(video, idx, out_path):
        base.save(out_path)
        return True

    monkeypatch.setattr(dsm, "eng_sub_streams", fake_eng_sub_streams)
    monkeypatch.setattr(dsm, "extract", fake_extract)

    out_ass = str(tmp_path / "out.ass")
    status, signs, dub = dsm.build("fake-video.mkv", str(dub_srt), out_ass)

    assert status == "ok"
    result = pysubs2.load(out_ass)

    dub_events = [e for e in result.events if e.style == "Dubtitles"]
    sign_events = [e for e in result.events if e.style != "Dubtitles"]

    assert dub_events, "expected at least one Dubtitles event"
    assert all(e.layer == 0 for e in dub_events)
    assert all(e.layer >= 1 for e in sign_events)

    # relative order between the two signs (originally layer 0 and layer 1) is preserved
    low_after = next(e for e in sign_events if e.plaintext.strip() == "low sign")
    high_after = next(e for e in sign_events if e.plaintext.strip() == "high sign")
    assert low_after.layer == 1
    assert high_after.layer == 2
    assert low_after.layer < high_after.layer


# --- V2 C10: chown failures are logged, not silently swallowed -------------------------

def test_process_one_logs_chown_failure_instead_of_swallowing(tmp_path, monkeypatch, capsys):
    srt = str(tmp_path / ("ep" + dsm.SUFFIX))
    open(srt, "w").close()
    monkeypatch.setattr(dsm, "find_video", lambda stem: str(tmp_path / "ep.mkv"))
    monkeypatch.setattr(dsm, "build", lambda video, srt, out_ass: ("ok", 0, 1))

    def _boom(*a, **kw):
        raise OSError("Operation not permitted")
    monkeypatch.setattr(dsm.os, "chown", _boom)

    assert dsm.process_one(srt) == "merged"  # chown failure must not abort the episode
    assert "chown failed for" in capsys.readouterr().out
