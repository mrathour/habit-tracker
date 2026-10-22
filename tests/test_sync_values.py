"""Turning Notion pages into local entries, following the saved mapping."""

from __future__ import annotations

from typing import Any

import pytest

from app.mapping.model import StoredMapping, parse_mapping
from app.mapping.properties import Property, schema_properties
from app.sync.values import UnreadableValueError, normalise, read_entry, relations_to_complete
from tests.support.notion_schemas import (
    BROKEN_EXPECTED,
    TASK_PAGE,
    WORK_LOG_IDS,
    Schema,
    broken_rows,
    page,
    prop,
    rich,
    schema,
    when,
    without,
    work_log_rows,
    work_log_schema,
)

IDS = WORK_LOG_IDS


def mapping_for(**changes: Any) -> StoredMapping:
    fields: dict[str, Any] = {
        "start": {"property_id": IDS["Start Time"], "part": "start"},
        "end": {"property_id": IDS["End Time"], "part": "start"},
        "task_name": {"property_id": "title"},
        "parent_task": {"property_id": IDS["Parent Task"]},
        "display_id": {"property_id": IDS["ID"]},
        "logged_minutes": {"property_id": IDS["MinuteSpent"]},
    }
    extra = changes.pop("extra", [])
    fields.update(changes)
    return parse_mapping({"version": 1, "fields": fields, "extra": extra})


def columns_of(source: Schema) -> dict[str, Property]:
    return {p.id: p for p in schema_properties({"properties": source})}


def test_work_log_row() -> None:
    row = work_log_rows()[1]
    entry = read_entry(row, mapping_for(), columns_of(work_log_schema()))
    assert entry.page_id == row["id"]
    assert entry.display_id == "7"
    assert entry.task_name == "Writing EVA resume"
    assert entry.start is not None
    assert entry.start.utc == "2026-10-20T01:22:00.000Z"
    assert entry.end is not None
    assert entry.end.utc == "2026-10-20T03:30:00.000Z"
    assert entry.logged_minutes == 128
    assert entry.parent_task_ids == [TASK_PAGE]
    assert entry.parent_task_id == TASK_PAGE
    assert entry.issues == []
    assert entry.created_time == "2026-10-20T01:22:00.000Z"


def test_every_broken_case_is_flagged_correctly() -> None:
    mapping = mapping_for()
    columns = columns_of(work_log_schema())
    for row in broken_rows():
        entry = read_entry(row, mapping, columns)
        assert [i["code"] for i in entry.issues] == BROKEN_EXPECTED[row["id"]], row["id"]


def test_blank_name_is_kept_as_empty_and_not_flagged() -> None:
    row = next(r for r in broken_rows() if r["id"] == "p-blank-name")
    entry = read_entry(row, mapping_for(), columns_of(work_log_schema()))
    assert entry.task_name is None
    assert entry.issues == []


def test_unused_fields_stay_empty() -> None:
    mapping = mapping_for(display_id=None, logged_minutes=None, parent_task=None, task_name=None)
    entry = read_entry(work_log_rows()[0], mapping, columns_of(work_log_schema()))
    assert (entry.display_id, entry.task_name, entry.logged_minutes) == (None, None, None)
    assert entry.parent_task_ids == []


def test_date_range_mapping_reads_both_ends() -> None:
    source = schema(prop("Name", "title", "title"), prop("Session", "s", "date"))
    mapping = parse_mapping(
        {
            "version": 1,
            "fields": {
                "start": {"property_id": "s", "part": "start"},
                "end": {"property_id": "s", "part": "end"},
            },
            "extra": [],
        }
    )
    with_end = page(
        source,
        {"Session": when("2026-10-21T09:00:00.000+05:30", "2026-10-21T10:15:00.000+05:30")},
        created="2026-10-21T00:00:00.000Z",
    )
    entry = read_entry(with_end, mapping, columns_of(source))
    assert entry.start is not None
    assert entry.start.utc == "2026-10-21T03:30:00.000Z"
    assert entry.end is not None
    assert entry.end.utc == "2026-10-21T04:45:00.000Z"
    assert entry.issues == []
    no_end = page(
        source, {"Session": when("2026-10-21T09:00:00.000+05:30")}, created="2026-10-21T00:00Z"
    )
    issues = read_entry(no_end, mapping, columns_of(source)).issues
    assert [(i["field"], i["code"]) for i in issues] == [("end", "missing_time")]
    assert "has no end" in issues[0]["message"]


