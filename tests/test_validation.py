"""Validation rules (PLAN.md 5). They report; they never stop anything."""

from __future__ import annotations

import pytest

from app.notion.dates import Moment, parse_moment
from app.validation.checks import (
    Unreadable,
    duration_minutes,
    format_minutes,
    validate_entry,
)


def at(text: str) -> Moment:
    moment = parse_moment(text)
    assert moment is not None
    return moment


START = at("2026-10-21T09:00:00.000+05:30")


def codes(**kwargs: object) -> list[tuple[str, str]]:
    kwargs.setdefault("end_from_range", False)
    kwargs.setdefault("logged_minutes", None)
    return [(i["field"], i["code"]) for i in validate_entry(**kwargs)]  # type: ignore[arg-type]


def test_a_good_entry_has_no_issues() -> None:
    assert codes(start=START, end=at("2026-10-21T10:00:00.000+05:30"), logged_minutes=60) == []


def test_zero_length_session_is_fine() -> None:
    assert codes(start=START, end=START) == []


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (None, START, [("start", "missing_time")]),
        (START, None, [("end", "missing_time")]),
        (None, None, [("start", "missing_time"), ("end", "missing_time")]),
        (at("2026-10-21"), START, [("start", "missing_time")]),
        (START, at("2026-10-21"), [("end", "missing_time")]),
    ],
)
def test_missing_time(start: Moment | None, end: Moment | None, expected: list[object]) -> None:
    assert codes(start=start, end=end, logged_minutes=5) == expected


def test_missing_time_messages() -> None:
    issues = validate_entry(
        start=at("2026-10-21"), end=None, end_from_range=False, logged_minutes=None
    )
    assert [i["message"] for i in issues] == [
        "Start time has a date (2026-10-21) but no time.",
        "End time is empty.",
    ]


def test_a_range_without_an_end_explains_where_to_add_it() -> None:
    issues = validate_entry(start=START, end=None, end_from_range=True, logged_minutes=None)
    assert issues[0]["message"] == (
        "End time is empty: the date in the Start time column has no end. Add an end date and "
        "time to its range."
    )


def test_invalid_range() -> None:
    issues = validate_entry(
        start=START,
        end=at("2026-10-21T08:53:00.000+05:30"),
        end_from_range=False,
        logged_minutes=999,
    )
    # Only the invalid range: never a mismatch as well (PLAN.md 5).
    assert issues == [
        {"field": "end", "code": "invalid_range", "message": "End time is 7 min before Start time."}
    ]


def test_duration_mismatch_message_matches_the_plan() -> None:
    issues = validate_entry(
        start=START,
        end=at("2026-10-21T11:03:00.000+05:30"),
        end_from_range=False,
        logged_minutes=148,
    )
    assert issues == [
        {
            "field": "logged_minutes",
            "code": "duration_mismatch",
            "message": "Logged 148 min, but Start → End is 123 min.",
        }
    ]


@pytest.mark.parametrize(
    ("logged", "flagged"),
    [(60, False), (61, False), (59, False), (61.01, True), (58.99, True), (0, True)],
)
def test_one_minute_tolerance(logged: float, flagged: bool) -> None:
    end = at("2026-10-21T10:00:00.000+05:30")
    issues = codes(start=START, end=end, logged_minutes=logged)
    assert (issues == [("logged_minutes", "duration_mismatch")]) is flagged


def test_mismatch_needs_logged_minutes() -> None:
    assert codes(start=START, end=at("2026-10-21T11:00:00.000+05:30"), logged_minutes=None) == []


def test_mismatch_is_skipped_when_a_time_is_missing() -> None:
    assert codes(start=START, end=None, logged_minutes=999) == [("end", "missing_time")]
    assert codes(start=at("2026-10-21"), end=START, logged_minutes=999) == [
        ("start", "missing_time")
    ]


def test_mismatch_across_time_zones_uses_utc() -> None:
    # 09:00 in India is 03:30 UTC; an end written in UTC 04:30 is an hour later.
    end = at("2026-10-21T04:30:00.000Z")
    assert codes(start=START, end=end, logged_minutes=60) == []


def test_unreadable_extra_fields() -> None:
    issues = validate_entry(
        start=START,
        end=START,
        end_from_range=False,
        logged_minutes=None,
        unreadable=[Unreadable("mood", "Mood", "Notion didn't send a value for it.")],
    )
    assert issues == [
        {
            "field": "extra:mood",
            "code": "unreadable_extra",
            "message": "“Mood” couldn't be read: Notion didn't send a value for it.",
        }
    ]


def test_duration_and_formatting() -> None:
    assert duration_minutes(START, at("2026-10-21T11:03:00.000+05:30")) == 123
    assert duration_minutes(at("2026-10-21"), START) is None
    assert format_minutes(148) == "148 min"
    assert format_minutes(2.54) == "2.5 min"
    assert format_minutes(59.99) == "60 min"
