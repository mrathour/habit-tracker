"""The dashboard's figures, from minutes per local day (PLAN.md 7).

* **Daily totals** for a date range.
* **Weekly totals**, weeks starting on the chosen weekday, with a 4-week rolling average: the
  mean of the week and the three before it, over the weeks since the first logged week when
  fewer than four exist. The current week is included and marked as partial.
* **Streaks**: a day counts when its total is more than 0 minutes (threshold 0) or at least the
  threshold. Today without time *yet* doesn't break the current streak: it runs through
  yesterday until today ends. Future days never count. Among equally long streaks, the longest
  shown is the most recent.
* **Calendar** days with minutes and session counts.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Final, TypedDict

from app.stats.allocation import Day
from app.stats.preferences import WEEKDAYS, Weekday

ROLLING_WEEKS: Final = 4


class DayTotal(TypedDict):
    date: str
    minutes: float
    sessions: int


class WeekTotal(TypedDict):
    start: str
    end: str
    minutes: float
    #: None before the first logged week.
    rolling_average: float | None
    partial: bool


class Streak(TypedDict):
    days: int
    start: str
    end: str


class Streaks(TypedDict):
    current: Streak | None
    longest: Streak | None
    #: Whether today already counts towards the current streak.
    today_counts: bool
    threshold_minutes: int


def dates_between(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def daily(days: Mapping[date, Day], first: date, last: date) -> list[DayTotal]:
    totals: list[DayTotal] = []
    for key in dates_between(first, last):
        entry = days.get(key)
        totals.append(
            {
                "date": key.isoformat(),
                "minutes": round(entry.minutes, 4) if entry else 0.0,
                "sessions": len(entry.sessions) if entry else 0,
            }
        )
    return totals


def week_start_of(key: date, week_start: Weekday) -> date:
    offset = (key.weekday() - WEEKDAYS.index(week_start)) % 7
    return key - timedelta(days=offset)


def weekly(
    days: Mapping[date, Day], today: date, weeks: int, week_start: Weekday
) -> list[WeekTotal]:
    """The last ``weeks`` weeks, ending with the current one."""
    current = week_start_of(today, week_start)
    starts = [current - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    logged = [key for key, value in days.items() if value.minutes > 0 and key <= today]
    first_week = week_start_of(min(logged), week_start) if logged else None
    lookback = starts[0] - timedelta(weeks=ROLLING_WEEKS - 1)
    totals: dict[date, float] = {}
    week = lookback
    while week <= current:
        totals[week] = sum(
            days[key].minutes
            for key in dates_between(week, week + timedelta(days=6))
            if key in days and key <= today
        )
        week += timedelta(weeks=1)
    result: list[WeekTotal] = []
    for start in starts:
        window = [
            start - timedelta(weeks=n)
            for n in range(ROLLING_WEEKS)
            if first_week is not None and start - timedelta(weeks=n) >= first_week
        ]
        average = (
            round(sum(totals[w] for w in window) / len(window), 4)
            if first_week is not None and start >= first_week and window
            else None
        )
        result.append(
            {
                "start": start.isoformat(),
                "end": (start + timedelta(days=6)).isoformat(),
                "minutes": round(totals[start], 4),
                "rolling_average": average,
                "partial": start == current,
            }
        )
    return result


def qualifies(minutes: float, threshold: int) -> bool:
    return minutes >= threshold if threshold > 0 else minutes > 0


def streaks(days: Mapping[date, Day], today: date, threshold: int) -> Streaks:
    good = {
        key for key, value in days.items() if key <= today and qualifies(value.minutes, threshold)
    }
    today_counts = today in good
    current: Streak | None = None
    end = today if today_counts else today - timedelta(days=1)
    if end in good:
        start = end
        while start - timedelta(days=1) in good:
            start -= timedelta(days=1)
        current = _streak(start, end)
    longest: Streak | None = None
    for key in sorted(good):
        if key - timedelta(days=1) in good:
            continue  # not the first day of a run
        run_end = key
        while run_end + timedelta(days=1) in good:
            run_end += timedelta(days=1)
        candidate = _streak(key, run_end)
        if longest is None or candidate["days"] >= longest["days"]:
            longest = candidate  # ties: the most recent wins (runs are visited in order)
    return {
        "current": current,
        "longest": longest,
        "today_counts": today_counts,
        "threshold_minutes": threshold,
    }


def _streak(start: date, end: date) -> Streak:
    return {"days": (end - start).days + 1, "start": start.isoformat(), "end": end.isoformat()}
