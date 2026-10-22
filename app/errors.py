"""Error types and the reports shown to the user when something goes wrong.

Every error that reaches the user carries a short ID that also appears in the log, so a report
like "error 3f9c2a1b" can be matched to its traceback.
"""

from __future__ import annotations

import logging
import secrets
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from types import TracebackType
from typing import Literal

from app.redaction import redact

logger = logging.getLogger(__name__)

ErrorKind = Literal["expected", "unexpected"]

UNEXPECTED_MESSAGE = "Something went wrong. The details have been saved to the log."


class AppError(Exception):
    """An error with a message written for the user.

    Raise it for failures the app anticipates (a missing file, a database from a newer version);
    anything else is treated as unexpected and reported with a generic message.
    """

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.user_message = message
        self.detail = detail

    #: A machine-readable state the UI can switch on. Subclasses override it.
    state: str | None = None


@dataclass(frozen=True, slots=True)
class ErrorReport:
    id: str
    kind: ErrorKind
    message: str
    detail: str | None
    #: A machine-readable state for the UI, such as "reconnect" or "offline" (AppError.state).
    code: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def new_error_id() -> str:
    return secrets.token_hex(4)


def describe_exception(exc: BaseException) -> str:
    """A one-line, redacted ``Type: message`` description of ``exc``."""
    text = str(exc).strip()
    name = type(exc).__name__
    return redact(f"{name}: {text}" if text else name)


def report_exception(exc: BaseException, *, context: str) -> ErrorReport:
    """Log ``exc`` with a fresh error ID and build the report the user will see."""
    error_id = new_error_id()
    if isinstance(exc, AppError):
        logger.warning(
            "%s failed [error %s]: %s", context, error_id, exc.user_message, exc_info=exc
        )
        detail = redact(exc.detail) if exc.detail else None
        return ErrorReport(error_id, "expected", redact(exc.user_message), detail, exc.state)
    logger.error("Unexpected error in %s [error %s]", context, error_id, exc_info=exc)
    return ErrorReport(error_id, "unexpected", UNEXPECTED_MESSAGE, describe_exception(exc))


ErrorListener = Callable[[ErrorReport], None]


def install_excepthooks(listener: ErrorListener) -> None:
    """Log uncaught exceptions on any thread and pass a report to ``listener``.

    The listener forwards the report to the window, so a failure in a background thread shows a
    message instead of disappearing silently.
    """

    def notify(exc: BaseException, context: str) -> None:
        report = report_exception(exc, context=context)
        try:
            listener(report)
        except Exception:
            logger.exception("Could not deliver error %s to the window", report.id)

    def main_hook(
        exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        notify(exc.with_traceback(tb), "the main thread")

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None or issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread else "unknown"
        notify(args.exc_value.with_traceback(args.exc_traceback), f"thread {name!r}")

    sys.excepthook = main_hook
    threading.excepthook = thread_hook