def test_several_parent_links_are_all_kept_and_not_flagged() -> None:
    row = work_log_rows()[0]
    row["properties"]["Parent Task"]["relation"] = [{"id": "a"}, {"id": "b"}, {"id": "a"}]
    entry = read_entry(row, mapping_for(), columns_of(work_log_schema()))
    assert entry.parent_task_ids == ["a", "b"]
    assert entry.parent_task_id == "a"
    assert entry.issues == []


def test_formula_logged_minutes() -> None:
    source = schema(without(work_log_schema(), "MinuteSpent"), prop("Calc", "f", "formula"))
    mapping = mapping_for(logged_minutes={"property_id": "f"})
    rows = work_log_rows(source)
    rows[0]["properties"]["Calc"]["formula"] = {"type": "number", "number": 2}
    rows[1]["properties"]["Calc"]["formula"] = {"type": "string", "string": "two"}
    assert read_entry(rows[0], mapping, columns_of(source)).logged_minutes == 2
    # A formula that isn't a number has no minutes to compare: no mismatch, no issue.
    entry = read_entry(rows[1], mapping, columns_of(source))
    assert entry.logged_minutes is None
    assert entry.issues == []


def test_number_display_id() -> None:
    source = schema(without(work_log_schema(), "ID"), prop("No.", "n", "number"))
    rows = work_log_rows(source)
    rows[0]["properties"]["No."]["number"] = 12.0
    mapping = mapping_for(display_id={"property_id": "n"})
    assert read_entry(rows[0], mapping, columns_of(source)).display_id == "12"


# --- extra fields -----------------------------------------------------------------------------


def extra_schema() -> Schema:
    return schema(
        work_log_schema(),
        prop("Mood", "mood", "select"),
        prop("Tags", "tags", "multi_select"),
        prop("Done", "done", "checkbox"),
        prop("Calc", "calc", "formula"),
        prop("Total", "total", "rollup"),
        prop("Due", "due", "date"),
        prop("Log it", "btn", "button"),
    )


def test_extra_fields_are_stored_by_id_with_name_and_type() -> None:
    source = extra_schema()
    row = work_log_rows(source)[0]
    values = row["properties"]
    values["Mood"]["select"] = {"name": "Focused"}
    values["Tags"]["multi_select"] = [{"name": "a"}, {"name": "b"}]
    values["Done"]["checkbox"] = True
    values["Calc"]["formula"] = {"type": "number", "number": 3}
    values["Total"]["rollup"] = {"type": "number", "number": 7, "function": "sum"}
    values["Due"]["date"] = when("2026-10-30")
    mapping = mapping_for(extra=["mood", "tags", "done", "calc", "total", "due", "btn"])
    entry = read_entry(row, mapping, columns_of(source))
    assert entry.extra_fields == {
        "mood": {"name": "Mood", "type": "select", "value": "Focused"},
        "tags": {"name": "Tags", "type": "multi_select", "value": ["a", "b"]},
        "done": {"name": "Done", "type": "checkbox", "value": True},
        "calc": {"name": "Calc", "type": "formula", "value": {"type": "number", "value": 3}},
        "total": {"name": "Total", "type": "rollup", "value": 7},
        "due": {
            "name": "Due",
            "type": "date",
            "value": {
                "start": {"utc": None, "date": "2026-10-30", "has_time": False},
                "end": None,
            },
        },
    }
    assert entry.issues == []


def test_unreadable_extra_field_flags_that_field_only() -> None:
    source = extra_schema()
    row = work_log_rows(source)[0]
    row["properties"]["Total"]["rollup"] = {"type": "incomplete", "incomplete": {}}
    del row["properties"]["Mood"]
    entry = read_entry(row, mapping_for(extra=["total", "mood"]), columns_of(source))
    assert entry.extra_fields["total"]["value"] is None
    assert [(i["field"], i["code"]) for i in entry.issues] == [
        ("extra:total", "unreadable_extra"),
        ("extra:mood", "unreadable_extra"),
    ]
    assert "couldn't finish calculating" in entry.issues[0]["message"]
    assert entry.start is not None  # everything else is still read


