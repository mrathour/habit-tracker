"""Which stored entries count as sessions (PLAN.md 5, 7).

The dashboard and the raw log both read sessions through :func:`counted_session`, so the two
always agree on which entries count, their durations and their overlaps.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Final

from app.stats.allocation import Session

#: Issues that keep an entry out of the charts (PLAN.md 5).
EXCLUDING_CODES: Final = ("missing_time", "invalid_range")


def counted_session(
    page_id: str,
    start_utc: str | None,
    end_utc: str | None,
    issues: Iterable[Mapping[str, object]],
    *,
    display_id: str | None = None,
    task_name: str | None = None,
) -> Session | None:
    """The entry as a session, or None when it's left out of the charts.

    Left out: entries flagged Missing time or Invalid range, and, as a guard, any entry stored
    without both times or with End before Start (validation flags those too).
    """
    if any(issue.get("code") in EXCLUDING_CODES for issue in issues):
        return None
    if not start_utc or not end_utc:
        return None
    start = datetime.fromisoformat(start_utc)
    end = datetime.fromisoformat(end_utc)
    if end < start:
        return None
    return Session(page_id, start, end, display_id, task_name)


def session_label(session: Session) -> str:
    """A session's label: "#6 Write docs", or the name alone ("Untitled" when blank)."""
    name = session.task_name or "Untitled"
    return f"#{session.display_id} {name}" if session.display_id else name
