"""Extra field values in the raw log: text, filters, sorting and CSV (PLAN.md 8)."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.rawlog.extras import filter_kind, number_text, read_extra

INDIA = ZoneInfo("Asia/Kolkata")
DUE = {
    "start": {"utc": "2026-10-21T19:00:00.000Z", "date": "2026-10-21", "has_time": True},
    "end": {"utc": "2026-10-21T20:30:00.000Z", "date": "2026-10-21", "has_time": True},
}


@pytest.mark.parametrize(
    ("kind", "value", "text", "csv"),
    [
        ("title", " Plan ", "Plan", "Plan"),
        ("rich_text", "Line one\nline two", "Line one\nline two", "Line one\nline two"),
        ("url", "https://example.com", "https://example.com", "https://example.com"),
        ("email", "me@example.com", "me@example.com", "me@example.com"),
        ("phone_number", "+91 98", "+91 98", "+91 98"),
        ("unique_id", "WL-6", "WL-6", "WL-6"),
        ("select", "Deep", "Deep", "Deep"),
        ("status", "Done", "Done", "Done"),
        ("verification", "verified", "verified", "verified"),
        ("multi_select", ["a", "b"], "a, b", "a, b"),
        ("number", 2.5, "2.5", "2.5"),
        ("number", 3.0, "3", "3"),
        ("checkbox", True, "Yes", "Yes"),
        ("checkbox", False, "No", "No"),
        ("files", ["a.pdf", "b.png"], "a.pdf, b.png", "a.pdf\nb.png"),
        ("people", ["u1", "u2"], "2 people", "2 people"),
        ("created_by", "u1", "1 person", "1 person"),
        ("relation", ["r1"], "1 linked page", "https://www.notion.so/r1"),
        ("place", {"name": "Office", "address": None, "lat": 1, "lon": 2}, "Office", "Office"),
        ("place", {"name": None, "address": None, "lat": 1.5, "lon": 2}, "1.5, 2", "1.5, 2"),
        # 19:00 UTC is 00:30 the next day in India; the range ends at 02:00.
        ("date", DUE, "2026-10-22 00:30 → 2026-10-22 02:00", "2026-10-22 00:30 → 2026-10-22 02:00"),
        (
            "date",
            {"start": {"utc": None, "date": "2026-10-30", "has_time": False}, "end": None},
            "2026-10-30",
            "2026-10-30",
        ),
        ("created_time", "2026-10-21T03:30:00.000Z", "2026-10-21 09:00", "2026-10-21 09:00"),
        ("formula", {"type": "string", "value": "ok"}, "ok", "ok"),
        ("formula", {"type": "boolean", "value": False}, "No", "No"),
        ("formula", {"type": "number", "value": 0.1 + 0.2}, "0.3", "0.3"),
        ("rollup", 7, "7", "7"),
        ("rollup", ["x", 2, True, ["y"]], "x, 2, Yes, y", "x, 2, Yes, y"),
    ],
)
def test_values_read_as_text_and_csv(kind: str, value: Any, text: str, csv: str) -> None:
    extra = read_extra(kind, value, INDIA)
    assert not extra.empty
    assert extra.text == text
    assert extra.csv == csv


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("title", None),
        ("rich_text", "   "),
        ("multi_select", []),
        ("people", []),
        ("relation", []),
        ("files", []),
        ("number", None),
        ("number", True),
        ("date", None),
        ("date", {"start": "nonsense"}),
        ("formula", {"type": "number", "value": None}),
        ("formula", "broken"),
        ("rollup", []),
        ("select", 5),
    ],
)
def test_empty_values(kind: str, value: Any) -> None:
    assert read_extra(kind, value, INDIA).empty


def test_checkbox_is_never_empty() -> None:
    assert not read_extra("checkbox", False, INDIA).empty
    assert read_extra("checkbox", False, INDIA).flag is False


def test_dates_filter_on_their_local_start_day() -> None:
    assert str(read_extra("date", DUE, INDIA).day) == "2026-10-22"
    assert str(read_extra("date", DUE, ZoneInfo("UTC")).day) == "2026-10-21"


def test_relation_cells_carry_links() -> None:
    cell = read_extra("relation", ["r1", "r2"], INDIA).cell
    assert cell == {
        "text": "2 linked pages",
        "links": ["https://www.notion.so/r1", "https://www.notion.so/r2"],
    }


def test_numbers_and_dates_are_formula_safe_text_is_not() -> None:
    assert read_extra("number", -5, INDIA).formula_safe
    assert read_extra("date", DUE, INDIA).formula_safe
    assert not read_extra("rich_text", "-5", INDIA).formula_safe


def test_sort_keys_never_compare_different_shapes() -> None:
    values = [
        read_extra("formula", {"type": "number", "value": 2}, INDIA),
        read_extra("formula", {"type": "string", "value": "b"}, INDIA),
        read_extra("formula", {"type": "date", "value": DUE}, INDIA),
        read_extra("formula", {"type": "boolean", "value": True}, INDIA),
    ]
    ordered = sorted(values, key=lambda v: v.sort)  # type: ignore[arg-type,return-value]
    assert [v.text for v in ordered] == ["2", "2026-10-22 00:30 → 2026-10-22 02:00", "Yes", "b"]


@pytest.mark.parametrize(
    ("kind", "values", "expected"),
    [
        ("title", [], "text"),
        ("files", [], "text"),
        ("number", [], "number"),
        ("checkbox", [], "checkbox"),
        ("multi_select", [], "options"),
        ("verification", [], "options"),
        ("last_edited_time", [], "date"),
        ("people", [], "presence"),
        ("relation", [], "presence"),
        ("formula", [{"type": "boolean", "value": True}], "checkbox"),
        ("formula", [{"type": "date", "value": DUE}, {"type": "date", "value": None}], "date"),
        ("formula", [], "text"),
        ("rollup", [3, 4, None], "number"),
        ("rollup", [DUE], "date"),
        ("rollup", [["a"]], "text"),
        ("unknown_new_type", [], "text"),
    ],
)
def test_filter_kinds(kind: str, values: list[Any], expected: str) -> None:
    assert filter_kind(kind, values) == expected


def test_number_text() -> None:
    assert number_text(12) == "12"
    assert number_text(2.50) == "2.5"
    assert number_text(-0.125) == "-0.125"
    assert number_text(1 / 3) == "0.333333"
