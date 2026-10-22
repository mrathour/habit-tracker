"""The dashboard's data from the local entries (PLAN.md 7)."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from app.db import Database, open_database
from app.db.settings import Settings
from app.paths import AppPaths
from app.stats.preferences import PreferenceError
from app.stats.service import DashboardError, StatsService

NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)  # 11:30 in India, 02:00 in New York
MISSING = [{"field": "end", "code": "missing_time", "message": "End time is empty."}]
INVALID = [{"field": "end", "code": "invalid_range", "message": "End time is 7 min before."}]
MISMATCH = [{"field": "logged_minutes", "code": "duration_mismatch", "message": "Logged…"}]


@pytest.fixture
def db(app_paths: AppPaths) -> Iterator[Database]:
    database = open_database(app_paths.database)
    yield database
    database.close()


@pytest.fixture
def stats(db: Database) -> StatsService:
    return StatsService(db=db.connection, settings=Settings(db.connection), clock=lambda: NOW)


def add(
    db: Database,
    page_id: str,
    start: str | None,
    end: str | None,
    issues: list[dict[str, str]] | None = None,
    **extra: Any,
) -> None:
    stamp = "2026-10-01T00:00:00.000Z"
    with db.connection:
        db.connection.execute(
            "INSERT INTO work_logs (page_id, display_id, task_name, start_utc, end_utc, issues,"
            " created_time, last_edited_time, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                page_id,
                extra.get("display_id"),
                extra.get("task_name"),
                start,
                end,
                json.dumps(issues or []),
                stamp,
                stamp,
                stamp,
            ),
        )


def request(**changes: Any) -> dict[str, Any]:
    return {"time_zone": "Asia/Kolkata", "range": {"days": 7}, "weeks": 12, "year": None} | changes


def by_date(days: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    return {d["date"]: d["minutes"] for d in days if d["minutes"]}


# A known set, with totals worked out by hand (times in UTC; India is UTC+5:30):
#  p1  2026-10-20 03:30 to 05:00 UTC = 20 Oct 09:00-10:30 India (90 min)
#  p2  2026-10-20 04:30 to 05:30 UTC = 20 Oct 10:00-11:00 India (60 min, 30 overlap with p1)
#  p3  2026-10-21 17:30 to 19:30 UTC = 21 Oct 23:00 to 22 Oct 01:00 India (crosses midnight)
#  p4  flagged Missing time, p5 Invalid range: left out
#  p6  flagged Duration mismatch: still counted, 2026-10-18 04:30-05:00 UTC (30 min)
def known_set(db: Database) -> None:
    add(
        db,
        "p1",
        "2026-10-20T03:30:00.000Z",
        "2026-10-20T05:00:00.000Z",
        display_id="1",
        task_name="Write",
    )
    add(
        db,
        "p2",
        "2026-10-20T04:30:00.000Z",
        "2026-10-20T05:30:00.000Z",
        display_id="2",
        task_name="Review",
    )
    add(db, "p3", "2026-10-21T17:30:00.000Z", "2026-10-21T19:30:00.000Z", display_id="3")
    add(db, "p4", "2026-10-21T04:30:00.000Z", None, MISSING)
    add(db, "p5", "2026-10-21T04:30:00.000Z", "2026-10-21T04:00:00.000Z", INVALID)
    add(db, "p6", "2026-10-18T04:30:00.000Z", "2026-10-18T05:00:00.000Z", MISMATCH)


def test_hand_checked_totals_in_india(db: Database, stats: StatsService) -> None:
    known_set(db)
    result = stats.dashboard(request())
    assert result["today"] == "2026-10-22"
    assert by_date(result["daily"]["days"]) == {
        "2026-10-18": 30,
        "2026-10-20": 120,  # 09:00 to 11:00, the overlap counted once
        "2026-10-21": 60,
        "2026-10-22": 60,
    }
    assert result["daily"]["total_minutes"] == 270
    assert result["daily"]["active_days"] == 4
    assert (result["entries"], result["counted_sessions"], result["excluded"]) == (6, 4, 2)
    assert result["flagged"] == 3
    # Current streak 20 to 22 Oct (19 Oct is empty).
    assert result["streaks"]["current"] == {"days": 3, "start": "2026-10-20", "end": "2026-10-22"}


def test_hand_checked_totals_in_new_york(db: Database, stats: StatsService) -> None:
    known_set(db)
    result = stats.dashboard(request(time_zone="America/New_York"))
    # New York is UTC-4 in October, and it is 02:00 on 22 Oct.
    # p1 is 19 Oct 23:30 to 20 Oct 01:00: split, 30 min on the 19th and 60 on the 20th.
    # p2 is 20 Oct 00:30-01:30: its first half hour overlaps p1, so it adds 30.
    # p3 is 21 Oct 13:30-15:30; p6 is 18 Oct 00:30-01:00.
    assert result["today"] == "2026-10-22"
    assert by_date(result["daily"]["days"]) == {
        "2026-10-18": 30,
        "2026-10-19": 30,
        "2026-10-20": 90,
        "2026-10-21": 120,
    }


def test_the_rules_follow_the_preferences(db: Database, stats: StatsService) -> None:
    known_set(db)
    stats.update_preferences({"overlap_rule": "sum", "midnight_rule": "start_date"})
    result = stats.dashboard(request())
    assert by_date(result["daily"]["days"]) == {
        "2026-10-18": 30,
        "2026-10-20": 150,
        "2026-10-21": 120,
    }


def test_day_detail_explains_a_day(db: Database, stats: StatsService) -> None:
    known_set(db)
    detail = stats.day_detail("Asia/Kolkata", "2026-10-20")
    assert detail["minutes"] == 120
    rows = {row["page_id"]: row for row in detail["sessions"]}
    assert list(rows) == ["p1", "p2"]
    assert rows["p1"]["minutes"] == 90
    assert rows["p1"]["counted_minutes"] == 90
    assert rows["p2"]["counted_minutes"] == 30
    assert rows["p2"]["overlap_minutes"] == 30
    assert rows["p2"]["overlaps_with"] == [{"page_id": "p1", "label": "#1 Write"}]
    assert rows["p1"]["overlaps_with"] == [{"page_id": "p2", "label": "#2 Review"}]
    assert rows["p1"]["url"] == "https://www.notion.so/p1"
    assert not rows["p1"]["crosses_midnight"]


def test_day_detail_marks_a_split_session(db: Database, stats: StatsService) -> None:
    known_set(db)
    detail = stats.day_detail("Asia/Kolkata", "2026-10-22")
    (row,) = detail["sessions"]
    assert row["page_id"] == "p3"
    assert row["crosses_midnight"]
    assert row["minutes"] == 120
    assert row["counted_minutes"] == 60
    assert row["overlap_minutes"] == 0


def test_day_detail_of_an_empty_day(db: Database, stats: StatsService) -> None:
    detail = stats.day_detail("Asia/Kolkata", "2026-10-19")
    assert detail["minutes"] == 0
    assert detail["sessions"] == []


def test_ranges(db: Database, stats: StatsService) -> None:
    for days in (7, 30, 90):
        result = stats.dashboard(request(range={"days": days}))
        assert len(result["daily"]["days"]) == days
        assert result["daily"]["last"] == "2026-10-22"
    custom = stats.dashboard(request(range={"from": "2026-01-01", "to": "2026-01-31"}))
    assert len(custom["daily"]["days"]) == 31


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"range": {"days": 14}}, "Choose 7, 30 or 90"),
        ({"range": {"from": "2026-02-01", "to": "2026-01-01"}}, "ends before it starts"),
        ({"range": {"from": "2026-10-01", "to": "2026-10-23"}}, "after today"),
        ({"range": {"from": "2020-01-01", "to": "2026-10-01"}}, "three years"),
        ({"range": {"from": "yesterday", "to": "2026-10-01"}}, "isn't a valid date"),
        ({"weeks": 10}, "12, 26 or 52"),
        ({"year": 2027}, "up to this one"),
        ({"time_zone": "Mars/Base"}, "doesn't recognise"),
        ({"time_zone": None}, "wasn't sent"),
    ],
)
def test_bad_requests(stats: StatsService, changes: dict[str, Any], message: str) -> None:
    with pytest.raises(DashboardError, match=message):
        stats.dashboard(request(**changes))


def test_calendar_last_12_months_and_years(db: Database, stats: StatsService) -> None:
    known_set(db)
    add(db, "old", "2025-03-01T04:30:00.000Z", "2025-03-01T05:30:00.000Z")
    result = stats.dashboard(request())
    calendar = result["calendar"]
    assert (calendar["first"], calendar["last"], calendar["year"]) == (
        "2025-10-23",
        "2026-10-22",
        None,
    )
    assert len(calendar["days"]) == 365
    assert calendar["max_minutes"] == 120
    assert calendar["years"] == [2025, 2026]
    year = stats.dashboard(request(year=2025))["calendar"]
    assert (year["first"], year["last"], year["total_minutes"]) == ("2025-01-01", "2025-12-31", 60)


def test_nothing_synced_yet(stats: StatsService) -> None:
    result = stats.dashboard(request())
    assert result["entries"] == 0
    assert result["daily"]["total_minutes"] == 0
    assert result["streaks"]["current"] is None
    assert result["calendar"]["years"] == []


def test_preferences(stats: StatsService) -> None:
    assert stats.preferences() == {
        "streak_threshold_minutes": 0,
        "week_start": "monday",
        "midnight_rule": "split",
        "overlap_rule": "once",
    }
    updated = stats.update_preferences({"streak_threshold_minutes": 30, "week_start": "sunday"})
    assert updated["streak_threshold_minutes"] == 30
    assert updated["week_start"] == "sunday"


@pytest.mark.parametrize(
    "changes",
    [
        {},
        "monday",
        {"streak_threshold_minutes": -1},
        {"streak_threshold_minutes": 1441},
        {"streak_threshold_minutes": True},
        {"week_start": "funday"},
        {"midnight_rule": "never"},
        {"overlap_rule": "twice"},
        {"colour": "green"},
    ],
)
def test_bad_preferences_are_refused(stats: StatsService, changes: object) -> None:
    with pytest.raises(PreferenceError):
        stats.update_preferences(changes)


def test_damaged_preferences_fall_back_to_defaults(db: Database, stats: StatsService) -> None:
    Settings(db.connection).set_many({"week_start": "funday", "streak_threshold_minutes": "x"})
    assert stats.preferences()["week_start"] == "monday"
    assert stats.preferences()["streak_threshold_minutes"] == 0
