"""The JS API: Python methods the UI calls as ``window.pywebview.api.<name>()``.

pywebview exposes every public attribute of :class:`Api`, so all state lives in underscore
attributes and only the bridge methods below are public. Each method returns the envelope from
:mod:`app.bridge`; the matching TypeScript types are in ``ui/src/bridge/types.ts``.
"""

from __future__ import annotations

import logging
import os
import platform
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypedDict
from urllib.parse import urlsplit

from app import APP_NAME, __version__
from app.bridge import bridge_method
from app.db import Database
from app.errors import AppError, new_error_id
from app.events import EventChannel
from app.paths import AppPaths

if TYPE_CHECKING:
    from app.mapping.review import MappingReview, MappingService, SaveResult
    from app.notion.connection import ConnectionInfo, ConnectionService, DataSourcePage
    from app.stats.preferences import Preferences
    from app.stats.service import Dashboard, DayDetail, StatsService
    from app.sync.engine import FlaggedPage, SyncService, SyncStatus

logger = logging.getLogger(__name__)

Mode = Literal["dev", "normal"]

BRIDGE_CHECK_MAX_STEPS: Final = 20
BRIDGE_CHECK_INTERVAL_S: Final = 0.4
CLIENT_ERROR_MAX_CHARS: Final = 8000


class WindowControl(Protocol):
    def destroy(self) -> None: ...


class AppInfo(TypedDict):
    name: str
    version: str
    mode: Mode
    diagnostics: bool
    python_version: str
    sqlite_version: str
    pywebview_version: str
    platform: str
    data_dir: str
    database_path: str
    log_dir: str
    schema_version: int
    started_at: str


class BridgeCheckStarted(TypedDict):
    run_id: str
    steps: int


class ClientErrorLogged(TypedDict):
    id: str


@dataclass(slots=True)
class AppContext:
    mode: Mode
    paths: AppPaths
    database: Database | None
    events: EventChannel
    diagnostics: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    window: WindowControl | None = None
    on_ui_ready: Callable[[], None] | None = None
    open_folder: Callable[[Path], None] = field(default=lambda path: _open_in_explorer(path))
    connection: ConnectionService | None = None
    mapping: MappingService | None = None
    sync: SyncService | None = None
    stats: StatsService | None = None
    open_url: Callable[[str], object] = field(default=lambda url: _open_in_browser(url))


