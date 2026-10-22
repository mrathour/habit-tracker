"""Data source schemas and rows shaped like Notion API 2026-03-11 responses, for tests.

The Work Log schema mirrors the author's real database (PLAN.md 3), checked in Notion on
2026-10-22: Name (title), Start Time and End Time (date), MinuteSpent (number), Parent Task
(relation, one page) and ID (unique ID, no prefix; Notion shows it as "№ ID"). Work Log (test)
has the same columns. Property IDs are realistic URL-encoded short IDs; the title's is "title".
"""

from __future__ import annotations

import copy
from typing import Any

from tests.support.fake_notion import FakeDatabase, FakeNotion

Schema = dict[str, dict[str, Any]]

WORK_LOG_IDS = {
    "Name": "title",
    "Start Time": "%3DjVp",
    "End Time": "Q%5Ckh",
    "MinuteSpent": "ZCx%3F",
    "Parent Task": "fmJa",
    "ID": "%7BmH%40",
}

TASK_TRACKER_DS = "520e0461-ff97-4231-8a49-9cad4558add1"
TASK_PAGE = "3fc15553-ce3d-8013-8a43-cb18275fee9b"

_CONFIG: dict[str, Any] = {
    "number": {"format": "number"},
    "relation": {
        "database_id": "3fc15553-ce3d-80aa-0000-000000000001",
        "data_source_id": TASK_TRACKER_DS,
        "type": "single_property",
        "single_property": {},
    },
    "unique_id": {"prefix": None},
    "formula": {"expression": 'dateBetween(prop("End"), prop("Start"), "minutes")'},
    "select": {"options": [{"id": "o1", "name": "Deep work", "color": "blue"}]},
    "multi_select": {"options": []},
    "status": {"options": [], "groups": [], "default_option": "Not started"},
    "rollup": {
        "relation_property_id": "fmJa",
        "rollup_property_id": "title",
        "function": "show_original",
    },
}


def prop(name: str, prop_id: str, kind: str, config: dict[str, Any] | None = None) -> Schema:
    return {
        name: {
            "id": prop_id,
            "name": name,
            "type": kind,
            "description": "",
            kind: config if config is not None else copy.deepcopy(_CONFIG.get(kind, {})),
        }
    }


def schema(*parts: Schema) -> Schema:
    result: Schema = {}
    for part in parts:
        result.update(part)
    return result


def work_log_schema(renamed: dict[str, str] | None = None) -> Schema:
    """The author's Work Log. ``renamed`` maps old column names to new ones (IDs unchanged)."""
    names = renamed or {}
    types = {
        "ID": "unique_id",
        "Name": "title",
        "Start Time": "date",
        "End Time": "date",
        "MinuteSpent": "number",
        "Parent Task": "relation",
    }
    return schema(
        *(prop(names.get(name, name), WORK_LOG_IDS[name], kind) for name, kind in types.items())
    )


def without(source: Schema, *names: str) -> Schema:
    return {name: spec for name, spec in source.items() if name not in names}


# --- values -----------------------------------------------------------------------------------


def rich(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    return [
        {
            "type": "text",
            "text": {"content": text, "link": None},
            "plain_text": text,
            "href": None,
            "annotations": {},
        }
    ]


def when(start: str | None, end: str | None = None, tz: str | None = None) -> dict[str, Any] | None:
    if start is None:
        return None
    return {"start": start, "end": end, "time_zone": tz}


def empty_value(kind: str) -> Any:
    if kind in ("title", "rich_text", "multi_select", "people", "files", "relation"):
        return []
    if kind == "checkbox":
        return False
    if kind == "unique_id":
        return {"prefix": None, "number": None}
    if kind == "formula":
        return {"type": "number", "number": None}
    if kind == "rollup":
        return {"type": "array", "array": [], "function": "show_original"}
    return None


def page(
    properties: Schema, values: dict[str, Any], *, created: str, page_id: str | None = None
) -> dict[str, Any]:
    """A page object whose ``properties`` follow ``properties``; ``values`` by column name."""
    body: dict[str, Any] = {}
    for name, spec in properties.items():
        kind = spec["type"]
        value = values.get(name, empty_value(kind))
        entry: dict[str, Any] = {"id": spec["id"], "type": kind, kind: value}
        if kind == "relation":
            entry["has_more"] = False
        body[name] = entry
    pid = page_id or f"page-{created}"
    return {
        "object": "page",
        "id": pid,
        "created_time": created,
        "last_edited_time": created,
        "in_trash": False,
        "properties": body,
        "url": f"https://www.notion.so/{pid.replace('-', '')}",
    }


def work_log_rows(properties: Schema | None = None) -> list[dict[str, Any]]:
    """Rows like the author's, oldest first. The newest has a blank name, as often happens."""
    source = properties or work_log_schema()
    names = {spec["id"]: name for name, spec in source.items()}

    def row(created: str, **by_original_name: Any) -> dict[str, Any]:
        values = {
            names[WORK_LOG_IDS[name]]: value
            for name, value in by_original_name.items()
            if WORK_LOG_IDS[name] in names
        }
        return page(source, values, created=created)

    task = [{"id": TASK_PAGE}]
    return [
        row(
            "2026-10-17T12:11:00.000Z",
            ID={"prefix": None, "number": 6},
            Name=rich("Work Log Table Created"),
            **{
                "Start Time": when("2026-10-17T17:41:00.000+05:30"),
                "End Time": when("2026-10-17T17:43:00.000+05:30"),
                "MinuteSpent": 2,
                "Parent Task": task,
            },
        ),
        row(
            "2026-10-20T01:22:00.000Z",
            ID={"prefix": None, "number": 7},
            Name=rich("Writing EVA resume"),
            **{
                "Start Time": when("2026-10-20T06:52:00.000+05:30"),
                "End Time": when("2026-10-20T09:00:00.000+05:30"),
                "MinuteSpent": 128,
                "Parent Task": task,
            },
        ),
        row(
            "2026-10-21T06:08:00.000Z",
            ID={"prefix": None, "number": 8},
            **{
                "Start Time": when("2026-10-21T11:38:00.000+05:30"),
                "End Time": when("2026-10-21T12:15:00.000+05:30"),
                "MinuteSpent": 37,
                "Parent Task": task,
            },
        ),
    ]


def add_source(
    notion: FakeNotion, title: str, properties: Schema, rows: list[dict[str, Any]] | None = None
) -> tuple[FakeDatabase, str]:
    """Add a one-source database with this schema and these rows; returns it and its source ID."""
    database = notion.add_database(title)
    source_id = database.data_source_ids[0]
    notion.data_sources[source_id].properties = properties
    notion.data_sources[source_id].pages = rows or []
    return database, source_id
