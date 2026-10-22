"""The raw log: columns, filters, sorting, paging and the remembered view (PLAN.md 8)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from app.db import Database, open_database
from app.db.settings import Settings
from app.paths import AppPaths
from app.rawlog.service import RawLogService
from app.rawlog.view import RawLogError
from app.stats.service import StatsService
from tests.support.rawlog_data import add, extras, known_set, mapping

NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
INDIA = "Asia/Kolkata"


@pytest.fixture
def db(app_paths: AppPaths) -> Iterator[Database]:
    database = open_database(app_paths.database)
    yield database
    database.close()


@pytest.fixture
def service(db: Database) -> RawLogService:
    known_set(db)
    return RawLogService(db=db.connection, settings=Settings(db.connection), clock=lambda: NOW)


def page(service: RawLogService, **request: Any) -> dict[str, Any]:
    body = {"time_zone": INDIA, "offset": 0, "limit": 100} | request
    return dict(service.page(body))


def ids(service: RawLogService, **request: Any) -> list[str]:
    return [row["page_id"] for row in page(service, **request)["rows"]]


def matching(service: RawLogService, **filters: Any) -> set[str]:
    return set(ids(service, filters=filters))


# --- columns -------------------------------------------------------------------------------


def test_columns_follow_the_mapping_in_table_order(service: RawLogService) -> None:
    columns = page(service)["columns"]
    assert [c["key"] for c in columns] == [
        "display_id",
        "task_name",
        "start",
        "end",
        "duration",
        "logged_minutes",
        "parent_task",
        "extra:mood",
        "extra:tags",
        "extra:bill",
        "extra:notes",
        "extra:score",
        "extra:due",
        "extra:ppl",
        "extra:rel",
        "extra:calc",
        "overlap",
        "issues",
    ]
    by_key = {c["key"]: c for c in columns}
    assert by_key["extra:mood"]["filter"] == "options"
    assert by_key["extra:mood"]["options"] == ["Focused", "Tired"]
    assert by_key["extra:tags"]["options"] == ["admin", "deep", "docs"]
    assert by_key["extra:bill"]["filter"] == "checkbox"
    assert by_key["extra:notes"]["filter"] == "text"
    assert by_key["extra:score"]["filter"] == "number"
    assert by_key["extra:due"]["filter"] == "date"
    assert by_key["extra:ppl"]["filter"] == "presence"
    assert by_key["extra:rel"]["filter"] == "presence"
    assert by_key["extra:calc"]["filter"] == "number"  # by its result type
    assert by_key["extra:due"]["type_label"] == "Date"


def test_unmapped_app_fields_have_no_column(db: Database, service: RawLogService) -> None:
    Settings(db.connection).set("mapping", mapping(display_id=False, logged=False, parent=False))
    keys = [c["key"] for c in page(service)["columns"]]
    assert "display_id" not in keys
    assert "logged_minutes" not in keys
    assert "parent_task" not in keys
    assert keys[:4] == ["task_name", "start", "end", "duration"]


def test_parent_choices_count_every_link(service: RawLogService) -> None:
    parents = page(service)["parents"]
    assert [(p["page_id"], p["entries"]) for p in parents] == [("t1", 2), ("t2", 1)]
    assert parents[0]["url"] == "https://www.notion.so/t1"
    # The newest entry linking t1 is p2 (blank name).
    assert parents[0]["latest_task_name"] is None


# --- rows ----------------------------------------------------------------------------------


def test_rows_carry_durations_overlaps_issues_and_links(service: RawLogService) -> None:
    rows = {row["page_id"]: row for row in page(service)["rows"]}
    p1 = rows["p1"]
    assert p1["duration_minutes"] == 90
    assert p1["overlap_minutes"] == 30
    assert p1["overlaps_with"] == [{"page_id": "p2", "label": "#2 Untitled"}]
    assert p1["url"] == "https://www.notion.so/p1"
    assert p1["parent_urls"] == ["https://www.notion.so/t1"]
    assert p1["extras"]["rel"] == {
        "text": "2 linked pages",
        "links": ["https://www.notion.so/r1", "https://www.notion.so/r2"],
    }
    assert p1["extras"]["bill"] == {"text": "Yes"}
    assert p1["extras"]["due"]["start"]["utc"] == "2026-10-25T04:00:00.000Z"
    assert rows["p2"]["parent_task_ids"] == ["t2", "t1"]
    # Entries left out of the charts have no duration and never overlap.
    assert rows["p4"]["duration_minutes"] is None
    assert rows["p5"]["duration_minutes"] is None
    assert rows["p5"]["overlap_minutes"] == 0
    assert rows["p3"]["issues"][0]["code"] == "duration_mismatch"
    # An unreadable extra field is stored empty.
    assert rows["p6"]["extras"]["notes"] is None


def test_paging(service: RawLogService) -> None:
    first = page(service, limit=2)
    assert first["total_entries"] == 6
    assert first["matched"] == 6
    assert [r["page_id"] for r in first["rows"]] == ["p4", "p3"]
    second = page(service, offset=2, limit=2)
    assert [r["page_id"] for r in second["rows"]] == ["p2", "p1"]
    assert page(service, offset=10)["rows"] == []


# --- sorting -------------------------------------------------------------------------------


def test_default_sort_is_newest_start_first(service: RawLogService) -> None:
    result = page(service)
    assert result["sort"] == {"column": "start", "direction": "desc"}
    assert [r["page_id"] for r in result["rows"]] == ["p4", "p3", "p2", "p1", "p5", "p6"]


@pytest.mark.parametrize(
    ("column", "ascending", "empty"),
    [
        # Empty values come last either way, in the tie order (newest start first).
        ("display_id", ["p1", "p2", "p4", "p3", "p5", "p6"], 1),
        ("task_name", ["p6", "p5", "p4", "p3", "p1", "p2"], 1),
        ("end", ["p6", "p5", "p1", "p2", "p3", "p4"], 1),
        ("duration", ["p6", "p2", "p1", "p3", "p4", "p5"], 2),
        ("logged_minutes", ["p2", "p1", "p3", "p4", "p5", "p6"], 3),
        ("extra:score", ["p2", "p1", "p4", "p3", "p5", "p6"], 4),
        ("extra:due", ["p1", "p3", "p4", "p2", "p5", "p6"], 4),
        ("extra:notes", ["p1", "p3", "p4", "p2", "p5", "p6"], 4),
    ],
)
def test_sorting_puts_empty_values_last_both_ways(
    service: RawLogService, column: str, ascending: list[str], empty: int
) -> None:
    assert ids(service, sort={"column": column, "direction": "asc"}) == ascending
    present, missing = ascending[: len(ascending) - empty], ascending[len(ascending) - empty :]
    descending = ids(service, sort={"column": column, "direction": "desc"})
    assert descending == [*reversed(present), *missing]


def test_display_ids_sort_naturally(db: Database, service: RawLogService) -> None:
    # "1", "2", "3", "10", then "WL-4": numbers in order, not as text ("10" before "2").
    result = ids(service, sort={"column": "display_id", "direction": "asc"})
    assert result[:4] == ["p1", "p2", "p4", "p3"]


def test_ties_keep_the_newest_start_first(service: RawLogService) -> None:
    # Every entry has 0 overlap minutes except p1 and p2.
    result = ids(service, sort={"column": "overlap", "direction": "asc"})
    assert result == ["p4", "p3", "p5", "p6", "p2", "p1"]
    by_issues = ids(service, sort={"column": "issues", "direction": "desc"})
    assert by_issues == ["p4", "p3", "p5", "p6", "p2", "p1"]


def test_an_unknown_sort_column_falls_back_to_the_default(service: RawLogService) -> None:
    result = page(service, sort={"column": "extra:gone", "direction": "asc"})
    assert result["sort"] == {"column": "start", "direction": "desc"}


# --- filters -------------------------------------------------------------------------------


def test_date_range_uses_the_local_start_date(service: RawLogService) -> None:
    # p3 starts 21 Oct 17:30 UTC = 21 Oct 23:00 in India, but 22 Oct in Tokyo.
    assert matching(service, date_from="2026-10-21", date_to="2026-10-21") == {"p3"}
    tokyo = ids(service, time_zone="Asia/Tokyo", filters={"date_from": "2026-10-22"})
    assert set(tokyo) == {"p3", "p4"}
    assert matching(service, date_to="2026-10-19") == {"p5", "p6"}


def test_task_name_search_ignores_case_and_accents_stay_exact(service: RawLogService) -> None:
    assert matching(service, search="WRITE") == {"p1"}
    assert matching(service, search="réunion") == {"p3"}
    assert matching(service, search="  docs ") == {"p1"}
    assert matching(service, search="nothing like it") == set()


def test_parent_filter_matches_any_linked_page(service: RawLogService) -> None:
    assert matching(service, parents=["t1"]) == {"p1", "p2"}
    assert matching(service, parents=["t2"]) == {"p2"}
    assert matching(service, no_parent=True) == {"p3", "p4", "p5", "p6"}


def test_duration_range_leaves_out_entries_without_a_valid_range(
    service: RawLogService,
) -> None:
    assert matching(service, duration_min=60) == {"p1", "p2", "p3"}
    assert matching(service, duration_min=60, duration_max=90) == {"p1", "p2"}
    assert matching(service, duration_max=30) == {"p6"}


def test_issue_filters(service: RawLogService) -> None:
    assert matching(service, issues="any") == {"p3", "p4", "p5", "p6"}
    assert matching(service, issues="none") == {"p1", "p2"}
    assert matching(service, issue_codes=["missing_time"]) == {"p4"}
    assert matching(service, issue_codes=["invalid_range", "unreadable_extra"]) == {"p5", "p6"}
    assert matching(service, issue_codes=["duration_mismatch"]) == {"p3"}


def test_overlap_filter(service: RawLogService) -> None:
    assert matching(service, overlaps=True) == {"p1", "p2"}


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"mood": {"op": "any_of", "values": ["Focused"]}}, {"p1"}),
        ({"tags": {"op": "any_of", "values": ["docs", "admin"]}}, {"p1", "p2"}),
        ({"bill": {"op": "is", "value": True}}, {"p1"}),
        ({"bill": {"op": "is", "value": False}}, {"p2", "p3", "p4", "p5", "p6"}),
        ({"notes": {"op": "contains", "value": "QUOTES"}}, {"p1"}),
        ({"notes": {"op": "contains", "value": "メモ"}}, {"p3"}),
        ({"notes": {"op": "empty"}}, {"p2", "p4", "p5", "p6"}),
        ({"notes": {"op": "not_empty"}}, {"p1", "p3"}),
        ({"score": {"op": "range", "min": 0}}, {"p1"}),
        ({"score": {"op": "range", "max": 0}}, {"p2"}),
        ({"due": {"op": "dates", "from": "2026-10-26"}}, {"p3"}),
        ({"due": {"op": "dates", "to": "2026-10-25"}}, {"p1"}),
        ({"ppl": {"op": "not_empty"}}, {"p1"}),
        ({"rel": {"op": "empty"}}, {"p2", "p3", "p4", "p5", "p6"}),
        ({"calc": {"op": "range", "min": 2}}, {"p2"}),
    ],
)
def test_extra_field_filters(
    service: RawLogService, spec: dict[str, Any], expected: set[str]
) -> None:
    assert matching(service, extra=spec) == expected


def test_filters_combine(service: RawLogService) -> None:
    assert matching(service, parents=["t1"], overlaps=True, search="write") == {"p1"}
    result = page(service, filters={"issues": "any", "date_from": "2026-10-21"})
    assert result["matched"] == 2
    assert result["total_entries"] == 6


@pytest.mark.parametrize(
    "filters",
    [
        "everything",
        {"date_from": "yesterday"},
        {"date_from": "2026-10-22", "date_to": "2026-10-01"},
        {"duration_min": -1},
        {"duration_min": 10, "duration_max": 5},
        {"duration_min": True},
        {"issues": "some"},
        {"issue_codes": ["sleepy"]},
        {"parents": ["t1"], "no_parent": True},
        {"parents": "t1"},
        {"search": 5},
        {"colour": "red"},
        {"extra": {"gone": {"op": "empty"}}},
        {"extra": {"bill": {"op": "contains", "value": "x"}}},
        {"extra": {"ppl": {"op": "any_of", "values": ["u1"]}}},
        {"extra": {"notes": {"op": "contains", "value": "  "}}},
        {"extra": {"score": {"op": "range"}}},
        {"extra": {"score": {"op": "range", "min": 5, "max": 1}}},
        {"extra": {"bill": {"op": "is", "value": "yes"}}},
        {"extra": {"mood": {"op": "any_of", "values": []}}},
        {"extra": {"due": {"op": "dates"}}},
    ],
)
def test_malformed_filters_are_refused(service: RawLogService, filters: object) -> None:
    with pytest.raises(RawLogError):
        service.page({"time_zone": INDIA, "filters": filters})


@pytest.mark.parametrize(
    "request_body",
    [
        "page 1",
        {"time_zone": None},
        {"time_zone": "Mars/Olympus"},
        {"time_zone": INDIA, "offset": -1},
        {"time_zone": INDIA, "limit": 0},
        {"time_zone": INDIA, "limit": 501},
        {"time_zone": INDIA, "sort": {"column": "start", "direction": "up"}},
    ],
)
def test_malformed_requests_are_refused(service: RawLogService, request_body: object) -> None:
    with pytest.raises(RawLogError):
        service.page(request_body)


# --- freshness -----------------------------------------------------------------------------


def test_new_data_shows_on_the_next_request(db: Database, service: RawLogService) -> None:
    assert page(service)["total_entries"] == 6
    add(
        db,
        "p7",
        "2026-10-22T04:00:00.000Z",
        "2026-10-22T04:30:00.000Z",
        task_name="Fresh",
        extra=extras(),
        synced_at="2026-10-22T05:00:00.000Z",
    )
    assert page(service)["total_entries"] == 7
    assert matching(service, search="fresh") == {"p7"}
    with db.connection:
        db.connection.execute("DELETE FROM work_logs")
    assert page(service)["total_entries"] == 0


def test_an_empty_log(db: Database) -> None:
    service = RawLogService(db=db.connection, settings=Settings(db.connection))
    result = page(service)
    assert result["total_entries"] == 0
    assert result["rows"] == []
    assert result["parents"] == []
    # Without a saved mapping every app field still has a column.
    assert [c["key"] for c in result["columns"]][:2] == ["display_id", "task_name"]


# --- overlaps agree with the dashboard -----------------------------------------------------


def test_overlaps_agree_with_the_dashboard_day_detail(db: Database) -> None:
    """The raw log and the day detail use the same function on the same sessions."""
    known_set(db)
    # Add a chain and a fully covered session, across midnight in India.
    add(db, "q1", "2026-10-20T18:00:00.000Z", "2026-10-20T20:00:00.000Z", task_name="Night")
    add(db, "q2", "2026-10-20T19:00:00.000Z", "2026-10-20T19:30:00.000Z", task_name="Inside")
    add(db, "q3", "2026-10-20T19:15:00.000Z", "2026-10-20T21:00:00.000Z", task_name="Chain")
    settings = Settings(db.connection)
    rawlog = RawLogService(db=db.connection, settings=settings)
    stats = StatsService(db=db.connection, settings=settings, clock=lambda: NOW)
    rows = {row["page_id"]: row for row in page(rawlog)["rows"]}
    checked = 0
    for day in ("2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"):
        for session in stats.day_detail(INDIA, day)["sessions"]:
            row = rows[session["page_id"]]
            assert row["overlap_minutes"] == session["overlap_minutes"]
            assert row["overlaps_with"] == session["overlaps_with"]
            assert row["duration_minutes"] == session["minutes"]
            checked += 1
    assert checked >= 6
    assert rows["q2"]["overlap_minutes"] == 30
    assert {o["page_id"] for o in rows["q1"]["overlaps_with"]} == {"q2", "q3"}


# --- the remembered view -------------------------------------------------------------------


def test_view_defaults_and_updates(service: RawLogService) -> None:
    assert service.view() == {
        "sort": {"column": "start", "direction": "desc"},
        "widths": {},
        "hidden": [],
    }
    updated = service.update_view({"sort": {"column": "duration", "direction": "asc"}})
    assert updated["sort"] == {"column": "duration", "direction": "asc"}
    updated = service.update_view({"widths": {"task_name": 320.4, "start": 10, "end": 9999}})
    assert updated["widths"] == {"task_name": 320, "start": 48, "end": 1200}
    updated = service.update_view({"hidden": ["extra:ppl", "overlap", "overlap"]})
    assert updated["hidden"] == ["extra:ppl", "overlap"]
    assert updated["sort"] == {"column": "duration", "direction": "asc"}
    assert page(service)["view"] == updated


def test_a_damaged_view_part_falls_back_alone(db: Database, service: RawLogService) -> None:
    Settings(db.connection).set(
        "raw_log_view",
        {"sort": {"column": "end", "direction": "asc"}, "widths": "wide", "hidden": [3]},
    )
    assert service.view() == {
        "sort": {"column": "end", "direction": "asc"},
        "widths": {},
        "hidden": [],
    }


@pytest.mark.parametrize(
    "changes",
    [
        None,
        {},
        {"colour": "red"},
        {"sort": {"column": "", "direction": "asc"}},
        {"widths": {"start": "wide"}},
        {"widths": [100]},
        {"hidden": "overlap"},
    ],
)
def test_malformed_view_changes_are_refused(service: RawLogService, changes: object) -> None:
    with pytest.raises(RawLogError):
        service.update_view(changes)
