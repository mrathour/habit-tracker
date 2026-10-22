from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest

from app.paths import HOME_ENV_VAR, AppPaths
from app.redaction import clear_registered_secrets
from tests.support.memory_keyring import MemoryKeyring


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Keep every test away from the real %APPDATA% folder and from each other's state."""
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path / "home"))
    clear_registered_secrets()
    # Never touch the real Windows Credential Manager.
    MemoryKeyring.reset()
    previous_keyring = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())  # type: ignore[no-untyped-call]
    yield
    keyring.set_keyring(previous_keyring)
    MemoryKeyring.reset()
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
