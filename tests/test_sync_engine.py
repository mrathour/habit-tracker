"""Quick sync and full sync against a fake Notion (PLAN.md 6)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.db import Database, open_database
from app.db.settings import Settings
from app.mapping.review import MappingService
from app.notion.client import NotionReader, RateLimiter
from app.notion.connection import ConnectionService
from app.notion.credentials import CredentialStore, StoredCredential, utc_now
from app.notion.errors import ReconnectRequiredError
from app.notion.handoff import TokenGrant
from app.notion.tokens import TokenManager
from app.paths import AppPaths
from app.redaction import Secret
from app.sync.engine import NotReadyError, SyncResult, SyncService
from tests.support.fake_notion import FakeNotion, notion_error
from tests.support.notion_schemas import (
    BROKEN_EXPECTED,
    TASK_PAGE,
    Schema,
    add_source,
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

NOTION_T0 = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)


class InstantLimiter(RateLimiter):
    def wait(self) -> None:
        return


class RefusingTokenService:
    def refresh(self, refresh_token: Secret) -> TokenGrant:
        raise ReconnectRequiredError(detail="invalid_grant")

    def revoke(self, token: Secret) -> None:  # pragma: no cover
        return


@dataclass
class Clock:
    """The PC's clock, which tests move independently of Notion's."""

    now: datetime = NOTION_T0

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Harness:
    notion: FakeNotion
    tokens: TokenManager
    settings: Settings
    database: Database
    connection: ConnectionService
    mapping: MappingService
    sync: SyncService
    pc: Clock
    events: list[dict[str, Any]] = field(default_factory=list)
    source_id: str = ""

    def use(
        self, properties: Schema, rows: list[dict[str, Any]], extra: list[str] | None = None
    ) -> str:
        database, source_id = add_source(self.notion, "Work Log (test)", properties, rows)
        self.connection.choose_data_source(database.id, source_id, True)
        review = self.mapping.review()
        self.mapping.save({f["key"]: f["selection"] for f in review["fields"]}, extra or [])
        self.source_id = source_id
        return source_id

    def run(self, kind: str = "auto") -> SyncResult:
        self.sync.start(kind)
        assert self.sync.wait(10), "sync didn't finish"
        result = self.sync.status()["last_result"]
        assert result is not None
        return result

    def rows(self) -> dict[str, dict[str, Any]]:
        cursor = self.database.connection.execute("SELECT * FROM work_logs")
        return {row["page_id"]: dict(row) for row in cursor}

    def queries(self) -> list[dict[str, Any]]:
        return [
            json.loads(r.content) for r in self.notion.requests if r.url.path.endswith("/query")
        ]

    def advance_notion(self, delta: timedelta) -> None:
        assert self.notion.server_now is not None
        self.notion.server_now += delta


@pytest.fixture
def harness(app_paths: AppPaths) -> Iterator[Harness]:
    database = open_database(app_paths.database)
    notion = FakeNotion(server_now=NOTION_T0)
    tokens = TokenManager(CredentialStore("notion-test"), RefusingTokenService())  # type: ignore[arg-type]
    tokens.replace_credential(
        StoredCredential(
            kind="pat", access_token=Secret(notion.issue_token()), obtained_at=utc_now()
        )
    )
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
    pc = Clock()
    events: list[dict[str, Any]] = []
    sync = SyncService(
        tokens=tokens,
        reader=reader,
        settings=settings,
        db=database.connection,
        database_path=app_paths.database,
        emit=lambda name, payload: events.append({"name": name, "payload": payload}),
        clock=pc,
    )
    mapping = MappingService(tokens=tokens, reader=reader, settings=settings)
    yield Harness(notion, tokens, settings, database, connection, mapping, sync, pc, events)
    sync.wait(10)
    database.close()


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- first sync -------------------------------------------------------------------------------


def test_first_sync_copies_every_entry(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    result = harness.run()
    assert result["ok"]
    assert result["kind"] == "full"
    assert result["reason"] == "First sync of this work log."
    assert (result["added"], result["updated"], result["removed"]) == (3, 0, 0)
    stored = harness.rows()
    assert set(stored) == {r["id"] for r in rows}
    first = stored[rows[0]["id"]]
    assert first["display_id"] == "6"
    assert first["task_name"] == "Work Log Table Created"
    assert first["start_utc"] == "2026-10-17T12:11:00.000Z"
    assert first["end_utc"] == "2026-10-17T12:13:00.000Z"
    assert first["logged_minutes"] == 2
    assert first["parent_task_id"] == TASK_PAGE
    assert json.loads(first["parent_task_ids"]) == [TASK_PAGE]
    assert json.loads(first["issues"]) == []
    status = harness.sync.status()
    assert status["entries"] == 3
    assert status["flagged"] == 0
    assert status["running"] is None
    assert status["last_successful_sync"] == iso(NOTION_T0)
    assert status["last_full_sync"] == iso(NOTION_T0)


def test_progress_is_pushed_while_syncing(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.run()
    phases = [e["payload"]["running"]["phase"] for e in harness.events if e["payload"]["running"]]
    assert phases[0] == "checking"
    assert "fetching" in phases
    assert "removing" in phases
    assert harness.events[-1]["payload"]["running"] is None


def test_pages_of_100_are_all_fetched(harness: Harness) -> None:
    source = work_log_schema()
    rows = [
        page(
            source,
            {"Start Time": when(f"2026-10-01T{i % 24:02d}:00:00.000Z")},
            created=f"2026-10-01T00:00:{i % 60:02d}.000Z",
            page_id=f"page-{i:03d}",
        )
        for i in range(250)
    ]
    harness.use(source, rows)
    result = harness.run()
    assert result["added"] == 250
    assert [q.get("start_cursor") for q in harness.queries()[-3:]] == [None, "100", "200"]


def test_relations_past_25_links_are_completed(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    links = [f"task-{i:02d}" for i in range(60)]
    harness.notion.link_many(rows[0]["id"], "Parent Task", links)
    harness.run("full")
    stored = harness.rows()[rows[0]["id"]]
    assert json.loads(stored["parent_task_ids"]) == links
    assert stored["parent_task_id"] == "task-00"
    assert json.loads(stored["issues"]) == []  # several links are never an issue


def test_broken_entries_are_imported_and_flagged(harness: Harness) -> None:
    harness.use(work_log_schema(), broken_rows())
    result = harness.run()
    assert result["ok"]
    stored = harness.rows()
    assert set(stored) == set(BROKEN_EXPECTED)
    for page_id, expected in BROKEN_EXPECTED.items():
        assert [i["code"] for i in json.loads(stored[page_id]["issues"])] == expected, page_id
    assert result["flagged"] == 5
    flagged = harness.sync.flagged_entries()
    assert flagged["total"] == 5
    mismatch = next(e for e in flagged["entries"] if e["page_id"] == "p-mismatch")
    assert mismatch["issues"][0]["message"] == "Logged 148 min, but Start → End is 123 min."
    assert mismatch["url"] == "https://www.notion.so/pmismatch"
    # Entries without a start time (empty, or a date only) come last.
    assert {e["page_id"] for e in flagged["entries"][-2:]} == {"p-no-start", "p-date-only"}


# --- quick sync and Notion's clock ------------------------------------------------------------


def test_quick_sync_picks_up_edits_and_new_entries(harness: Harness) -> None:
    rows = work_log_rows()
    source = work_log_schema()
    harness.use(source, rows)
    harness.run()
    harness.advance_notion(timedelta(hours=1))
    harness.notion.edit_page(rows[2]["id"], Name=rich("Renamed later"))
    new = page(
        source,
        {"Start Time": when("2026-10-22T10:30:00.000Z"), "End Time": when("2026-10-22T11:00Z")},
        created=harness.notion.edited_stamp(),
        page_id="page-new",
    )
    new["last_edited_time"] = harness.notion.edited_stamp()
    harness.notion.data_sources[harness.source_id].pages.append(new)
    harness.advance_notion(timedelta(minutes=2))
    result = harness.run()
    assert result["kind"] == "quick"
    assert (result["added"], result["updated"], result["removed"]) == (1, 1, 0)
    assert harness.rows()[rows[2]["id"]]["task_name"] == "Renamed later"
    assert harness.queries()[-1]["filter"] == {
        "timestamp": "last_edited_time",
        "last_edited_time": {"on_or_after": iso(NOTION_T0 - timedelta(minutes=5))},
    }
    assert harness.sync.status()["last_successful_sync"] == iso(
        NOTION_T0 + timedelta(hours=1, minutes=2)
    )


def test_quick_sync_never_removes_anything(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    harness.advance_notion(timedelta(minutes=10))
    harness.notion.delete_page(rows[0]["id"])
    result = harness.run()
    assert result["kind"] == "quick"
    assert result["removed"] == 0
    assert rows[0]["id"] in harness.rows()


@pytest.mark.parametrize("pc_offset", [timedelta(hours=3), timedelta(hours=-3)])
def test_cursor_follows_notions_clock_not_the_pcs(harness: Harness, pc_offset: timedelta) -> None:
    # The PC's clock is 3 hours fast or slow. Every edit made in Notion after the first sync
    # must still be found, and the cursor must be Notion's time.
    harness.pc.now = NOTION_T0 + pc_offset
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    assert harness.sync.status()["last_successful_sync"] == iso(NOTION_T0)

    # An edit made in Notion one minute after the sync started.
    harness.advance_notion(timedelta(minutes=1))
    harness.notion.edit_page(rows[0]["id"], Name=rich("Edited a minute later"))
    harness.advance_notion(timedelta(minutes=30))
    harness.pc.now += timedelta(minutes=31)
    result = harness.run()
    assert result["kind"] == "quick"
    assert result["updated"] == 1
    assert harness.rows()[rows[0]["id"]]["task_name"] == "Edited a minute later"
    on_or_after = harness.queries()[-1]["filter"]["last_edited_time"]["on_or_after"]
    assert on_or_after == iso(NOTION_T0 - timedelta(minutes=5))


def test_without_a_date_header_the_newest_edit_is_the_cursor(harness: Harness) -> None:
    harness.notion.send_date = False
    harness.use(work_log_schema(), work_log_rows())
    harness.pc.now = NOTION_T0 + timedelta(days=2)  # never used for the cursor
    harness.run()
    # The newest last_edited_time among the rows (2026-10-21T06:08Z).
    assert harness.sync.status()["last_successful_sync"] == "2026-10-21T06:08:00.000Z"


def test_without_a_date_header_or_rows_the_cursor_stays(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.run()
    harness.notion.send_date = False
    harness.advance_notion(timedelta(hours=1))
    harness.run("quick")
    assert harness.sync.status()["last_successful_sync"] == iso(NOTION_T0)


# --- when a full sync runs --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("notion_later", "kind"),
    [(timedelta(hours=23, minutes=59), "quick"), (timedelta(hours=24, minutes=1), "full")],
)
def test_launch_runs_a_full_sync_once_a_day(
    harness: Harness, notion_later: timedelta, kind: str
) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.run()
    harness.advance_notion(notion_later)
    harness.pc.now = NOTION_T0 + timedelta(minutes=5)  # the PC's clock doesn't decide it
    result = harness.run("auto")
    assert result["kind"] == kind
    if kind == "full":
        assert "more than 24 hours ago" in (result["reason"] or "")
        assert harness.sync.status()["last_full_sync"] == iso(NOTION_T0 + notion_later)


def test_an_explicit_quick_sync_ignores_the_daily_rule(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.run()
    harness.advance_notion(timedelta(days=3))
    assert harness.run("quick")["kind"] == "quick"


def test_a_changed_mapping_runs_a_full_sync_and_clears_the_flag(harness: Harness) -> None:
    source = schema(work_log_schema(), prop("Mood", "mood", "select"))
    harness.use(source, work_log_rows(source))
    harness.run()
    review = harness.mapping.review()
    harness.mapping.save({f["key"]: f["selection"] for f in review["fields"]}, ["mood"])
    assert harness.sync.status()["full_sync_required"]
    harness.advance_notion(timedelta(minutes=10))
    result = harness.run()
    assert result["kind"] == "full"
    assert result["reason"] == "The column mapping changed."
    assert result["updated"] == 3  # every entry gained the Mood field
    assert not harness.sync.status()["full_sync_required"]


# --- full sync removals -----------------------------------------------------------------------


def test_full_sync_removes_entries_deleted_in_notion(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    harness.notion.delete_page(rows[0]["id"])
    result = harness.run("full")
    assert result["removed"] == 1
    assert result["pending_removal"] is None
    assert rows[0]["id"] not in harness.rows()


def test_a_failed_full_sync_removes_nothing(harness: Harness) -> None:
    source = work_log_schema()
    rows = [
        page(source, {}, created=f"2026-10-01T00:{i // 60:02d}:{i % 60:02d}.000Z", page_id=f"p{i}")
        for i in range(150)
    ]
    harness.use(source, rows)
    harness.run()
    for row in rows[:20]:
        harness.notion.delete_page(row["id"])
    harness.advance_notion(timedelta(minutes=1))
    # Schema check and page 1 succeed; page 2 fails for good (more 503s than the retries).
    original = harness.notion._query
    calls = {"n": 0}

    def failing_query(source_obj: Any, body: dict[str, Any]) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] >= 2:
            return notion_error(503, "service_unavailable")
        return original(source_obj, body)

    harness.notion._query = failing_query  # type: ignore[method-assign,assignment]
    result = harness.run("full")
    assert not result["ok"]
    assert result["error"] is not None
    assert result["error"]["code"] == "notion_error"
    assert len(harness.rows()) == 150  # nothing removed
    assert harness.sync.status()["last_full_sync"] == iso(NOTION_T0)  # unchanged


def test_mass_removal_waits_for_the_user_and_other_changes_still_apply(
    harness: Harness,
) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    harness.advance_notion(timedelta(minutes=5))
    harness.notion.delete_page(rows[0]["id"])
    harness.notion.delete_page(rows[1]["id"])
    harness.notion.edit_page(rows[2]["id"], Name=rich("Still here, edited"))
    result = harness.run("full")
    assert result["ok"]
    assert result["pending_removal"] == 2
    assert result["removed"] == 0
    assert result["updated"] == 1
    assert len(harness.rows()) == 3
    assert harness.rows()[rows[2]["id"]]["task_name"] == "Still here, edited"
    pending = harness.sync.status()["pending_removal"]
    assert pending is not None
    assert (pending["count"], pending["total"]) == (2, 3)

    status = harness.sync.resolve_pending_removal(True)
    assert status["pending_removal"] is None
    assert set(harness.rows()) == {rows[2]["id"]}
    assert status["last_result"] is not None
    assert status["last_result"]["removed"] == 2


def test_keeping_them_clears_the_question(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    for row in rows:
        harness.notion.delete_page(row["id"])  # all of them: always asks
    result = harness.run("full")
    assert result["pending_removal"] == 3
    status = harness.sync.resolve_pending_removal(False)
    assert status["pending_removal"] is None
    assert len(harness.rows()) == 3


def test_half_or_less_is_removed_without_asking(harness: Harness) -> None:
    source = work_log_schema()
    rows = [
        page(source, {}, created=f"2026-10-0{i + 1}T00:00:00.000Z", page_id=f"p{i}")
        for i in range(4)
    ]
    harness.use(source, rows)
    harness.run()
    harness.notion.delete_page("p0")
    harness.notion.delete_page("p1")
    result = harness.run("full")
    assert result["removed"] == 2
    assert result["pending_removal"] is None


def test_entries_back_in_notion_are_not_removed_later(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    harness.advance_notion(timedelta(minutes=5))
    for row in rows:
        harness.notion.delete_page(row["id"])
    harness.run("full")
    # One comes back (restored from the trash) and a quick sync copies it again.
    _source, restored = harness.notion.find_page(rows[0]["id"])
    restored["in_trash"] = False
    harness.advance_notion(timedelta(minutes=5))
    restored["last_edited_time"] = harness.notion.edited_stamp()
    harness.pc.now += timedelta(minutes=10)
    harness.run("quick")
    harness.sync.resolve_pending_removal(True)
    assert set(harness.rows()) == {rows[0]["id"]}


def test_resolving_with_nothing_pending_is_an_error(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    with pytest.raises(Exception, match="No entries are waiting"):
        harness.sync.resolve_pending_removal(True)


# --- failures ---------------------------------------------------------------------------------


def test_offline_skips_the_sync_and_keeps_local_data(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.run()
    harness.notion.next_failures.append(httpx.ConnectError("no network"))
    result = harness.run()
    assert not result["ok"]
    assert result["error"] is not None
    assert result["error"]["code"] == "offline"
    assert harness.sync.status()["entries"] == 3
    assert harness.sync.status()["last_successful_sync"] == iso(NOTION_T0)


def test_a_rejected_pasted_token(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.notion.valid_tokens.clear()
    result = harness.run()
    assert result["error"] is not None
    assert result["error"]["code"] == "paste_new_token"


def test_rate_limits_are_waited_out(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.notion.next_failures.append(
        httpx.Response(
            429,
            headers={"Retry-After": "0"},
            json={"object": "error", "status": 429, "code": "rate_limited", "message": "slow"},
        )
    )
    assert harness.run()["ok"]


def test_a_missing_required_column_stops_the_sync_before_reading(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.notion.data_sources[harness.source_id].properties = without(
        work_log_schema(), "End Time"
    )
    harness.notion.requests.clear()
    result = harness.run()
    assert not result["ok"]
    assert result["error"] is not None
    assert result["error"]["code"] == "schema_blocked"
    assert result["error"]["issues"][0]["code"] == "required_missing"
    assert "“End Time”" in result["error"]["message"]
    assert harness.queries() == []
    assert harness.rows() == {}


def test_optional_column_gone_is_a_warning(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    source = without(work_log_schema(), "MinuteSpent")
    harness.notion.data_sources[harness.source_id].properties = source
    harness.notion.data_sources[harness.source_id].pages = work_log_rows(source)
    result = harness.run()
    assert result["ok"]
    assert len(result["warnings"]) == 1
    assert "Syncing continues without Logged minutes" in result["warnings"][0]
    assert all(row["logged_minutes"] is None for row in harness.rows().values())


def test_an_unreadable_page_is_skipped_but_never_removed(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    harness.notion.find_page(rows[0]["id"])[1]["created_time"] = "garbled"
    result = harness.run("full")
    assert result["skipped"] == 1
    assert result["removed"] == 0
    assert rows[0]["id"] in harness.rows()


# --- starting and queueing --------------------------------------------------------------------


def test_not_ready_without_a_mapping(harness: Harness) -> None:
    database, source_id = add_source(harness.notion, "Log", work_log_schema(), [])
    harness.connection.choose_data_source(database.id, source_id, True)
    with pytest.raises(NotReadyError, match="Map your columns"):
        harness.sync.start()


def test_unknown_kind(harness: Harness) -> None:
    harness.use(work_log_schema(), [])
    with pytest.raises(Exception, match="Unknown kind"):
        harness.sync.start("sideways")


def test_a_full_sync_asked_for_during_a_quick_one_runs_after_it(harness: Harness) -> None:
    harness.use(work_log_schema(), work_log_rows())
    harness.run()
    asked = {"done": False}
    original = harness.sync._emit

    def emit(name: str, payload: Any) -> None:
        running = payload.get("running") if isinstance(payload, dict) else None
        if running and running["kind"] == "quick" and not asked["done"]:
            asked["done"] = True
            harness.sync.start("full")
        original(name, payload)

    harness.sync._emit = emit
    harness.advance_notion(timedelta(minutes=10))
    harness.sync.start("auto")
    assert harness.sync.wait(10)
    kinds = [e["payload"]["running"]["kind"] for e in harness.events if e["payload"]["running"]]
    ran = [kind for i, kind in enumerate(kinds) if kind and (i == 0 or kinds[i - 1] != kind)]
    assert ran[-2:] == ["quick", "full"]
    assert harness.sync.status()["last_result"]["kind"] == "full"  # type: ignore[index]


def test_switching_databases_forgets_sync_state(harness: Harness) -> None:
    rows = work_log_rows()
    harness.use(work_log_schema(), rows)
    harness.run()
    for row in rows:
        harness.notion.delete_page(row["id"])
    harness.run("full")
    harness.use(work_log_schema(), [])
    status = harness.sync.status()
    assert status["pending_removal"] is None
    assert status["last_result"] is None
    assert status["last_successful_sync"] is None
    assert status["entries"] == 0


# --- the UI stays responsive ------------------------------------------------------------------


def test_ui_reads_stay_responsive_during_a_large_full_sync(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 5,000-entry full sync never holds the app's shared connection while it works.

    The sync writes, and reads its own progress, through its own connection (WAL lets the UI
    read meanwhile). The shared connection's lock guards only the UI side's short reads. This
    checks both: the lock is free during every upsert, and the UI's reads and a settings write
    stay fast for the whole sync.
    """
    import statistics
    import threading
    import time

    from app.db.connection import lock_for
    from app.sync import store as sync_store

    source = work_log_schema()
    rows = [
        page(
            source,
            {
                "Name": rich(f"Session {i}"),
                "Start Time": when(f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}T09:00:00.000Z"),
                "End Time": when(f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}T10:00:00.000Z"),
                "MinuteSpent": 60 if i % 10 else 90,  # every tenth is flagged
            },
            created="2025-01-01T00:00:00.000Z",
            page_id=f"page-{i:05d}",
        )
        for i in range(5000)
    ]
    harness.use(source, rows)

    # Notion answers each page of 100 after 40 ms, so the sync lasts a few seconds.
    original_query = harness.notion._query

    def slow_query(source_obj: Any, body: dict[str, Any]) -> httpx.Response:
        time.sleep(0.04)
        return original_query(source_obj, body)

    harness.notion._query = slow_query  # type: ignore[method-assign,assignment]

    main = harness.database.connection

    class RecordingLock:
        """The shared connection's lock, noting which threads take it during the sync."""

        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.taken_by_sync_while_running: list[str] = []

        def _note(self) -> None:
            name = threading.current_thread().name
            if name.startswith("sync-") and harness.sync._run is not None:
                self.taken_by_sync_while_running.append(name)

        def acquire(self, *args: Any, **kwargs: Any) -> bool:
            self._note()
            return bool(self.inner.acquire(*args, **kwargs))

        def release(self) -> None:
            self.inner.release()

        def __enter__(self) -> bool:
            return self.acquire()

        def __exit__(self, *exc: object) -> None:
            self.release()

        def _is_owned(self) -> bool:
            return bool(self.inner._is_owned())

    recording = RecordingLock(main.lock)  # type: ignore[attr-defined]
    main.lock = recording  # type: ignore[attr-defined]
    harness.settings._lock = recording  # type: ignore[assignment]
    lock_free: list[bool] = []
    own_connection: list[bool] = []
    original_upsert = sync_store.upsert

    def checked_upsert(conn: Any, entries: Any, synced_at: str) -> sync_store.UpsertCounts:
        own_connection.append(conn is not main)
        # Runs on the sync thread: it must not own the shared connection's lock here.
        lock_free.append(not lock_for(main)._is_owned())  # type: ignore[attr-defined]
        return original_upsert(conn, entries, synced_at)

    monkeypatch.setattr(sync_store, "upsert", checked_upsert)

    latencies: list[float] = []
    write_latencies: list[float] = []
    seen_running = 0
    harness.sync.start("full")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        began = time.perf_counter()
        status = harness.sync.status()
        harness.sync.flagged_entries(0, 50)
        latencies.append(time.perf_counter() - began)
        began = time.perf_counter()
        harness.settings.set("week_start", "monday")
        write_latencies.append(time.perf_counter() - began)
        if status["running"] is None:
            break
        seen_running += 1
        time.sleep(0.01)
    assert harness.sync.wait(120)

    result = harness.sync.status()["last_result"]
    assert result is not None
    assert result["ok"]
    assert result["added"] == 5000
    assert result["flagged"] == 500
    assert len(own_connection) == 50
    assert all(own_connection), "the sync wrote through the app's shared connection"
    assert all(lock_free), "the sync thread held the shared connection's lock during an upsert"
    assert recording.taken_by_sync_while_running == [], "the sync used the shared connection"
    print(  # noqa: T201 - shown with -s, for the record
        f"{len(latencies)} UI reads during the sync: median "
        f"{statistics.median(latencies) * 1000:.1f} ms, max {max(latencies) * 1000:.1f} ms; "
        f"settings writes max {max(write_latencies) * 1000:.1f} ms"
    )
    assert seen_running >= 20, f"too few reads overlapped the sync ({seen_running})"
    assert max(latencies) < 0.5, f"slowest UI read took {max(latencies):.3f}s"
    assert statistics.median(latencies) < 0.05
    assert max(write_latencies) < 0.5, f"slowest settings write took {max(write_latencies):.3f}s"
