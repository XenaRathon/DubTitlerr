"""Unit tests for dub_signs_merge.py: keep_event() classifier + build() layer ordering."""

import pysubs2

import common
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


def test_keep_event_keeps_the_fansub_translation_style():
    # Reversed 2026-09-02 (.procoder/todo/20260830-drop-transcribed-song-lyrics-restore-
    # fansub-translation.md): a "Song Translation" style used to be dropped on the
    # assumption whisper's transcribed lyrics would replace it, which only holds if the
    # dub re-sings the song in English. On a Japanese-sung opening nothing replaces it, and
    # what lands instead is hallucination -- so the fansub's own translation is kept now,
    # and build() drops the whisper cards over that span instead (see _song_spans tests).
    assert dsm.keep_event(ev(text=r"{\k30}some{\k30}translated{\k30}lyrics", style="Song Translation"))


def test_keep_event_keeps_song_family_kanji_and_english_siblings():
    # Real style names from SAO's own wiki: the Romaji sibling already matched KEEP_STYLE's
    # "romaji", but Kanji/Japanese/English siblings matched nothing and fell through to
    # "assume dialogue, drop" -- half of each song's on-screen text silently missing.
    assert dsm.keep_event(ev(text="karaoke text", style="Opening-Kanji-L1"))
    assert dsm.keep_event(ev(text="karaoke text", style="ED1-Japanese"))
    assert dsm.keep_event(ev(text="karaoke text", style="ED1-English"))


def test_keep_event_song_family_beats_weak_drop_guess():
    # "ED1-Default" isn't a real observed style name, but it exercises the same precedence
    # bug WEAK_DROP_STYLE's "default" guess caused elsewhere: an unambiguous song-family
    # prefix must win over a style-name guess, the same way an unambiguous tag already does.
    assert dsm.keep_event(ev(text="plain lyric, no tags", style="ED1-Default"))


def test_keep_event_keeps_positioned_sign_even_on_a_style_named_default():
    # Real bug, MARRIAGETOXIN S01E01: the release's OWN signs/songs track uses "Default"
    # as its style name (many groups do -- it isn't reserved for dialogue). DROP_STYLE's
    # generic dialogue-name guess ("default") used to fire unconditionally and drop the
    # event before its \pos tag was ever checked -- 15 of 16 real signs in that episode
    # all silently vanished. A style-name GUESS must yield to an unambiguous tag signal.
    assert dsm.keep_event(ev(text=r"{\pos(100,200)}Sign text", style="Default"))


def test_keep_event_still_drops_untagged_plain_text_on_a_weak_drop_style():
    # The residual, ACCEPTED gap: with no tag signal at all, an ambiguous style name still
    # falls back to "assume dialogue" -- there is nothing else to disambiguate it on.
    assert not dsm.keep_event(ev(text="Just a caption, no tags.", style="Default"))


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

    def fake_signs_sub_streams(video, langs):
        return [0]

    def fake_extract(video, idx, out_path):
        base.save(out_path)
        return True

    monkeypatch.setattr(dsm, "signs_sub_streams", fake_signs_sub_streams)
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


# --- V2 Phase D: diagnostic logging (D1/D3/D4/D5) ----------------------------


def _two_track_build(tmp_path, monkeypatch, track0, track1):
    """Common scaffold: two fake source tracks (SSAFile objects), one dub line."""
    dub_srt = tmp_path / "dub.srt"
    dub_srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nDub line\n\n",
        encoding="utf-8",
    )

    def fake_signs_sub_streams(video, langs):
        return [0, 1]

    tracks = {0: track0, 1: track1}

    def fake_extract(video, idx, out_path):
        tracks[idx].save(out_path)
        return True

    monkeypatch.setattr(dsm, "signs_sub_streams", fake_signs_sub_streams)
    monkeypatch.setattr(dsm, "extract", fake_extract)

    out_ass = str(tmp_path / "out.ass")
    status, signs, dub = dsm.build("fake-video.mkv", str(dub_srt), out_ass)
    return status, signs, dub, out_ass


