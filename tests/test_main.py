from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from app import main
from app.errors import AppError
from app.paths import AppPaths


@pytest.fixture
def built_ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>ok</title>", encoding="utf-8")
    monkeypatch.setattr(main, "ui_dist_dir", lambda: dist)
    return dist


@pytest.fixture
def missing_ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "ui_dist_dir", lambda: tmp_path / "no-dist")


def test_parse_args_defaults() -> None:
    args = main.parse_args([])
    assert not args.dev
    assert not args.diagnostics
    assert not args.self_check
    assert args.dev_url == "http://127.0.0.1:5173/"


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main.parse_args(["--version"])
    assert exited.value.code == 0
    assert "habit-tracker" in capsys.readouterr().out


@pytest.mark.usefixtures("missing_ui")
def test_missing_ui_is_an_app_error() -> None:
    with pytest.raises(AppError, match="interface files are missing"):
        main.built_ui_url()


def test_built_ui_is_loaded_over_file_url(built_ui: Path) -> None:
    url = main.built_ui_url()
    assert url.startswith("file:///")
    assert url.endswith("/dist/index.html")


def test_prepare_succeeds(built_ui: Path, app_paths: AppPaths) -> None:
    startup = main.prepare(main.parse_args([]), app_paths)
    try:
        assert startup.error is None
        assert startup.url is not None
        assert startup.database is not None
        assert startup.database.schema_version >= 1
        assert startup.dev_server is None
    finally:
        startup.close()


@pytest.mark.usefixtures("built_ui")
def test_prepare_turns_failures_into_reports(app_paths: AppPaths) -> None:
    app_paths.database.write_bytes(b"garbage" * 500)
    startup = main.prepare(main.parse_args([]), app_paths)
    assert startup.url is None
    assert startup.error is not None
    assert "damaged" in startup.error.message
    startup.close()


def test_dev_mode_refused_in_a_frozen_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(AppError, match="Dev mode"):
        main.start_dev_ui("http://127.0.0.1:5173/")


@pytest.mark.usefixtures("built_ui")
def test_self_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main.main(["--self-check"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["schema_version"] >= 1
    assert report["error"] is None
    home = AppPaths.resolve()
    assert home.database.is_file()
    assert (home.logs_dir / "habit-tracker.log").is_file()


@pytest.mark.usefixtures("missing_ui")
def test_self_check_reports_failures(capsys: pytest.CaptureFixture[str]) -> None:
    assert main.main(["--self-check"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["error"]["kind"] == "expected"
    assert "npm --prefix ui run build" in report["error"]["detail"]


def test_unwritable_data_folder_shows_a_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("HABIT_TRACKER_HOME", str(blocker / "HabitTracker"))
    shown: list[str] = []
    monkeypatch.setattr(main, "show_fatal_message", shown.append)
    assert main.main(["--self-check"]) == 1
    assert "couldn't create its data folder" in shown[0]


def test_window_failure_shows_a_message(monkeypatch: pytest.MonkeyPatch, built_ui: Path) -> None:
    def broken(*_args: object, **_kwargs: object) -> int:
        raise OSError("WebView2 not found")

    shown: list[str] = []
    monkeypatch.setattr(main, "run_window", broken)
    monkeypatch.setattr(main, "check_webview_runtime", lambda: True)
    monkeypatch.setattr(main, "show_fatal_message", shown.append)
    assert main.main([]) == 1
    assert "couldn't open its window" in shown[0]
    assert "WebView2" in shown[0]


def test_watchdog_fires_when_the_ui_never_reports_ready() -> None:
    fired = threading.Event()
    watchdog = main.UiReadyWatchdog(0.05, fired.set)
    watchdog.page_loading()
    watchdog.page_loaded()
    assert fired.wait(2)


def test_watchdog_stays_quiet_when_the_ui_is_ready() -> None:
    fired = threading.Event()
    watchdog = main.UiReadyWatchdog(0.2, fired.set)
    watchdog.page_loading()
    watchdog.page_loaded()
    watchdog.ui_ready()
    time.sleep(0.4)
    assert not fired.is_set()


def test_watchdog_rearms_after_a_reload() -> None:
    fired = threading.Event()
    watchdog = main.UiReadyWatchdog(0.1, fired.set)
    watchdog.page_loading()
    watchdog.page_loaded()
    watchdog.ui_ready()
    time.sleep(0.2)
    watchdog.page_loading()
    watchdog.page_loaded()
    assert fired.wait(2)
