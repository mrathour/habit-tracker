"""The saved mapping: reading it back and checking a user's choice before saving."""

from __future__ import annotations

from typing import Any

import pytest

from app.mapping.model import (
    MappingChoiceError,
    MappingFormatError,
    build_mapping,
    parse_mapping,
    same_choice,
    validate_choice,
)
from app.mapping.properties import Property, schema_properties
from tests.support.notion_schemas import WORK_LOG_IDS, prop, schema, without, work_log_schema

IDS = WORK_LOG_IDS


def props(source: dict[str, Any] | None = None) -> list[Property]:
    return schema_properties({"properties": source or work_log_schema()})


def choice(**changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "start": {"property_id": IDS["Start Time"], "part": "start"},
        "end": {"property_id": IDS["End Time"], "part": "start"},
        "task_name": {"property_id": "title"},
        "parent_task": {"property_id": IDS["Parent Task"]},
        "display_id": {"property_id": IDS["ID"]},
        "logged_minutes": {"property_id": IDS["MinuteSpent"]},
    }
    fields.update(changes)
    return fields


def problems(fields: object, extra: object = None, source: dict[str, Any] | None = None) -> str:
    with pytest.raises(MappingChoiceError) as caught:
        validate_choice(fields, [] if extra is None else extra, props(source))
    return str(caught.value)


def test_valid_choice_round_trips() -> None:
    extended = schema(work_log_schema(), prop("Mood", "mood", "select"))
    chosen, extra = validate_choice(choice(), ["mood", "mood"], props(extended))
    mapping = build_mapping(chosen, extra, props(extended), "2026-10-22T10:00:00.000Z")
    assert mapping["extra"] == ["mood"]
    assert mapping["names_at_save"]["mood"] == "Mood"
    assert mapping["names_at_save"][IDS["End Time"]] == "End Time"
    assert parse_mapping(mapping) == mapping


def test_optional_fields_can_be_unused() -> None:
    chosen, _ = validate_choice(
        choice(logged_minutes=None, display_id=None, task_name=None, parent_task=None), [], props()
    )
    assert chosen["logged_minutes"] is None


def test_range_choice() -> None:
    source = without(work_log_schema(), "End Time")
    chosen, _ = validate_choice(
        choice(end={"property_id": IDS["Start Time"], "part": "end"}), [], props(source)
    )
    assert chosen["end"] == {"property_id": IDS["Start Time"], "part": "end"}


def test_required_fields_are_required() -> None:
    message = problems(choice(start=None, end=None))
    assert "Start time is required" in message
    assert "End time is required" in message


def test_wrong_type_is_explained() -> None:
    message = problems(choice(end={"property_id": IDS["MinuteSpent"], "part": "start"}))
    assert "“MinuteSpent” is a Number column, but End time needs a Date column." in message


def test_unknown_column() -> None:
    assert "no longer exists" in problems(choice(task_name={"property_id": "gone"}))


def test_a_column_feeds_one_field() -> None:
    message = problems(choice(end={"property_id": IDS["Start Time"], "part": "start"}))
    assert "“Start Time” is chosen for both Start time and End time" in message


def test_range_end_must_come_from_the_start_column() -> None:
    message = problems(choice(end={"property_id": IDS["End Time"], "part": "end"}))
    assert "only be used with the column chosen for Start time" in message


@pytest.mark.parametrize(
    "start",
    [
        {"property_id": IDS["Start Time"], "part": "end"},
        {"property_id": IDS["Start Time"], "part": "middle"},
        {"property_id": IDS["Start Time"], "extra": 1},
        "Start Time",
    ],
)
def test_malformed_refs(start: object) -> None:
    problems(choice(start=start))


def test_non_date_fields_have_no_part() -> None:
    assert "unexpected form" in problems(
        choice(task_name={"property_id": "title", "part": "start"})
    )


def test_unknown_field() -> None:
    assert "Unknown app fields: mood." in problems({**choice(), "mood": None})


def test_payload_shapes() -> None:
    problems("fields", [])
    problems(choice(), "extra")


def test_extra_fields_are_checked() -> None:
    extended = schema(work_log_schema(), prop("Go", "btn", "button"))
    message = problems(choice(), ["btn", IDS["MinuteSpent"], "gone", 5], extended)
    assert "“Go” can't be read" in message
    assert "“MinuteSpent” is already mapped" in message
    assert "An additional field no longer exists" in message
    assert "unexpected form" in message


def test_every_problem_is_reported_at_once() -> None:
    with pytest.raises(MappingChoiceError) as caught:
        validate_choice(choice(start=None, task_name={"property_id": "gone"}), ["gone"], props())
    assert len(caught.value.problems) == 3


def test_same_choice_ignores_names_times_and_extra_order() -> None:
    extended = schema(work_log_schema(), prop("A", "a", "select"), prop("B", "b", "checkbox"))
    chosen, _ = validate_choice(choice(), [], props(extended))
    first = build_mapping(chosen, ["a", "b"], props(extended), "2026-10-22T10:00:00.000Z")
    renamed = props(
        schema(
            work_log_schema({"Name": "Task"}), prop("A", "a", "select"), prop("B", "b", "checkbox")
        )
    )
    second = build_mapping(chosen, ["b", "a"], renamed, "2026-10-23T10:00:00.000Z")
    assert same_choice(first, second)
    third = build_mapping({**chosen, "logged_minutes": None}, ["a", "b"], props(extended), "x")
    assert not same_choice(first, third)


def test_parse_drops_duplicate_extras_and_fills_absent_fields() -> None:
    parsed = parse_mapping(
        {"version": 1, "fields": {"start": {"property_id": "s"}}, "extra": ["a", "a"]}
    )
    assert parsed["extra"] == ["a"]
    assert parsed["fields"]["end"] is None
    assert parsed["names_at_save"] == {}


def test_parse_refuses_a_newer_version() -> None:
    with pytest.raises(MappingFormatError, match="newer version"):
        parse_mapping({"version": 2, "fields": {}, "extra": []})
