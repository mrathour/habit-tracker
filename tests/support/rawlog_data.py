"""A known set of local entries for the raw log's tests (PLAN.md 8).

Times are UTC; India (Asia/Kolkata) is UTC+5:30.

====  ===  ===============  ===========================  ==============================
ID    #    Task name        Start → End (UTC)            Notes
====  ===  ===============  ===========================  ==============================
p1    1    Write docs       20 Oct 03:30 → 05:00         90 min; parent t1; every extra set
p2    2    (blank)          20 Oct 04:30 → 05:30         overlaps p1 by 30 min; parents t2, t1
p3    10   Réunion équipe   21 Oct 17:30 → 19:30         crosses midnight in India; mismatch
p4    3    No end           22 Oct 03:00 → (none)        Missing time
p5    WL-4 Backwards        19 Oct 05:00 → 04:53         Invalid range
p6    -    =SUM(A1)         18 Oct 04:30 → 05:00         Unreadable extra (notes)
====  ===  ===============  ===========================  ==============================
"""

from __future__ import annotations

import json
from typing import Any

from app.db import Database
from app.db.settings import Settings

STAMP = "2026-10-01T00:00:00.000Z"

EXTRA_NAMES = {
    "mood": ("Mood", "select"),
    "tags": ("Tags", "multi_select"),
    "bill": ("Billable", "checkbox"),
    "notes": ("Notes", "rich_text"),
    "score": ("Score", "number"),
    "due": ("Due", "date"),
    "ppl": ("Helpers", "people"),
    "rel": ("Related", "relation"),
    "calc": ("Calc", "formula"),
}

MISMATCH = {
    "field": "logged_minutes",
    "code": "duration_mismatch",
    "message": "Logged 200 min, but Start → End is 120 min.",
}
MISSING = {"field": "end", "code": "missing_time", "message": "End time is empty."}
INVALID = {
    "field": "end",
    "code": "invalid_range",
    "message": "End time is 7 min before Start time.",
}
UNREADABLE = {
    "field": "extra:notes",
    "code": "unreadable_extra",
    "message": "“Notes” couldn't be read: Notion didn't send a value for it.",
}


def mapping(*, display_id: bool = True, logged: bool = True, parent: bool = True) -> dict[str, Any]:
    return {
        "version": 1,
        "fields": {
            "start": {"property_id": "s", "part": "start"},
            "end": {"property_id": "e", "part": "start"},
            "task_name": {"property_id": "title"},
            "parent_task": {"property_id": "par"} if parent else None,
            "display_id": {"property_id": "id"} if display_id else None,
            "logged_minutes": {"property_id": "min"} if logged else None,
        },
        "extra": list(EXTRA_NAMES),
        "names_at_save": {key: name for key, (name, _kind) in EXTRA_NAMES.items()},
        "saved_at": STAMP,
    }


def extras(**values: Any) -> dict[str, Any]:
    """Every extra field, empty unless given."""
    stored: dict[str, Any] = {}
    for key, (name, kind) in EXTRA_NAMES.items():
        default: Any = False if kind == "checkbox" else ([] if kind.endswith("select") else None)
        if kind in ("people", "relation"):
            default = []
        stored[key] = {"name": name, "type": kind, "value": values.get(key, default)}
    return stored


def add(
    db: Database,
    page_id: str,
    start: str | None,
    end: str | None,
    *,
    display_id: str | None = None,
    task_name: str | None = None,
    parents: list[str] | None = None,
    logged: float | None = None,
    extra: dict[str, Any] | None = None,
    issues: list[dict[str, str]] | None = None,
    synced_at: str = STAMP,
) -> None:
    parents = parents or []
    with db.connection:
        db.connection.execute(
            "INSERT INTO work_logs (page_id, display_id, task_name, start_utc, end_utc,"
            " parent_task_id, parent_task_ids, logged_minutes, extra_fields, issues,"
            " created_time, last_edited_time, synced_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                page_id,
                display_id,
                task_name,
                start,
                end,
                parents[0] if parents else None,
                json.dumps(parents),
                logged,
                json.dumps(extra if extra is not None else extras(), ensure_ascii=False),
                json.dumps(issues or [], ensure_ascii=False),
                STAMP,
                STAMP,
                synced_at,
            ),
        )


def known_set(db: Database) -> None:
    Settings(db.connection).set_many({"mapping": mapping(), "database_title": "Work Log (test)"})
    add(
        db,
        "p1",
        "2026-10-20T03:30:00.000Z",
        "2026-10-20T05:00:00.000Z",
        display_id="1",
        task_name="Write docs",
        parents=["t1"],
        logged=90,
        extra=extras(
            mood="Focused",
            tags=["deep", "docs"],
            bill=True,
            notes='Commas, "quotes"\nand a second line',
            score=4,
            due={
                "start": {
                    "utc": "2026-10-25T04:00:00.000Z",
                    "date": "2026-10-25",
                    "has_time": True,
                },
                "end": None,
            },
            ppl=["u1"],
            rel=["r1", "r2"],
            calc={"type": "number", "value": 1.5},
        ),
    )
    add(
        db,
        "p2",
        "2026-10-20T04:30:00.000Z",
        "2026-10-20T05:30:00.000Z",
        display_id="2",
        parents=["t2", "t1"],
        logged=60,
        extra=extras(mood="Tired", tags=["admin"], score=-2, calc={"type": "number", "value": 3}),
    )
    add(
        db,
        "p3",
        "2026-10-21T17:30:00.000Z",
        "2026-10-21T19:30:00.000Z",
        display_id="10",
        task_name="Réunion équipe",
        logged=200,
        extra=extras(
            notes="日本語のメモ",
            due={"start": {"utc": None, "date": "2026-10-30", "has_time": False}, "end": None},
        ),
        issues=[MISMATCH],
    )
    add(
        db,
        "p4",
        "2026-10-22T03:00:00.000Z",
        None,
        display_id="3",
        task_name="No end",
        issues=[MISSING],
    )
    add(
        db,
        "p5",
        "2026-10-19T05:00:00.000Z",
        "2026-10-19T04:53:00.000Z",
        display_id="WL-4",
        task_name="Backwards",
        issues=[INVALID],
    )
    add(
        db,
        "p6",
        "2026-10-18T04:30:00.000Z",
        "2026-10-18T05:00:00.000Z",
        task_name="=SUM(A1)",
        extra=extras(notes=None),
        issues=[UNREADABLE],
    )
