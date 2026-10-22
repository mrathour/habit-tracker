"""Every local entry, read once and ready to filter, sort and show (PLAN.md 8).

A snapshot is built from ``work_logs`` for one time zone and kept until the data changes, so
scrolling and changing filters don't read the database again. Overlaps come from the
dashboard's own functions (``app/stats``), on the same counted sessions, so the raw log and the
day detail always agree.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final, Literal, TypedDict
from zoneinfo import ZoneInfo

from app.db.connection import lock_for
from app.db.settings import MAPPING_KEY, Settings
from app.mapping.fields import FieldKey
from app.mapping.model import MappingFormatError, parse_mapping
from app.mapping.properties import type_label
from app.rawlog.extras import EMPTY, ExtraValue, FilterKind, filter_kind, read_extra
from app.stats.allocation import overlaps
from app.stats.sessions import counted_session, session_label
from app.validation.checks import Issue

ColumnKind = Literal[
    "display_id",
    "task_name",
    "start",
    "end",
    "duration",
    "logged_minutes",
    "parent_task",
    "extra",
    "overlap",
    "issues",
]

#: App columns in table order, with the mapped field each needs (None: always shown).
APP_COLUMNS: Final[tuple[tuple[ColumnKind, str, FieldKey | None], ...]] = (
    ("display_id", "ID", "display_id"),
    ("task_name", "Task name", "task_name"),
    ("start", "Start", None),
    ("end", "End", None),
    ("duration", "Duration", None),
    ("logged_minutes", "Logged minutes", "logged_minutes"),
    ("parent_task", "Parent task", "parent_task"),
)
#: After the extra fields.
TRAILING_COLUMNS: Final[tuple[tuple[ColumnKind, str], ...]] = (
    ("overlap", "Overlap"),
    ("issues", "Issues"),
)

EXTRA_PREFIX: Final = "extra:"

_DISPLAY_ID = re.compile(r"^(.*?)(\d+)$")


class ColumnInfo(TypedDict):
    key: str
    label: str
    kind: ColumnKind
    #: Extra fields only: the Notion type, its label, and the filter it offers.
    type: str | None
    type_label: str | None
    filter: FilterKind | None
    #: Options seen in this column (option filters only), sorted.
    options: list[str]


class OverlapWith(TypedDict):
    page_id: str
    label: str


@dataclass(frozen=True, slots=True)
class ExtraColumn:
    property_id: str
    name: str
    type: str
    filter: FilterKind
    options: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{EXTRA_PREFIX}{self.property_id}"


@dataclass(slots=True)
class LogRow:
    page_id: str
    display_id: str | None
    task_name: str | None
    start_utc: str | None
    end_utc: str | None
    start: datetime | None
    end: datetime | None
    #: The local date the entry starts on, for the date filter.
    day: date | None
    #: End minus Start, only for entries that count (PLAN.md 5).
    duration: float | None
    logged_minutes: float | None
    parent_ids: list[str]
    extras: dict[str, ExtraValue]
    issues: list[Issue]
    codes: frozenset[str]
    overlap_minutes: float = 0.0
    overlaps_with: list[OverlapWith] = field(default_factory=list)
    search: str = ""

    def extra_value(self, property_id: str) -> ExtraValue:
        return self.extras.get(property_id, EMPTY)


@dataclass(frozen=True, slots=True)
class Snapshot:
    zone: ZoneInfo
    rows: list[LogRow]
    columns: list[ColumnInfo]
    extra_columns: dict[str, ExtraColumn]
    #: Every linked parent page: page ID -> (entries linking it, the newest entry's task name).
    parents: dict[str, tuple[int, str | None]]


def fingerprint(conn: sqlite3.Connection, settings: Settings) -> tuple[Any, ...]:
    """Changes whenever the entries or the mapping change.

    ``data_version`` moves when another connection (the sync's) commits; the count and newest
    ``synced_at`` catch writes on the shared connection (clearing local data).
    """
    with lock_for(conn):
        version = conn.execute("PRAGMA data_version").fetchone()[0]
        count, newest = conn.execute("SELECT COUNT(*), MAX(synced_at) FROM work_logs").fetchone()
    return (version, count, newest, json.dumps(settings.get(MAPPING_KEY), sort_keys=True))


def build(conn: sqlite3.Connection, settings: Settings, zone: ZoneInfo) -> Snapshot:
    mapped, extra_ids, names_at_save = _mapping(settings)
    with lock_for(conn):
        records = conn.execute(
            "SELECT page_id, display_id, task_name, start_utc, end_utc, parent_task_ids,"
            " logged_minutes, extra_fields, issues FROM work_logs ORDER BY synced_at, page_id"
        ).fetchall()

    # Each extra column's latest name and type: rows come oldest sync first, so later win.
    latest: dict[str, tuple[str, str]] = {}
    raw_extras: list[dict[str, Any]] = []
    for record in records:
        extras = json.loads(record[7])
        raw_extras.append(extras)
        for property_id in extra_ids:
            stored = extras.get(property_id)
            if isinstance(stored, dict) and isinstance(stored.get("type"), str):
                latest[property_id] = (str(stored.get("name") or ""), stored["type"])

    rows: list[LogRow] = []
    sessions = []
    for record, extras in zip(records, raw_extras, strict=True):
        page_id, display_id, task_name, start_utc, end_utc = record[:5]
        issues: list[Issue] = json.loads(record[8])
        start = datetime.fromisoformat(start_utc) if start_utc else None
        end = datetime.fromisoformat(end_utc) if end_utc else None
        session = counted_session(
            page_id, start_utc, end_utc, issues, display_id=display_id, task_name=task_name
        )
        if session is not None:
            sessions.append(session)
        values: dict[str, ExtraValue] = {}
        for property_id in extra_ids:
            stored = extras.get(property_id)
            if isinstance(stored, dict):
                kind = str(stored.get("type") or latest.get(property_id, ("", ""))[1])
                values[property_id] = read_extra(kind, stored.get("value"), zone)
        rows.append(
            LogRow(
                page_id=page_id,
                display_id=display_id,
                task_name=task_name,
                start_utc=start_utc,
                end_utc=end_utc,
                start=start,
                end=end,
                day=start.astimezone(zone).date() if start else None,
                duration=session.minutes if session else None,
                logged_minutes=record[6],
                parent_ids=[p for p in json.loads(record[5]) if isinstance(p, str)],
                extras=values,
                issues=issues,
                codes=frozenset(str(issue.get("code")) for issue in issues),
                search=(task_name or "").casefold(),
            )
        )

    by_id = {row.page_id: row for row in rows}
    for page_id, (minutes, others) in overlaps(sessions).items():
        row = by_id[page_id]
        row.overlap_minutes = minutes
        row.overlaps_with = [{"page_id": o.page_id, "label": session_label(o)} for o in others]

    extra_columns: dict[str, ExtraColumn] = {}
    for property_id in extra_ids:
        name, kind = latest.get(property_id, (names_at_save.get(property_id, ""), ""))
        stored_values = [
            extras[property_id].get("value")
            for extras in raw_extras
            if isinstance(extras.get(property_id), dict)
        ]
        filter_as = filter_kind(kind, stored_values)
        options: set[str] = set()
        if filter_as == "options":
            for row in rows:
                options.update(row.extra_value(property_id).options)
        extra_columns[property_id] = ExtraColumn(
            property_id=property_id,
            name=name or names_at_save.get(property_id) or "Untitled column",
            type=kind,
            filter=filter_as,
            options=tuple(sorted(options, key=str.casefold)),
        )

    return Snapshot(
        zone=zone,
        rows=rows,
        columns=_columns(mapped, extra_columns),
        extra_columns=extra_columns,
        parents=_parents(rows),
    )


def display_id_key(value: str) -> tuple[str, float, str]:
    """IDs sort naturally: "WL-9" before "WL-10", and 9 before 10."""
    match = _DISPLAY_ID.match(value)
    if match:
        return (match.group(1).casefold(), float(match.group(2)), value)
    return (value.casefold(), -1.0, value)


def _mapping(settings: Settings) -> tuple[set[FieldKey], list[str], dict[str, str]]:
    """The mapped app fields, the extra fields in order, and their names at save."""
    try:
        stored = parse_mapping(settings.get(MAPPING_KEY))
    except MappingFormatError:
        # No mapping (or a damaged one): show every app field, and no extra fields.
        return {key for _k, _l, key in APP_COLUMNS if key}, [], {}
    mapped = {key for key, ref in stored["fields"].items() if ref is not None}
    return mapped, list(stored["extra"]), dict(stored["names_at_save"])


def _columns(mapped: set[FieldKey], extras: dict[str, ExtraColumn]) -> list[ColumnInfo]:
    columns: list[ColumnInfo] = []
    for kind, label, needs in APP_COLUMNS:
        if needs is None or needs in mapped:
            columns.append(_column(kind, kind, label))
    for extra in extras.values():
        column = _column(extra.key, "extra", extra.name)
        column["type"] = extra.type or None
        column["type_label"] = type_label(extra.type) if extra.type else None
        column["filter"] = extra.filter
        column["options"] = list(extra.options)
        columns.append(column)
    for kind, label in TRAILING_COLUMNS:
        columns.append(_column(kind, kind, label))
    return columns


def _column(key: str, kind: ColumnKind, label: str) -> ColumnInfo:
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "type": None,
        "type_label": None,
        "filter": None,
        "options": [],
    }


def _parents(rows: list[LogRow]) -> dict[str, tuple[int, str | None]]:
    counts: dict[str, int] = {}
    newest: dict[str, tuple[str, str | None]] = {}
    for row in rows:
        for parent in dict.fromkeys(row.parent_ids):
            counts[parent] = counts.get(parent, 0) + 1
            stamp = row.start_utc or ""
            if parent not in newest or stamp > newest[parent][0]:
                newest[parent] = (stamp, row.task_name)
    return {parent: (count, newest[parent][1]) for parent, count in counts.items()}
