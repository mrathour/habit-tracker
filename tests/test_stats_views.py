"""Daily totals, weekly trends and streaks (PLAN.md 7)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.stats.allocation import Day
from app.stats.preferences import WEEKDAYS, Weekday
from app.stats.views import daily, qualifies, streaks, week_start_of, weekly

TODAY = date(2026, 10, 22)  # a Thursday


def days_with(minutes_by_day: dict[date, float]) -> dict[date, Day]:
    return {
        key: Day(minutes=value, sessions={f"p{key}": value})
        for key, value in minutes_by_day.items()
    }


# --- daily ------------------------------------------------------------------------------------


def test_daily_fills_empty_days() -> None:
    result = daily(days_with({date(2026, 10, 21): 90}), date(2026, 10, 20), date(2026, 10, 22))
    assert result == [
        {"date": "2026-10-20", "minutes": 0.0, "sessions": 0},
        {"date": "2026-10-21", "minutes": 90, "sessions": 1},
        {"date": "2026-10-22", "minutes": 0.0, "sessions": 0},
    ]


def test_daily_range_edges_are_inclusive() -> None:
    result = daily({}, date(2026, 10, 16), TODAY)
    assert [d["date"] for d in result][0::6] == ["2026-10-16", "2026-10-22"]
    assert len(result) == 7


# --- weekly -----------------------------------------------------------------------------------


@pytest.mark.parametrize("start_day", WEEKDAYS)
def test_week_start_for_every_weekday(start_day: Weekday) -> None:
    start = week_start_of(TODAY, start_day)
    assert start.weekday() == WEEKDAYS.index(start_day)
    assert start <= TODAY < start + timedelta(days=7)


def test_weekly_totals_and_rolling_average() -> None:
    # Monday weeks: 5, 12 and 19 Oct, and the current week from 19 Oct (today is the 22nd).
    data = days_with(
        {
            date(2026, 9, 28): 60,  # week of 28 Sep: 60
            date(2026, 10, 6): 120,  # week of 5 Oct: 120
            date(2026, 10, 13): 30,  # week of 12 Oct: 30
            date(2026, 10, 19): 100,  # current week so far: 100 + 50
            date(2026, 10, 22): 50,
            date(2026, 10, 23): 999,  # tomorrow: never counted
        }
    )
    result = weekly(data, TODAY, 4, "monday")
    assert [w["start"] for w in result] == ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]
    assert [w["minutes"] for w in result] == [60, 120, 30, 150]
    assert [w["partial"] for w in result] == [False, False, False, True]
    # At the start of the data the average covers only the weeks so far.
    assert [w["rolling_average"] for w in result] == [60, 90, 70, 90]


def test_rolling_average_is_empty_before_the_first_logged_week() -> None:
    result = weekly(days_with({date(2026, 10, 20): 60}), TODAY, 3, "monday")
    assert [w["rolling_average"] for w in result] == [None, None, 60]


def test_rolling_average_uses_weeks_before_the_window() -> None:
    data = days_with({date(2026, 9, 14) + timedelta(weeks=n): 10 * (n + 1) for n in range(6)})
    result = weekly(data, TODAY, 2, "monday")
    # Weeks 5 (50 min) and 6 (60) shown; averages over weeks 2-5 and 3-6.
    assert [w["minutes"] for w in result] == [50, 60]
    assert [w["rolling_average"] for w in result] == [35, 45]


def test_weeks_starting_on_sunday() -> None:
    result = weekly(days_with({date(2026, 10, 18): 60}), TODAY, 1, "sunday")
    assert result[0]["start"] == "2026-10-18"
    assert result[0]["minutes"] == 60


def test_no_data_at_all() -> None:
    result = weekly({}, TODAY, 12, "monday")
    assert len(result) == 12
    assert all(w["minutes"] == 0 and w["rolling_average"] is None for w in result)


# --- streaks ----------------------------------------------------------------------------------


def run(*offsets: int, minutes: float = 30) -> dict[date, Day]:
    return days_with({TODAY - timedelta(days=n): minutes for n in offsets})


def test_threshold_zero_means_any_time() -> None:
    assert qualifies(0.5, 0)
    assert not qualifies(0, 0)
    assert qualifies(30, 30)
    assert not qualifies(29.9, 30)


def test_current_streak_including_today() -> None:
    result = streaks(run(0, 1, 2, 4), TODAY, 0)
    assert result["current"] == {"days": 3, "start": "2026-10-20", "end": "2026-10-22"}
    assert result["today_counts"]


def test_today_without_time_yet_keeps_the_streak() -> None:
    result = streaks(run(1, 2, 3), TODAY, 0)
    assert result["current"] == {"days": 3, "start": "2026-10-19", "end": "2026-10-21"}
    assert not result["today_counts"]


def test_a_missed_yesterday_ends_the_streak() -> None:
    result = streaks(run(2, 3), TODAY, 0)
    assert result["current"] is None
    assert result["longest"] == {"days": 2, "start": "2026-10-19", "end": "2026-10-20"}


def test_threshold_breaks_short_days() -> None:
    data = run(0, 1, 2) | days_with({TODAY - timedelta(days=1): 10})
    assert streaks(data, TODAY, 0)["current"] == {
        "days": 3,
        "start": "2026-10-20",
        "end": "2026-10-22",
    }
    assert streaks(data, TODAY, 15)["current"] == {
        "days": 1,
        "start": "2026-10-22",
        "end": "2026-10-22",
    }


def test_longest_streak_and_ties_prefer_the_most_recent() -> None:
    result = streaks(run(1, 2, 5, 6, 10, 11), TODAY, 0)
    assert result["longest"] == {"days": 2, "start": "2026-10-20", "end": "2026-10-21"}
    longer = streaks(run(1, 10, 11, 12), TODAY, 0)
    assert longer["longest"] == {"days": 3, "start": "2026-10-10", "end": "2026-10-12"}


def test_future_days_never_count() -> None:
    data = run(0) | days_with({TODAY + timedelta(days=1): 60, TODAY + timedelta(days=2): 60})
    result = streaks(data, TODAY, 0)
    assert result["current"] == {"days": 1, "start": "2026-10-22", "end": "2026-10-22"}
    assert result["longest"] == result["current"]


def test_no_streak_at_all() -> None:
    assert streaks({}, TODAY, 0) == {
        "current": None,
        "longest": None,
        "today_counts": False,
        "threshold_minutes": 0,
    }
