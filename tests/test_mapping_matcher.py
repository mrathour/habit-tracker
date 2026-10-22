"""Auto-matching columns to app fields (PLAN.md 4.2)."""

from __future__ import annotations

import pytest

from app.mapping.fields import FIELDS
from app.mapping.matcher import (
    ColumnEvidence,
    FieldMatch,
    match_columns,
    name_tier,
    name_tokens,
)
from app.mapping.properties import Property, schema_properties
from tests.support.notion_schemas import (
    WORK_LOG_IDS,
    Schema,
    prop,
    schema,
    without,
    work_log_schema,
)


def props_of(source: Schema) -> list[Property]:
    return schema_properties({"properties": source})


def matched(match: FieldMatch) -> str | None:
    return match.ref["property_id"] if match.status == "matched" and match.ref else None


# --- the author's databases --------------------------------------------------------------------


def test_work_log_maps_every_field_without_help() -> None:
    result = match_columns(props_of(work_log_schema()))
    assert {key: m.status for key, m in result.items()} == dict.fromkeys(
        [f.key for f in FIELDS], "matched"
    )
    assert result["start"].ref == {"property_id": WORK_LOG_IDS["Start Time"], "part": "start"}
    assert result["end"].ref == {"property_id": WORK_LOG_IDS["End Time"], "part": "start"}
    assert result["task_name"].ref == {"property_id": "title"}
    assert result["parent_task"].ref == {"property_id": WORK_LOG_IDS["Parent Task"]}
    assert result["display_id"].ref == {"property_id": WORK_LOG_IDS["ID"]}
    assert result["logged_minutes"].ref == {"property_id": WORK_LOG_IDS["MinuteSpent"]}
    assert not result["end"].from_range


def test_work_log_test_copy_maps_the_same_way() -> None:
    # Work Log (test) has the same columns; Notion gives a copy its own property IDs.
    copy_ids = {
        "Name": "title",
        "Start Time": "a%3Ab",
        "End Time": "c%3Ad",
        "MinuteSpent": "e%3Af",
        "Parent Task": "g%3Ah",
        "ID": "i%3Aj",
    }
    types = work_log_schema()
    source = schema(*(prop(name, copy_ids[name], spec["type"]) for name, spec in types.items()))
    result = match_columns(props_of(source))
    assert matched(result["start"]) == "a%3Ab"
    assert matched(result["end"]) == "c%3Ad"
    assert matched(result["logged_minutes"]) == "e%3Af"
    assert matched(result["parent_task"]) == "g%3Ah"
    assert matched(result["display_id"]) == "i%3Aj"


def test_the_order_notion_lists_columns_in_does_not_matter() -> None:
    reversed_source = dict(reversed(list(work_log_schema().items())))
    assert match_columns(props_of(reversed_source)) == match_columns(props_of(work_log_schema()))


def test_renamed_columns_keep_their_ids() -> None:
    # Renames that still read naturally are matched to the same IDs.
    source = work_log_schema(
        {"Start Time": "Began", "End Time": "Finished", "MinuteSpent": "Duration"}
    )
    result = match_columns(props_of(source))
    assert matched(result["start"]) == WORK_LOG_IDS["Start Time"]
    assert matched(result["end"]) == WORK_LOG_IDS["End Time"]
    assert matched(result["logged_minutes"]) == WORK_LOG_IDS["MinuteSpent"]


def test_renamed_beyond_recognition_asks_instead_of_guessing() -> None:
    source = work_log_schema({"Start Time": "Alpha", "End Time": "Beta"})
    result = match_columns(props_of(source))
    both = (WORK_LOG_IDS["Start Time"], WORK_LOG_IDS["End Time"])
    assert result["start"].status == "choose"
    assert set(result["start"].choose_from) == set(both)
    assert result["end"].status == "choose"
    assert result["start"].ref is None


# --- missing end time -------------------------------------------------------------------------


def test_no_end_time_column() -> None:
    result = match_columns(props_of(without(work_log_schema(), "End Time")))
    assert matched(result["start"]) == WORK_LOG_IDS["Start Time"]
    assert result["end"] == FieldMatch("missing")
    assert matched(result["logged_minutes"]) == WORK_LOG_IDS["MinuteSpent"]


def test_no_date_columns_at_all() -> None:
    result = match_columns(props_of(without(work_log_schema(), "Start Time", "End Time")))
    assert result["start"].status == "missing"
    assert result["end"].status == "missing"
    assert result["task_name"].status == "matched"


