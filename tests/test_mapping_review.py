"""The mapping review screen's data and saving (PLAN.md 4.2), against a fake Notion."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.db import Database, open_database
from app.db.settings import Settings
from app.errors import AppError
from app.mapping.model import MappingChoiceError
from app.mapping.review import (
    SAMPLE_ROWS,
    FieldReview,
    MappingReview,
    MappingService,
    NoDatabaseError,
    SourceUnavailableError,
)
from app.notion.client import NotionReader, RateLimiter
from app.notion.connection import ConnectionService
from app.notion.credentials import CredentialStore, StoredCredential, utc_now
from app.notion.errors import (
    NotConnectedError,
    OfflineError,
    PasteNewTokenError,
    ReconnectRequiredError,
)
from app.notion.handoff import TokenGrant
from app.notion.tokens import TokenManager
from app.paths import AppPaths
from app.redaction import Secret
from tests.support.fake_notion import FakeNotion, notion_error
from tests.support.notion_schemas import (
    WORK_LOG_IDS,
    Schema,
    add_source,
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
NOW = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)


class InstantLimiter(RateLimiter):
    def wait(self) -> None:
        return


class RefusingTokenService:
    """A token service whose refresh is refused, as when the user removed the connection."""

    def refresh(self, refresh_token: Secret) -> TokenGrant:
        raise ReconnectRequiredError(detail="invalid_grant")

    def revoke(self, token: Secret) -> None:  # pragma: no cover - not used here
        return


@dataclass
class Harness:
    notion: FakeNotion
    tokens: TokenManager
    settings: Settings
    database: Database
    mapping: MappingService
    connection: ConnectionService

    def connect(self, kind: str = "pat") -> str:
        token = self.notion.issue_token()
        self.tokens.replace_credential(
            StoredCredential(
                kind=kind,  # type: ignore[arg-type]
                access_token=Secret(token),
                refresh_token=Secret("nrt_" + "r" * 32) if kind == "oauth" else None,
                obtained_at=utc_now(),
            )
        )
        return token

    def use(self, title: str, properties: Schema, rows: list[dict[str, Any]] | None = None) -> str:
        database, source_id = add_source(self.notion, title, properties, rows)
        self.connection.choose_data_source(database.id, source_id, True)
        return source_id


@pytest.fixture
def harness(app_paths: AppPaths) -> Iterator[Harness]:
    database = open_database(app_paths.database)
    notion = FakeNotion()
    tokens = TokenManager(CredentialStore("notion-test"), RefusingTokenService())  # type: ignore[arg-type]
    reader = NotionReader(
        tokens,
        http=httpx.Client(transport=httpx.MockTransport(notion.handle)),
        base_url="https://api.notion.test",
        limiter=InstantLimiter(),
        sleep=lambda _s: None,
    )
    settings = Settings(database.connection)
    connection = ConnectionService(
        tokens=tokens,
        reader=reader,
        service=RefusingTokenService(),  # type: ignore[arg-type]
        settings=settings,
        db=database.connection,
        emit=lambda _n, _p: None,
    )
    mapping = MappingService(tokens=tokens, reader=reader, settings=settings, clock=lambda: NOW)
    harness = Harness(notion, tokens, settings, database, mapping, connection)
    harness.connect()
    yield harness
    database.close()


def field(review: MappingReview, key: str) -> FieldReview:
    return next(f for f in review["fields"] if f["key"] == key)


def selections(review: MappingReview) -> dict[str, Any]:
    return {f["key"]: f["selection"] for f in review["fields"]}


def payload(review: MappingReview) -> dict[str, Any]:
    return selections(review)


# --- the author's Work Log ---------------------------------------------------------------------


def test_work_log_maps_with_no_changes(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), work_log_rows())
    review = harness.mapping.review()
    assert {f["key"]: f["status"] for f in review["fields"]} == {
        "start": "auto",
        "end": "auto",
        "task_name": "auto",
        "parent_task": "auto",
        "display_id": "auto",
        "logged_minutes": "auto",
    }
    assert selections(review) == {
        "start": {"property_id": IDS["Start Time"], "part": "start"},
        "end": {"property_id": IDS["End Time"], "part": "start"},
        "task_name": {"property_id": "title"},
        "parent_task": {"property_id": IDS["Parent Task"]},
        "display_id": {"property_id": IDS["ID"]},
        "logged_minutes": {"property_id": IDS["MinuteSpent"]},
    }
    assert not review["saved"]
    assert review["schema_check"] is None
    assert review["rows_sampled"] == 3
    assert review["database_title"] == "Work Log"


def test_samples_are_the_newest_rows(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), work_log_rows())
    columns = {c["name"]: c for c in harness.mapping.review()["columns"]}
    # Newest first; the newest entry has a blank name, so the title shows the next two.
    assert [s["text"] for s in columns["Name"]["samples"]] == [  # type: ignore[typeddict-item]
        "Writing EVA resume",
        "Work Log Table Created",
    ]
    assert columns["Name"]["filled"] == 2
    assert [s["text"] for s in columns["ID"]["samples"]] == ["8", "7", "6"]  # type: ignore[typeddict-item]
    assert [s["text"] for s in columns["MinuteSpent"]["samples"]] == ["37", "128", "2"]  # type: ignore[typeddict-item]
    assert columns["Parent Task"]["samples"][0] == {"kind": "text", "text": "1 linked page"}
    start = columns["Start Time"]["samples"][0]
    assert start == {
        "kind": "date",
        "start": {"utc": "2026-10-21T06:08:00.000Z", "date": "2026-10-21", "has_time": True},
        "end": None,
    }
    assert columns["Start Time"]["dates_without_time"] == 0
    assert not columns["Start Time"]["has_range"]
    assert (
        columns["Parent Task"]["note"]
        == "Linked pages are kept as links; their titles aren't read."
    )


def test_sample_query_is_one_read_of_the_newest_rows(harness: Harness) -> None:
    rows = [
        page(
            work_log_schema(),
            {"MinuteSpent": i},
            created=f"2026-10-{1 + i // 24:02d}T{i % 24:02d}:00:00.000Z",
        )
        for i in range(40)
    ]
    source_id = harness.use("Work Log", work_log_schema(), rows)
    harness.notion.requests.clear()
    review = harness.mapping.review()
    queries = [r for r in harness.notion.requests if r.url.path.endswith("/query")]
    assert len(queries) == 1
    assert queries[0].url.path == f"/v1/data_sources/{source_id}/query"
    assert json.loads(queries[0].content) == {
        "page_size": SAMPLE_ROWS,
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }
    assert review["rows_sampled"] == SAMPLE_ROWS
    minutes = next(c for c in review["columns"] if c["name"] == "MinuteSpent")
    assert [s["text"] for s in minutes["samples"]] == ["39", "38", "37"]  # type: ignore[typeddict-item]


def test_only_compatible_columns_are_offered(harness: Harness) -> None:
    extended = schema(work_log_schema(), prop("Notes", "notes", "rich_text"))
    harness.use("Work Log", extended, work_log_rows(extended))
    review = harness.mapping.review()
    assert [o["label"] for o in field(review, "task_name")["options"]] == ["Name", "Notes"]
    assert [o["label"] for o in field(review, "display_id")["options"]] == ["ID", "MinuteSpent"]
    assert [o["label"] for o in field(review, "logged_minutes")["options"]] == ["MinuteSpent"]
    assert field(review, "parent_task")["needs"] == "Relation"
    end_options = [(o["label"], o["part"]) for o in field(review, "end")["options"]]
    assert end_options == [
        ("Start Time", "start"),
        ("End Time", "start"),
        ("End of the date range in “Start Time”", "end"),
        ("End of the date range in “End Time”", "end"),
    ]
    assert all(o["part"] is None for o in field(review, "task_name")["options"])


def test_work_log_test_copy(harness: Harness) -> None:
    harness.use("Work Log (test)", work_log_schema(), work_log_rows())
    review = harness.mapping.review()
    assert all(f["status"] == "auto" for f in review["fields"])
    assert review["database_title"] == "Work Log (test)"


# --- empty database ---------------------------------------------------------------------------


def test_empty_database_maps_from_the_schema(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    review = harness.mapping.review()
    assert review["rows_sampled"] == 0
    assert all(f["status"] == "auto" for f in review["fields"])
    assert all(c["samples"] == [] for c in review["columns"])


# --- missing end time -------------------------------------------------------------------------


def test_no_end_time_column_explains_exactly(harness: Harness) -> None:
    source = without(work_log_schema(), "End Time")
    harness.use("Work Log (no end)", source, work_log_rows(source))
    review = harness.mapping.review()
    end = field(review, "end")
    assert end["status"] == "missing"
    assert end["selection"] is None
    assert end["missing_help"] == (
        "Your database needs a second Date column to use as the end time. In Notion, add a Date "
        "column for when each session ends and turn on “Include time”. Or, if “Start Time” holds "
        "each session as a date range (start → end), choose “End of the date range in “Start "
        "Time”” for End time."
    )
    # The range end is still on offer, by hand.
    assert [o["label"] for o in end["options"]] == [
        "Start Time",
        "End of the date range in “Start Time”",
    ]
    assert field(review, "start")["missing_help"] is None
    with pytest.raises(MappingChoiceError, match="End time is required"):
        harness.mapping.save(payload(review), [])


def test_no_date_column_explains_both(harness: Harness) -> None:
    source = without(work_log_schema(), "Start Time", "End Time")
    harness.use("Notes", source, [])
    review = harness.mapping.review()
    assert field(review, "start")["status"] == "missing"
    assert "has no Date column" in (field(review, "start")["missing_help"] or "")
    assert "also needs a Date column" in (field(review, "end")["missing_help"] or "")


# --- date range -------------------------------------------------------------------------------


def session_rows(properties: Schema) -> list[dict[str, Any]]:
    return [
        page(
            properties,
            {
                "Name": rich("Planning"),
                "Session": when("2026-10-21T09:00:00.000+05:30", "2026-10-21T10:15:00.000+05:30"),
            },
            created="2026-10-21T03:30:00.000Z",
        )
    ]


def test_single_range_column_is_detected_and_saved(harness: Harness) -> None:
    source = schema(prop("Name", "title", "title"), prop("Session", "s%3A1", "date"))
    harness.use("Sessions", source, session_rows(source))
    review = harness.mapping.review()
    assert field(review, "start")["selection"] == {"property_id": "s%3A1", "part": "start"}
    assert field(review, "end")["selection"] == {"property_id": "s%3A1", "part": "end"}
    assert field(review, "end")["status"] == "auto"
    session = next(c for c in review["columns"] if c["id"] == "s%3A1")
    assert session["has_range"]
    first = session["samples"][0]
    assert first["kind"] == "date"
    assert first["end"] is not None
    assert first["end"]["utc"] == "2026-10-21T04:45:00.000Z"
    harness.mapping.save(payload(review), [])
    stored = harness.settings.get("mapping")
    assert isinstance(stored, dict)
    assert stored["fields"]["end"] == {"property_id": "s%3A1", "part": "end"}


# --- ambiguity --------------------------------------------------------------------------------


def test_ambiguous_dates_ask_and_block_until_chosen(harness: Harness) -> None:
    source = schema(
        prop("Name", "title", "title"), prop("Date", "d1", "date"), prop("Date 2", "d2", "date")
    )
    harness.use("Log", source, [])
    review = harness.mapping.review()
    start = field(review, "start")
    assert start["status"] == "choose"
    assert start["selection"] is None
    assert set(start["choose_from"]) == {"d1", "d2"}
    with pytest.raises(MappingChoiceError):
        harness.mapping.save(payload(review), [])
    chosen = payload(review) | {
        "start": {"property_id": "d1", "part": "start"},
        "end": {"property_id": "d2", "part": "start"},
    }
    assert harness.mapping.save(chosen, [])["changed"] is False


# --- saving and reopening ---------------------------------------------------------------------


def test_first_save_does_not_require_a_full_sync(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), work_log_rows())
    review = harness.mapping.review()
    result = harness.mapping.save(payload(review), [])
    assert result == {"changed": False, "full_sync_required": None}
    info = harness.connection.info()
    assert info["mapping_saved"]
    assert info["full_sync_required"] is None
    stored = harness.settings.get("mapping")
    assert isinstance(stored, dict)
    assert stored["saved_at"] == "2026-10-22T10:00:00.000Z"
    assert stored["names_at_save"][IDS["Start Time"]] == "Start Time"


def test_reopening_shows_the_saved_mapping(harness: Harness) -> None:
    extended = schema(work_log_schema(), prop("Mood", "mood", "select"))
    harness.use("Work Log", extended, [])
    first = harness.mapping.review()
    harness.mapping.save(payload(first) | {"display_id": None}, ["mood"])
    again = harness.mapping.review()
    assert again["saved"]
    assert again["saved_at"] == "2026-10-22T10:00:00.000Z"
    assert field(again, "display_id")["status"] == "unused"
    assert field(again, "start")["status"] == "saved"
    assert again["extra"] == ["mood"]
    assert again["schema_check"] is not None
    assert again["schema_check"]["ok"]


def test_saving_the_same_mapping_again_changes_nothing(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    review = harness.mapping.review()
    harness.mapping.save(payload(review), [])
    assert harness.mapping.save(payload(review), []) == {
        "changed": False,
        "full_sync_required": None,
    }


def test_changing_the_mapping_requires_a_full_sync(harness: Harness) -> None:
    extended = schema(work_log_schema(), prop("Mood", "mood", "select"))
    harness.use("Work Log", extended, [])
    review = harness.mapping.review()
    harness.mapping.save(payload(review), [])
    result = harness.mapping.save(payload(review), ["mood"])
    flag = {
        "since": "2026-10-22T10:00:00.000Z",
        "reason": "The column mapping changed, so entries already copied need the new columns.",
    }
    assert result == {"changed": True, "full_sync_required": flag}
    assert harness.connection.info()["full_sync_required"] == flag
    assert harness.mapping.review()["full_sync_required"] == flag
    # Changing it back doesn't clear the flag: entries may already hold the other columns'
    # data, and only a full sync settles that.
    assert harness.mapping.save(payload(review), [])["full_sync_required"] == flag


def test_a_damaged_saved_mapping_is_replaced_and_needs_a_full_sync(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    harness.settings.set("mapping", {"version": 1, "fields": "broken"})
    review = harness.mapping.review()
    assert not review["saved"]
    assert review["schema_check"] is not None
    assert review["schema_check"]["blocking"][0]["code"] == "mapping_invalid"
    assert all(f["status"] == "auto" for f in review["fields"])
    assert harness.mapping.save(payload(review), [])["changed"] is True


def test_renamed_columns_keep_the_mapping(harness: Harness) -> None:
    source_id = harness.use("Work Log", work_log_schema(), [])
    harness.mapping.save(payload(harness.mapping.review()), [])
    harness.notion.data_sources[source_id].properties = work_log_schema(
        {"Start Time": "Began at", "End Time": "Stopped at"}
    )
    review = harness.mapping.review()
    assert field(review, "start")["status"] == "saved"
    assert field(review, "start")["selection"] == {
        "property_id": IDS["Start Time"],
        "part": "start",
    }
    assert review["schema_check"] is not None
    assert {(r["old_name"], r["new_name"]) for r in review["schema_check"]["renamed"]} == {
        ("Start Time", "Began at"),
        ("End Time", "Stopped at"),
    }


def test_removed_and_retyped_columns_are_flagged_on_reopening(harness: Harness) -> None:
    extended = schema(work_log_schema(), prop("Mood", "mood", "select"))
    source_id = harness.use("Work Log", extended, [])
    harness.mapping.save(payload(harness.mapping.review()), ["mood"])
    changed = without(extended, "End Time", "Mood")
    changed["MinuteSpent"] = {
        "id": IDS["MinuteSpent"],
        "name": "MinuteSpent",
        "type": "rich_text",
        "rich_text": {},
    }
    harness.notion.data_sources[source_id].properties = changed
    review = harness.mapping.review()
    end = field(review, "end")
    assert end["status"] == "removed"
    assert end["selection"] is None
    assert "“End Time” used for End time no longer exists" in (end["message"] or "")
    minutes = field(review, "logged_minutes")
    assert minutes["status"] == "type_changed"
    assert "now a Text column" in (minutes["message"] or "")
    assert review["extra"] == []
    assert review["schema_check"] is not None
    assert [w["code"] for w in review["schema_check"]["warnings"]] == [
        "optional_type_changed",
        "extra_missing",
    ]


def test_range_end_is_dropped_when_its_start_column_goes(harness: Harness) -> None:
    source = schema(prop("Name", "title", "title"), prop("Session", "s%3A1", "date"))
    source_id = harness.use("Sessions", source, session_rows(source))
    harness.mapping.save(payload(harness.mapping.review()), [])
    harness.notion.data_sources[source_id].properties = schema(prop("Name", "title", "title"))
    review = harness.mapping.review()
    assert field(review, "start")["status"] == "removed"
    assert field(review, "end")["status"] == "removed"
    assert field(review, "end")["selection"] is None
    assert "has no Date column" in (field(review, "start")["missing_help"] or "")


def test_switching_databases_forgets_the_mapping_and_flag(harness: Harness) -> None:
    extended = schema(work_log_schema(), prop("Mood", "mood", "select"))
    harness.use("Work Log", extended, [])
    review = harness.mapping.review()
    harness.mapping.save(payload(review), [])
    harness.mapping.save(payload(review), ["mood"])
    harness.use("Work Log (test)", work_log_schema(), [])
    info = harness.connection.info()
    assert not info["mapping_saved"]
    assert info["full_sync_required"] is None


def test_save_checks_against_a_fresh_schema(harness: Harness) -> None:
    source_id = harness.use("Work Log", work_log_schema(), [])
    review = harness.mapping.review()
    harness.notion.data_sources[source_id].properties = without(work_log_schema(), "End Time")
    with pytest.raises(MappingChoiceError, match="no longer exists"):
        harness.mapping.save(payload(review), [])
    assert harness.settings.get("mapping") is None


def test_formula_samples_decide_whether_it_can_be_logged_minutes(harness: Harness) -> None:
    source = schema(work_log_schema(), prop("Minutes (calc)", "f%3A1", "formula"))
    rows = [
        page(
            source,
            {"Minutes (calc)": {"type": "string", "string": "2 min"}},
            created="2026-10-21T00:00:00.000Z",
        )
    ]
    harness.use("Work Log", source, rows)
    review = harness.mapping.review()
    labels = [o["label"] for o in field(review, "logged_minutes")["options"]]
    assert labels == ["MinuteSpent"]
    formula = next(c for c in review["columns"] if c["id"] == "f%3A1")
    assert formula["formula_types"] == ["string"]


def test_unusable_columns_are_listed_with_reasons(harness: Harness) -> None:
    source = schema(
        work_log_schema(),
        prop("Log it", "b%3A1", "button"),
        prop("Legacy", "u%3A1", "unsupported"),
        prop("Hologram", "h%3A1", "hologram"),
    )
    harness.use("Work Log", source, work_log_rows(source))
    columns = {c["name"]: c for c in harness.mapping.review()["columns"]}
    assert not columns["Log it"]["readable"]
    assert "hold no value" in (columns["Log it"]["reason"] or "")
    assert "through its API" in (columns["Legacy"]["reason"] or "")
    assert "Hologram properties" in (columns["Hologram"]["reason"] or "")
    assert columns["Name"]["reason"] is None
    with pytest.raises(MappingChoiceError, match="can't be read"):
        harness.mapping.save(payload(harness.mapping.review()), ["b%3A1"])


# --- errors -----------------------------------------------------------------------------------


def test_not_connected(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    harness.tokens.forget()
    with pytest.raises(NotConnectedError):
        harness.mapping.review()


def test_no_database_chosen(harness: Harness) -> None:
    with pytest.raises(NoDatabaseError) as caught:
        harness.mapping.review()
    assert caught.value.state == "no_database"


def test_database_no_longer_shared(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    harness.notion.unshared.update(db.id for db in harness.notion.databases.values())
    with pytest.raises(SourceUnavailableError) as caught:
        harness.mapping.review()
    assert caught.value.state == "source_unavailable"
    assert "can't open “Work Log” any more" in caught.value.user_message


def test_offline(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    harness.notion.next_failures.append(httpx.ConnectError("down"))
    with pytest.raises(OfflineError):
        harness.mapping.review()


def test_pasted_token_rejected(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    harness.notion.valid_tokens.clear()
    with pytest.raises(PasteNewTokenError) as caught:
        harness.mapping.review()
    assert caught.value.state == "paste_new_token"


def test_notion_sign_in_rejected(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    harness.connect("oauth")
    harness.notion.valid_tokens.clear()
    with pytest.raises(ReconnectRequiredError) as caught:
        harness.mapping.review()
    assert caught.value.state == "reconnect"


def test_server_errors_on_the_sample_query_are_retried(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), work_log_rows())
    harness.notion.next_failures += [
        httpx.Response(
            200,
            json=harness.notion.data_source_json(next(iter(harness.notion.data_sources.values()))),
        ),
        notion_error(503, "service_unavailable"),
    ]
    assert harness.mapping.review()["rows_sampled"] == 3


def test_errors_reach_the_ui_with_their_state(harness: Harness) -> None:
    harness.use("Work Log", work_log_schema(), [])
    with pytest.raises(AppError) as caught:
        harness.mapping.save("nonsense", [])
    assert caught.value.state == "mapping_invalid"