def _sign_track(style_name="Sign", fontname="Arial", fontsize=40.0, text="a sign"):
    t = pysubs2.SSAFile()
    st = pysubs2.SSAStyle()
    st.fontname = fontname
    st.fontsize = fontsize
    t.styles[style_name] = st
    t.events = [pysubs2.SSAEvent(start=0, end=1000, style=style_name, text=r"{\pos(100,200)}" + text)]
    return t


def test_style_conflict_logged_when_font_or_size_differ(tmp_path, monkeypatch, capsys):
    track0 = _sign_track(fontname="Arial", fontsize=40.0, text="first")
    track1 = _sign_track(fontname="Comic Sans MS", fontsize=50.0, text="second")

    status, *_ = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    out = capsys.readouterr().out
    assert "style conflict: 'Sign' — font/size differ, using first definition" in out


def test_style_no_conflict_logged_when_identical(tmp_path, monkeypatch, capsys):
    track0 = _sign_track(fontname="Arial", fontsize=40.0, text="first")
    track1 = _sign_track(fontname="Arial", fontsize=40.0, text="second")

    status, *_ = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    assert "style conflict" not in capsys.readouterr().out


def test_style_conflict_keeps_first_definition(tmp_path, monkeypatch):
    track0 = _sign_track(fontname="Arial", fontsize=40.0, text="first")
    track1 = _sign_track(fontname="Comic Sans MS", fontsize=50.0, text="second")

    status, _signs, _dub, out_ass = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    result = pysubs2.load(out_ass)
    assert result.styles["Sign"].fontname == "Arial"  # first definition wins (unchanged)
    assert result.styles["Sign"].fontsize == 40.0


def test_wrapstyle_difference_logged(tmp_path, monkeypatch, capsys):
    track0 = _sign_track(text="first")
    track0.info["WrapStyle"] = "0"
    track1 = _sign_track(text="second")
    track1.info["WrapStyle"] = "2"

    status, *_ = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    assert "WrapStyle differs: base=0 track=2 — using base" in capsys.readouterr().out


def test_wrapstyle_no_log_when_same(tmp_path, monkeypatch, capsys):
    track0 = _sign_track(text="first")
    track0.info["WrapStyle"] = "1"
    track1 = _sign_track(text="second")
    track1.info["WrapStyle"] = "1"

    status, *_ = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    assert "WrapStyle differs" not in capsys.readouterr().out


def test_scaled_border_and_shadow_forced_yes(tmp_path, monkeypatch):
    track0 = _sign_track(text="first")
    track0.info["ScaledBorderAndShadow"] = "no"  # source disagrees; must be overridden
    track1 = _sign_track(text="second")

    status, _signs, _dub, out_ass = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    result = pysubs2.load(out_ass)
    assert result.info.get("ScaledBorderAndShadow") == "yes"


def test_resolution_mismatch_warns_without_dropping_events(tmp_path, monkeypatch, capsys):
    track0 = _sign_track(text="first")
    track0.info["PlayResX"] = "1280"
    track0.info["PlayResY"] = "720"
    track1 = _sign_track(text="second")
    track1.info["PlayResX"] = "1920"
    track1.info["PlayResY"] = "1080"

    status, signs, _dub, out_ass = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    assert "WARNING: resolution mismatch between subtitle tracks" in capsys.readouterr().out
    assert signs == 2  # WARN ONLY -- both tracks' events still kept, no coordinate transform (V3)
    result = pysubs2.load(out_ass)
    assert {e.plaintext.strip() for e in result.events if e.style == "Sign"} == {"first", "second"}


def test_resolution_no_mismatch_no_warning(tmp_path, monkeypatch, capsys):
    track0 = _sign_track(text="first")
    track0.info["PlayResX"] = "1280"
    track0.info["PlayResY"] = "720"
    track1 = _sign_track(text="second")
    track1.info["PlayResX"] = "1280"
    track1.info["PlayResY"] = "720"

    status, *_ = _two_track_build(tmp_path, monkeypatch, track0, track1)

    assert status == "ok"
    assert "resolution mismatch" not in capsys.readouterr().out


# --- context isolation: the signs/songs source is never our own old dubtitle ---
#
# dub_signs_merge imports common.signs_sub_streams directly, so it inherits the TRACK_NAME
# exclusion with no code of its own. These two cases pin that inheritance end-to-end
# (real common.signs_sub_streams, ffprobe stubbed) rather than through a monkeypatched
# signs_sub_streams, which would only ever test the stub.


