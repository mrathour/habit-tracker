"""Is the Microsoft Edge WebView2 Runtime installed? (PLAN.md 10, 13)

The installer installs the runtime if it is missing, but it can be removed later. Without it,
pywebview quietly falls back to Internet Explorer's engine, which can't run the app's interface,
so the app checks first and explains instead.

The check mirrors pywebview's own (``webview/platforms/winforms.py``): the runtime's version in
the EdgeUpdate registry keys, per user and per machine, and .NET Framework 4.6.2 or later, which
pywebview's Windows back end needs.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

#: EdgeUpdate client IDs: the Evergreen runtime, then the Beta, Dev and Canary channels, which
#: pywebview also accepts.
WEBVIEW2_CLIENT_IDS: Final = (
    "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
    "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
    "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",
    "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",
)
#: The oldest runtime pywebview supports.
MIN_WEBVIEW2: Final = (86, 0, 622, 0)
#: .NET Framework 4.6.2 (the ``Release`` value).
MIN_DOTNET_RELEASE: Final = 394802
WEBVIEW2_URL: Final = "https://developer.microsoft.com/microsoft-edge/webview2/"
DOTNET_URL: Final = "https://dotnet.microsoft.com/download/dotnet-framework"

Hive = Literal["HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"]
#: Reads one registry value: (hive, key path, value name) -> value, or None if absent.
RegistryReader = Callable[[Hive, str, str], object]


@dataclass(frozen=True, slots=True)
class RuntimeCheck:
    webview2_version: str | None
    dotnet_ok: bool

    @property
    def ok(self) -> bool:
        return self.webview2_version is not None and self.dotnet_ok


def read_registry(hive: Hive, path: str, name: str) -> object:
    if sys.platform != "win32":  # pragma: no cover - the app targets Windows
        return None
    import winreg

    try:
        with winreg.OpenKey(getattr(winreg, hive), path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def parse_version(text: object) -> tuple[int, ...] | None:
    if not isinstance(text, str):
        return None
    try:
        parts = tuple(int(part) for part in text.strip().split("."))
    except ValueError:
        return None
    return parts if parts and any(parts) else None  # "0.0.0.0" means removed


def webview2_version(
    read: RegistryReader = read_registry, *, machine: str | None = None
) -> str | None:
    """The newest usable WebView2 runtime version, or None."""
    is_x86 = (machine or platform.machine()).lower() == "x86"
    best: tuple[int, ...] | None = None
    for client in WEBVIEW2_CLIENT_IDS:
        locations: list[tuple[Hive, str]] = [
            ("HKEY_CURRENT_USER", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client}"),
            (
                "HKEY_LOCAL_MACHINE",
                rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client}"
                if is_x86
                else rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{client}",
            ),
        ]
        for hive, path in locations:
            version = parse_version(read(hive, path, "pv"))
            if version is not None and version >= MIN_WEBVIEW2:
                best = max(best or version, version)
    return ".".join(str(part) for part in best) if best else None


def dotnet_ok(read: RegistryReader = read_registry) -> bool:
    release = read(
        "HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "Release"
    )
    return isinstance(release, int) and release >= MIN_DOTNET_RELEASE


def check_runtime(read: RegistryReader = read_registry) -> RuntimeCheck:
    return RuntimeCheck(webview2_version=webview2_version(read), dotnet_ok=dotnet_ok(read))


def missing_runtime_help(check: RuntimeCheck, app_name: str) -> tuple[str, str]:
    """What to tell the user, and the Microsoft page that helps (opened only if they agree)."""
    if check.webview2_version is None:
        return (
            f"{app_name} needs the Microsoft Edge WebView2 Runtime to show its window, and it "
            "isn't installed on this PC.\n\n"
            "It's free from Microsoft. Choose Yes to open Microsoft's download page, install the "
            f"Evergreen Runtime, then open {app_name} again. Running the {app_name} installer "
            "again also installs it.",
            WEBVIEW2_URL,
        )
    return (
        f"{app_name} needs Microsoft .NET Framework 4.6.2 or later, which is part of Windows 10 "
        "and 11 but is missing on this PC.\n\n"
        "Choose Yes to open Microsoft's download page, install .NET Framework, then open "
        f"{app_name} again.",
        DOTNET_URL,
    )
