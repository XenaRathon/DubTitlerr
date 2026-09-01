"""MERGE_WINDOW: the hours in which a merge sweep may run."""

import common


def test_no_window_configured_always_runs():
    # Empty is the default and must behave exactly as before this existed.
    assert common.within_window("", 3, 0) is True


def test_a_daytime_window_includes_its_own_hours():
    assert common.within_window("09:00-17:00", 12, 0) is True
    assert common.within_window("09:00-17:00", 3, 0) is False


def test_a_window_that_crosses_midnight_is_not_read_as_empty():
    # 23:00-07:30 is the real case: start > end, so a naive start <= now <= end test is
    # false for EVERY minute of the day and the sweep never runs at all.
    assert common.within_window("23:00-07:30", 23, 30) is True
    assert common.within_window("23:00-07:30", 2, 0) is True
    assert common.within_window("23:00-07:30", 7, 29) is True


def test_the_end_of_a_crossing_window_is_exclusive():
    # 07:30 is when the endpoint is stopped, so a sweep starting AT 07:30 would run into a
    # backend that is going away underneath it.
    assert common.within_window("23:00-07:30", 7, 30) is False
    assert common.within_window("23:00-07:30", 12, 0) is False


def test_a_malformed_window_runs_rather_than_blocking_forever():
    # A typo must not silently stop every sweep; the loud path is to keep working.
    assert common.within_window("garbage", 3, 0) is True
    assert common.within_window("23:00", 3, 0) is True
