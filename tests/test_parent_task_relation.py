"""Parent Task as a relation to the Task Tracker (issue #12).

Notion leaves a relation out of a data source's schema while the database it links to isn't
shared with the connection. These tests use the author's real Work Log schema (sanitised) and a
Task Tracker that is shared or not: the mapping explains how to share it, a relation that
appears later is offered, and once mapped the links sync and reach the raw log and the day
detail.
"""

# ruff: noqa: F811 - the tests take the imported "harness" fixture as a parameter

from __future__ import annotations

import json

import pytest

from app.mapping.model import MappingFormatError, parse_mapping
from app.mapping.review import FieldReview, MappingReview
from app.rawlog.service import RawLogService
from app.stats.service import StatsService
from tests.support.notion_schemas import (
    REAL_WORK_LOG_IDS,
    SECOND_TASK,
    TASK_PAGE,
    add_source,
    add_task_tracker,
    real_work_log_rows,
    real_work_log_schema,
)
from tests.test_sync_engine import (
    Harness,
    harness,  # noqa: F401 - the shared sync harness fixture
)

IDS = REAL_WORK_LOG_IDS
ZONE = "Asia/Kolkata"


def connect(h: Harness, *, shared: bool) -> MappingReview:
    tracker = add_task_tracker(h.notion, shared=shared)
    database, source_id = add_source(
        h.notion, "Work Log", real_work_log_schema(), real_work_log_rows()
    )
    h.connection.choose_data_source(database.id, source_id, True)
    h.source_id = source_id
    h.tracker_id = tracker.id  # type: ignore[attr-defined]
    return h.mapping.review()


def field(review: MappingReview, key: str) -> FieldReview:
    return next(f for f in review["fields"] if f["key"] == key)


def save(h: Harness, review: MappingReview) -> None:
    h.mapping.save({f["key"]: f["selection"] for f in review["fields"]}, [])


def share_tracker(h: Harness) -> None:
    h.notion.unshared.discard(h.tracker_id)  # type: ignore[attr-defined]


def entries(h: Harness) -> dict[str, list[str]]:
    return {page_id: json.loads(row["parent_task_ids"]) for page_id, row in h.rows().items()}


# --- shared: maps automatically, syncs, and opens -----------------------------------------------


def test_a_shared_task_tracker_maps_parent_task_automatically(harness: Harness) -> None:
    review = connect(harness, shared=True)
    parent = field(review, "parent_task")
    assert parent["status"] == "auto"
    assert parent["selection"] == {"property_id": IDS["Parent Task"]}
    assert parent["share_help"] is None
    assert review["hidden_columns"] == []
    columns = {c["name"]: c for c in review["columns"]}
    assert (
        columns["Parent Task"]["note"]
        == "Linked pages are kept as links; their titles aren't read."
    )
    assert columns["Fix Start Time"]["readable"] is False  # the button is listed, never used
    assert {f["key"]: f["status"] for f in review["fields"]} == dict.fromkeys(
        ["start", "end", "task_name", "parent_task", "display_id", "logged_minutes"], "auto"
    )


def test_parent_task_links_sync_and_reach_the_raw_log_and_day_detail(harness: Harness) -> None:
    save(harness, connect(harness, shared=True))
    assert harness.run()["ok"]
    assert sorted(entries(harness).values()) == [[TASK_PAGE], [TASK_PAGE, SECOND_TASK]]

    task_url = f"https://www.notion.so/{TASK_PAGE.replace('-', '')}"
    second_url = f"https://www.notion.so/{SECOND_TASK.replace('-', '')}"
    db, settings = harness.database.connection, harness.settings
    raw = RawLogService(db=db, settings=settings).page({"time_zone": ZONE})
    assert sorted(row["parent_urls"] for row in raw["rows"]) == [
        [task_url],
        [task_url, second_url],
    ]
    detail = StatsService(db=db, settings=settings).day_detail(ZONE, "2026-10-23")
    assert [s["parent_task_ids"] for s in detail["sessions"]] == [
        [TASK_PAGE],
        [TASK_PAGE, SECOND_TASK],
    ]
    assert [s["parent_urls"] for s in detail["sessions"]] == [[task_url], [task_url, second_url]]
    assert harness.sync.status()["mapping_suggestions"] == []


def test_day_detail_has_no_parent_links_when_the_field_is_not_used(harness: Harness) -> None:
    review = connect(harness, shared=True)
    harness.mapping.save(
        {f["key"]: f["selection"] for f in review["fields"]} | {"parent_task": None}, []
    )
    harness.run()
    db, settings = harness.database.connection, harness.settings
    detail = StatsService(db=db, settings=settings).day_detail(ZONE, "2026-10-23")
    assert [s["parent_urls"] for s in detail["sessions"]] == [[], []]


# --- not shared: explain, then offer the column once it appears --------------------------------


def test_an_unshared_task_tracker_hides_the_column_and_names_it(harness: Harness) -> None:
    review = connect(harness, shared=False)
    assert "Parent Task" not in {c["name"] for c in review["columns"]}
    parent = field(review, "parent_task")
    assert parent["status"] == "unused"
    assert parent["options"] == []
    assert review["hidden_columns"] == [
        {"name": "Parent Task", "type": "relation", "type_label": "Relation"}
    ]
    assert parent["share_help"] is not None
    assert parent["share_help"].startswith("Notion is hiding the relation column “Parent Task”")
    assert "••• → Connections" in parent["share_help"]
    assert "Check again" in parent["share_help"]
    # Everything else still maps, so setup can finish without the parent task.
    assert field(review, "start")["status"] == "auto"