# --- date ranges ------------------------------------------------------------------------------


def session_schema() -> Schema:
    return schema(
        prop("Name", "title", "title"),
        prop("Session", "s%3A1", "date"),
        prop("Minutes", "m%3A1", "number"),
    )


def test_single_range_column_gives_start_and_end() -> None:
    evidence = {"s%3A1": ColumnEvidence(has_range=True)}
    result = match_columns(props_of(session_schema()), evidence)
    assert result["start"].ref == {"property_id": "s%3A1", "part": "start"}
    assert result["end"].ref == {"property_id": "s%3A1", "part": "end"}
    assert result["end"].from_range


def test_single_date_column_without_rows_leaves_end_missing() -> None:
    # Nothing shows it holds ranges: the user can still pick its range end by hand.
    result = match_columns(props_of(session_schema()))
    assert matched(result["start"]) == "s%3A1"
    assert result["end"].status == "missing"


def test_range_column_beside_another_unnamed_date_is_a_choice() -> None:
    # Neither name says "start", so two columns fit Start equally: never guessed, even though
    # one holds ranges. End then follows the ordinary rules.
    source = schema(session_schema(), prop("Due date", "d%3A1", "date"))
    evidence = {"s%3A1": ColumnEvidence(has_range=True)}
    result = match_columns(props_of(source), evidence)
    assert result["start"].status == "choose"
    assert result["end"].status == "choose"


def test_range_column_named_like_a_start() -> None:
    source = schema(
        prop("Name", "title", "title"),
        prop("Started", "s%3A1", "date"),
        prop("Due date", "d%3A1", "date"),
    )
    evidence = {"s%3A1": ColumnEvidence(has_range=True)}
    result = match_columns(props_of(source), evidence)
    assert matched(result["start"]) == "s%3A1"
    assert result["end"].ref == {"property_id": "s%3A1", "part": "end"}


def test_an_end_column_beats_range_values() -> None:
    evidence = {WORK_LOG_IDS["Start Time"]: ColumnEvidence(has_range=True)}
    result = match_columns(props_of(work_log_schema()), evidence)
    assert result["end"].ref == {"property_id": WORK_LOG_IDS["End Time"], "part": "start"}
    assert not result["end"].from_range


# --- ambiguity --------------------------------------------------------------------------------


def test_two_unnamed_date_columns_are_a_choice() -> None:
    source = schema(
        prop("Name", "title", "title"), prop("Date", "d1", "date"), prop("Date 2", "d2", "date")
    )
    result = match_columns(props_of(source))
    assert result["start"].status == "choose"
    assert set(result["start"].choose_from) == {"d1", "d2"}
    assert result["end"].status == "choose"


def test_two_start_like_columns_are_a_choice() -> None:
    source = schema(
        prop("Start", "a", "date"), prop("Start (planned)", "b", "date"), prop("End", "c", "date")
    )
    result = match_columns(props_of(source))
    assert result["start"].status == "choose"
    assert set(result["start"].choose_from) == {"a", "b"}
    assert matched(result["end"]) == "c"


def test_three_date_columns_with_clear_names() -> None:
    source = schema(
        prop("Clock in", "a", "date"), prop("Clock out", "b", "date"), prop("Created", "c", "date")
    )
    result = match_columns(props_of(source))
    assert matched(result["start"]) == "a"
    assert matched(result["end"]) == "b"


def test_two_relations_without_a_clear_name_are_a_choice() -> None:
    source = schema(
        work_log_schema(),
        prop("Project", "p%3A1", "relation"),
    )
    result = match_columns(props_of(source))
    # "Parent Task" and "Project" both name a parent task.
    assert result["parent_task"].status == "choose"
    assert set(result["parent_task"].choose_from) == {WORK_LOG_IDS["Parent Task"], "p%3A1"}


def test_a_lone_unrelated_relation_is_still_the_parent_task() -> None:
    source = schema(work_log_schema({"Parent Task": "Links"}))
    assert matched(match_columns(props_of(source))["parent_task"]) == WORK_LOG_IDS["Parent Task"]


def test_an_unnamed_relation_among_two_is_not_used() -> None:
    source = schema(work_log_schema(), prop("Tags", "t%3A1", "relation"))
    result = match_columns(props_of(source))
    assert matched(result["parent_task"]) == WORK_LOG_IDS["Parent Task"]


# --- optional fields need evidence ------------------------------------------------------------


