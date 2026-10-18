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
    assert results["badge"].startswith("Normal mode")
    assert results["csp"] is not None
    assert "script-src 'sha256-" in results["csp"]
    assert "unsafe-eval" not in results["csp"]
    check_ui_results(results, log)


@pytest.mark.skipif(
    not (REPO_ROOT / "ui" / "node_modules" / "vite").is_dir(), reason="UI packages not installed"
)
def test_dev_mode(tmp_path: Path) -> None:
    results, log = run_harness(tmp_path, "ui", "--dev")
    assert results["badge"].startswith("Dev mode")
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
