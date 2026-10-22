"""Notion date values to UTC (PLAN.md 6.4 "Time zones")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.notion.dates import Moment, date_of, parse_date_value, parse_moment, utc_iso


def test_offset_is_converted_to_utc() -> None:
    assert parse_moment("2026-10-17T17:41:00.000+05:30") == Moment(
        utc="2026-10-17T12:11:00.000Z", date="2026-10-17", has_time=True
    )


def test_z_offset() -> None:
    assert parse_moment("2026-10-17T12:11:00.000Z") == Moment(
        utc="2026-10-17T12:11:00.000Z", date="2026-10-17", has_time=True
    )


def test_no_offset_is_localized_with_the_time_zone() -> None:
    moment = parse_moment("2026-10-17T17:41:00.000", "Asia/Kolkata")
    assert moment is not None
    assert moment.utc == "2026-10-17T12:11:00.000Z"


def test_daylight_saving_is_respected() -> None:
    winter = parse_moment("2026-01-15T09:00:00.000", "Europe/London")
    summer = parse_moment("2026-07-15T09:00:00.000", "Europe/London")
    assert winter is not None
    assert winter.utc == "2026-01-15T09:00:00.000Z"
    assert summer is not None
    assert summer.utc == "2026-07-15T08:00:00.000Z"


def test_no_offset_and_no_time_zone_is_utc() -> None:
    moment = parse_moment("2026-10-17T12:11:00")
    assert moment is not None
    assert moment.utc == "2026-10-17T12:11:00.000Z"


def test_date_only_has_no_time() -> None:
    assert parse_moment("2026-10-17") == Moment(utc=None, date="2026-10-17", has_time=False)


def test_calendar_date_is_the_one_written_in_notion() -> None:
    # 00:30 in India is still the previous day in UTC; the written date is kept for display.
    moment = parse_moment("2026-10-18T00:30:00.000+05:30")
    assert moment is not None
    assert moment.date == "2026-10-18"
    assert moment.utc == "2026-10-17T19:00:00.000Z"


@pytest.mark.parametrize("text", [None, "", "  ", "yesterday", "2026-13-01", "2026-10-17T25:00", 5])
def test_unreadable_values(text: object) -> None:
    assert parse_moment(text) is None


def test_unknown_time_zone_is_unreadable() -> None:
    assert parse_moment("2026-10-17T17:41:00.000", "Mars/Olympus_Mons") is None


def test_offset_wins_over_an_unknown_time_zone() -> None:
    moment = parse_moment("2026-10-17T17:41:00.000+05:30", "Mars/Olympus_Mons")
    assert moment is not None
    assert moment.utc == "2026-10-17T12:11:00.000Z"


def test_range() -> None:
    value = parse_date_value(
        {"start": "2026-10-17T17:41:00.000+05:30", "end": "2026-10-17T18:41:00.000+05:30"}
    )
    assert value is not None
    assert value.start.utc == "2026-10-17T12:11:00.000Z"
    assert value.end is not None
    assert value.end.utc == "2026-10-17T13:11:00.000Z"


def test_range_uses_the_time_zone_for_both_ends() -> None:
    value = parse_date_value(
        {"start": "2026-10-17T09:00:00.000", "end": "2026-10-17T10:00:00.000", "time_zone": "UTC"}
    )
    assert value is not None
    assert value.end is not None
    assert (value.start.utc, value.end.utc) == (
        "2026-10-17T09:00:00.000Z",
        "2026-10-17T10:00:00.000Z",
    )


def test_single_date_has_no_end() -> None:
    value = parse_date_value({"start": "2026-10-17", "end": None})
    assert value is not None
    assert value.end is None


def test_empty_and_malformed_values() -> None:
    assert parse_date_value(None) is None
    assert parse_date_value({"start": None}) is None
    assert parse_date_value("2026-10-17") is None
    assert date_of({"id": "x", "type": "date", "date": None}) is None


def test_utc_iso() -> None:
    india = timezone(timedelta(hours=5, minutes=30))
    assert utc_iso(datetime(2026, 10, 17, 17, 41, tzinfo=india)) == "2026-10-17T12:11:00.000Z"
    assert utc_iso(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00.000Z"
