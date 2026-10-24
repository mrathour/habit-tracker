"""Entry point: ``habit-tracker`` (normal mode) or ``habit-tracker --dev``.

* **Normal mode** loads the built UI from ``ui/dist`` over ``file://``. There is no local web
  server (PLAN.md 10).
* **Dev mode** loads the Vite dev server (started automatically if it isn't running) for hot
  reload, logs at DEBUG to the console as well, and enables the web inspector.
* ``--self-check`` starts everything except the window and reports the result, for CI.

If startup fails, the window still opens and shows a readable error page instead of the UI. If
even the window can't open (for example WebView2 is missing), a Windows message box explains.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app import APP_NAME, __version__
from app.api import Api, AppContext, Mode
from app.db import Database, open_database
from app.db.settings import Settings
from app.devserver import DEFAULT_DEV_URL, ViteDevServer, ensure_dev_server
from app.error_page import render_error_page
from app.errors import AppError, ErrorReport, install_excepthooks, report_exception
from app.events import EventChannel
from app.log import adopt_pywebview_logger, configure_logging
from app.mapping.review import MappingService
from app.notion.client import DEFAULT_NOTION_URL, NOTION_URL_ENV_VAR, NotionReader
from app.notion.connection import ConnectionService
from app.notion.credentials import CredentialStore
from app.notion.service_client import DEFAULT_SERVICE_URL, SERVICE_URL_ENV_VAR, TokenServiceClient
from app.notion.tokens import TokenManager
from app.paths import AppPaths, resource_root, ui_dist_dir
from app.rawlog.service import RawLogService
from app.single_instance import SingleInstance, bring_existing_window_to_front
from app.stats.service import StatsService
from app.sync.engine import SyncService

logger = logging.getLogger(__name__)

WINDOW_SIZE: Final = (1280, 820)
WINDOW_MIN_SIZE: Final = (960, 640)
#: How long the built UI may take to report ready before the window shows an error instead.
#: Dev mode has no watchdog: Vite's error overlay and the inspector show what went wrong, and
#: replacing the page would stop hot reload from recovering once the code is fixed.
UI_READY_TIMEOUT_S: Final = 15.0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="habit-tracker", description=APP_NAME)
    parser.add_argument(
        "--dev", action="store_true", help="load the Vite dev server with hot reload"
    )
    parser.add_argument(
        "--dev-url",
        default=DEFAULT_DEV_URL,
        help=f"dev server address (default {DEFAULT_DEV_URL})",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="show diagnostic tools in the UI (always on in dev mode)",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="start up without opening a window, print a JSON report, and exit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


@dataclass(slots=True)
class Startup:
    """What the window should show, and what must be cleaned up when it closes."""

    url: str | None
    error: ErrorReport | None
    database: Database | None
    dev_server: ViteDevServer | None

    def close(self) -> None:
        if self.dev_server is not None:
            self.dev_server.stop()
        if self.database is not None:
            self.database.close()


def built_ui_url() -> str:
    index = ui_dist_dir() / "index.html"
    if not index.is_file():
        raise AppError(
            "The app's interface files are missing.",
            detail=f"{index} wasn't found. From the project folder run: npm --prefix ui run build",
        )
    return index.as_uri()


def start_dev_ui(dev_url: str) -> ViteDevServer | None:
    if getattr(sys, "frozen", False):
        raise AppError("Dev mode is only available when running from source.")
    return ensure_dev_server(resource_root() / "ui", dev_url)


def prepare(args: argparse.Namespace, paths: AppPaths) -> Startup:
    """Open the database and find the UI. Failures become an error report, not an exception."""
    startup = Startup(url=None, error=None, database=None, dev_server=None)
    try:
        startup.database = open_database(paths.database)
        if args.dev:
            startup.dev_server = start_dev_ui(args.dev_url)
            startup.url = args.dev_url
        else:
            startup.url = built_ui_url()
    except Exception as exc:  # noqa: BLE001 - shown in the window instead of crashing
        startup.error = report_exception(exc, context="startup")
        startup.url = None
    return startup


def self_check(args: argparse.Namespace, paths: AppPaths, log_file: Path) -> int:
    startup = prepare(args, paths)
    try:
        import webview  # noqa: F401 - only checking that the GUI library imports

        report: dict[str, Any] = {
            "ok": startup.error is None,
            "version": __version__,
            "mode": "dev" if args.dev else "normal",
            "python": platform.python_version(),
            "data_dir": str(paths.root),
            "database": str(paths.database),
            "schema_version": startup.database.schema_version if startup.database else None,
            "log_file": str(log_file),
            "ui_url": startup.url,
            "error": startup.error.to_dict() if startup.error else None,
        }
    finally:
        startup.close()
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["ok"] else 1


class UiReadyWatchdog:
    """Shows the error page if the UI loads but never reports ready (a blank window)."""

    def __init__(self, timeout_s: float, on_timeout: Callable[[], None]) -> None:
        self._timeout_s = timeout_s
        self._on_timeout = on_timeout
        self._ready = threading.Event()
        self._armed = False
        self._lock = threading.Lock()

    def page_loading(self) -> None:
        with self._lock:
            self._ready.clear()

    def page_loaded(self) -> None:
        with self._lock:
            if self._armed:
                return
            self._armed = True
        threading.Thread(target=self._watch, name="ui-ready-watchdog", daemon=True).start()

    def ui_ready(self) -> None:
        self._ready.set()

    def _watch(self) -> None:
        try:
            if not self._ready.wait(self._timeout_s):
                self._on_timeout()
        finally:
            with self._lock:
                self._armed = False


def build_services(
    paths: AppPaths, database: Database, events: EventChannel
) -> tuple[ConnectionService, MappingService, SyncService, StatsService, RawLogService]:
    """Wire the Notion connection (Credential Manager, token service, reader and settings), the
    column mapping, the sync engine, the dashboard and the raw log, which share its reader and
    settings."""
    service = TokenServiceClient(os.environ.get(SERVICE_URL_ENV_VAR) or DEFAULT_SERVICE_URL)
    notion_url = os.environ.get(NOTION_URL_ENV_VAR) or DEFAULT_NOTION_URL
    tokens = TokenManager(CredentialStore.for_paths(paths), service)
    settings = Settings(database.connection)

    def make_reader(manager: TokenManager) -> NotionReader:
        return NotionReader(manager, base_url=notion_url)

    reader = make_reader(tokens)
    connection = ConnectionService(
        tokens=tokens,
        reader=reader,
        service=service,
        settings=settings,
        db=database.connection,
        emit=events.emit,
        make_reader=make_reader,
    )
    mapping = MappingService(tokens=tokens, reader=reader, settings=settings)
    sync = SyncService(
        tokens=tokens,
        reader=reader,
        settings=settings,
        db=database.connection,
        database_path=database.path,
        emit=events.emit,
    )
    stats = StatsService(db=database.connection, settings=settings)
    rawlog = RawLogService(db=database.connection, settings=settings)
    return connection, mapping, sync, stats, rawlog


def save_dialog(window: Any) -> Callable[[str], str | None]:  # noqa: ANN401 - a pywebview Window
    """The native Windows Save dialog for CSV files; returns the chosen path or None."""

    def choose(suggested: str) -> str | None:
        import webview

        result = window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=suggested,
            file_types=("CSV file (*.csv)", "All files (*.*)"),
        )
        if not result:
            return None
        return result if isinstance(result, str) else str(result[0])

    return choose


def run_window(
    args: argparse.Namespace,
    paths: AppPaths,
    *,
    automation: Callable[[Any], None] | None = None,
) -> int:
    """Open the window and block until it closes.

    ``automation`` runs on a background thread once the GUI loop starts, with the window as its
    argument. Only the end-to-end tests use it, to drive the real UI.
    """
    import webview

    adopt_pywebview_logger(debug=args.dev)
    mode: Mode = "dev" if args.dev else "normal"
    events = EventChannel()
    startup = prepare(args, paths)
    connection, mapping, sync, stats, rawlog = (
        build_services(paths, startup.database, events)
        if startup.database
        else (None, None, None, None, None)
    )
    context = AppContext(
        mode=mode,
        paths=paths,
        database=startup.database,
        events=events,
        diagnostics=args.dev or args.diagnostics,
        connection=connection,
        mapping=mapping,
        sync=sync,
        stats=stats,
        rawlog=rawlog,
    )
    install_excepthooks(lambda report: events.emit("app:error", report.to_dict()))

    def error_html(report: ErrorReport, title: str) -> str:
        return render_error_page(report, title=title, log_dir=paths.logs_dir)

    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    window = webview.create_window(
        APP_NAME,
        url=startup.url,
        html=error_html(startup.error, f"{APP_NAME} couldn't start") if startup.error else None,
        js_api=Api(context),
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=WINDOW_MIN_SIZE,
    )
    if window is None:  # pragma: no cover - only when an `initialized` handler cancels it
        startup.close()
        return 1
    context.window = window
    context.choose_save_path = save_dialog(window)
    events.attach(window)

    showing_ui = startup.error is None

    def on_ui_timeout() -> None:
        nonlocal showing_ui
        report = report_exception(
            AppError(
                "The app's interface didn't finish loading.",
                detail="The page loaded, but the interface never reported that it was ready.",
            ),
            context="loading the interface",
        )
        showing_ui = False
        window.load_html(error_html(report, "Something went wrong"))

    watchdog = UiReadyWatchdog(UI_READY_TIMEOUT_S, on_ui_timeout)
    context.on_ui_ready = watchdog.ui_ready

    def on_before_load() -> None:
        events.mark_loading()
        watchdog.page_loading()

    def on_loaded() -> None:
        if showing_ui and mode == "normal":
            watchdog.page_loaded()

    window.events.before_load += on_before_load
    window.events.loaded += on_loaded

    logger.info("Opening the window (%s mode)", mode)
    try:
        if automation is None:
            webview.start(debug=args.dev, private_mode=True)
        else:
            webview.start(automation, (window,), debug=args.dev, private_mode=True)
    finally:
        startup.close()
        logger.info("Window closed")
    return 0


def show_fatal_message(message: str) -> None:
    """Last resort when the window itself can't be shown."""
    if sys.platform == "win32":
        import ctypes

        mb_iconerror = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, mb_iconerror)
    else:  # pragma: no cover - the app targets Windows
        sys.stderr.write(message + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = AppPaths.resolve()
    try:
        paths.ensure()
        log_file = configure_logging(paths.logs_dir, debug=args.dev, console=args.dev)
    except OSError as exc:
        show_fatal_message(
            f"{APP_NAME} couldn't create its data folder:\n{paths.root}\n\n{exc.strerror or exc}"
        )
        return 1

    logger.info(
        "%s %s starting (Python %s, %s mode)",
        APP_NAME,
        __version__,
        platform.python_version(),
        "dev" if args.dev else "normal",
    )
    logger.info("Data folder: %s", paths.root)

    if args.self_check:
        return self_check(args, paths, log_file)

    with SingleInstance(paths.instance_lock_name) as instance:
        if instance.already_running:
            logger.info("Habit Tracker is already running; bringing its window to the front")
            if not bring_existing_window_to_front(APP_NAME):
                show_fatal_message(f"{APP_NAME} is already running.")
            return 0
        try:
            return run_window(args, paths)
        except Exception as exc:  # noqa: BLE001 - last resort: explain instead of vanishing
            report = report_exception(exc, context="the window")
            show_fatal_message(
                f"{APP_NAME} couldn't open its window.\n\n{report.detail or report.message}\n\n"
                f"Error ID {report.id}. Details are in the log folder:\n{paths.logs_dir}\n\n"
                "If this keeps happening, check that the Microsoft Edge WebView2 Runtime is "
                "installed."
            )
            return 1


if __name__ == "__main__":
    sys.exit(main())