def _ffprobe_streams(monkeypatch, streams):
    import json as _json
    import types as _types

    def run(cmd, **kw):
        return _types.SimpleNamespace(stdout=_json.dumps({"streams": streams}), returncode=0)

    monkeypatch.setattr(common, "subprocess", _types.SimpleNamespace(run=run, DEVNULL=-3))


def _ass_stream(index, title=None, lang="eng"):
    tags = {"language": lang}
    if title is not None:
        tags["title"] = title
    return {"index": index, "codec_name": "ass", "tags": tags}


def test_build_reads_the_fansub_and_never_our_old_dubtitles_track(monkeypatch, tmp_path):
    extracted = []
    _ffprobe_streams(monkeypatch, [_ass_stream(2, title="English (Fansub)"), _ass_stream(3, title=common.TRACK_NAME)])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: extracted.append(idx) or False)
    dsm.build("fake-video.mkv", str(tmp_path / "dub.srt"), str(tmp_path / "out.ass"))
    assert extracted == [2]  # signs are lifted from the fansub only


def test_build_finds_no_signs_when_the_only_sub_is_our_dubtitle(monkeypatch, tmp_path):
    """No fallback: rather than re-lifting last version's signs out of our own output,
    the merge reports no-signs."""
    extracted = []
    _ffprobe_streams(monkeypatch, [_ass_stream(3, title=common.TRACK_NAME)])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: extracted.append(idx) or False)
    status, signs, added = dsm.build("fake-video.mkv", str(tmp_path / "dub.srt"), str(tmp_path / "out.ass"))
    assert status == "no-signs"
    assert extracted == []


# --- multi-layer typeset compositions must survive dedup ----------------------
#
# Fansub typesetters build a sign out of SEVERAL events stacked on the same
# \pos: a black backing copy on the low layer supplying the stroke/drop-shadow,
# and the visible copy on the layer above (often \bord0 plus a \t() that
# animates the fill to white). They share start, end, style and — because the
# colour lives entirely in override tags — identical PLAINTEXT.
#
# The dedup key used to be (start, end, style, plaintext), which collapsed such
# a pair to its FIRST member: the black backing layer. Every One Pace credit and
# caption rendered as solid black text instead of white-with-black-stroke, and
# the counts halved (Credits-207+ 32 source events -> 16 merged).


def _layered_track(style_name="Credits"):
    """One track holding a real two-layer composition (black backing + white top)."""
    t = pysubs2.SSAFile()
    t.styles[style_name] = pysubs2.SSAStyle()
    t.events = [
        pysubs2.SSAEvent(
            start=10, end=3490, style=style_name, layer=0, text=r"{\pos(100,922)\bord3\c&H000000&\1a&H00&}Video Editing"
        ),
        pysubs2.SSAEvent(
            start=10,
            end=3490,
            style=style_name,
            layer=1,
            text=r"{\pos(100,922)\bord0\c&H000000&\t(0,1001,1,\c&HFFFFFF&)}Video Editing",
        ),
    ]
    return t


def test_build_keeps_both_layers_of_a_stacked_sign(tmp_path, monkeypatch):
    """The white top layer must not be discarded as a duplicate of the black backing."""
    track = _layered_track()
    status, signs, dub, out_ass = _two_track_build(tmp_path, monkeypatch, track, pysubs2.SSAFile())
    assert status == "ok"
    result = pysubs2.load(out_ass)
    kept = [e for e in result.events if e.style == "Credits"]
    assert len(kept) == 2, "the stacked composition was collapsed to one layer"
    assert any(r"\c&HFFFFFF&" in e.text for e in kept), "the white top layer was dropped"


def test_build_still_dedups_the_same_sign_carried_by_two_tracks(tmp_path, monkeypatch):
    """Releases ship the same sign in both the full track and the signs/songs track.
    Byte-identical events must still collapse to one, or every sign renders twice."""
    status, signs, dub, out_ass = _two_track_build(tmp_path, monkeypatch, _layered_track(), _layered_track())
    assert status == "ok"
    result = pysubs2.load(out_ass)
    assert len([e for e in result.events if e.style == "Credits"]) == 2