class Api:
    def __init__(self, context: AppContext) -> None:
        self._ctx = context
        self._bridge_check_lock = threading.Lock()

    @bridge_method
    def get_app_info(self) -> AppInfo:
        ctx = self._ctx
        return {
            "name": APP_NAME,
            "version": __version__,
            "mode": ctx.mode,
            "diagnostics": ctx.diagnostics,
            "python_version": platform.python_version(),
            "sqlite_version": sqlite3.sqlite_version,
            "pywebview_version": _pywebview_version(),
            "platform": platform.platform(),
            "data_dir": str(ctx.paths.root),
            "database_path": str(ctx.paths.database),
            "log_dir": str(ctx.paths.logs_dir),
            "schema_version": ctx.database.schema_version if ctx.database else 0,
            "started_at": ctx.started_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

    @bridge_method
    def ui_ready(self) -> None:
        """Called by the UI once its event listener is attached."""
        logger.info("The UI reported ready")
        self._ctx.events.mark_ready()
        if self._ctx.on_ui_ready is not None:
            self._ctx.on_ui_ready()

    @bridge_method
    def run_bridge_check(self, steps: object = 5) -> BridgeCheckStarted:
        """Push ``steps`` progress events from a background thread, then a done event.

        It exercises the same path sync progress will use: work on a worker thread reporting to
        the UI while the window stays responsive.
        """
        if not isinstance(steps, int) or isinstance(steps, bool):
            raise AppError("The bridge check needs a whole number of steps.")
        if not 1 <= steps <= BRIDGE_CHECK_MAX_STEPS:
            raise AppError(f"The bridge check takes 1 to {BRIDGE_CHECK_MAX_STEPS} steps.")
        if not self._bridge_check_lock.acquire(blocking=False):
            raise AppError("A bridge check is already running.")
        run_id = new_error_id()

        def work() -> None:
            try:
                started = time.monotonic()
                for step in range(1, steps + 1):
                    time.sleep(BRIDGE_CHECK_INTERVAL_S)
                    self._ctx.events.emit(
                        "bridge-check:progress",
                        {"run_id": run_id, "step": step, "steps": steps, "thread": _thread_name()},
                    )
                elapsed_ms = round((time.monotonic() - started) * 1000)
                self._ctx.events.emit(
                    "bridge-check:done", {"run_id": run_id, "elapsed_ms": elapsed_ms}
                )
            finally:
                self._bridge_check_lock.release()

        threading.Thread(target=work, name=f"bridge-check-{run_id}", daemon=True).start()
        return {"run_id": run_id, "steps": steps}

    @bridge_method
    def log_client_error(self, report: object) -> ClientErrorLogged:
        """Log an error caught in the UI and return the error ID to show the user."""
        error_id = new_error_id()
        fields = report if isinstance(report, dict) else {"message": report}
        source = _clip(fields.get("source"), 40) or "ui"
        message = _clip(fields.get("message"), 1000) or "(no message)"
        stack = _clip(fields.get("stack"), CLIENT_ERROR_MAX_CHARS)
        component_stack = _clip(fields.get("componentStack"), CLIENT_ERROR_MAX_CHARS)
        details = "\n".join(part for part in (stack, component_stack) if part)
        logger.error("UI error (%s) [error %s]: %s\n%s", source, error_id, message, details)
        return {"id": error_id}

    @bridge_method
    def open_log_folder(self) -> None:
        self._ctx.open_folder(self._ctx.paths.logs_dir)

    @bridge_method
    def raise_test_error(self, where: object = "call") -> None:
        """Diagnostics only: fail on purpose to show how errors are reported."""
        if not self._ctx.diagnostics:
            raise AppError("Test errors are only available in dev mode or with --diagnostics.")
        if where == "call":
            raise RuntimeError("Test error raised inside a bridge call")
        if where == "thread":

            def fail() -> None:
                raise RuntimeError("Test error raised in a background thread")

            threading.Thread(target=fail, name="test-error", daemon=True).start()
            return
        raise AppError("Unknown test error location.", detail=repr(where))

    @bridge_method
    def quit(self) -> None:
        if self._ctx.window is not None:
            self._ctx.window.destroy()

    # --- Notion connection (PLAN.md 12) -------------------------------------------------

    def _connection(self) -> ConnectionService:
        if self._ctx.connection is None:
            raise AppError("The Notion connection isn't available because the app didn't start.")
        return self._ctx.connection

    @bridge_method
    def get_connection(self) -> ConnectionInfo:
        return self._connection().info()

    @bridge_method
    def connect_with_token(self, kind: object, token: object) -> ConnectionInfo:
        """Validate a pasted token with Notion, then store it. Nothing is stored on failure."""
        return self._connection().connect_with_token(kind, token)

    @bridge_method
    def start_sign_in(self) -> dict[str, object]:
        """Open Notion's consent page; the outcome arrives as connect:* events."""
        return self._connection().start_sign_in()

    @bridge_method
    def cancel_sign_in(self) -> None:
        self._connection().cancel_sign_in()

    @bridge_method
    def logout(self, clear_local_data: object) -> dict[str, object]:
        return self._connection().logout(clear_local_data)

    @bridge_method
    def list_data_sources(self, cursor: object = None) -> DataSourcePage:
        return self._connection().list_data_sources(cursor)

    @bridge_method
    def choose_data_source(
        self, database_id: object, data_source_id: object, confirm_replace: object = False
    ) -> ConnectionInfo:
        return self._connection().choose_data_source(database_id, data_source_id, confirm_replace)

    # --- Column mapping (PLAN.md 4) ------------------------------------------------------

    def _mapping(self) -> MappingService:
        if self._ctx.mapping is None:
            raise AppError("The column mapping isn't available because the app didn't start.")
        return self._ctx.mapping

    @bridge_method
    def get_mapping_review(self) -> MappingReview:
        """The chosen database's columns with sample values, and each app field's column."""
        return self._mapping().review()

    @bridge_method
    def save_mapping(self, fields: object, extra: object) -> SaveResult:
        return self._mapping().save(fields, extra)

    # --- Sync (PLAN.md 6) ------------------------------------------------------------------

    def _sync(self) -> SyncService:
        if self._ctx.sync is None:
            raise AppError("Syncing isn't available because the app didn't start.")
        return self._ctx.sync

    @bridge_method
    def get_sync_status(self) -> SyncStatus:
        return self._sync().status()

    @bridge_method
    def start_sync(self, kind: object = "auto") -> SyncStatus:
        """Start a sync in the background ("auto", "quick" or "full"); progress arrives as
        sync:status events."""
        return self._sync().start(kind)

    @bridge_method
    def get_flagged_entries(self, offset: object = 0, limit: object = 50) -> FlaggedPage:
        return self._sync().flagged_entries(offset, limit)

    @bridge_method
    def resolve_pending_removal(self, remove: object) -> SyncStatus:
        """Answer the mass-removal question: remove the entries, or keep them."""
        return self._sync().resolve_pending_removal(remove)

    # --- Dashboard (PLAN.md 7) ---------------------------------------------------------------

    def _stats(self) -> StatsService:
        if self._ctx.stats is None:
            raise AppError("The dashboard isn't available because the app didn't start.")
        return self._ctx.stats

    @bridge_method
    def get_dashboard(self, request: object) -> Dashboard:
        """Every chart's figures: {time_zone, range: {days} or {from, to}, weeks, year}."""
        return self._stats().dashboard(request)

    @bridge_method
    def get_day_detail(self, time_zone: object, day: object) -> DayDetail:
        return self._stats().day_detail(time_zone, day)

    @bridge_method
    def get_preferences(self) -> Preferences:
        return self._stats().preferences()

    @bridge_method
    def set_preferences(self, changes: object) -> Preferences:
        return self._stats().update_preferences(changes)

    @bridge_method
    def open_external(self, url: object) -> None:
        """Open a help or Notion link in the default browser. Only known HTTPS sites."""
        if not isinstance(url, str) or not _is_allowed_external(url):
            raise AppError("That link can't be opened.")
        self._ctx.open_url(url)


def _open_in_explorer(path: Path) -> None:
    os.startfile(path)  # noqa: S606 - opens a folder the app owns in Explorer


ALLOWED_EXTERNAL_HOSTS: Final = frozenset(
    {
        "habit-tracker.mrathour.workers.dev",
        "www.notion.so",
        "notion.so",
        "www.notion.com",
        "notion.com",
        "app.notion.com",
        "developers.notion.com",
    }
)


def _is_allowed_external(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_EXTERNAL_HOSTS


def _open_in_browser(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def _clip(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _thread_name() -> str:
    return threading.current_thread().name


def _pywebview_version() -> str:
    module = sys.modules.get("webview")
    return str(getattr(module, "__version__", "")) or _package_version("pywebview")


def _package_version(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"
