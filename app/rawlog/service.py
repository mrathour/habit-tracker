"""The raw log for the UI (PLAN.md 8): filtered, sorted pages of entries, and CSV export.

Filtering and sorting run in Python on a :mod:`snapshot <app.rawlog.snapshot>` of every entry,
kept until the data or the time zone changes. The table asks for the rows it is showing, a page
at a time, so it stays fast with thousands of entries. The last filtered and sorted order is
kept too, so scrolling only slices it.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.settings import Settings
from app.rawlog import snapshot as snapshots
from app.rawlog import view
from app.rawlog.export import Cell, ExportError, safe_file_name, write_csv
from app.rawlog.extras import EMPTY, ExtraCell, number_text
from app.rawlog.filters import parse as parse_filters
from app.rawlog.snapshot import (
    EXTRA_PREFIX,
    ColumnInfo,
    LogRow,
    OverlapWith,
    Snapshot,
    display_id_key,
)
from app.rawlog.view import RawLogError, SortSpec, ViewPrefs
from app.sync.store import notion_url
from app.validation.checks import Issue

logger = logging.getLogger(__name__)

MAX_PAGE: Final = 500

#: Chooses where to save: gets a suggested file name, returns a path or None if cancelled.
ChooseSavePath = Callable[[str], str | None]


class RawLogRow(TypedDict):
    page_id: str
    url: str
    display_id: str | None
    task_name: str | None
    start_utc: str | None
    end_utc: str | None
    duration_minutes: float | None
    logged_minutes: float | None
    parent_task_ids: list[str]
    parent_urls: list[str]
    extras: dict[str, ExtraCell | None]
    issues: list[Issue]
    overlap_minutes: float
    overlaps_with: list[OverlapWith]


class ParentChoice(TypedDict):
    page_id: str
    url: str
    entries: int
    #: The task name of the newest entry linking it (titles of linked pages aren't read).
    latest_task_name: str | None


class RawLogPage(TypedDict):
    time_zone: str
    #: Every local entry, and those matching the filters.
    total_entries: int
    matched: int
    offset: int
    rows: list[RawLogRow]
    sort: SortSpec
    columns: list[ColumnInfo]
    parents: list[ParentChoice]
    view: ViewPrefs


class ExportResult(TypedDict):
    status: Literal["saved", "cancelled", "empty"]
    path: str | None
    rows: int


class RawLogService:
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
        self._lock = threading.Lock()
        self._snapshot: tuple[tuple[Any, ...], Snapshot] | None = None
        self._ordered: tuple[tuple[Any, ...], list[LogRow]] | None = None
        self._last_export: Path | None = None

    # --- the table ---------------------------------------------------------------------------

    def page(self, request: object) -> RawLogPage:
        """One page of rows: ``{time_zone, filters, sort, offset, limit}``."""
        if not isinstance(request, dict):
            raise RawLogError("The raw log request was sent in an unexpected form.")
        offset = _whole(request.get("offset", 0), "offset", 0, None)
        limit = _whole(request.get("limit", 100), "page size", 1, MAX_PAGE)
        snap, rows, sort = self._query(request)
        prefs = view.read(self._settings)
        return {
            "time_zone": str(snap.zone.key),
            "total_entries": len(snap.rows),
            "matched": len(rows),
            "offset": offset,
            "rows": [_row_out(row) for row in rows[offset : offset + limit]],
            "sort": sort,
            "columns": snap.columns,
            "parents": [
                {
                    "page_id": page_id,
                    "url": notion_url(page_id),
                    "entries": count,
                    "latest_task_name": name,
                }
                for page_id, (count, name) in sorted(
                    snap.parents.items(), key=lambda item: (-item[1][0], item[0])
                )
            ],
            "view": prefs,
        }

    def view(self) -> ViewPrefs:
        return view.read(self._settings)

    def update_view(self, changes: object) -> ViewPrefs:
        return view.update(self._settings, changes)

    # --- CSV export --------------------------------------------------------------------------

    def export(self, request: object, columns: object, choose: ChooseSavePath) -> ExportResult:
        """Save the rows, columns and order on screen as CSV, asking where with ``choose``."""
        if not isinstance(request, dict):
            raise RawLogError("The export request was sent in an unexpected form.")
        snap, rows, _sort = self._query(request)
        chosen = _export_columns(columns, snap)
        if not rows:
            return {"status": "empty", "path": None, "rows": 0}
        today = self._clock().astimezone(snap.zone).date().isoformat()
        title = self._settings.get_str("database_title") or "Work log"
        picked = choose(safe_file_name(f"{title} raw log {today}"))
        if not picked:
            return {"status": "cancelled", "path": None, "rows": 0}
        target = Path(picked)
        if not target.suffix:
            target = target.with_suffix(".csv")
        header = [_header(column, snap) for column in chosen]
        written = write_csv(target, header, _csv_rows(rows, chosen, snap))
        self._last_export = target.resolve()
        logger.info("Exported %d raw log rows (%d columns) to CSV", written, len(chosen))
        return {"status": "saved", "path": str(self._last_export), "rows": written}

    def last_export(self) -> Path:
        if self._last_export is None or not self._last_export.exists():
            raise ExportError("The exported file can't be found. It may have been moved.")
        return self._last_export

    # --- data --------------------------------------------------------------------------------

    def _query(self, request: dict[str, Any]) -> tuple[Snapshot, list[LogRow], SortSpec]:
        zone = _zone(request.get("time_zone"))
        sort = view.parse_sort(request.get("sort", view.DEFAULT_SORT))
        with self._lock:
            snap = self._current(zone)
            known = {column["key"] for column in snap.columns}
            if sort["column"] not in known:
                sort = dict(view.DEFAULT_SORT)  # type: ignore[assignment]
            filters = parse_filters(request.get("filters"), snap)
            key = (id(snap), filters, sort["column"], sort["direction"])
            if self._ordered is not None and self._ordered[0] == key:
                return snap, self._ordered[1], sort
            matching = [row for row in snap.rows if not filters.active or filters.matches(row)]
            rows = _sorted(matching, sort, snap)
            self._ordered = (key, rows)
            return snap, rows, sort

    def _current(self, zone: ZoneInfo) -> Snapshot:
        key = (*snapshots.fingerprint(self._db, self._settings), str(zone.key))
        if self._snapshot is None or self._snapshot[0] != key:
            self._snapshot = (key, snapshots.build(self._db, self._settings, zone))
            self._ordered = None
        return self._snapshot[1]


# --- sorting ---------------------------------------------------------------------------------


def _sorted(rows: list[LogRow], sort: SortSpec, snap: Snapshot) -> list[LogRow]:
    """Empty values last in both directions; ties keep the newest start first."""
    rows = sorted(rows, key=lambda row: row.page_id)
    rows.sort(key=lambda row: row.start_utc or "", reverse=True)
    rows.sort(key=lambda row: row.start_utc is None)
    key = _sort_key(sort["column"], snap)
    present = [row for row in rows if key(row) is not None]
    missing = [row for row in rows if key(row) is None]
    present.sort(key=key, reverse=sort["direction"] == "desc")
    return present + missing


def _sort_key(column: str, snap: Snapshot) -> Callable[[LogRow], Any]:
    if column.startswith(EXTRA_PREFIX):
        property_id = column.removeprefix(EXTRA_PREFIX)
        return lambda row: row.extra_value(property_id).sort
    if column == "display_id":
        return lambda row: display_id_key(row.display_id) if row.display_id else None
    if column == "task_name":
        return lambda row: row.task_name.casefold() if row.task_name else None
    if column == "start":
        return lambda row: row.start
    if column == "end":
        return lambda row: row.end
    if column == "duration":
        return lambda row: row.duration
    if column == "logged_minutes":
        return lambda row: row.logged_minutes
    if column == "parent_task":
        return lambda row: row.parent_ids[0] if row.parent_ids else None
    if column == "overlap":
        return lambda row: row.overlap_minutes
    return lambda row: len(row.issues)


# --- rows for the UI and the CSV file -------------------------------------------------------


def _row_out(row: LogRow) -> RawLogRow:
    return {
        "page_id": row.page_id,
        "url": notion_url(row.page_id),
        "display_id": row.display_id,
        "task_name": row.task_name,
        "start_utc": row.start_utc,
        "end_utc": row.end_utc,
        "duration_minutes": round(row.duration, 4) if row.duration is not None else None,
        "logged_minutes": row.logged_minutes,
        "parent_task_ids": row.parent_ids,
        "parent_urls": [notion_url(page_id) for page_id in row.parent_ids],
        "extras": {property_id: value.cell for property_id, value in row.extras.items()},
        "issues": row.issues,
        "overlap_minutes": round(row.overlap_minutes, 4),
        "overlaps_with": row.overlaps_with,
    }


def _export_columns(value: object, snap: Snapshot) -> list[ColumnInfo]:
    if not isinstance(value, list) or not value:
        raise RawLogError("Choose at least one column to export.")
    by_key = {column["key"]: column for column in snap.columns}
    chosen: list[ColumnInfo] = []
    for key in value:
        if not isinstance(key, str) or key not in by_key:
            raise RawLogError("A column to export isn't in the raw log.", detail=repr(key))
        if by_key[key] not in chosen:
            chosen.append(by_key[key])
    return chosen


def _header(column: ColumnInfo, snap: Snapshot) -> str:
    zone = str(snap.zone.key)
    kind = column["kind"]
    if kind in ("start", "end") or (kind == "extra" and column["filter"] == "date"):
        return f"{column['label']} ({zone})"
    if kind in ("duration", "overlap"):
        return f"{column['label']} (min)"
    return column["label"]


def _csv_rows(
    rows: Sequence[LogRow], columns: Sequence[ColumnInfo], snap: Snapshot
) -> Iterator[list[Cell]]:
    for row in rows:
        yield [_csv_cell(row, column, snap.zone) for column in columns]


def _csv_cell(row: LogRow, column: ColumnInfo, zone: ZoneInfo) -> Cell:
    kind = column["kind"]
    if kind == "display_id":
        return Cell(row.display_id or "")
    if kind == "task_name":
        return Cell(row.task_name or "")
    if kind in ("start", "end"):
        moment = row.start if kind == "start" else row.end
        text = moment.astimezone(zone).strftime("%Y-%m-%d %H:%M") if moment else ""
        return Cell(text, formula_safe=True)
    if kind == "duration":
        return Cell(_minutes(row.duration), formula_safe=True)
    if kind == "logged_minutes":
        return Cell(_minutes(row.logged_minutes), formula_safe=True)
    if kind == "parent_task":
        return Cell("\n".join(notion_url(p) for p in row.parent_ids))
    if kind == "overlap":
        overlap = row.overlap_minutes if row.overlap_minutes > 0 else None
        return Cell(_minutes(overlap), formula_safe=True)
    if kind == "issues":
        return Cell("\n".join(issue["message"] for issue in row.issues))
    value = row.extras.get(column["key"].removeprefix(EXTRA_PREFIX), EMPTY)
    return Cell(value.csv, formula_safe=value.formula_safe)


def _minutes(value: float | None) -> str:
    return number_text(round(value, 2)) if value is not None else ""


# --- request values --------------------------------------------------------------------------


def _zone(name: object) -> ZoneInfo:
    if not isinstance(name, str) or not name:
        raise RawLogError("The computer's time zone wasn't sent.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RawLogError(
            "Habit Tracker doesn't recognise this computer's time zone.", detail=name
        ) from exc


def _whole(value: object, what: str, low: int, high: int | None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < low:
        raise RawLogError(f"The {what} was sent in an unexpected form.")
    if high is not None and value > high:
        raise RawLogError(f"The {what} can be at most {high}.")
    return value