# --- song-span drop: whisper's OP/ED hallucinations dropped, fansub lyrics kept --------
#
# .procoder/todo/20260830-drop-transcribed-song-lyrics-restore-fansub-translation.md.
# Measured on SAO S01E02: whisper mangles a Japanese-sung opening into pseudo-romaji and
# then invents English outright (avg_logprob -1.7 to -4.1 against -0.3/-0.7 for ordinary
# dialogue). The fansub's own Romaji/Kanji/English lyrics are kept (KEEP_STYLE/
# SONG_FAMILY_STYLE); the whisper cards timed inside that span are dropped instead.


def _song_track():
    """One signs track with an 'Opening' song block (0-5000ms) built from several
    syllable-timed events, the way a real karaoke track is -- not one event per song."""
    t = pysubs2.SSAFile()
    t.styles["Opening-Romaji-L1"] = pysubs2.SSAStyle()
    t.styles["Opening-English"] = pysubs2.SSAStyle()
    t.styles["Signs"] = pysubs2.SSAStyle()
    t.events = [
        pysubs2.SSAEvent(start=0, end=2000, style="Opening-Romaji-L1", text=r"{\k100}mi{\k100}so{\k100}ra"),
        pysubs2.SSAEvent(start=2000, end=5000, style="Opening-English", text="the translated lyric"),
        pysubs2.SSAEvent(start=20000, end=21000, style="Signs", text=r"{\pos(100,200)}a shop sign"),
    ]
    return t


def _dub_srt_with_cards(tmp_path):
    dub_srt = tmp_path / "dub.srt"
    dub_srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nWhisper hallucination during the OP\n\n"
        "2\n00:00:25,000 --> 00:00:27,000\nReal spoken dialogue after the OP\n\n",
        encoding="utf-8",
    )
    return str(dub_srt)


def test_dub_card_inside_a_song_span_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [0])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: _song_track().save(out) or True)
    out_ass = str(tmp_path / "out.ass")

    status, signs, dub = dsm.build("fake-video.mkv", _dub_srt_with_cards(tmp_path), out_ass)

    assert status == "ok"
    result = pysubs2.load(out_ass)
    dub_texts = {e.plaintext.strip() for e in result.events if e.style == "Dubtitles"}
    assert "Whisper hallucination during the OP" not in dub_texts
    assert "Real spoken dialogue after the OP" in dub_texts
    assert dub == 1  # only the surviving card counted


def test_fansub_song_lyrics_survive_alongside_the_drop(tmp_path, monkeypatch):
    monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [0])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: _song_track().save(out) or True)
    out_ass = str(tmp_path / "out.ass")

    dsm.build("fake-video.mkv", _dub_srt_with_cards(tmp_path), out_ass)

    result = pysubs2.load(out_ass)
    kept_texts = {e.plaintext.strip() for e in result.events if e.style != "Dubtitles"}
    assert "misora" in kept_texts  # Romaji sibling
    assert "the translated lyric" in kept_texts  # English sibling -- the reversed behaviour
    assert "a shop sign" in kept_texts  # ordinary sign, unaffected


def test_song_span_drop_logs_the_count(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [0])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: _song_track().save(out) or True)
    dsm.build("fake-video.mkv", _dub_srt_with_cards(tmp_path), str(tmp_path / "out.ass"))
    assert "song-span dropped 1 whisper dub card" in capsys.readouterr().out


def test_no_song_family_styles_means_no_drop_one_pace_case(tmp_path, monkeypatch):
    """One Pace has no chapters and no OP/ED at all -- a signs track with ordinary sign
    events only must leave every dub card untouched."""
    track = pysubs2.SSAFile()
    track.styles["Signs"] = pysubs2.SSAStyle()
    track.events = [pysubs2.SSAEvent(start=0, end=1000, style="Signs", text=r"{\pos(1,1)}a sign")]
    monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [0])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: track.save(out) or True)

    status, signs, dub = dsm.build("fake-video.mkv", _dub_srt_with_cards(tmp_path), str(tmp_path / "out.ass"))

    assert status == "ok"
    assert dub == 2  # both dub cards survive -- nothing classified as a song span


