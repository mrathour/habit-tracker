"""Notion date values, converted to UTC (PLAN.md 6.4 "Time zones").

Notion writes a date property's ``start`` and ``end`` as ISO 8601 text:

* with an offset (``Z``, ``+05:30``): converted directly to UTC;
* with a time but no offset, plus the property's ``time_zone``: localized with ``zoneinfo``, then
  converted to UTC;
* a date only (``2026-10-17``): kept as the calendar date with ``has_time`` false. Validation
  reports it as a Missing time issue (PLAN.md 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class Moment:
    """One end of a Notion date value."""

    #: ISO 8601 UTC ending in "Z" (to the millisecond), or None for a date without a time.
    utc: str | None
    #: The calendar date as written in Notion, ``YYYY-MM-DD``.
    date: str
    has_time: bool


@dataclass(frozen=True, slots=True)
class DateValue:
    start: Moment
    #: Set when the value is a range (Start → End inside one property).
    end: Moment | None


def utc_iso(moment: datetime) -> str:
    """``moment`` as ISO 8601 UTC with milliseconds and a ``Z``, as the database stores it."""
    text = moment.astimezone(UTC).isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")


def parse_moment(text: object, time_zone: object = None) -> Moment | None:
    """Parse one ISO 8601 value from Notion. Returns None when it can't be read."""
    if not isinstance(text, str) or not text.strip():
        return None
    value = text.strip()
    if len(value) == 10:
        try:
            return Moment(utc=None, date=date.fromisoformat(value).isoformat(), has_time=False)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        zone = _zone(time_zone)
        if zone is None and time_zone not in (None, ""):
            return None  # a time zone Notion named but this computer doesn't know
        parsed = parsed.replace(tzinfo=zone or UTC)
    return Moment(utc=utc_iso(parsed), date=parsed.date().isoformat(), has_time=True)


def parse_date_value(value: object) -> DateValue | None:
    """Parse a property value's ``date`` object (``{start, end, time_zone}``).

    Returns None when the property is empty or its start can't be read. A range whose end can't
    be read keeps its start and drops the end.
    """
    if not isinstance(value, dict):
        return None
    zone = value.get("time_zone")
    start = parse_moment(value.get("start"), zone)
    if start is None:
        return None
    return DateValue(start=start, end=parse_moment(value.get("end"), zone))


def date_of(property_value: dict[str, Any]) -> DateValue | None:
    """The date inside a ``date`` property value, or None when it is empty."""
    return parse_date_value(property_value.get("date"))


def _zone(name: object) -> ZoneInfo | None:
    if not isinstance(name, str) or not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
