"""Turning sessions into minutes per local day (PLAN.md 7).

The two rules are always applied in the same order:

1. **Which sessions count.** Only entries with a valid range: anything flagged Missing time or
   Invalid range is left out (PLAN.md 5). Durations come from End minus Start.
2. **The overlap rule** decides which time counts:

   * ``once`` (default): a moment covered by two or more sessions counts once. It is credited
     to the session that started first (then the one that ends first, then by page ID). Totals
     are then actual time spent working, and with the split rule no day exceeds 24 hours.
   * ``sum``: every session counts its full time, overlaps included.

3. **The midnight rule** decides which day that time belongs to:

   * ``split`` (default): each moment belongs to the local day it falls on, so a session
     crossing midnight is split proportionally between the days it covers.
   * ``start_date``: all the time credited to a session belongs to its start date. A single
     session longer than a day can then put more than 24 hours on one date.

A day's session count is every session the midnight rule places on that day (``split``: every
session that touches the day; ``start_date``: every session starting on it), whether or not its
time was counted under the overlap rule.

Local days use the IANA time zone the UI sends, with ``zoneinfo``, so daylight-saving days of
23 and 25 hours are handled.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.stats.preferences import MidnightRule, OverlapRule

MINUTE: Final = 60.0


@dataclass(frozen=True, slots=True)
class Session:
    page_id: str
    start: datetime  # aware, UTC
    end: datetime  # aware, UTC, not before start
    display_id: str | None = None
    task_name: str | None = None

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / MINUTE


@dataclass(frozen=True, slots=True)
class Piece:
    """A stretch of counted time, credited to one session."""

    owner: Session
    start: datetime
    end: datetime


@dataclass(slots=True)
class Day:
    minutes: float = 0.0
    #: page ID -> minutes credited to that session on this day (0 when fully overlapped).
    sessions: dict[str, float] = field(default_factory=dict)


def counted_pieces(sessions: Sequence[Session], overlap: OverlapRule) -> list[Piece]:
    """Step 2: the time that counts, as pieces each credited to one session."""
    ordered = sorted(sessions, key=_priority)
    if overlap == "sum":
        return [Piece(s, s.start, s.end) for s in ordered if s.end > s.start]
    pieces: list[Piece] = []
    covered_until: datetime | None = None
    for session in ordered:
        # Every earlier session started no later than this one, so the time they cover from
        # this session's start onwards is one stretch, up to the latest end seen so far.
        start = session.start if covered_until is None else max(session.start, covered_until)
        if session.end > start:
            pieces.append(Piece(session, start, session.end))
        if covered_until is None or session.end > covered_until:
            covered_until = session.end
    return pieces


def allocate(
    sessions: Sequence[Session],
    zone: ZoneInfo,
    midnight: MidnightRule,
    overlap: OverlapRule,
) -> dict[date, Day]:
    """Minutes and sessions per local day, applying the overlap rule, then the midnight rule."""
    days: dict[date, Day] = {}

    def day(key: date) -> Day:
        return days.setdefault(key, Day())

    # Which sessions belong to which days (counted even when their time was overlapped).
    for session in sessions:
        for key in _session_days(session, zone, midnight):
            day(key).sessions.setdefault(session.page_id, 0.0)
    for piece in counted_pieces(sessions, overlap):
        if midnight == "start_date":
            key = local_date(piece.owner.start, zone)
            minutes = (piece.end - piece.start).total_seconds() / MINUTE
            _credit(day(key), piece.owner.page_id, minutes)
            continue
        for key, part_start, part_end in split_at_midnight(piece.start, piece.end, zone):
            minutes = (part_end - part_start).total_seconds() / MINUTE
            _credit(day(key), piece.owner.page_id, minutes)
    return days


def overlap_minutes(session: Session, others: Iterable[Session]) -> tuple[float, list[Session]]:
    """How much of ``session`` other sessions also cover, and which ones overlap it."""
    spans: list[tuple[datetime, datetime]] = []
    touching: list[Session] = []
    for other in others:
        if other.page_id == session.page_id:
            continue
        start, end = max(session.start, other.start), min(session.end, other.end)
        if end > start:
            spans.append((start, end))
            touching.append(other)
    total = 0.0
    for start, end in _merge(spans):
        total += (end - start).total_seconds() / MINUTE
    return total, sorted(touching, key=_priority)


def local_date(moment: datetime, zone: ZoneInfo) -> date:
    return moment.astimezone(zone).date()


def midnight_after(key: date, zone: ZoneInfo) -> datetime:
    """The instant the local day ``key`` ends (the next day's 00:00 in ``zone``)."""
    return datetime.combine(key + timedelta(days=1), time(0), tzinfo=zone)


def split_at_midnight(
    start: datetime, end: datetime, zone: ZoneInfo
) -> Iterator[tuple[date, datetime, datetime]]:
    """The parts of [start, end) on each local day."""
    cursor = start
    while cursor < end:
        key = local_date(cursor, zone)
        boundary = midnight_after(key, zone)
        if boundary <= cursor:  # pragma: no cover - guards against odd zone data
            boundary = cursor + timedelta(hours=1)
        part_end = min(end, boundary)
        yield key, cursor, part_end
        cursor = part_end


def _session_days(session: Session, zone: ZoneInfo, midnight: MidnightRule) -> list[date]:
    if midnight == "start_date" or session.end <= session.start:
        return [local_date(session.start, zone)]
    return [key for key, _s, _e in split_at_midnight(session.start, session.end, zone)]


def _credit(target: Day, page_id: str, minutes: float) -> None:
    target.minutes += minutes
    target.sessions[page_id] = target.sessions.get(page_id, 0.0) + minutes


def _priority(session: Session) -> tuple[datetime, datetime, str]:
    return (session.start, session.end, session.page_id)


def _merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
