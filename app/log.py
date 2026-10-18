"""Logging setup: rotating UTC log files under ``%APPDATA%\\HabitTracker\\logs``.

Every handler formats through :class:`RedactingFormatter`, which masks tokens and secrets in
the final text, including exception tracebacks and values passed as arguments.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import Final, override

from app.redaction import redact

LOG_FILE_NAME: Final = "habit-tracker.log"
MAX_LOG_BYTES: Final = 2 * 1024 * 1024
LOG_BACKUP_COUNT: Final = 5

_FORMAT: Final = "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"

# Third-party loggers that are noisy at DEBUG or may echo request details.
_QUIET_LOGGERS: Final = ("urllib3", "httpx", "httpcore", "notion_client", "bottle")


class RedactingFormatter(logging.Formatter):
    """Formats records with UTC ISO 8601 timestamps and masks secrets in the result."""

    def __init__(self, fmt: str = _FORMAT) -> None:
        super().__init__(fmt)

    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
        return f"{stamp}.{int(record.msecs):03d}Z"

    @override
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(logs_dir: Path, *, debug: bool = False, console: bool = False) -> Path:
    """Send all log output to a rotating file in ``logs_dir`` and return the file's path.

    Calling it again replaces the handlers it installed earlier, so tests can point it at a
    temporary folder.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / LOG_FILE_NAME
    formatter = RedactingFormatter()

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_habit_tracker", False):
            root.removeHandler(handler)
            handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handlers: list[logging.Handler] = [file_handler]
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(formatter)
        handler._habit_tracker = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    adopt_pywebview_logger(debug=debug)

    logging.captureWarnings(True)
    return log_file


def adopt_pywebview_logger(*, debug: bool = False) -> None:
    """Send pywebview's log output through our handlers.

    pywebview adds its own unredacted console handler when it is first imported, so this runs
    again right after that import.
    """
    pywebview_logger = logging.getLogger("pywebview")
    for handler in list(pywebview_logger.handlers):
        pywebview_logger.removeHandler(handler)
        handler.close()
    pywebview_logger.propagate = True
    pywebview_logger.setLevel(logging.DEBUG if debug else logging.INFO)
