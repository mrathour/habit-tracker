from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import paths
from app.paths import HOME_ENV_VAR, AppPaths


def test_defaults_to_appdata_habit_tracker() -> None:
    resolved = AppPaths.resolve({"APPDATA": r"C:\Users\someone\AppData\Roaming"})
    assert resolved.root == Path(r"C:\Users\someone\AppData\Roaming") / "HabitTracker"
    assert resolved.database == resolved.root / "habit_tracker.db"
    assert resolved.logs_dir == resolved.root / "logs"


def test_falls_back_to_roaming_profile_without_appdata() -> None:
    resolved = AppPaths.resolve({})
    assert resolved.root == Path.home() / "AppData" / "Roaming" / "HabitTracker"


def test_env_override(tmp_path: Path) -> None:
    resolved = AppPaths.resolve({HOME_ENV_VAR: str(tmp_path / "x"), "APPDATA": "ignored"})
    assert resolved.root == (tmp_path / "x").resolve()


def test_ensure_creates_folders_and_is_idempotent(tmp_path: Path) -> None:
    app_paths = AppPaths(tmp_path / "nested" / "HabitTracker")
    app_paths.ensure()
    app_paths.ensure()
    assert app_paths.root.is_dir()
    assert app_paths.logs_dir.is_dir()


def test_resource_root_is_repo_root_from_source() -> None:
    assert (paths.resource_root() / "pyproject.toml").is_file()
    assert paths.ui_dist_dir() == paths.resource_root() / "ui" / "dist"


def test_resource_root_in_a_frozen_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.resource_root() == tmp_path
