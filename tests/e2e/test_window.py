"""End-to-end checks that open the real window (marker ``gui``).

Excluded from the default run; run them with ``uv run pytest -m gui``. They need WebView2 and a
built UI (``npm --prefix ui run build``); the dev-mode test also needs ``ui/node_modules`` and
port 5173 free.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.paths import HOME_ENV_VAR, ui_dist_dir

pytestmark = pytest.mark.gui

HARNESS = Path(__file__).with_name("window_check.py")
REPO_ROOT = Path(__file__).resolve().parents[2]


def run_harness(tmp_path: Path, scenario: str, *flags: str) -> tuple[dict[str, Any], str]:
    home = tmp_path / "home"
    out = tmp_path / "results.json"
    env = {**os.environ, HOME_ENV_VAR: str(home)}
    completed = subprocess.run(  # noqa: S603 - fixed command
        [sys.executable, str(HARNESS), str(out), scenario, *flags],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    results: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    log = (home / "logs" / "habit-tracker.log").read_text(encoding="utf-8")
    assert "failure" not in results, results["failure"]
    assert results["finished"] is True
    assert results["exit_code"] == 0
    return results, log


def check_ui_results(results: dict[str, Any], log: str) -> None:
    # The UI called a Python method and showed its result.
    assert "Python\n3.12" in results["facts"]
    assert "schema version 1" in results["facts"]

    # Python pushed progress events from a background thread, all received in order.
    events = results["events"]
    assert len(events) == 6
    assert "bridge-check:done" in events[0]
    assert all(f"step {n} of 5" in e for n, e in zip(range(5, 0, -1), events[1:], strict=True))
    assert all("bridge-check-" in e for e in events[1:])

    # Each kind of error produced a readable banner with an error ID, and was logged.
    banners = results["banners"]
    assert len(banners) == 4
    assert all("Error ID" in b for b in banners)
    assert any("Test error raised inside a bridge call" in b for b in banners)
    assert any("Test error raised in a background thread" in b for b in banners)
    assert any("Test promise rejection" in b for b in banners)
    assert any("Test error thrown from a timer" in b for b in banners)
    assert "Something went wrong" in results["fatal"]
    assert "Error ID" in results["fatal"]
    for text in (
        "Unexpected error in bridge call raise_test_error()",
        "Unexpected error in thread 'test-error'",
        "UI error (promise)",
        "UI error (window)",
        "UI error (render)",
        "The UI reported ready",
    ):
        assert text in log


@pytest.mark.skipif(not (ui_dist_dir() / "index.html").is_file(), reason="UI not built")
def test_normal_mode(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "ui")
    assert results["dev_flag"] is None
    assert results["csp"] is not None
    assert "script-src 'sha256-" in results["csp"]
    assert "unsafe-eval" not in results["csp"]
    check_ui_results(results, log)


@pytest.mark.skipif(
    not (REPO_ROOT / "ui" / "node_modules" / "vite").is_dir(), reason="UI packages not installed"
)
def test_dev_mode(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "ui", "--dev")
    assert results["dev_flag"] == "Dev mode"
    assert results["csp"] is None
    check_ui_results(results, log)
    assert "Vite dev server is ready" in log or "already running" in log


def test_startup_failure_shows_an_error_page(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "startup-error")
    assert results["title"] == "Habit Tracker couldn't start"
    assert "damaged" in results["text"]
    assert "Error ID" in results["text"]
    assert "Open log folder" in results["text"]
    assert results["detail"]
    assert "habit_tracker.db" in results["detail"]
    assert "startup failed" in log


def test_blank_window_is_replaced_by_an_error_page(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "blank-ui")
    assert results["title"] == "Something went wrong"
    assert "didn't finish loading" in results["text"]
    assert "Error ID" in results["text"]
    assert "loading the interface failed" in log


SERVICE_READY = (REPO_ROOT / "service" / "node_modules" / "wrangler").is_dir()


@pytest.mark.skipif(not (ui_dist_dir() / "index.html").is_file(), reason="UI not built")
def test_connect_with_a_personal_access_token(tmp_path: Path) -> None:
    # Criterion (a), against a fake Notion: connect, pick the work log, log out, reconnect.
    results, log = run_harness(tmp_path, "connect-token")
    assert "Work Log (test)" in results["first_picker"]
    assert "Reading has 2 data sources" in results["first_picker"]
    assert "Mayank's personal access token" in results["first_topbar"]
    assert results["first_mapping_end"] == "End Time · Date"
    assert "connected and reads Work Log (test)" in results["first_home"]
    assert results["first_keyring"] == 1
    assert "Connected with a personal access token" in results["first_settings"]
    assert "revoke it under Personal access tokens" in results["first_summary"]
    assert "kept on this computer" in results["first_summary"]
    assert results["first_keyring_after_logout"] == 0
    # Reconnecting keeps the database choice; clearing local data forgets it.
    assert "connected and reads Work Log (test)" in results["again_home"]
    assert results["again_keyring"] == 1
    assert "were deleted" in results["cleared_summary"]
    assert results["cleared_keyring_after_logout"] == 0
    assert results["after_clear"] == "picker"
    assert "Connected to Notion with a pasted pat token" in log
    assert "ntn_" not in log


@pytest.mark.skipif(not SERVICE_READY, reason="service/node_modules not installed")
def test_connect_to_notion_through_the_token_service(tmp_path: Path) -> None:
    # The full OAuth chain: app -> local Worker -> fake Notion -> Worker -> loopback listener.
    results, log = run_harness(tmp_path, "connect-oauth")
    pages = results["browser_pages"]
    assert pages[-1]["status"] == 200
    assert "Connected to Notion" in pages[-1]["text"]
    assert pages[-1]["url"].startswith("http://127.0.0.1:")
    assert "E2E Workspace" in results["oauth_topbar"]
    assert "Connected with Notion sign-in" in results["oauth_settings"]
    assert results["oauth_keyring"] == 1
    assert "Notion cancelled Habit Tracker's access" in results["oauth_summary"]
    assert results["oauth_keyring_after_logout"] == 0
    assert results["valid_tokens_remaining"] == 0  # revoke reached Notion
    assert "Connected to Notion through OAuth" in log
    assert "ntn_" not in log
    assert "nrt_" not in log


@pytest.mark.skipif(not SERVICE_READY, reason="service/node_modules not installed")
def test_declining_in_notion_is_reported_at_once(tmp_path: Path) -> None:
    results, _log = run_harness(tmp_path, "connect-oauth-deny")
    assert "Access wasn't allowed" in results["notice"]
    assert "Sign-in cancelled" in results["browser_pages"][-1]["text"]
    assert results["keyring"] == 0


@pytest.mark.skipif(not (ui_dist_dir() / "index.html").is_file(), reason="UI not built")
def test_column_mapping(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "mapping")
    # No end-time column: the exact explanation, and saving is blocked.
    row = results["no_end_row"]
    assert "Your database needs a second Date column to use as the end time." in row
    assert "choose “End of the date range in “Start Time”” for End time." in row
    assert "End time:" in results["no_end_blockers"]
    assert results["no_end_save_disabled"] is True
    # The Work Log maps with no changes, and shows its real values.
    assert results["fields"] == {
        "start": "Start Time · Date",
        "end": "End Time · Date",
        "task_name": "Name · Title",
        "parent_task": "Parent Task · Relation",
        "display_id": "ID · ID",
        "logged_minutes": "MinuteSpent · Number",
    }
    assert results["samples"]["logged_minutes"].split() == ["37", "128", "2"]
    assert results["samples"]["display_id"].split() == ["8", "7", "6"]
    assert "Writing EVA resume" in results["samples"]["task_name"]
    assert "1 linked page" in results["samples"]["parent_task"]
    assert "2026" in results["samples"]["start"]
    assert "Column mapping saved." in results["saved_home"]
    # Changing the saved mapping records that a full sync is required.
    assert "Mapping saved: a full sync is needed" in results["changed_home"]
    assert "Full sync required" in results["settings"]
    assert "Saved the column mapping (changed; full sync required)" in log
    assert "ntn_" not in log