# --- _song_spans boundaries: what the 2s merge gap includes and excludes ------
#
# R-2 (2026-09-02 beta review). The drop deletes dialogue over a blanket interval, and the
# only production evidence for it is a single read-only SAO S01E02 run this repository
# cannot reproduce. These pin the boundary behaviour of the pure functions so that a change
# to SONG_SPAN_MERGE_GAP_MS, or to the merge itself, is visible in the suite rather than in
# a shipped track. Two of them pin a KNOWN CEILING, not desirable behaviour; each says so.


def _spans(*pairs):
    """_song_spans over song-family-styled events with the given (start, end) ms."""
    evs = [pysubs2.SSAEvent(start=s, end=e, style="Opening-Romaji-L1") for s, e in pairs]
    return dsm._song_spans(evs)


def test_song_events_closer_than_the_gap_merge_into_one_span():
    """The case the gap exists for: SAO E02's opening is 2,142 syllable events, and each
    adjacent pair must collapse into the one span that matters."""
    assert _spans((0, 1000), (1500, 2500)) == [[0, 2500]]


def test_song_events_further_apart_than_the_gap_stay_separate_spans():
    """An OP and an ED are minutes apart. Ordinary dialogue between them must not sit
    inside a merged span."""
    assert _spans((0, 1000), (90000, 95000)) == [[0, 1000], [90000, 95000]]


def test_a_slow_ballad_leaves_its_own_gaps_uncovered_known_ceiling():
    """KNOWN CEILING, pinned deliberately. A ballad whose lyric events are more than 2s
    apart yields one span per line, not one span per song, so a whisper hallucination
    sitting in the instrumental gap is NOT dropped. That is under-drop -- the shipped track
    keeps a hallucinated card -- which is strictly safer than deleting real dialogue, and
    is why widening the gap is not the automatic answer. If a measured ballad shows this
    firing, the fix is per-event avg_logprob gating (see the debt: note in build()), not a
    larger blanket interval."""
    spans = _spans((0, 1000), (4000, 5000), (8000, 9000))
    assert spans == [[0, 1000], [4000, 5000], [8000, 9000]]
    assert not dsm._overlaps_any(2000, 3000, spans), "the gap is uncovered -- by design, for now"


def test_dialogue_inside_a_bridged_gap_is_dropped_known_ceiling():
    """KNOWN CEILING, pinned deliberately, and the sharpest edge of the whole feature: the
    merge extends a span ACROSS the gap between two song events, so a dub card that
    overlaps NEITHER event is still dropped. Two events 1.5s apart bridge into [0, 3500],
    and a card at [1800, 2200] -- entirely between the two lyrics -- is deleted.

    This is over-drop: it removes text, and the removal is silent apart from the count in
    the log line. It is bounded to the sub-2s window between two song-styled events, which
    no measured release has put dialogue into. Revisit with the same avg_logprob gate the
    build() debt: note names."""
    spans = _spans((0, 1000), (2500, 3500))
    assert spans == [[0, 3500]], "the 1.5s gap is under the 2s merge threshold"
    assert dsm._overlaps_any(1800, 2200, spans), "a card in the bridged gap is dropped"


def test_narration_over_an_opening_is_dropped_known_ceiling(tmp_path, monkeypatch):
    """KNOWN CEILING, pinned deliberately, end to end. A show that narrates over its OP
    loses that narration from the dub track along with the lyrics -- the build() debt: note
    is the record of that trade. This test is what fires when someone gates the drop on
    confidence instead of on the span."""
    monkeypatch.setattr(dsm, "signs_sub_streams", lambda video, langs: [0])
    monkeypatch.setattr(dsm, "extract", lambda video, idx, out: _song_track().save(out) or True)
    dub_srt = tmp_path / "dub.srt"
    dub_srt.write_text(
        "1\n00:00:02,500 --> 00:00:04,500\nMy name is Kirito, and this is how it started.\n\n"
        "2\n00:00:25,000 --> 00:00:27,000\nReal spoken dialogue after the OP\n\n",
        encoding="utf-8",
    )

    status, _signs, dub = dsm.build("fake-video.mkv", str(dub_srt), str(tmp_path / "out.ass"))

    assert status == "ok"
    assert dub == 1, "the narration is dropped with the song span -- documented, not desired"
