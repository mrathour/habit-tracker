"""Locations of everything the app stores on disk.

All user data lives under ``%APPDATA%\\HabitTracker\\`` so it survives reinstalls (PLAN.md 13).
Settings are rows in the database's ``settings`` table (PLAN.md 11), not a separate file.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "HabitTracker"
DATABASE_FILE_NAME = "habit_tracker.db"
LOG_DIR_NAME = "logs"

#: Overrides the data folder. Used by tests and for running a throwaway copy of the app.
HOME_ENV_VAR = "HABIT_TRACKER_HOME"


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path

    @property
    def database(self) -> Path:
        return self.root / DATABASE_FILE_NAME

    @property
    def logs_dir(self) -> Path:
        return self.root / LOG_DIR_NAME

    @classmethod
    def resolve(cls, environ: os._Environ[str] | dict[str, str] | None = None) -> AppPaths:
        env = os.environ if environ is None else environ
        override = env.get(HOME_ENV_VAR)
        if override:
            return cls(Path(override).expanduser().resolve())
        appdata = env.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return cls(base / APP_DIR_NAME)

    def ensure(self) -> None:
        """Create the data and log folders if they don't exist yet."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


def resource_root() -> Path:
    """The folder that holds bundled read-only resources such as ``ui/dist``.

    In a PyInstaller build that is the extraction folder; from source it is the repository root.
    """
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent


def ui_dist_dir() -> Path:
    return resource_root() / "ui" / "dist"
