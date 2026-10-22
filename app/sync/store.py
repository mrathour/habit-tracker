"""Reading and writing ``work_logs`` for the sync engine and the Home screen (PLAN.md 11)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final, TypedDict

from app.db.connection import transaction
from app.sync.values import Entry
from app.validation.checks import Issue

#: The columns a sync writes, apart from page_id and synced_at.
_COLUMNS: Final = (
    "display_id",
    "task_name",
    "start_utc",
    "end_utc",
    "parent_task_id",
    "parent_task_ids",
    "logged_minutes",
    "extra_fields",
    "issues",
    "created_time",
    "last_edited_time",
)

#: SQLite's limit on bound parameters is 32766; stay well under it.
_CHUNK: Final = 500


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    added: int
    updated: int


class FlaggedEntry(TypedDict):
    page_id: str
    display_id: str | None
    task_name: str | None
    start_utc: str | None
    end_utc: str | None
    issues: list[Issue]
    url: str


def notion_url(page_id: str) -> str:
    """Notion page links are built when shown (PLAN.md 11)."""
    return f"https://www.notion.so/{page_id.replace('-', '')}"


def _row(entry: Entry) -> tuple[Any, ...]:
    return (
        entry.display_id,
        entry.task_name,
        entry.start.utc if entry.start else None,
        entry.end.utc if entry.end else None,
        entry.parent_task_id,
        json.dumps(entry.parent_task_ids),
        entry.logged_minutes,
        json.dumps(entry.extra_fields, ensure_ascii=False, sort_keys=True),
        json.dumps(entry.issues, ensure_ascii=False),
        entry.created_time,
        entry.last_edited_time,
    )


def upsert(conn: sqlite3.Connection, entries: Sequence[Entry], synced_at: str) -> UpsertCounts:
    """Insert or update ``entries`` in one transaction.

    An entry counts as updated only when something stored changed, so a full sync of an
    unchanged database reports "0 updated".
    """
    if not entries:
        return UpsertCounts(0, 0)
    placeholders = ", ".join("?" * len(entries))
    columns = ", ".join(_COLUMNS)
    added = updated = 0
    with transaction(conn):
        existing = {
            row[0]: tuple(row[1:])
            for row in conn.execute(
                f"SELECT page_id, {columns} FROM work_logs WHERE page_id IN ({placeholders})",  # noqa: S608
                [e.page_id for e in entries],
            )
        }
        for entry in entries:
            values = _row(entry)
            before = existing.get(entry.page_id)
            if before is None:
                added += 1
            elif before == values:
                continue
            else:
                updated += 1
            conn.execute(
                f"INSERT INTO work_logs (page_id, {columns}, synced_at)"  # noqa: S608
                f" VALUES (?, {', '.join('?' * len(_COLUMNS))}, ?)"
                " ON CONFLICT (page_id) DO UPDATE SET "
                + ", ".join(f"{c} = excluded.{c}" for c in (*_COLUMNS, "synced_at")),
                (entry.page_id, *values, synced_at),
            )
    return UpsertCounts(added, updated)


def page_ids(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT page_id FROM work_logs")}


def delete(
    conn: sqlite3.Connection, ids: Iterable[str], *, synced_before: str | None = None
) -> int:
    """Delete these entries; with ``synced_before``, only ones not written since then."""
    batch = list(ids)
    removed = 0
    with transaction(conn):
        for start in range(0, len(batch), _CHUNK):
            chunk = batch[start : start + _CHUNK]
            marks = ", ".join("?" * len(chunk))
            sql = f"DELETE FROM work_logs WHERE page_id IN ({marks})"  # noqa: S608
            params: list[str] = list(chunk)
            if synced_before is not None:
                sql += " AND synced_at <= ?"
                params.append(synced_before)
            removed += conn.execute(sql, params).rowcount
    return removed


def counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """(entries, flagged entries)."""
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(json_array_length(issues) > 0), 0) FROM work_logs"
    ).fetchone()
    return int(row[0]), int(row[1])


def flagged(conn: sqlite3.Connection, limit: int, offset: int = 0) -> list[FlaggedEntry]:
    """Entries with issues, newest start first (entries without a start come last)."""
    rows = conn.execute(
        "SELECT page_id, display_id, task_name, start_utc, end_utc, issues FROM work_logs"
        " WHERE json_array_length(issues) > 0"
        " ORDER BY start_utc IS NULL, start_utc DESC, created_time DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        {
            "page_id": row[0],
            "display_id": row[1],
            "task_name": row[2],
            "start_utc": row[3],
            "end_utc": row[4],
            "issues": json.loads(row[5]),
            "url": notion_url(row[0]),
        }
        for row in rows
    ]
