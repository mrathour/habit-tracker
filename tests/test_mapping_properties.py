"""Property types, readability and sample values."""

from __future__ import annotations

from typing import Any

import pytest

from app.mapping.properties import (
    READABLE_TYPES,
    TYPE_LABELS,
    SchemaFormatError,
    column_note,
    formula_result_type,
    has_date_without_time,
    is_range,
    is_readable,
    sample_of,
    schema_properties,
    unusable_reason,
)
from tests.support.notion_schemas import rich, when, work_log_schema

#: Every property type in Notion API 2026-03-11.
API_TYPES = [
    "button",
    "checkbox",
    "created_by",
    "created_time",
    "date",
    "email",
    "files",
    "formula",
    "last_edited_by",
    "last_edited_time",
    "multi_select",
    "number",
    "people",
    "phone_number",
    "place",
    "relation",
    "rich_text",
    "rollup",
    "select",
    "status",
    "title",
    "unique_id",
    "url",
    "verification",
]


def value(kind: str, inner: Any, **more: Any) -> dict[str, Any]:
    return {"id": "x", "type": kind, kind: inner, **more}


def text_of(raw: dict[str, Any]) -> str | None:
    sample = sample_of(raw)
    if sample is None:
        return None
    assert sample["kind"] == "text"
    return sample["text"]


def test_every_api_type_has_a_label_and_a_verdict() -> None:
    for kind in API_TYPES:
        assert kind in TYPE_LABELS, f"{kind} has no label"
        assert is_readable(kind) == (kind != "button")
        assert (unusable_reason(kind) is None) == is_readable(kind)
    assert set(API_TYPES) - {"button"} == set(READABLE_TYPES)


def test_unusable_reasons_explain() -> None:
    assert "hold no value" in (unusable_reason("button") or "")
    assert "through its API" in (unusable_reason("unsupported") or "")
    assert unusable_reason("hologram") == (
        "Habit Tracker doesn't know how to read Hologram properties yet."
    )


def test_notes_for_types_kept_differently() -> None:
    assert "count" in (column_note("people") or "")
    assert "titles aren't read" in (column_note("relation") or "")
    assert column_note("number") is None


def test_schema_properties_reads_every_column() -> None:
    props = schema_properties({"properties": work_log_schema()})
    assert [(p.name, p.type) for p in props] == [
        ("ID", "unique_id"),
        ("Name", "title"),
        ("Start Time", "date"),
        ("End Time", "date"),
        ("MinuteSpent", "number"),
        ("Parent Task", "relation"),
    ]
    assert props[0].config == {"prefix": None}


def test_schema_properties_skips_malformed_columns() -> None:
    props = schema_properties(
        {
            "properties": {
                "Good": {"id": "g", "type": "number", "number": {}},
                "No id": {"type": "number"},
                "Not a dict": 5,
                "No type": {"id": "t"},
            }
        }
    )
    assert [p.id for p in props] == ["g"]


def test_schema_without_properties_is_an_error() -> None:
    with pytest.raises(SchemaFormatError):
        schema_properties({"object": "data_source"})


