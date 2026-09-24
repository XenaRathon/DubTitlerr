"""Unit tests for tools/sns_extract.py: off_default_position()/classify_event() with
programmatic pysubs2.SSAEvent fixtures (no .ass files exist in tests/fixtures -- same
pattern as tests/test_dub_signs_merge.py's ev() helper)."""

import pysubs2
import sns_extract as sns

PLAY_RES_Y = 288


def ev(text="hello", style="Default"):
    return pysubs2.SSAEvent(text=text, style=style)


# --- classify_event() matrix -------------------------------------------------


def test_classify_event_keeps_positioned_sign():
    e = ev(text=r"{\pos(400,50)}Sign text", style="Text")
    assert sns.classify_event(e, PLAY_RES_Y) in ("keep", "position_only")


def test_classify_event_keeps_karaoke():
    e = ev(text=r"{\k30}ka{\k30}ra{\k30}o{\k30}ke", style="Text")
    assert sns.classify_event(e, PLAY_RES_Y) in ("keep", "position_only")


def test_classify_event_drops_plain_dialogue():
    e = ev(text="Just talking.", style="Main")
    assert sns.classify_event(e, PLAY_RES_Y) == "drop"


def test_classify_event_an8_top_alignment_counted_position_only():
    # A KNOWN FP class: plain dialogue top-aligned with \an8 and nothing else --
    # dub_signs_merge.keep_event would ALSO return True for this (its own POSITIONED
    # regex matches \an8), but off_default_position is checked first here so the
    # reason attributes to "position_only", not "keep" -- see module docstring.
    e = ev(text=r"{\an8}Top-aligned dialogue, not actually a sign.", style="Default")
    assert sns.off_default_position(e, PLAY_RES_Y) is True
    assert sns.classify_event(e, PLAY_RES_Y) == "position_only"


def test_classify_event_keeps_credits_style():
    e = ev(text="Directed by Someone", style="Credits")
    assert sns.classify_event(e, PLAY_RES_Y) == "keep"


def test_off_default_position_false_for_an2_bottom_center():
    e = ev(text=r"{\an2}Bottom-center dialogue.", style="Default")
    assert sns.off_default_position(e, PLAY_RES_Y) is False


def test_off_default_position_false_with_no_override_tags():
    e = ev(text="Plain line, no tags at all.", style="Default")
    assert sns.off_default_position(e, PLAY_RES_Y) is False


def test_off_default_position_true_for_move_near_top():
    e = ev(text=r"{\move(100,50,300,50)}Moving sign", style="Text")
    assert sns.off_default_position(e, PLAY_RES_Y) is True


# --- mixed-track counting -----------------------------------------------------


def test_extract_counts_a_mixed_track(tmp_path):
    subs = pysubs2.SSAFile()
    subs.info["PlayResY"] = "288"
    subs.append(ev(text="Just talking.", style="Main"))  # drop
    subs.append(ev(text=r"{\k30}ka{\k30}ra", style="Text"))  # keep or position_only
    subs.append(ev(text=r"{\an8}Top dialogue.", style="Default"))  # position_only
    subs.append(ev(text="Directed by Someone", style="Credits"))  # keep
    src = tmp_path / "track.ass"
    subs.save(str(src))

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    kept, counts = sns.extract(str(src), str(out_dir))

    assert counts[("Main", "drop")] == 1
    assert counts[("Default", "position_only")] == 1
    assert counts[("Credits", "keep")] == 1
    assert len(kept.events) == 3  # everything except the dropped "Main" line
    assert (out_dir / "track.sns.ass").exists()
