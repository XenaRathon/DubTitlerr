"""The scorer for a bake-off judged against human verdicts rather than against a counter."""

from tools.verdict_bakeoff import judge


def test_exact_match_of_the_humans_typed_text_is_exact():
    assert judge("correct", "The Flame-Flame Fruit.", "the flame flame fruit", "The Flame-Flame Fruit.") == "exact"


def test_right_words_wrong_casing_is_near_not_exact():
    # The failure the recovered store is full of: the model gets the words and misses the
    # capitalisation and hyphenation a human put back. Scoring that as a miss hides how
    # close a model is; scoring it as a hit hides that it is not shippable.
    assert judge("correct", "The Flame-Flame Fruit.", "the flame flame fruit", "the flame flame fruit.") == "near"


def test_leaving_the_line_untouched_is_inert_not_wrong():
    assert (
        judge(
            "accept", "He'll carry out Operation SOP.", "He'll carry out Operation S .O .P.", "He'll carry out Operation S .O .P."
        )
        == "inert"
    )


def test_reproducing_a_rejected_proposal_is_a_trap():
    # The human rejected "Donquixote". A model that proposes it again has failed in the one
    # way a change-counter cannot see: it made an edit, and the edit was the wrong one.
    assert (
        judge(
            "reject",
            "Someone's standing up to the Donquixote family!",
            "Someone's standing up to the Don Quixote family!",
            "Someone's standing up to the Donquixote family!",
        )
        == "trap"
    )


def test_leaving_a_rejected_line_alone_is_exact():
    assert (
        judge(
            "reject",
            "Someone's standing up to the Donquixote family!",
            "Someone's standing up to the Don Quixote family!",
            "Someone's standing up to the Don Quixote family!",
        )
        == "exact"
    )


def test_an_error_marker_is_never_compared_against_the_original():
    assert judge("accept", "x", "y", "<ERROR HTTP 503>") == "error"


def test_an_untouched_line_is_inert_even_when_it_matches_the_answers_words():
    # "hello" is loose-equal to "Hello." -- so whichever of `inert` and `near` is tested
    # first decides this line. It must be `inert`: the model did nothing, and reporting
    # that as near-accuracy is how an inert model wins a bake-off it never competed in.
    assert judge("accept", "Hello.", "hello", "hello") == "inert"


def test_a_correct_verdict_with_no_typed_text_is_dropped_not_backfilled():
    from tools.verdict_bakeoff import targets_from_store

    store = {
        "decisions": [
            {"orig": "a", "proposed": "P", "verdict": "correct", "text": "  "},
            {"orig": "b", "proposed": "Q", "verdict": "correct", "text": "R"},
        ]
    }
    assert targets_from_store(store) == [("b", "R", "correct")]


def test_trap_rate_is_over_the_rejects_only_not_the_whole_set():
    from tools.verdict_bakeoff import tally

    # One reject, fallen into; nine positives. A denominator of 10 would report 10%.
    res = [("reject", "trap")] + [("accept", "exact")] * 9
    assert tally(res)["trap_rate"] == 1.0


def test_hit_rate_counts_only_the_positive_verdicts_in_its_numerator():
    from tools.verdict_bakeoff import tally

    # A reject correctly left alone scores "exact", but it is not a hit against an answer --
    # there was no answer to find. Counting it over a positives-only denominator produced a
    # 167% hit rate on the first live run.
    res = [("reject", "exact"), ("reject", "exact"), ("accept", "exact")]
    assert tally(res)["hit_rate"] == 1.0
