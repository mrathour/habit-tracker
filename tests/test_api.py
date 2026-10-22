from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app import api as api_module
from app.api import Api, AppContext
from app.db import Database, open_database
from app.events import EventChannel
from app.paths import AppPaths

PUBLIC_METHODS = {
    "get_app_info",
    "ui_ready",
    "run_bridge_check",
    "log_client_error",
    "open_log_folder",
    "raise_test_error",
    "quit",
    "get_connection",
    "connect_with_token",
    "start_sign_in",
    "cancel_sign_in",
    "logout",
    "list_data_sources",
    "choose_data_source",
    "get_mapping_review",
    "save_mapping",
    "get_sync_status",
    "start_sync",
    "get_flagged_entries",
    "resolve_pending_removal",
    "get_dashboard",
    "get_day_detail",
    "get_preferences",
    "set_preferences",
    "open_external",
}


class RecordingChannel(EventChannel):
    def __init__(self) -> None:
        super().__init__()
        self.emitted: list[tuple[str, Any]] = []
        self.ready_calls = 0
        self.done = threading.Event()

    def emit(self, name: str, payload: object = None) -> None:
        self.emitted.append((name, payload))
        if name.endswith(":done"):
            self.done.set()

    def mark_ready(self) -> None:
        self.ready_calls += 1


class FakeWindow:
    destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


@pytest.fixture
def database(app_paths: AppPaths) -> Iterator[Database]:
    db = open_database(app_paths.database)
    yield db
    db.close()


@pytest.fixture
def channel() -> RecordingChannel:
    return RecordingChannel()


def make_api(
    app_paths: AppPaths, channel: EventChannel, database: Database | None, **kw: Any
) -> tuple[Api, AppContext]:
    context = AppContext(mode="normal", paths=app_paths, database=database, events=channel, **kw)
    return Api(context), context


def test_only_bridge_methods_are_exposed(app_paths: AppPaths, channel: RecordingChannel) -> None:
    # pywebview exposes every public attribute, recursing into objects (webview/util.py).
    api, _ = make_api(app_paths, channel, None)
    public = {name for name in dir(api) if not name.startswith("_")}
    assert public == PUBLIC_METHODS
    for name in public:
        assert inspect.ismethod(getattr(api, name))


def test_get_app_info(app_paths: AppPaths, channel: RecordingChannel, database: Database) -> None:
    api, _ = make_api(app_paths, channel, database, diagnostics=True)
    response = api.get_app_info()
    assert response["ok"] is True
    info = response["data"]  # type: ignore[typeddict-item]
    assert info["name"] == "Habit Tracker"
    assert info["mode"] == "normal"
    assert info["diagnostics"] is True
    assert info["schema_version"] == database.schema_version
    assert info["data_dir"] == str(app_paths.root)
    assert info["started_at"].endswith("Z")
    assert info["pywebview_version"] not in ("", "unknown")


def test_get_app_info_without_a_database(app_paths: AppPaths, channel: RecordingChannel) -> None:
    api, _ = make_api(app_paths, channel, None)
    assert api.get_app_info()["data"]["schema_version"] == 0  # type: ignore[typeddict-item]


def test_ui_ready_marks_channel_and_calls_back(
    app_paths: AppPaths, channel: RecordingChannel
) -> None:
    called: list[bool] = []
    api, _ = make_api(app_paths, channel, None, on_ui_ready=lambda: called.append(True))
    assert api.ui_ready() == {"ok": True, "data": None}
    assert channel.ready_calls == 1
    assert called == [True]


def test_bridge_check_pushes_progress_from_a_worker_thread(
    app_paths: AppPaths, channel: RecordingChannel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "BRIDGE_CHECK_INTERVAL_S", 0)
    api, _ = make_api(app_paths, channel, None)
    response = api.run_bridge_check(3)
    assert response["ok"] is True
    run_id = response["data"]["run_id"]  # type: ignore[typeddict-item]
    assert channel.done.wait(5)

    names = [name for name, _ in channel.emitted]
    assert names == ["bridge-check:progress"] * 3 + ["bridge-check:done"]
    steps = [payload["step"] for name, payload in channel.emitted if name.endswith("progress")]
    assert steps == [1, 2, 3]
    assert all(payload["run_id"] == run_id for _, payload in channel.emitted)
    assert channel.emitted[0][1]["thread"] == f"bridge-check-{run_id}"
    assert channel.emitted[0][1]["thread"] != threading.current_thread().name


@pytest.mark.parametrize("steps", [0, 21, -1, "5", 2.5, True, None])
def test_bridge_check_rejects_bad_steps(
    app_paths: AppPaths, channel: RecordingChannel, steps: object
) -> None:
    api, _ = make_api(app_paths, channel, None)
    response = api.run_bridge_check(steps)
    assert response["ok"] is False
    assert response["error"]["kind"] == "expected"  # type: ignore[typeddict-item]


