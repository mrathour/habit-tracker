from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.paths import HOME_ENV_VAR, AppPaths
from app.redaction import clear_registered_secrets


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Keep every test away from the real %APPDATA% folder and from each other's state."""
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path / "home"))
    clear_registered_secrets()
    yield
    clear_registered_secrets()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_habit_tracker", False):
            root.removeHandler(handler)
            handler.close()


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths(tmp_path / "home")
    paths.ensure()
    return paths
