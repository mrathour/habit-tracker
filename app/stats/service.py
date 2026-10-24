"""The dashboard's data for the UI (PLAN.md 7), computed from the local entries on each request.

The UI sends its IANA time zone with every request, so local days follow the computer's zone,
including daylight-saving changes, without guessing it from Windows' own zone names.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Final, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.connection import lock_for
from app.db.settings import Settings
from app.errors import AppError
from app.stats import preferences
from app.stats.allocation import Session, allocate, overlap_minutes
from app.stats.preferences import Preferences
from app.stats.sessions import counted_session, session_label
from app.stats.views import DayTotal, Streaks, WeekTotal, daily, streaks, weekly
from app.sync.store import notion_url

DAILY_RANGES: Final = (7, 30, 90)
WEEK_RANGES: Final = (12, 26, 52)
#: The longest custom range the daily chart shows.
MAX_CUSTOM_DAYS: Final = 3 * 366


class DashboardError(AppError):
    state = "invalid_request"


class DailyView(TypedDict):
    first: str
    last: str
    days: list[DayTotal]
    total_minutes: float
    active_days: int


class CalendarView(TypedDict):
    first: str
    last: str
    #: None for the last 12 months.
    year: int | None
    days: list[DayTotal]
    total_minutes: float
    max_minutes: float
    years: list[int]


class Dashboard(TypedDict):
    time_zone: str
    today: str
    preferences: Preferences
    entries: int
    counted_sessions: int
    #: Entries left out of the charts (Missing time or Invalid range).
    excluded: int
    #: Entries with any issue.
    flagged: int
    daily: DailyView
    weekly: list[WeekTotal]
    streaks: Streaks
    calendar: CalendarView


class OverlapWith(TypedDict):
    page_id: str
    label: str


class DetailSession(TypedDict):
    page_id: str
    display_id: str | None
    task_name: str | None
    start_utc: str
    end_utc: str
    minutes: float
    counted_minutes: float
    crosses_midnight: bool
    overlap_minutes: float
    overlaps_with: list[OverlapWith]
    url: str
    #: Every page linked in the parent task relation, in Notion's order; the first is the
    #: parent task (PLAN.md 4.1). Empty when nothing is linked or the field is "Not used".
    parent_task_ids: list[str]
    parent_urls: list[str]


class DayDetail(TypedDict):
    date: str
    time_zone: str
    minutes: float
    preferences: Preferences
    sessions: list[DetailSession]


class StatsService:
    def __init__(
        self,
        *,
        db: sqlite3.Connection,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._db = db
        self._settings = settings
        self._clock = clock

    # --- preferences -------------------------------------------------------------------------

    def preferences(self) -> Preferences:
        return preferences.read(self._settings)

    def update_preferences(self, changes: object) -> Preferences:
        return preferences.update(self._settings, changes)

    # --- the dashboard -----------------------------------------------------------------------

    def dashboard(self, request: object) -> Dashboard:
        if not isinstance(request, dict):
            raise DashboardError("The dashboard request was sent in an unexpected form.")
        zone = _zone(request.get("time_zone"))
        prefs = self.preferences()
        today = self._clock().astimezone(zone).date()
        sessions, counts = self._load()
        days = allocate(sessions, zone, prefs["midnight_rule"], prefs["overlap_rule"])
        first, last = _daily_range(request.get("range"), today)
        daily_days = daily(days, first, last)
        year = request.get("year")
        cal_first, cal_last, cal_year = _calendar_range(year, today)
        calendar_days = daily(days, cal_first, cal_last)
        weeks = request.get("weeks", 26)
        if weeks not in WEEK_RANGES:
            raise DashboardError("Choose 12, 26 or 52 weeks.")
        years = sorted({key.year for key, value in days.items() if value.minutes > 0})
        return {
            "time_zone": str(zone.key),
            "today": today.isoformat(),
            "preferences": prefs,
            "entries": counts[0],
            "counted_sessions": len(sessions),
            "excluded": counts[1],
            "flagged": counts[2],
            "daily": {
                "first": first.isoformat(),
                "last": last.isoformat(),
                "days": daily_days,
                "total_minutes": round(sum(d["minutes"] for d in daily_days), 4),
                "active_days": sum(1 for d in daily_days if d["minutes"] > 0),
            },
            "weekly": weekly(days, today, weeks, prefs["week_start"]),
            "streaks": streaks(days, today, prefs["streak_threshold_minutes"]),
            "calendar": {
                "first": cal_first.isoformat(),
                "last": cal_last.isoformat(),
                "year": cal_year,
                "days": calendar_days,
                "total_minutes": round(sum(d["minutes"] for d in calendar_days), 4),
                "max_minutes": max((d["minutes"] for d in calendar_days), default=0.0),
                "years": years,
            },
        }

    def day_detail(self, time_zone: object, day: object) -> DayDetail:
        zone = _zone(time_zone)
        key = _date(day, "day")
        prefs = self.preferences()
        sessions, _counts = self._load()
        days = allocate(sessions, zone, prefs["midnight_rule"], prefs["overlap_rule"])
        entry = days.get(key)
        by_id = {s.page_id: s for s in sessions}
        parents = self._parent_links(list(entry.sessions) if entry else [])
        rows: list[DetailSession] = []
        for page_id, counted in entry.sessions.items() if entry else []:
            session = by_id[page_id]
            parent_ids = parents.get(page_id, [])
            overlapped, others = overlap_minutes(session, sessions)
            start_local = session.start.astimezone(zone).date()
            end_local = (session.end - timedelta(microseconds=1)).astimezone(zone).date()
            rows.append(
                {
                    "page_id": page_id,
                    "display_id": session.display_id,
                    "task_name": session.task_name,
                    "start_utc": _iso(session.start),
                    "end_utc": _iso(session.end),
                    "minutes": round(session.minutes, 4),
                    "counted_minutes": round(counted, 4),
                    "crosses_midnight": session.end > session.start and end_local != start_local,
                    "overlap_minutes": round(overlapped, 4),
                    "overlaps_with": [
                        {"page_id": other.page_id, "label": session_label(other)}
                        for other in others
                    ],
                    "url": notion_url(page_id),
                    "parent_task_ids": parent_ids,
                    "parent_urls": [notion_url(parent) for parent in parent_ids],
                }
            )
        rows.sort(key=lambda row: (row["start_utc"], row["end_utc"], row["page_id"]))
        return {
            "date": key.isoformat(),
            "time_zone": str(zone.key),
            "minutes": round(entry.minutes, 4) if entry else 0.0,
            "preferences": prefs,
            "sessions": rows,
        }

    # --- data --------------------------------------------------------------------------------

    def _parent_links(self, page_ids: list[str]) -> dict[str, list[str]]:
        """Each entry's linked parent pages, by entry page ID."""
        if not page_ids:
            return {}
        marks = ",".join("?" * len(page_ids))
        with lock_for(self._db):
            rows = self._db.execute(
                f"SELECT page_id, parent_task_ids FROM work_logs WHERE page_id IN ({marks})",  # noqa: S608 - only placeholders
                page_ids,
            ).fetchall()
        links: dict[str, list[str]] = {}
        for page_id, raw in rows:
            try:
                value = json.loads(raw) if raw else []
            except ValueError:
                value = []
            links[page_id] = (
                [str(p) for p in value if isinstance(p, str)] if isinstance(value, list) else []
            )
        return links

    def _load(self) -> tuple[list[Session], tuple[int, int, int]]:
        """Sessions that count, and (entries, excluded, flagged)."""
        with lock_for(self._db):
            rows = self._db.execute(
                "SELECT page_id, display_id, task_name, start_utc, end_utc, issues FROM work_logs"
            ).fetchall()
        sessions: list[Session] = []
        excluded = flagged = 0
        for page_id, display_id, task_name, start_utc, end_utc, issues_json in rows:
            issues = json.loads(issues_json)
            if issues:
                flagged += 1
            session = counted_session(
                page_id, start_utc, end_utc, issues, display_id=display_id, task_name=task_name
            )
            if session is None:
                excluded += 1
                continue
            sessions.append(session)
        return sessions, (len(rows), excluded, flagged)