def test_extra_field_missing_from_the_schema_is_skipped_quietly() -> None:
    # The schema check already warned about it before the sync.
    entry = read_entry(
        work_log_rows()[0], mapping_for(extra=["gone"]), columns_of(work_log_schema())
    )
    assert entry.extra_fields == {}
    assert entry.issues == []


def v(kind: str, inner: Any) -> dict[str, Any]:
    return {"id": "x", "type": kind, kind: inner}


@pytest.mark.parametrize(
    ("kind", "inner", "expected"),
    [
        ("title", rich("Hello"), "Hello"),
        ("rich_text", [], None),
        ("number", 2.5, 2.5),
        ("number", None, None),
        ("select", None, None),
        ("status", {"name": "Done"}, "Done"),
        ("multi_select", [], []),
        ("checkbox", False, False),
        ("url", "https://x.test", "https://x.test"),
        ("email", None, None),
        ("phone_number", "+91", "+91"),
        ("people", [{"id": "u1"}, {"object": "user"}], ["u1"]),
        ("created_by", {"id": "u1"}, "u1"),
        ("last_edited_by", None, None),
        ("files", [{"name": "a.pdf"}, {"name": ""}], ["a.pdf"]),
        ("relation", [{"id": "p1"}], ["p1"]),
        ("unique_id", {"prefix": "WL", "number": 6}, "WL-6"),
        ("unique_id", {"prefix": None, "number": None}, None),
        ("created_time", "2026-10-21T08:00:00.000Z", "2026-10-21T08:00:00.000Z"),
        ("date", None, None),
        ("verification", {"state": "verified"}, "verified"),
        (
            "place",
            {"name": "Office", "lat": 1.5, "lon": 2, "extra": 1},
            {"name": "Office", "address": None, "lat": 1.5, "lon": 2},
        ),
        ("place", None, None),
        ("formula", {"type": "boolean", "boolean": True}, {"type": "boolean", "value": True}),
        ("formula", {"type": "string", "string": "x"}, {"type": "string", "value": "x"}),
        ("formula", {"type": "date", "date": None}, {"type": "date", "value": None}),
        ("rollup", {"type": "date", "date": None}, None),
        (
            "rollup",
            {"type": "array", "array": [v("title", rich("Task A")), v("number", 3)]},
            ["Task A", 3],
        ),
    ],
)
def test_normalise(kind: str, inner: Any, expected: Any) -> None:
    assert normalise(v(kind, inner), kind) == expected


@pytest.mark.parametrize(
    ("value", "kind", "reason"),
    [
        (None, "number", "didn't send a value"),
        (v("rich_text", []), "number", "a rich_text value where a number was expected"),
        (v("date", {"start": "nonsense"}), "date", "isn't in a form"),
        (v("formula", {"type": "mystery"}), "formula", "gave a mystery result"),
        (v("rollup", {"type": "unsupported"}), "rollup", "can't calculate this rollup"),
        (v("rollup", {"type": "array", "array": [5]}), "rollup", "malformed"),
        (v("created_time", "never"), "created_time", "isn't a valid date"),
        (v("hologram", {}), "hologram", "can't read hologram values"),
    ],
)
def test_unreadable_values(value: object, kind: str, reason: str) -> None:
    with pytest.raises(UnreadableValueError, match=reason):
        normalise(value, kind)


def test_relations_to_complete() -> None:
    row = work_log_rows()[0]
    row["properties"]["Parent Task"]["has_more"] = True
    assert relations_to_complete(row, {IDS["Parent Task"]}) == [IDS["Parent Task"]]
    assert relations_to_complete(row, {"other"}) == []


def test_a_page_without_timestamps_cannot_be_stored() -> None:
    row = work_log_rows()[0]
    row["created_time"] = "yesterday"
    with pytest.raises(UnreadableValueError):
        read_entry(row, mapping_for(), columns_of(work_log_schema()))