# --- samples ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (value("title", rich("Writing EVA resume")), "Writing EVA resume"),
        (value("title", []), None),
        (value("rich_text", rich("  spaced   out  ")), "spaced out"),
        (value("number", 128), "128"),
        (value("number", 2.0), "2"),
        (value("number", 1.5), "1.5"),
        (value("number", None), None),
        (value("select", {"name": "Deep work"}), "Deep work"),
        (value("select", None), None),
        (value("status", {"name": "Done"}), "Done"),
        (value("multi_select", [{"name": "a"}, {"name": "b"}]), "a, b"),
        (value("multi_select", []), None),
        (value("checkbox", True), "Yes"),
        (value("checkbox", False), "No"),
        (value("url", "https://example.test"), "https://example.test"),
        (value("email", ""), None),
        (value("phone_number", "+91 1"), "+91 1"),
        (value("people", [{"id": "u1"}, {"id": "u2"}]), "2 people"),
        (value("people", [{"id": "u1"}]), "1 person"),
        (value("created_by", {"object": "user", "id": "u1"}), "1 person"),
        (value("files", [{"name": "notes.pdf"}]), "notes.pdf"),
        (value("relation", [{"id": "p1"}], has_more=False), "1 linked page"),
        (
            value("relation", [{"id": f"p{i}"} for i in range(25)], has_more=True),
            "25+ linked pages",
        ),
        (value("relation", [], has_more=False), None),
        (value("unique_id", {"prefix": None, "number": 6}), "6"),
        (value("unique_id", {"prefix": "WL", "number": 6}), "WL-6"),
        (value("unique_id", {"prefix": None, "number": None}), None),
        (value("verification", {"state": "verified"}), "Verified"),
        (value("place", {"name": "Office", "lat": 1, "lon": 2}), "Office"),
        (value("place", {"lat": 28.6139, "lon": 77.209}), "28.6139, 77.2090"),
        (value("formula", {"type": "number", "number": 37}), "37"),
        (value("formula", {"type": "string", "string": "late"}), "late"),
        (value("formula", {"type": "boolean", "boolean": False}), "No"),
        (value("formula", {"type": "number", "number": None}), None),
        (value("rollup", {"type": "number", "number": 3}), "3"),
        (
            value("rollup", {"type": "array", "array": [value("title", rich("Task A"))]}),
            "Task A",
        ),
        (value("rollup", {"type": "array", "array": [value("people", [])]}), "1 item"),
        (value("rollup", {"type": "array", "array": []}), None),
        (value("button", {}), None),
        (value("unsupported", {}), None),
    ],
)
def test_text_samples(raw: dict[str, Any], expected: str | None) -> None:
    assert text_of(raw) == expected


def test_long_text_is_shortened() -> None:
    text = text_of(value("rich_text", rich("x" * 200)))
    assert text is not None
    assert len(text) == 80
    assert text.endswith("…")


def test_date_sample() -> None:
    sample = sample_of(value("date", when("2026-10-17T17:41:00.000+05:30")))
    assert sample == {
        "kind": "date",
        "start": {"utc": "2026-10-17T12:11:00.000Z", "date": "2026-10-17", "has_time": True},
        "end": None,
    }


def test_range_sample() -> None:
    raw = value("date", when("2026-10-17T17:41:00.000+05:30", "2026-10-17T18:00:00.000+05:30"))
    sample = sample_of(raw)
    assert sample is not None
    assert sample["kind"] == "date"
    assert sample["end"] is not None
    assert sample["end"]["utc"] == "2026-10-17T12:30:00.000Z"
    assert is_range(raw)


def test_date_only_sample() -> None:
    raw = value("date", when("2026-10-17"))
    sample = sample_of(raw)
    assert sample is not None
    assert sample["kind"] == "date"
    assert sample["start"] == {"utc": None, "date": "2026-10-17", "has_time": False}
    assert has_date_without_time(raw)
    assert not is_range(raw)


def test_created_time_and_formula_dates_are_dates() -> None:
    created = sample_of(value("created_time", "2026-10-17T12:11:00.000Z"))
    assert created is not None
    assert created["kind"] == "date"
    formula = sample_of(value("formula", {"type": "date", "date": when("2026-10-17")}))
    assert formula is not None
    assert formula["kind"] == "date"
    rollup = sample_of(value("rollup", {"type": "date", "date": when("2026-10-17")}))
    assert rollup is not None
    assert rollup["kind"] == "date"


def test_empty_date() -> None:
    assert sample_of(value("date", None)) is None
    assert not is_range(value("date", None))
    assert not has_date_without_time(value("number", 3))


@pytest.mark.parametrize("raw", [None, "text", {"type": 5}, {"id": "x"}])
def test_malformed_values(raw: object) -> None:
    assert sample_of(raw) is None


def test_formula_result_type() -> None:
    assert formula_result_type(value("formula", {"type": "number", "number": 3})) == "number"
    assert formula_result_type(value("formula", {"type": "string", "string": "x"})) == "string"
    assert formula_result_type(value("formula", {"type": "number", "number": None})) is None
    assert formula_result_type(value("number", 3)) is None
