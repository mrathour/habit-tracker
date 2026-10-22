"""Quick sync and full sync (PLAN.md 6).

Every sync runs on a background thread with its own SQLite connection, one at a time:

1. **Schema check** (6.3): ``GET /v1/data_sources/{id}``, then :func:`check_schema`. A blocking
   problem stops the sync before anything is read; warnings are reported with the result.
2. **Which kind.** "auto" (each launch) runs a full sync when nothing has been fully synced yet,
   when the mapping changed (``full_sync_required``), or when the last full sync is more than
   24 hours old, because quick sync can't see formula and rollup values that change without
   the page itself being edited. Otherwise it runs a quick sync.
3. **Fetch and store.** Pages of 100 from ``POST .../query`` (quick sync filters on
   ``last_edited_time`` from the last successful sync minus 5 minutes). Relations with more than
   25 links are completed. Each page is validated and upserted; each batch is committed.
4. **Full sync only: removals**, and only if every page was fetched. If they would remove more
   than half of the local entries, or all of them, they wait for the user's decision
   (``pending_removal``); the sync's other changes still apply.
5. **Bookkeeping on Notion's clock.** The cursor for the next quick sync is the ``Date`` header of
   Notion's first response in this sync (the schema check), which is Notion's time when the sync
   started. The PC's clock is never used for it, so a PC clock that is fast or slow can't skip
   edits. If that header is missing, the newest ``last_edited_time`` received is used instead:
   it is never later than the true start, so it is always safe, only less up to date.

Progress and results reach the UI as ``sync:status`` events with the whole status, so the UI
never has to piece it together.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal, TypedDict

from app.db.connection import connect, lock_for
from app.db.settings import FULL_SYNC_REQUIRED_KEY, MAPPING_KEY, Settings
from app.errors import AppError, report_exception
from app.mapping.model import StoredMapping, parse_mapping
from app.mapping.properties import schema_properties
from app.notion.client import NotionReader
from app.notion.dates import utc_iso
from app.notion.errors import NotConnectedError
from app.notion.tokens import TokenManager
from app.sync import store
from app.sync.schema_check import SchemaCheck, SchemaIssueDict, check_schema
from app.sync.values import Entry, UnreadableValueError, read_entry, relations_to_complete

logger = logging.getLogger(__name__)

PAGE_SIZE: Final = 100
#: Notion records last_edited_time only to the minute; the overlap catches edits at the edge.
QUICK_SYNC_OVERLAP: Final = timedelta(minutes=5)
#: Formula and rollup values can change without editing the page; a full sync refreshes them.
FULL_SYNC_MAX_AGE: Final = timedelta(hours=24)
#: Removals above this share of the local entries wait for the user's decision.
MASS_REMOVAL_SHARE: Final = 0.5

LAST_SUCCESSFUL_SYNC_KEY: Final = "last_successful_sync"
LAST_FULL_SYNC_KEY: Final = "last_full_sync"
LAST_SYNC_RESULT_KEY: Final = "last_sync_result"
PENDING_REMOVAL_KEY: Final = "pending_removal"

SyncKind = Literal["quick", "full"]
Requested = Literal["auto", "quick", "full"]
Phase = Literal["checking", "fetching", "removing"]


class SyncError(TypedDict):
    id: str
    code: str | None
    message: str
    #: For "schema_blocked": what changed in Notion.
    issues: list[SchemaIssueDict]


class SyncResult(TypedDict):
    kind: SyncKind | None
    #: Why this kind ran, e.g. "Last full sync was more than 24 hours ago."
    reason: str | None
    finished_at: str
    ok: bool
    added: int
    updated: int
    removed: int
    flagged: int
    #: Pages Notion sent that couldn't be read at all (kept locally, never removed).
    skipped: int
    warnings: list[str]
    pending_removal: int | None
    error: SyncError | None


class Progress(TypedDict):
    kind: SyncKind | None
    phase: Phase
    pages_fetched: int
    added: int
    updated: int
    removed: int


class PendingRemoval(TypedDict):
    count: int
    total: int
    found_at: str


class SyncStatus(TypedDict):
    running: Progress | None
    last_result: SyncResult | None
    last_successful_sync: str | None
    last_full_sync: str | None
    entries: int
    flagged: int
    pending_removal: PendingRemoval | None
    full_sync_required: bool


class FlaggedPage(TypedDict):
    entries: list[store.FlaggedEntry]
    total: int


class NotReadyError(AppError):
    state = "not_ready"


class SchemaBlockedError(AppError):
    state = "schema_blocked"

    def __init__(self, check: SchemaCheck) -> None:
        super().__init__(
            "Syncing can't start: " + " ".join(issue.message for issue in check.blocking)
        )
        self.check = check


@dataclass
class _Run:
    requested: Requested
    progress: Progress = field(
        default_factory=lambda: Progress(
            kind=None, phase="checking", pages_fetched=0, added=0, updated=0, removed=0
        )
    )


class SyncService:
    def __init__(
        self,
        *,
        tokens: TokenManager,
        reader: NotionReader,
        settings: Settings,
        db: sqlite3.Connection,
        database_path: Path | str,
        emit: Callable[[str, object], None],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        open_connection: Callable[[Path | str], sqlite3.Connection] = connect,
    ) -> None:
        self._tokens = tokens
        self._reader = reader
        self._settings = settings
        self._db = db
        self._database_path = database_path
        self._emit = emit
        self._clock = clock
        self._open = open_connection
        self._lock = threading.Lock()
        self._run: _Run | None = None
        self._queued_full = False
        self._thread: threading.Thread | None = None
        self._idle = threading.Event()
        self._idle.set()

    # --- the UI's view -------------------------------------------------------------------

    def status(self) -> SyncStatus:
        """For the UI's threads: read through the app's shared connection, under its lock.

        The lock is held only for these few reads. A running sync never takes it while it
        works: it writes, and reads its own progress, through its own connection.
        """
        with self._lock:
            progress = self._run.progress.copy() if self._run else None
        with lock_for(self._db):
            status = _stored_status(self._db, self._settings)
        status["running"] = progress
        return status

    def flagged_entries(self, offset: object = 0, limit: object = 50) -> FlaggedPage:
        start = offset if isinstance(offset, int) and offset >= 0 else 0
        size = limit if isinstance(limit, int) and 1 <= limit <= 500 else 50
        with lock_for(self._db):
            return {
                "entries": store.flagged(self._db, size, start),
                "total": store.counts(self._db)[1],
            }

    # --- starting --------------------------------------------------------------------------

    def start(self, requested: object = "auto") -> SyncStatus:
        """Start a sync in the background. While one runs, a full sync request is queued."""
        if requested not in ("auto", "quick", "full"):
            raise AppError("Unknown kind of sync.", detail=repr(requested))
        self._check_ready()
        with self._lock:
            if self._run is None:
                self._begin_locked(requested)
            elif requested == "full" and self._run.progress["kind"] != "full":
                self._queued_full = True  # runs right after the current sync
        return self.status()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until no sync is running (tests and shutdown)."""
        return self._idle.wait(timeout)

    def _check_ready(self) -> None:
        if self._tokens.credential() is None:
            raise NotConnectedError
        if not self._settings.get_str("data_source_id"):
            raise NotReadyError("Choose your work log before syncing.")
        if self._settings.get(MAPPING_KEY) is None:
            raise NotReadyError("Map your columns before syncing.")

    def _begin_locked(self, requested: Requested) -> None:
        self._run = _Run(requested)
        self._idle.clear()
        self._thread = threading.Thread(
            target=self._work, args=(self._run,), name=f"sync-{requested}", daemon=True
        )
        self._thread.start()

    # --- the pending removal (mass-removal safeguard) ---------------------------------------

    def resolve_pending_removal(self, remove: object) -> SyncStatus:
        if not isinstance(remove, bool):
            raise AppError("Choose whether to remove or keep the entries.")
        pending = self._settings.get(PENDING_REMOVAL_KEY)
        if not isinstance(pending, dict):
            raise AppError("No entries are waiting to be removed.")
        with self._lock:
            if self._run is not None:
                raise AppError("Wait for the current sync to finish, then try again.")
        removed = 0
        if remove:
            ids = [str(pid) for pid in pending.get("page_ids", [])]
            with lock_for(self._db):
                removed = store.delete(self._db, ids, synced_before=str(pending["found_at"]))
            logger.info("Removed %d entries after the user confirmed", removed)
        else:
            logger.info(
                "Kept %d entries the last full sync didn't find", len(pending.get("page_ids", []))
            )
        result = self._settings.get(LAST_SYNC_RESULT_KEY)
        updates: dict[str, object] = {PENDING_REMOVAL_KEY: None}
        if isinstance(result, dict):
            with lock_for(self._db):
                entries_flagged = store.counts(self._db)[1]
            updates[LAST_SYNC_RESULT_KEY] = {
                **result,
                "removed": int(result.get("removed", 0)) + removed,
                "pending_removal": None,
                "flagged": entries_flagged,
            }
        self._settings.set_many(updates)
        status = self.status()
        self._emit("sync:status", status)
        return status

    # --- the work ----------------------------------------------------------------------------

    def _work(self, run: _Run) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._open(self._database_path)
            settings = Settings(conn)
            result = self._sync(run, conn, settings)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a result the UI shows
            result = self._failure(run, exc, conn)
            if conn is not None:
                Settings(conn).set(LAST_SYNC_RESULT_KEY, result)
            else:
                self._settings.set(LAST_SYNC_RESULT_KEY, result)
        finally:
            if conn is not None:
                conn.close()
        with self._lock:
            self._run = None
            again = self._queued_full and result["ok"]
            self._queued_full = False
            if again:
                self._begin_locked("full")
            else:
                self._idle.set()
        self._emit("sync:status", self.status())

    def _sync(self, run: _Run, conn: sqlite3.Connection, settings: Settings) -> SyncResult:
        self._publish(run, conn, settings)
        source_id = settings.get_str("data_source_id")
        if not source_id:
            raise NotReadyError("Choose your work log before syncing.")
        self._reader.forget_server_time()
        source = self._reader.retrieve_data_source(source_id)
        server_now = self._reader.server_time()
        check = check_schema(settings.get(MAPPING_KEY), source)
        if not check.ok:
            raise SchemaBlockedError(check)
        mapping = parse_mapping(settings.get(MAPPING_KEY))
        columns = {p.id: p for p in schema_properties(source)}
        now = server_now or self._clock()
        kind, reason = self._choose_kind(run.requested, settings, now)
        run.progress["kind"] = kind
        run.progress["phase"] = "fetching"
        self._publish(run, conn, settings)
        logger.info("%s sync started (%s)", kind.capitalize(), reason)

        local_before = store.page_ids(conn)
        filter_body = None
        if kind == "quick":
            cursor = _parse(settings.get_str(LAST_SUCCESSFUL_SYNC_KEY))
            if cursor is None:  # pragma: no cover - _choose_kind runs a full sync without one
                raise RuntimeError("quick sync without a cursor")
            filter_body = {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_after": utc_iso(cursor - QUICK_SYNC_OVERLAP)},
            }
        seen: set[str] = set()
        skipped = 0
        newest_edit: datetime | None = None
        start_cursor: str | None = None
        while True:
            page = self._reader.query_data_source(
                source_id, page_size=PAGE_SIZE, start_cursor=start_cursor, filter=filter_body
            )
            rows = [
                row
                for row in page.get("results", [])
                if isinstance(row, dict) and row.get("object") == "page" and row.get("id")
            ]
            entries: list[Entry] = []
            for row in rows:
                seen.add(str(row["id"]))
                self._complete_relations(row, mapping)
                try:
                    entries.append(read_entry(row, mapping, columns))
                except UnreadableValueError as exc:
                    skipped += 1
                    logger.warning("Skipped a page Notion sent that couldn't be read: %s", exc)
                    continue
                edited = _parse(entries[-1].last_edited_time)
                if edited and (newest_edit is None or edited > newest_edit):
                    newest_edit = edited
            counts = store.upsert(conn, entries, utc_iso(self._clock()))
            run.progress["pages_fetched"] += len(rows)
            run.progress["added"] += counts.added
            run.progress["updated"] += counts.updated
            self._publish(run, conn, settings)
            next_cursor = page.get("next_cursor")
            if not page.get("has_more") or not isinstance(next_cursor, str):
                break
            start_cursor = next_cursor

        # Every page arrived: only now may a full sync remove anything.
        pending_count: int | None = None
        updates: dict[str, object] = {}
        if kind == "full":
            missing = local_before - seen
            run.progress["phase"] = "removing"
            self._publish(run, conn, settings)
            if missing and _is_mass_removal(len(missing), len(local_before)):
                pending_count = len(missing)
                updates[PENDING_REMOVAL_KEY] = {
                    "count": len(missing),
                    "total": len(local_before),
                    "found_at": utc_iso(self._clock()),
                    "page_ids": sorted(missing),
                }
                logger.warning(
                    "Full sync would remove %d of %d entries; waiting for the user",
                    len(missing),
                    len(local_before),
                )
            else:
                run.progress["removed"] = store.delete(conn, missing)
                updates[PENDING_REMOVAL_KEY] = None
            updates[LAST_FULL_SYNC_KEY] = utc_iso(now)
            updates[FULL_SYNC_REQUIRED_KEY] = None

        cursor_time = server_now or newest_edit
        if cursor_time is not None:
            updates[LAST_SUCCESSFUL_SYNC_KEY] = utc_iso(cursor_time)
        else:
            logger.info("Notion sent no Date header and no pages; the sync cursor stays put")
        result: SyncResult = {
            "kind": kind,
            "reason": reason,
            "finished_at": utc_iso(self._clock()),
            "ok": True,
            "added": run.progress["added"],
            "updated": run.progress["updated"],
            "removed": run.progress["removed"],
            "flagged": store.counts(conn)[1],
            "skipped": skipped,
            "warnings": [issue.message for issue in check.warnings],
            "pending_removal": pending_count,
            "error": None,
        }
        updates[LAST_SYNC_RESULT_KEY] = result
        settings.set_many(updates)
        logger.info(
            "%s sync finished: %d added, %d updated, %d removed, %d flagged%s",
            kind.capitalize(),
            result["added"],
            result["updated"],
            result["removed"],
            result["flagged"],
            f", {pending_count} removals waiting" if pending_count else "",
        )
        return result

    def _choose_kind(
        self, requested: Requested, settings: Settings, now: datetime
    ) -> tuple[SyncKind, str]:
        last_full = _parse(settings.get_str(LAST_FULL_SYNC_KEY))
        cursor = _parse(settings.get_str(LAST_SUCCESSFUL_SYNC_KEY))
        if requested == "full":
            return "full", "You asked for a full sync."
        if last_full is None or cursor is None:
            return "full", "First sync of this work log."
        if settings.get(FULL_SYNC_REQUIRED_KEY) is not None:
            return "full", "The column mapping changed."
        if requested == "auto" and now - last_full > FULL_SYNC_MAX_AGE:
            return "full", (
                "The last full sync was more than 24 hours ago, so formula and rollup values "
                "are refreshed."
            )
        return "quick", "Checking for entries added or edited since the last sync."

    def _complete_relations(self, row: dict[str, Any], mapping: StoredMapping) -> None:
        wanted = {
            ref["property_id"]
            for key, ref in mapping["fields"].items()
            if ref and key == "parent_task"
        } | set(mapping["extra"])
        for prop_id in relations_to_complete(row, wanted):
            ids: list[dict[str, str]] = []
            start_cursor: str | None = None
            while True:
                item = self._reader.retrieve_property_item(str(row["id"]), prop_id, start_cursor)
                for result in item.get("results", []):
                    relation = result.get("relation") if isinstance(result, dict) else None
                    if isinstance(relation, dict) and relation.get("id"):
                        ids.append({"id": str(relation["id"])})
                next_cursor = item.get("next_cursor")
                if not item.get("has_more") or not isinstance(next_cursor, str):
                    break
                start_cursor = next_cursor
            for value in row["properties"].values():
                if isinstance(value, dict) and value.get("id") == prop_id:
                    value["relation"] = ids
                    value["has_more"] = False

    def _failure(
        self, run: _Run, exc: BaseException, conn: sqlite3.Connection | None
    ) -> SyncResult:
        report = report_exception(exc, context=f"{run.requested} sync")
        issues = (
            [issue.to_dict() for issue in exc.check.blocking]
            if isinstance(exc, SchemaBlockedError)
            else []
        )
        return {
            "kind": run.progress["kind"],
            "reason": None,
            "finished_at": utc_iso(self._clock()),
            "ok": False,
            "added": run.progress["added"],
            "updated": run.progress["updated"],
            "removed": run.progress["removed"],
            "flagged": store.counts(conn)[1] if conn is not None else self._flagged_count(),
            "skipped": 0,
            "warnings": [],
            "pending_removal": None,
            "error": {
                "id": report.id,
                "code": report.code,
                "message": report.message,
                "issues": issues,
            },
        }

    def _flagged_count(self) -> int:
        with lock_for(self._db):
            return store.counts(self._db)[1]

    def _publish(self, run: _Run, conn: sqlite3.Connection, settings: Settings) -> None:
        """Push progress, read through the sync's own connection: never the shared one."""
        status = _stored_status(conn, settings)
        status["running"] = run.progress.copy()
        self._emit("sync:status", status)


def _stored_status(conn: sqlite3.Connection, settings: Settings) -> SyncStatus:
    """Everything but the running sync, from the settings and the local entries on ``conn``."""
    entries, flagged = store.counts(conn)
    pending = settings.get(PENDING_REMOVAL_KEY)
    result = settings.get(LAST_SYNC_RESULT_KEY)
    return {
        "running": None,
        "last_result": result if isinstance(result, dict) else None,  # type: ignore[typeddict-item]
        "last_successful_sync": settings.get_str(LAST_SUCCESSFUL_SYNC_KEY),
        "last_full_sync": settings.get_str(LAST_FULL_SYNC_KEY),
        "entries": entries,
        "flagged": flagged,
        "pending_removal": (
            {
                "count": int(pending["count"]),
                "total": int(pending["total"]),
                "found_at": str(pending["found_at"]),
            }
            if isinstance(pending, dict)
            else None
        ),
        "full_sync_required": settings.get(FULL_SYNC_REQUIRED_KEY) is not None,
    }


def _is_mass_removal(missing: int, total: int) -> bool:
    return total > 0 and (missing == total or missing > total * MASS_REMOVAL_SHARE)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