def test_without_the_hidden_values_the_help_is_general(harness: Harness) -> None:
    harness.notion.unshared_relation_values = "omitted"
    review = connect(harness, shared=False)
    assert review["hidden_columns"] == []
    help_text = field(review, "parent_task")["share_help"]
    assert help_text is not None
    assert help_text.startswith("Habit Tracker can't see a relation column in this database.")


def test_check_again_after_sharing_maps_it(harness: Harness) -> None:
    assert field(connect(harness, shared=False), "parent_task")["options"] == []
    share_tracker(harness)
    again = harness.mapping.review()  # what "Check again" calls
    assert field(again, "parent_task")["status"] == "auto"
    assert field(again, "parent_task")["share_help"] is None


def test_a_relation_shared_after_saving_is_offered_then_synced(harness: Harness) -> None:
    save(harness, connect(harness, shared=False))
    assert harness.run()["ok"]
    assert harness.sync.status()["mapping_suggestions"] == []
    assert set(map(tuple, entries(harness).values())) == {()}

    share_tracker(harness)
    assert harness.run()["ok"]
    [suggestion] = harness.sync.status()["mapping_suggestions"]
    assert suggestion == {
        "field": "parent_task",
        "field_label": "Parent task link",
        "property_id": IDS["Parent Task"],
        "column_name": "Parent Task",
        "message": (
            "Notion now shows the Relation column “Parent Task”, which fits Parent task link. "
            "Review the column mapping to use it."
        ),
    }

    review = harness.mapping.review()
    parent = field(review, "parent_task")
    assert parent["status"] == "new_column"
    assert parent["selection"] == {"property_id": IDS["Parent Task"]}
    assert parent["message"] is not None
    assert "appeared in Notion" in parent["message"]
    assert review["schema_check"] is not None
    assert [s["field"] for s in review["schema_check"]["suggestions"]] == ["parent_task"]

    save(harness, review)
    assert harness.sync.status()["mapping_suggestions"] == []
    assert harness.sync.status()["full_sync_required"]
    result = harness.run()
    assert result["kind"] == "full"
    assert sorted(entries(harness).values()) == [[TASK_PAGE], [TASK_PAGE, SECOND_TASK]]
    assert harness.sync.status()["mapping_suggestions"] == []


def test_a_dismissed_suggestion_stays_dismissed(harness: Harness) -> None:
    save(harness, connect(harness, shared=False))
    share_tracker(harness)
    harness.run()
    assert len(harness.sync.status()["mapping_suggestions"]) == 1

    assert harness.mapping.dismiss_suggestion(IDS["Parent Task"]) == []
    assert harness.sync.status()["mapping_suggestions"] == []
    stored = parse_mapping(harness.settings.get("mapping"))
    assert stored["known_columns"] is not None
    assert IDS["Parent Task"] in stored["known_columns"]
    assert stored["fields"]["parent_task"] is None  # nothing changed but the offer

    harness.run()
    assert harness.sync.status()["mapping_suggestions"] == []
    assert field(harness.mapping.review(), "parent_task")["status"] == "unused"
    assert not harness.sync.status()["full_sync_required"]


@pytest.mark.parametrize("value", [None, 7, ""])
def test_dismissing_needs_a_column_id(harness: Harness, value: object) -> None:
    with pytest.raises(Exception, match="unexpected form"):
        harness.mapping.dismiss_suggestion(value)


def test_a_mapping_saved_before_known_columns_still_gets_the_offer(harness: Harness) -> None:
    save(harness, connect(harness, shared=False))
    stored = harness.settings.get("mapping")
    assert isinstance(stored, dict)
    harness.settings.set("mapping", {k: v for k, v in stored.items() if k != "known_columns"})
    share_tracker(harness)
    harness.run()
    assert [s["field"] for s in harness.sync.status()["mapping_suggestions"]] == ["parent_task"]


def test_a_column_seen_at_save_and_left_unused_is_not_offered(harness: Harness) -> None:
    review = connect(harness, shared=True)
    harness.mapping.save(
        {f["key"]: f["selection"] for f in review["fields"]} | {"parent_task": None}, []
    )
    harness.run()
    assert harness.sync.status()["mapping_suggestions"] == []
    assert field(harness.mapping.review(), "parent_task")["status"] == "unused"


def test_clearing_local_data_forgets_the_offer(harness: Harness) -> None:
    save(harness, connect(harness, shared=False))
    share_tracker(harness)
    harness.run()
    harness.connection.logout(True)
    assert harness.settings.get("mapping_suggestions") is None


def test_damaged_known_columns_are_refused() -> None:
    base = {"version": 1, "fields": {}, "extra": [], "names_at_save": {}, "saved_at": ""}
    assert parse_mapping(base)["known_columns"] is None
    assert parse_mapping(base | {"known_columns": ["a", "a", "b"]})["known_columns"] == ["a", "b"]
    for broken in ("a", [1], {"a": 1}):
        with pytest.raises(MappingFormatError):
            parse_mapping(base | {"known_columns": broken})