def test_a_number_without_a_name_signal_is_not_used() -> None:
    source = schema(
        prop("Name", "title", "title"),
        prop("Start", "a", "date"),
        prop("End", "b", "date"),
        prop("Score", "n", "number"),
    )
    result = match_columns(props_of(source))
    assert result["logged_minutes"] == FieldMatch("unused")
    assert result["display_id"] == FieldMatch("unused")


def test_title_beats_a_text_column_named_task() -> None:
    source = schema(prop("Untitled", "title", "title"), prop("Task", "r", "rich_text"))
    assert matched(match_columns(props_of(source))["task_name"]) == "title"


def test_a_number_named_like_an_id_is_the_display_id() -> None:
    source = schema(prop("Entry No.", "n", "number"), prop("Minutes", "m", "number"))
    result = match_columns(props_of(source))
    assert matched(result["display_id"]) == "n"
    assert matched(result["logged_minutes"]) == "m"


def test_unique_id_beats_a_number_named_id() -> None:
    source = schema(prop("ID", "u", "unique_id"), prop("Old ID", "n", "number"))
    assert matched(match_columns(props_of(source))["display_id"]) == "u"


def test_each_column_feeds_only_one_field() -> None:
    source = schema(prop("Minutes", "m", "number"))
    result = match_columns(props_of(source))
    used = [matched(m) for m in result.values() if matched(m)]
    assert used == ["m"]


# --- formulas ---------------------------------------------------------------------------------


def test_a_number_formula_can_be_logged_minutes() -> None:
    source = schema(prop("Minutes logged", "f", "formula"))
    evidence = {"f": ColumnEvidence(formula_types=frozenset({"number"}))}
    assert matched(match_columns(props_of(source), evidence)["logged_minutes"]) == "f"


def test_a_formula_with_no_values_yet_can_be_logged_minutes() -> None:
    source = schema(prop("Minutes logged", "f", "formula"))
    assert matched(match_columns(props_of(source))["logged_minutes"]) == "f"


def test_a_text_formula_cannot_be_logged_minutes() -> None:
    source = schema(prop("Minutes logged", "f", "formula"))
    evidence = {"f": ColumnEvidence(formula_types=frozenset({"string"}))}
    assert match_columns(props_of(source), evidence)["logged_minutes"].status == "unused"


def test_a_number_is_preferred_to_a_formula() -> None:
    source = schema(prop("Minutes (calc)", "f", "formula"), prop("Minutes", "n", "number"))
    assert matched(match_columns(props_of(source))["logged_minutes"]) == "n"


# --- unsupported types ------------------------------------------------------------------------


def test_unsupported_and_unknown_types_are_never_matched() -> None:
    source = schema(
        work_log_schema(),
        prop("Start again", "b1", "button"),
        prop("Start (legacy)", "u1", "unsupported"),
        prop("Start hologram", "x1", "hologram"),
        prop("Where", "p1", "place"),
        prop("Verified", "v1", "verification"),
    )
    result = match_columns(props_of(source))
    assert matched(result["start"]) == WORK_LOG_IDS["Start Time"]
    assert matched(result["end"]) == WORK_LOG_IDS["End Time"]


# --- names ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("MinuteSpent", ["minute", "spent"]),
        ("Start Time", ["start", "time"]),
        ("№ ID", ["id"]),
        ("⏱️ Duration (min)", ["duration", "min"]),
        ("end_time2", ["end", "time", "2"]),
        ("StartTime", ["start", "time"]),
    ],
)
def test_name_tokens(name: str, tokens: list[str]) -> None:
    assert name_tokens(name) == tokens


@pytest.mark.parametrize(
    ("field", "name", "tier"),
    [
        ("start", "Start Time", 3),
        ("start", "Clock in", 3),
        ("start", "starttime", 2),
        ("start", "Strat", 1),
        ("start", "Created", 0),
        ("end", "Finished at", 3),
        ("end", "endtime", 2),
        ("end", "Spend", 0),
        ("end", "Clock out", 3),
        ("logged_minutes", "MinuteSpent", 3),
        ("logged_minutes", "Minuts", 2),
        ("logged_minutes", "Durration", 1),
        ("display_id", "№ ID", 3),
        ("parent_task", "Parent Task", 3),
    ],
)
def test_name_tiers(field: str, name: str, tier: int) -> None:
    assert name_tier(field, name) == tier  # type: ignore[arg-type]
