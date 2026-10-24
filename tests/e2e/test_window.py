"""End-to-end checks that open the real window (marker ``gui``).

Excluded from the default run; run them with ``uv run pytest -m gui``. They need WebView2 and a
built UI (``npm --prefix ui run build``); the dev-mode test also needs ``ui/node_modules`` and
port 5173 free.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from app.paths import HOME_ENV_VAR, ui_dist_dir
from tests.support.notion_schemas import BROKEN_EXPECTED, SECOND_TASK, TASK_PAGE

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
    assert "schema version 2" in results["facts"]

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
    # Saving the change starts the full sync it needs, which clears the flag when it finishes.
    assert "Full sync" in results["changed_home"]
    assert "The column mapping changed." in results["changed_home"]
    assert "Full sync required" not in results["settings"]
    assert "Saved the column mapping (changed; full sync required)" in log
    assert "Full sync started (The column mapping changed.)" in log
    assert "ntn_" not in log


@pytest.mark.skipif(not (ui_dist_dir() / "index.html").is_file(), reason="UI not built")
def test_sync_across_launches(tmp_path: Path) -> None:
    import sqlite3

    # First launch: connect, map, and the first (full) sync copies everything.
    first, log = run_harness(tmp_path, "sync-first")
    panel = first["first"]["panel"]
    assert "Full sync" in panel
    assert "10 added · 0 updated · 0 removed" in panel
    assert "First sync of this work log." in panel
    flagged = "\n".join(first["first"]["flagged"])
    assert "Logged 148 min, but Start → End is 123 min." in flagged
    assert "End time is 7 min before Start time." in flagged
    assert "End time is empty." in flagged
    assert "Start time is empty." in flagged
    assert "Start time has a date (2026-10-21) but no time." in flagged
    assert len(first["first"]["flagged"]) == 5
    assert "Full sync finished: 10 added, 0 updated, 0 removed, 5 flagged" in log

    # Second launch, after edits and a deletion in Notion: a quick sync picks up the edits...
    second, log = run_harness(tmp_path, "sync-relaunch")
    relaunch = second["relaunch"]
    assert "Quick sync" in relaunch["panel"]
    assert "0 added · 2 updated · 0 removed" in relaunch["panel"]
    assert any("Mismatch, renamed" in item for item in relaunch["flagged"])
    assert not any("End time is empty." in item for item in relaunch["flagged"])
    assert len(relaunch["flagged"]) == 4
    # ... and only the full sync removes the deleted entry.
    assert "1 removed" in second["full"]["panel"]
    assert "You asked for a full sync." in second["full"]["panel"]

    db = sqlite3.connect(tmp_path / "home" / "habit_tracker.db")
    try:
        ids = {row[0] for row in db.execute("SELECT page_id FROM work_logs")}
        names = dict(db.execute("SELECT page_id, task_name FROM work_logs").fetchall())
    finally:
        db.close()
    assert len(ids) == 9
    assert "p-ok" not in ids
    assert names["p-mismatch"] == "Mismatch, renamed"
    assert "ntn_" not in log


@pytest.mark.skipif(not (ui_dist_dir() / "index.html").is_file(), reason="UI not built")
def test_dashboard_totals_match_hand_calculation(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "dashboard")
    assert results["canvases"] >= 3  # the real charts drew under the strict CSP
    assert results["banners"] == 0
    stats = "\n".join(results["stats"]).lower()  # the labels are uppercased by CSS
    assert "current streak\n3 days" in stats
    assert "through yesterday" in stats
    assert "longest streak\n3 days" in stats
    assert "in this range\n4 h 15 min" in stats
    assert "3 active days of 30" in stats
    rows = results["daily_rows"]
    # Newest first: yesterday, two days ago, three days ago.
    assert [row.split("\t")[1:] for row in rows[:3]] == [
        ["45 min", "1"],
        ["2 h 30 min", "3"],
        ["1 h", "1"],
    ]
    detail = results["detail"]
    assert "2 h 30 min" in detail
    assert "counted from 3 sessions" in detail
    assert "Overlaps Review by 30 min." in detail
    assert "Overlaps Write by 30 min." in detail
    assert "Crosses midnight: split between the days it covers." in detail
    assert "Overlapping time is counted once" in detail
    assert "ntn_" not in log


#: Which cells each stored issue turns red (PLAN.md 5): Invalid range colours Start as well.
def expected_red(issues: list[dict[str, str]]) -> dict[str, str]:
    by_kind: dict[str, list[str]] = {}
    for issue in issues:
        field = issue["field"]
        kinds = [field if not field.startswith("extra:") else "extra"]
        if issue["code"] == "invalid_range":
            kinds.insert(0, "start")
        for kind in kinds:
            by_kind.setdefault(kind, []).append(issue["message"])
    return {kind: "\n".join(messages) for kind, messages in by_kind.items()}


def test_raw_log_flags_every_broken_entry_with_its_explanation(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "rawlog")
    with closing(sqlite3.connect(tmp_path / "home" / "habit_tracker.db")) as db:
        total = db.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0]
        stored = {
            page_id: json.loads(issues)
            for page_id, issues in db.execute(
                "SELECT page_id, issues FROM work_logs WHERE json_array_length(issues) > 0"
            )
        }
    # The dashboard's flagged count opened the raw log filtered to entries with issues.
    assert "Has issues" in results["chips"]
    flagged = {page_id for page_id, codes in BROKEN_EXPECTED.items() if codes}
    assert set(stored) == flagged
    shown = {row["page_id"]: dict(row["red"]) for row in results["rows"]}
    assert set(shown) == flagged
    for page_id, issues in stored.items():
        assert sorted(issue["code"] for issue in issues) == sorted(BROKEN_EXPECTED[page_id])
        assert shown[page_id] == expected_red(issues), page_id
    assert results["tooltip"] == "Logged 148 min, but Start → End is 123 min."
    # A click selects without opening; a double-click opens that entry.
    assert results["opened_after_click"] == []
    assert results["opened_after_double_click"] == ["https://www.notion.so/pmismatch"]
    # The export saved exactly the rows on screen, as UTF-8 with a BOM.
    assert f"Exported {len(flagged)} entries" in results["export_notice"]
    assert results["csv_bom"] is True
    rows = list(csv.reader(io.StringIO(results["csv"], newline="")))
    assert rows[0][2].startswith("Start (")
    assert len(rows) == len(flagged) + 1
    assert "Logged 148 min, but Start → End is 123 min." in {row[-1] for row in rows[1:]}
    # Clearing the filters shows every entry again.
    assert results["all_status"].startswith(f"{total} entries")
    assert "ntn_" not in log


def test_parent_task_maps_once_its_database_is_shared_and_opens_in_notion(
    tmp_path: Path,
) -> None:
    """Issue #12, with the real Work Log's schema: Notion hides "Parent Task" until the Task
    Tracker is shared, the mapping says how to share it, and once mapped its links open."""
    results, log = run_harness(tmp_path, "parent-task")
    # Unshared: the column is hidden, the field explains how to share the Task Tracker.
    assert results["parent_before"] == "Not used"
    assert "Share the linked database to use parent task link" in results["share_help"]
    assert "Notion is hiding the relation column “Parent Task”" in results["share_help"]
    assert "••• → Connections" in results["share_help"]
    # Shared, then Check again: mapped automatically.
    assert results["parent_after"] == "Parent Task · Relation"
    assert results["share_help_after"] is False
    with closing(sqlite3.connect(tmp_path / "home" / "habit_tracker.db")) as db:
        links = dict(db.execute("SELECT page_id, parent_task_ids FROM work_logs"))
    assert {k: json.loads(v) for k, v in links.items()} == {
        "parent-a": [TASK_PAGE],
        "parent-b": [TASK_PAGE, SECOND_TASK],
    }
    task, second = (f"https://www.notion.so/{p.replace('-', '')}" for p in (TASK_PAGE, SECOND_TASK))
    # The raw log's Parent task cell, then both links in the day detail.
    assert results["raw_cell"].startswith("Parent task")  # then its "⋯" filter chip
    assert results["opened_from_raw_log"] == [task]
    assert "Parent task" in results["detail"]
    assert "Linked page 2" in results["detail"]
    assert results["opened"] == [task, task, second]
    assert "ntn_" not in log
