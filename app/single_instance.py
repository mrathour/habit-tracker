"""Only one copy of the app runs per data folder (PLAN.md 10, 12.5).

A Windows named mutex marks the running copy. A second launch brings the existing window to
the front and exits. Because only one copy runs, the in-process refresh lock in
:mod:`app.notion.tokens` covers every caller, so two copies can never renew the same rotating
refresh token at once.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from types import TracebackType
from typing import Final, Self

logger = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS: Final = 183
SW_RESTORE: Final = 9


class SingleInstance:
    """Holds the named mutex while the app runs. Use as a context manager."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._handle: int | None = None
        self.already_running = False

    def acquire(self) -> bool:
        """True if this is the only copy; False if another copy already holds the lock."""
        if sys.platform != "win32":  # pragma: no cover - the app targets Windows
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(error, "CreateMutexW failed")
        self._handle = handle
        self.already_running = error == ERROR_ALREADY_EXISTS
        if self.already_running:
            self.release()
        return not self.already_running

    def release(self) -> None:
        if self._handle is not None and sys.platform == "win32":
            ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(self._handle))
        self._handle = None

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def bring_existing_window_to_front(title: str) -> bool:
    """Restore and focus the running copy's window. True if it was found."""
    if sys.platform != "win32":  # pragma: no cover
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True
