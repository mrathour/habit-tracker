from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from html import escape
from pathlib import Path

import pytest

from app.bridge import bridge_method
from app.error_page import render_error_page
from app.errors import (
    UNEXPECTED_MESSAGE,
    AppError,
    ErrorReport,
    describe_exception,
    install_excepthooks,
    report_exception,
)


@pytest.fixture
def restore_hooks() -> Iterator[None]:
    saved = (sys.excepthook, threading.excepthook)
    yield
    sys.excepthook, threading.excepthook = saved


def test_expected_errors_keep_their_message(caplog: pytest.LogCaptureFixture) -> None:
    report = report_exception(AppError("Shown to the user", detail="more"), context="testing")
    assert report.kind == "expected"
    assert report.message == "Shown to the user"
    assert report.detail == "more"
    assert report.id in caplog.text
    assert len(report.id) == 8


def test_unexpected_errors_get_a_generic_message(caplog: pytest.LogCaptureFixture) -> None:
    report = report_exception(KeyError("missing"), context="testing")
    assert report.kind == "unexpected"
    assert report.message == UNEXPECTED_MESSAGE
    assert report.detail == "KeyError: 'missing'"
    assert f"[error {report.id}]" in caplog.text
    assert "Traceback" in caplog.text or caplog.records[-1].exc_info is not None


def test_reports_are_redacted() -> None:
    token = "secret_" + "x" * 40
    report = report_exception(RuntimeError(f"bad {token}"), context="testing")
    assert token not in str(report.to_dict())
    expected = report_exception(AppError(f"bad {token}", detail=token), context="testing")
    assert token not in str(expected.to_dict())


def test_describe_exception_without_message() -> None:
    assert describe_exception(ValueError()) == "ValueError"


class _Api:
    @bridge_method
    def works(self, value: int) -> int:
        return value * 2

    @bridge_method
    def fails_expectedly(self) -> None:
        raise AppError("Nope")

    @bridge_method
    def crashes(self) -> None:
        raise ZeroDivisionError("boom")


def test_bridge_method_wraps_results() -> None:
    api = _Api()
    assert api.works(21) == {"ok": True, "data": 42}
    expected = api.fails_expectedly()
    assert expected["ok"] is False
    assert expected["error"]["message"] == "Nope"  # type: ignore[typeddict-item]
    crashed = api.crashes()
    assert crashed["ok"] is False
    assert crashed["error"]["kind"] == "unexpected"  # type: ignore[typeddict-item]
    assert crashed["error"]["detail"] == "ZeroDivisionError: boom"  # type: ignore[typeddict-item]
    assert _Api.works.__name__ == "works"


@pytest.mark.usefixtures("restore_hooks")
def test_thread_exceptions_are_logged_and_forwarded(caplog: pytest.LogCaptureFixture) -> None:
    received: list[ErrorReport] = []
    install_excepthooks(received.append)

    def fail() -> None:
        raise RuntimeError("from a worker")

    worker = threading.Thread(target=fail, name="worker-1")
    worker.start()
    worker.join()

    assert len(received) == 1
    assert received[0].detail == "RuntimeError: from a worker"
    assert "thread 'worker-1'" in caplog.text


@pytest.mark.usefixtures("restore_hooks")
def test_main_thread_hook_and_failing_listener(caplog: pytest.LogCaptureFixture) -> None:
    def broken_listener(report: ErrorReport) -> None:
        raise OSError("window gone")

    install_excepthooks(broken_listener)
    try:
        raise LookupError("uncaught")
    except LookupError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    assert "Could not deliver error" in caplog.text
    assert "uncaught" in caplog.text


@pytest.mark.usefixtures("restore_hooks")
def test_keyboard_interrupt_goes_to_the_default_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[type[BaseException]] = []
    monkeypatch.setattr(sys, "__excepthook__", lambda t, v, tb: seen.append(t))
    received: list[ErrorReport] = []
    install_excepthooks(received.append)
    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert seen == [KeyboardInterrupt]
    assert received == []


def test_error_page_escapes_everything() -> None:
    report = ErrorReport(
        id="<id>",
        kind="unexpected",
        message="<script>alert(1)</script>",
        detail="a & b </textarea>",
    )
    log_dir = Path("C:/logs/<x>")
    html = render_error_page(report, title="Title <b>", log_dir=log_dir)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "a &amp; b &lt;/textarea&gt;" in html
    assert "Title &lt;b&gt;" in html
    assert "&lt;id&gt;" in html
    assert escape(str(log_dir)) in html


def test_error_page_without_detail() -> None:
    report = ErrorReport(id="abc", kind="expected", message="Plain", detail=None)
    html = render_error_page(report, title="T", log_dir=Path("logs"))
    assert 'id="detail"' not in html
    assert "Open log folder" in html
