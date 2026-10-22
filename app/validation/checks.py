"""Validation rules for one entry (PLAN.md 5).

Every entry is imported; its issues are stored with it as ``[{field, code, message}]``. The
raw log (Phase 7) turns the named field's cell red and shows the message on hover.

* **Missing time**: Start or End is empty, or has a date but no time. Excluded from charts.
* **Invalid range**: End is before Start. Stored on the End field; both cells turn red.
* **Duration mismatch**: Logged minutes differs from End minus Start by more than 1 minute. Checked
  only when Logged minutes has a value and the range is valid.
* **Unreadable extra field**: an extra field's value couldn't be read.

Blank task names are never an issue. Neither is a parent task with several links.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, TypedDict

from app.notion.dates import Moment

IssueCode = Literal["missing_time", "invalid_range", "duration_mismatch", "unreadable_extra"]

#: Logged minutes may differ from End minus Start by this much without an issue.
MISMATCH_TOLERANCE_MIN: Final = 1.0


class Issue(TypedDict):
    #: An app field ("start", "end", "logged_minutes") or "extra:<property id>".
    field: str
    code: IssueCode
    message: str


@dataclass(frozen=True, slots=True)
class Unreadable:
    property_id: str
    name: str
    reason: str


def duration_minutes(start: Moment, end: Moment) -> float | None:
    """End minus Start in minutes, when both have a time."""
    if not (start.utc and end.utc):
        return None
    begin = datetime.fromisoformat(start.utc)
    finish = datetime.fromisoformat(end.utc)
    return (finish - begin).total_seconds() / 60


def format_minutes(minutes: float) -> str:
    """148 → "148 min", 2.5 → "2.5 min", 125 → "125 min" (raw log style: minutes only)."""
    rounded = round(minutes, 1)
    text = str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"
    return f"{text} min"


def validate_entry(
    *,
    start: Moment | None,
    end: Moment | None,
    end_from_range: bool,
    logged_minutes: float | None,
    unreadable: Sequence[Unreadable] = (),
) -> list[Issue]:
    issues: list[Issue] = []
    start_ok = _time_issue(issues, "start", "Start time", start, from_range=False)
    end_ok = _time_issue(issues, "end", "End time", end, from_range=end_from_range)
    if start_ok and end_ok and start is not None and end is not None:
        minutes = duration_minutes(start, end)
        if minutes is not None and minutes < 0:
            issues.append(
                {
                    "field": "end",
                    "code": "invalid_range",
                    "message": f"End time is {format_minutes(-minutes)} before Start time.",
                }
            )
        elif (
            minutes is not None
            and logged_minutes is not None
            and abs(logged_minutes - minutes) > MISMATCH_TOLERANCE_MIN
        ):
            issues.append(
                {
                    "field": "logged_minutes",
                    "code": "duration_mismatch",
                    "message": (
                        f"Logged {format_minutes(logged_minutes)}, but Start → End is "
                        f"{format_minutes(minutes)}."
                    ),
                }
            )
    for item in unreadable:
        issues.append(
            {
                "field": f"extra:{item.property_id}",
                "code": "unreadable_extra",
                "message": f"“{item.name}” couldn't be read: {item.reason}",
            }
        )
    return issues


def _time_issue(
    issues: list[Issue], field: str, label: str, moment: Moment | None, *, from_range: bool
) -> bool:
    """Add a Missing time issue when needed. Returns True when the moment has a time."""
    if moment is None:
        message = (
            "End time is empty: the date in the Start time column has no end. Add an end date "
            "and time to its range."
            if from_range
            else f"{label} is empty."
        )
        issues.append({"field": field, "code": "missing_time", "message": message})
        return False
    if not moment.has_time:
        issues.append(
            {
                "field": field,
                "code": "missing_time",
                "message": f"{label} has a date ({moment.date}) but no time.",
            }
        )
        return False
    return True
