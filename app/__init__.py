"""Habit Tracker back end."""

from importlib.metadata import PackageNotFoundError, version

APP_NAME = "Habit Tracker"

try:
    __version__ = version("habit-tracker")
except PackageNotFoundError:  # pragma: no cover - only when run from an unpackaged copy
    __version__ = "0.0.0+unknown"
