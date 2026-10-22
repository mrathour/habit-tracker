"""The schema check before every sync (PLAN.md 6.3)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.mapping.model import MAPPING_VERSION
from app.sync.schema_check import SchemaCheck, check_schema
from tests.support.notion_schemas import (
    WORK_LOG_IDS,
    Schema,
    prop,
    schema,
    without,
    work_log_schema,
)

IDS = WORK_LOG_IDS


def work_log_mapping(**changes: Any) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "version": MAPPING_VERSION,
        "fields": {
            "start": {"property_id": IDS["Start Time"], "part": "start"},
            "end": {"property_id": IDS["End Time"], "part": "start"},
            "task_name": {"property_id": "title"},
            "parent_task": {"property_id": IDS["Parent Task"]},
            "display_id": {"property_id": IDS["ID"]},
            "logged_minutes": {"property_id": IDS["MinuteSpent"]},
        },
        "extra": [],
        "names_at_save": {
            IDS["Start Time"]: "Start Time",
            IDS["End Time"]: "End Time",
            "title": "Name",
            IDS["Parent Task"]: "Parent Task",
            IDS["ID"]: "ID",
            IDS["MinuteSpent"]: "MinuteSpent",
        },
        "saved_at": "2026-10-22T10:00:00.000Z",
    }
    mapping.update(changes)
    return mapping


def source(properties: Schema) -> dict[str, Any]:
    return {"object": "data_source", "id": "ds", "properties": properties}


def retype(properties: Schema, name: str, kind: str) -> Schema:
    changed = copy.deepcopy(properties)
    spec = changed[name]
    old = spec["type"]
    spec.pop(old)
    spec["type"] = kind
    spec[kind] = {}
    return changed


def codes(check: SchemaCheck) -> tuple[list[str], list[str]]:
    return [i.code for i in check.blocking], [i.code for i in check.warnings]


# --- all good ---------------------------------------------------------------------------------


def test_unchanged_work_log_passes() -> None:
    check = check_schema(work_log_mapping(), source(work_log_schema()))
    assert check.ok
    assert codes(check) == ([], [])
    assert check.renamed == []


def test_renamed_columns_are_not_problems() -> None:
    renamed = work_log_schema({"End Time": "Finish", "MinuteSpent": "Minutes"})
    check = check_schema(work_log_mapping(), source(renamed))
    assert check.ok
    assert codes(check) == ([], [])
    assert set(check.renamed) == {
        (IDS["End Time"], "End Time", "Finish"),
        (IDS["MinuteSpent"], "MinuteSpent", "Minutes"),
    }


def test_new_columns_are_not_problems() -> None:
    extended = schema(work_log_schema(), prop("Mood", "mood", "select"))
    assert check_schema(work_log_mapping(), source(extended)).ok


def test_unused_optional_fields_are_fine() -> None:
    mapping = work_log_mapping()
    mapping["fields"]["logged_minutes"] = None
    mapping["fields"]["display_id"] = None
    check = check_schema(mapping, source(without(work_log_schema(), "MinuteSpent", "ID")))
    assert check.ok
    assert codes(check) == ([], [])


# --- blocking ---------------------------------------------------------------------------------


def test_no_mapping_blocks() -> None:
    check = check_schema(None, source(work_log_schema()))
    assert codes(check) == (["mapping_missing"], [])
    assert "haven't been mapped" in check.blocking[0].message


@pytest.mark.parametrize(
    "mapping",
    [
        "nonsense",
        {"version": 1},
        {"version": 1, "fields": {"start": {"property_id": 5}}, "extra": []},
        {"version": 1, "fields": {}, "extra": "x"},
        {"version": 0, "fields": {}, "extra": []},
        {"version": True, "fields": {}, "extra": []},
    ],
)
def test_damaged_mapping_blocks(mapping: object) -> None:
    check = check_schema(mapping, source(work_log_schema()))
    assert codes(check) == (["mapping_invalid"], [])
    assert "damaged" in check.blocking[0].message


def test_mapping_from_a_newer_app_blocks() -> None:
    check = check_schema(work_log_mapping(version=2), source(work_log_schema()))
    assert codes(check) == (["mapping_invalid"], [])
    assert "newer version" in check.blocking[0].message


def test_unreadable_schema_blocks() -> None:
    check = check_schema(work_log_mapping(), {"object": "data_source"})
    assert codes(check) == (["schema_unreadable"], [])


def test_required_column_deleted_blocks() -> None:
    check = check_schema(work_log_mapping(), source(without(work_log_schema(), "End Time")))
    assert codes(check) == (["required_missing"], [])
    issue = check.blocking[0]
    assert issue.field == "end"
    assert issue.property_id == IDS["End Time"]
    assert issue.message == (
        "The column “End Time” used for End time no longer exists in Notion, so syncing can't "
        "start. Choose another column for End time on the mapping screen."
    )


def test_required_column_deleted_without_a_saved_name() -> None:
    mapping = work_log_mapping(names_at_save={})
    check = check_schema(mapping, source(without(work_log_schema(), "Start Time")))
    assert check.blocking[0].message.startswith("The column used for Start time no longer")


def test_required_column_changed_type_blocks() -> None:
    changed = retype(work_log_schema(), "Start Time", "rich_text")
    check = check_schema(work_log_mapping(), source(changed))
    assert codes(check) == (["required_type_changed"], [])
    assert check.blocking[0].message == (
        "The column “Start Time” used for Start time is now a Text column in Notion, but Start "
        "time needs a Date column, so syncing can't start. Change it back to Date in Notion, or "
        "choose another column on the mapping screen."
    )


def test_both_required_columns_gone() -> None:
    check = check_schema(
        work_log_mapping(), source(without(work_log_schema(), "Start Time", "End Time"))
    )
    assert codes(check) == (["required_missing", "required_missing"], [])
    assert [i.field for i in check.blocking] == ["start", "end"]


def test_required_field_left_empty_blocks() -> None:
    mapping = work_log_mapping()
    mapping["fields"]["end"] = None
    check = check_schema(mapping, source(work_log_schema()))
    assert codes(check) == (["mapping_invalid"], [])
    assert "End time" in check.blocking[0].message


def test_blocking_and_warnings_together() -> None:
    broken = without(work_log_schema(), "End Time", "MinuteSpent")
    check = check_schema(work_log_mapping(), source(broken))
    assert not check.ok
    assert codes(check) == (["required_missing"], ["optional_missing"])


# --- warnings ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "field"),
    [
        ("MinuteSpent", "logged_minutes"),
        ("Parent Task", "parent_task"),
        ("ID", "display_id"),
        ("Name", "task_name"),
    ],
)
def test_optional_column_deleted_warns(column: str, field: str) -> None:
    # (Notion never deletes the title, but the check doesn't rely on that.)
    check = check_schema(work_log_mapping(), source(without(work_log_schema(), column)))
    assert check.ok
    assert codes(check) == ([], ["optional_missing"])
    assert check.warnings[0].field == field
    assert "Syncing continues without" in check.warnings[0].message


def test_optional_column_changed_type_warns() -> None:
    changed = retype(work_log_schema(), "MinuteSpent", "rich_text")
    check = check_schema(work_log_mapping(), source(changed))
    assert check.ok
    assert codes(check) == ([], ["optional_type_changed"])
    assert check.warnings[0].message == (
        "The column “MinuteSpent” used for Logged minutes is now a Text column, which Logged "
        "minutes can't use. Syncing continues without Logged minutes; change it back to Number "
        "or Formula in Notion or choose another column on the mapping screen."
    )


def test_formula_logged_minutes_passes_the_schema_check() -> None:
    # A formula's result type isn't in the schema; validation copes with non-numbers later.
    changed = retype(work_log_schema(), "MinuteSpent", "formula")
    assert codes(check_schema(work_log_mapping(), source(changed))) == ([], [])


def test_extra_field_deleted_warns() -> None:
    mapping = work_log_mapping(extra=["mood"], names_at_save={"mood": "Mood"})
    check = check_schema(mapping, source(work_log_schema()))
    assert check.ok
    assert codes(check) == ([], ["extra_missing"])
    assert check.warnings[0].message == (
        "The additional column “Mood” no longer exists in Notion. Syncing continues without it."
    )
    assert check.warnings[0].property_id == "mood"


def test_extra_field_now_unreadable_warns() -> None:
    mapping = work_log_mapping(extra=["mood"])
    extended = schema(work_log_schema(), prop("Mood", "mood", "button"))
    check = check_schema(mapping, source(extended))
    assert codes(check) == ([], ["extra_unreadable"])
    assert "now a Button column" in check.warnings[0].message


def test_extra_field_changed_to_another_readable_type_is_fine() -> None:
    mapping = work_log_mapping(extra=["mood"])
    extended = schema(work_log_schema(), prop("Mood", "mood", "multi_select"))
    assert codes(check_schema(mapping, source(extended))) == ([], [])


# --- date ranges ------------------------------------------------------------------------------


def range_mapping() -> dict[str, Any]:
    mapping = work_log_mapping()
    mapping["fields"]["end"] = {"property_id": IDS["Start Time"], "part": "end"}
    return mapping


def range_schema() -> Schema:
    return without(work_log_schema({"Start Time": "Session"}), "End Time")


def test_range_mapping_passes() -> None:
    assert codes(check_schema(range_mapping(), source(range_schema()))) == ([], [])


def test_range_column_deleted_is_one_clear_problem() -> None:
    check = check_schema(range_mapping(), source(without(range_schema(), "Session")))
    assert codes(check) == (["required_missing"], [])
    assert "used for Start time and End time (as a date range)" in check.blocking[0].message


def test_range_column_changed_type_is_one_clear_problem() -> None:
    check = check_schema(range_mapping(), source(retype(range_schema(), "Session", "number")))
    assert codes(check) == (["required_type_changed"], [])
    assert "now a Number column" in check.blocking[0].message


def test_to_dict() -> None:
    check = check_schema(work_log_mapping(), source(without(work_log_schema(), "MinuteSpent")))
    assert check.to_dict() == {
        "ok": True,
        "blocking": [],
        "warnings": [
            {
                "code": "optional_missing",
                "field": "logged_minutes",
                "property_id": IDS["MinuteSpent"],
                "message": check.warnings[0].message,
            }
        ],
        "renamed": [],
    }