def test_only_one_bridge_check_at_a_time(
    app_paths: AppPaths, channel: RecordingChannel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "BRIDGE_CHECK_INTERVAL_S", 0.05)
    api, _ = make_api(app_paths, channel, None)
    assert api.run_bridge_check(5)["ok"] is True
    second = api.run_bridge_check(5)
    assert second["ok"] is False
    assert "already running" in str(second["error"]["message"])  # type: ignore[typeddict-item]
    assert channel.done.wait(5)
    time.sleep(0.05)
    assert api.run_bridge_check(1)["ok"] is True


def test_client_errors_are_logged_with_an_id(
    app_paths: AppPaths, channel: RecordingChannel, caplog: pytest.LogCaptureFixture
) -> None:
    api, _ = make_api(app_paths, channel, None)
    response = api.log_client_error(
        {"source": "render", "message": "Boom", "stack": "at X", "componentStack": "in App"}
    )
    error_id = response["data"]["id"]  # type: ignore[typeddict-item]
    assert f"UI error (render) [error {error_id}]: Boom" in caplog.text
    assert "at X" in caplog.text
    assert "in App" in caplog.text


def test_client_errors_tolerate_odd_input(
    app_paths: AppPaths, channel: RecordingChannel, caplog: pytest.LogCaptureFixture
) -> None:
    api, _ = make_api(app_paths, channel, None)
    assert api.log_client_error("just a string")["ok"] is True
    assert api.log_client_error(None)["ok"] is True
    huge = api.log_client_error({"message": "m", "stack": "s" * 50_000})
    assert huge["ok"] is True
    assert "s" * 8001 not in caplog.text


def test_open_log_folder(app_paths: AppPaths, channel: RecordingChannel) -> None:
    opened: list[Path] = []
    api, _ = make_api(app_paths, channel, None, open_folder=opened.append)
    assert api.open_log_folder()["ok"] is True
    assert opened == [app_paths.logs_dir]


def test_test_errors_need_diagnostics(app_paths: AppPaths, channel: RecordingChannel) -> None:
    api, _ = make_api(app_paths, channel, None)
    response = api.raise_test_error("call")
    assert response["ok"] is False
    assert response["error"]["kind"] == "expected"  # type: ignore[typeddict-item]


def test_test_errors_with_diagnostics(app_paths: AppPaths, channel: RecordingChannel) -> None:
    api, _ = make_api(app_paths, channel, None, diagnostics=True)
    call = api.raise_test_error("call")
    assert call["ok"] is False
    assert call["error"]["kind"] == "unexpected"  # type: ignore[typeddict-item]
    unknown = api.raise_test_error("elsewhere")
    assert unknown["error"]["kind"] == "expected"  # type: ignore[typeddict-item]

    failures: list[BaseException | None] = []
    original = threading.excepthook
    threading.excepthook = lambda args: failures.append(args.exc_value)
    try:
        assert api.raise_test_error("thread")["ok"] is True
        deadline = time.monotonic() + 5
        while not failures and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        threading.excepthook = original
    assert isinstance(failures[0], RuntimeError)


def test_quit_destroys_the_window(app_paths: AppPaths, channel: RecordingChannel) -> None:
    api, context = make_api(app_paths, channel, None)
    assert api.quit()["ok"] is True  # no window yet: nothing to do
    window = FakeWindow()
    context.window = window
    api.quit()
    assert window.destroyed


def test_connection_methods_need_a_started_app(
    app_paths: AppPaths, channel: RecordingChannel
) -> None:
    api, _ = make_api(app_paths, channel, None)
    response = api.get_connection()
    assert response["ok"] is False
    assert "didn't start" in str(response["error"]["message"])  # type: ignore[typeddict-item]


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://habit-tracker.mrathour.workers.dev/support", True),
        ("https://www.notion.so/my-page", True),
        ("https://developers.notion.com/docs", True),
        ("http://www.notion.so/insecure", False),
        ("https://evil.example/phish", False),
        ("https://notion.so.evil.example/", False),
        ("javascript:alert(1)", False),
        ("file:///C:/Windows", False),
        (42, False),
    ],
)
def test_open_external_only_opens_known_https_sites(
    app_paths: AppPaths, channel: RecordingChannel, url: object, allowed: bool
) -> None:
    opened: list[str] = []
    api, _ = make_api(app_paths, channel, None, open_url=opened.append)
    response = api.open_external(url)
    assert response["ok"] is allowed
    assert opened == ([url] if allowed else [])