def _zone(name: object) -> ZoneInfo:
    if not isinstance(name, str) or not name:
        raise DashboardError("The computer's time zone wasn't sent.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DashboardError(
            "Habit Tracker doesn't recognise this computer's time zone.", detail=name
        ) from exc


def _date(value: object, what: str) -> date:
    if not isinstance(value, str):
        raise DashboardError(f"The {what} wasn't sent as a date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DashboardError(f"The {what} isn't a valid date.", detail=value) from exc


def _daily_range(value: object, today: date) -> tuple[date, date]:
    if value is None:
        value = {"days": 30}
    if not isinstance(value, dict):
        raise DashboardError("The date range was sent in an unexpected form.")
    if "days" in value:
        if value["days"] not in DAILY_RANGES:
            raise DashboardError("Choose 7, 30 or 90 days, or a custom range.")
        return today - timedelta(days=int(value["days"]) - 1), today
    first, last = _date(value.get("from"), "start date"), _date(value.get("to"), "end date")
    if last < first:
        raise DashboardError("The range ends before it starts.")
    if last > today:
        raise DashboardError("The range can't end after today.")
    if (last - first).days + 1 > MAX_CUSTOM_DAYS:
        raise DashboardError("Choose a range of at most three years.")
    return first, last


def _calendar_range(year: object, today: date) -> tuple[date, date, int | None]:
    if year is None:
        # The last 12 months: from the day after the same date a year ago, through today.
        return _year_ago(today) + timedelta(days=1), today, None
    if not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= today.year:
        raise DashboardError("Choose a year up to this one.")
    return date(year, 1, 1), min(date(year, 12, 31), today), year


def _year_ago(today: date) -> date:
    try:
        return today.replace(year=today.year - 1)
    except ValueError:  # 29 February
        return today.replace(year=today.year - 1, day=28)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
