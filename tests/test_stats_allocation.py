"""Minutes per local day: the overlap rule, then the midnight rule (PLAN.md 7)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.stats.allocation import Session, allocate, counted_pieces, overlap_minutes
from app.stats.preferences import MidnightRule, OverlapRule

INDIA = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")


def s(page_id: str, start: str, end: str, zone: ZoneInfo = INDIA) -> Session:
    """A session from local wall-clock times ("2026-10-21 09:00")."""

    def instant(text: str) -> datetime:
        return datetime.fromisoformat(text).replace(tzinfo=zone).astimezone(UTC)

    return Session(page_id, instant(start), instant(end))


def minutes(
    sessions: list[Session],
    midnight: MidnightRule = "split",
    overlap: OverlapRule = "once",
    zone: ZoneInfo = INDIA,
) -> dict[str, float]:
    days = allocate(sessions, zone, midnight, overlap)
    return {key.isoformat(): round(day.minutes, 6) for key, day in sorted(days.items())}


def per_session(
    sessions: list[Session],
    key: str,
    midnight: MidnightRule = "split",
    overlap: OverlapRule = "once",
) -> dict[str, float]:
    days = allocate(sessions, INDIA, midnight, overlap)
    return {pid: round(m, 6) for pid, m in days[date.fromisoformat(key)].sessions.items()}


# --- single sessions and midnight -------------------------------------------------------------


def test_one_session_within_a_day() -> None:
    assert minutes([s("a", "2026-10-21 09:00", "2026-10-21 10:30")]) == {"2026-10-21": 90}


def test_a_session_crossing_midnight_is_split_proportionally() -> None:
    session = s("a", "2026-10-21 23:00", "2026-10-22 01:30")
    assert minutes([session]) == {"2026-10-21": 60, "2026-10-22": 90}
    assert minutes([session], midnight="start_date") == {"2026-10-21": 150}


def test_a_session_across_several_days() -> None:
    session = s("a", "2026-10-21 22:00", "2026-10-23 02:00")
    assert minutes([session]) == {"2026-10-21": 120, "2026-10-22": 1440, "2026-10-23": 120}
    # The start-date rule puts it all on one date, even past 24 hours.
    assert minutes([session], midnight="start_date") == {"2026-10-21": 1680}


def test_a_zero_length_session_counts_as_a_session_with_no_time() -> None:
    days = allocate([s("a", "2026-10-21 09:00", "2026-10-21 09:00")], INDIA, "split", "once")
    assert days[date(2026, 10, 21)].minutes == 0
    assert list(days[date(2026, 10, 21)].sessions) == ["a"]


def test_days_follow_the_time_zone() -> None:
    # 23:30 to 00:30 UTC is one evening in New York and one morning in India.
    session = Session(
        "a", datetime(2026, 10, 21, 23, 30, tzinfo=UTC), datetime(2026, 10, 22, 0, 30, tzinfo=UTC)
    )
    assert minutes([session], zone=NEW_YORK) == {"2026-10-21": 60}
    assert minutes([session], zone=INDIA) == {"2026-10-22": 60}
    assert minutes([session], zone=ZoneInfo("UTC")) == {"2026-10-21": 30, "2026-10-22": 30}


def test_daylight_saving_days_are_23_and_25_hours() -> None:
    spring = s("a", "2026-03-29 00:00", "2026-03-30 00:00", LONDON)
    autumn = s("b", "2026-10-25 00:00", "2026-10-26 00:00", LONDON)
    assert minutes([spring], zone=LONDON) == {"2026-03-29": 23 * 60}
    assert minutes([autumn], zone=LONDON) == {"2026-10-25": 25 * 60}


def test_crossing_midnight_on_a_daylight_saving_night() -> None:
    # London, 25 Oct 2026: clocks go back at 02:00. 22:00 to 03:00 is 6 real hours.
    session = s("a", "2026-10-24 22:00", "2026-10-25 03:00", LONDON)
    assert minutes([session], zone=LONDON) == {"2026-10-24": 120, "2026-10-25": 240}


# --- overlaps ---------------------------------------------------------------------------------


def test_two_overlapping_sessions() -> None:
    sessions = [
        s("a", "2026-10-21 09:00", "2026-10-21 10:00"),
        s("b", "2026-10-21 09:30", "2026-10-21 11:00"),
    ]
    assert minutes(sessions) == {"2026-10-21": 120}  # 09:00 to 11:00, counted once
    assert minutes(sessions, overlap="sum") == {"2026-10-21": 150}
    # The overlapping half hour is credited to the session that started first.
    assert per_session(sessions, "2026-10-21") == {"a": 60, "b": 60}
    assert per_session(sessions, "2026-10-21", overlap="sum") == {"a": 60, "b": 90}


def test_one_session_inside_another() -> None:
    sessions = [
        s("outer", "2026-10-21 09:00", "2026-10-21 12:00"),
        s("inner", "2026-10-21 10:00", "2026-10-21 11:00"),
    ]
    assert minutes(sessions) == {"2026-10-21": 180}
    assert minutes(sessions, overlap="sum") == {"2026-10-21": 240}
    # The inner session still counts as a session on that day, with no time of its own.
    assert per_session(sessions, "2026-10-21") == {"outer": 180, "inner": 0}


def test_a_chain_of_three_overlapping_sessions() -> None:
    sessions = [
        s("a", "2026-10-21 09:00", "2026-10-21 10:00"),
        s("b", "2026-10-21 09:45", "2026-10-21 10:30"),
        s("c", "2026-10-21 10:15", "2026-10-21 11:00"),
    ]
    assert minutes(sessions) == {"2026-10-21": 120}
    assert minutes(sessions, overlap="sum") == {"2026-10-21": 150}
    assert per_session(sessions, "2026-10-21") == {"a": 60, "b": 30, "c": 30}


def test_identical_duplicate_entries() -> None:
    sessions = [
        s("dup-1", "2026-10-21 09:00", "2026-10-21 10:00"),
        s("dup-2", "2026-10-21 09:00", "2026-10-21 10:00"),
    ]
    assert minutes(sessions) == {"2026-10-21": 60}
    assert minutes(sessions, overlap="sum") == {"2026-10-21": 120}
    # Ties go to the earlier end, then the page ID: dup-1 keeps the time.
    assert per_session(sessions, "2026-10-21") == {"dup-1": 60, "dup-2": 0}


def test_sessions_that_touch_do_not_overlap() -> None:
    sessions = [
        s("a", "2026-10-21 09:00", "2026-10-21 10:00"),
        s("b", "2026-10-21 10:00", "2026-10-21 11:00"),
    ]
    assert minutes(sessions) == minutes(sessions, overlap="sum") == {"2026-10-21": 120}
    assert overlap_minutes(sessions[0], sessions) == (0.0, [])


def test_overlap_across_midnight_with_the_split_rule() -> None:
    sessions = [
        s("late", "2026-10-21 23:00", "2026-10-22 01:00"),
        s("later", "2026-10-21 23:30", "2026-10-22 02:00"),
    ]
    # Once: 23:00 to 02:00 is 3 hours: 1 h on the 21st, 2 h on the 22nd.
    assert minutes(sessions) == {"2026-10-21": 60, "2026-10-22": 120}
    assert minutes(sessions, overlap="sum") == {"2026-10-21": 90, "2026-10-22": 180}
    assert per_session(sessions, "2026-10-22") == {"late": 60, "later": 60}


def test_overlap_across_midnight_with_the_start_date_rule() -> None:
    sessions = [
        s("late", "2026-10-21 23:00", "2026-10-22 01:00"),
        s("next-day", "2026-10-22 00:30", "2026-10-22 02:00"),
    ]
    # Overlap first: "late" keeps 23:00 to 01:00, "next-day" only 01:00 to 02:00.
    # Then each session's counted time goes to its own start date.
    assert minutes(sessions, midnight="start_date") == {"2026-10-21": 120, "2026-10-22": 60}
    assert minutes(sessions, midnight="start_date", overlap="sum") == {
        "2026-10-21": 120,
        "2026-10-22": 90,
    }


def test_no_day_exceeds_24_hours_with_the_defaults() -> None:
    sessions = [s(f"p{i}", "2026-10-21 00:00", "2026-10-22 00:00") for i in range(3)] + [
        s("x", "2026-10-21 05:00", "2026-10-21 20:00")
    ]
    assert minutes(sessions) == {"2026-10-21": 1440}
    assert minutes(sessions, overlap="sum") == {"2026-10-21": 3 * 1440 + 900}


def test_session_counts_include_overlapped_sessions() -> None:
    sessions = [
        s("a", "2026-10-21 09:00", "2026-10-21 12:00"),
        s("b", "2026-10-21 10:00", "2026-10-21 11:00"),
    ]
    days = allocate(sessions, INDIA, "split", "once")
    assert len(days[date(2026, 10, 21)].sessions) == 2


def test_counted_pieces_are_credited_in_start_order() -> None:
    sessions = [
        s("b", "2026-10-21 09:30", "2026-10-21 11:00"),
        s("a", "2026-10-21 09:00", "2026-10-21 10:00"),
    ]
    pieces = counted_pieces(sessions, "once")
    assert [(p.owner.page_id, p.start.astimezone(INDIA).strftime("%H:%M")) for p in pieces] == [
        ("a", "09:00"),
        ("b", "10:00"),
    ]


@pytest.mark.parametrize(
    ("sessions", "expected"),
    [
        (
            [
                s("a", "2026-10-21 09:00", "2026-10-21 10:00"),
                s("b", "2026-10-21 09:30", "2026-10-21 11:00"),
            ],
            30,
        ),
        (
            [
                s("a", "2026-10-21 09:00", "2026-10-21 12:00"),
                s("b", "2026-10-21 10:00", "2026-10-21 11:00"),
            ],
            60,
        ),
        (
            [
                s("a", "2026-10-21 09:00", "2026-10-21 12:00"),
                s("b", "2026-10-21 09:30", "2026-10-21 10:00"),
                s("c", "2026-10-21 09:45", "2026-10-21 10:30"),
            ],
            60,  # b and c overlap each other too; a's overlapped time is 09:30 to 10:30
        ),
    ],
)
def test_overlap_minutes_for_the_day_detail(sessions: list[Session], expected: float) -> None:
    overlapped, others = overlap_minutes(sessions[0], sessions)
    assert overlapped == expected
    assert [o.page_id for o in others] == [x.page_id for x in sessions[1:]]
