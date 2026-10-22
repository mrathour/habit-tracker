"""The WebView2 startup check (PLAN.md 13)."""

from __future__ import annotations

import sys

import pytest

from app import main
from app.webview2 import (
    DOTNET_URL,
    WEBVIEW2_URL,
    Hive,
    RegistryReader,
    RuntimeCheck,
    check_runtime,
    missing_runtime_help,
    parse_version,
    read_registry,
    webview2_version,
)

RUNTIME = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
CANARY = "{65C35B14-6C1D-4122-AC46-7148CC9D6497}"
MACHINE_64 = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{RUNTIME}"
MACHINE_32 = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{RUNTIME}"
USER = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{RUNTIME}"
REMOVED = ".".join("0000")  # an uninstalled runtime
DOTNET = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"


def registry(values: dict[tuple[Hive, str, str], object]) -> RegistryReader:
    def read(hive: Hive, path: str, name: str) -> object:
        return values.get((hive, path, name))

    return read


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("130.0.2849.80", (130, 0, 2849, 80)),
        (" 86.0.622.0 ", (86, 0, 622, 0)),
        (REMOVED, None),  # what an uninstall leaves behind
        ("", None),
        ("abc", None),
        (None, None),
        (130, None),
    ],
)
def test_parse_version(text: object, expected: tuple[int, ...] | None) -> None:
    assert parse_version(text) == expected


def test_per_machine_runtime_on_64_bit() -> None:
    read = registry({("HKEY_LOCAL_MACHINE", MACHINE_64, "pv"): "130.0.2849.80"})
    assert webview2_version(read, machine="AMD64") == "130.0.2849.80"
    # The 64-bit key layout isn't used on 32-bit Windows.
    assert webview2_version(read, machine="x86") is None


def test_per_machine_runtime_on_32_bit() -> None:
    read = registry({("HKEY_LOCAL_MACHINE", MACHINE_32, "pv"): "120.0.1.2"})
    assert webview2_version(read, machine="x86") == "120.0.1.2"


def test_per_user_runtime() -> None:
    """A non-administrator install of the runtime (the installer's bootstrapper, per user)."""
    read = registry({("HKEY_CURRENT_USER", USER, "pv"): "131.0.1.1"})
    assert webview2_version(read, machine="AMD64") == "131.0.1.1"


def test_newest_of_several_wins() -> None:
    read = registry(
        {
            ("HKEY_LOCAL_MACHINE", MACHINE_64, "pv"): "120.0.1.2",
            ("HKEY_CURRENT_USER", USER, "pv"): "131.0.1.1",
            (
                "HKEY_CURRENT_USER",
                rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{CANARY}",
                "pv",
            ): "133.0.0.1",
        }
    )
    assert webview2_version(read, machine="AMD64") == "133.0.0.1"


@pytest.mark.parametrize("value", [REMOVED, "85.0.1.1", None, "garbage"])
def test_removed_or_too_old_runtime(value: object) -> None:
    read = registry({("HKEY_LOCAL_MACHINE", MACHINE_64, "pv"): value})
    assert webview2_version(read, machine="AMD64") is None


def test_dotnet_requirement() -> None:
    base: dict[tuple[Hive, str, str], object] = {
        ("HKEY_LOCAL_MACHINE", MACHINE_64, "pv"): "130.0.1.1"
    }
    assert check_runtime(registry(base)).ok is False  # no .NET key at all
    old = {**base, ("HKEY_LOCAL_MACHINE", DOTNET, "Release"): 394801}
    assert check_runtime(registry(old)).ok is False
    good = {**base, ("HKEY_LOCAL_MACHINE", DOTNET, "Release"): 528040}
    assert check_runtime(registry(good)) == RuntimeCheck("130.0.1.1", dotnet_ok=True)


def test_help_names_what_is_missing() -> None:
    message, url = missing_runtime_help(RuntimeCheck(None, dotnet_ok=True), "Habit Tracker")
    assert "WebView2 Runtime" in message
    assert url == WEBVIEW2_URL
    message, url = missing_runtime_help(RuntimeCheck("130.0.1.1", dotnet_ok=False), "HT")
    assert ".NET Framework 4.6.2" in message
    assert url == DOTNET_URL


@pytest.mark.skipif(sys.platform != "win32", reason="reads the Windows registry")
def test_this_machine_has_the_runtime() -> None:
    """The dev PC and CI runners have WebView2; the real registry reader finds it."""
    assert check_runtime().ok is True
    assert read_registry("HKEY_CURRENT_USER", r"SOFTWARE\No\Such\Key", "pv") is None


# --- At startup ---------------------------------------------------------------------------


def test_missing_runtime_explains_and_offers_the_download(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    opened: list[str] = []
    monkeypatch.setattr(main, "check_runtime", lambda: RuntimeCheck(None, dotnet_ok=True))

    def answer_yes(message: str) -> bool:
        asked.append(message)
        return True

    monkeypatch.setattr(main, "ask_yes_no", answer_yes)
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.setattr(main, "run_window", lambda *_a, **_k: pytest.fail("window opened"))
    assert main.main([]) == 1
    assert "WebView2 Runtime" in asked[0]
    assert opened == [WEBVIEW2_URL]


def test_declining_the_download_opens_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(main, "check_runtime", lambda: RuntimeCheck(None, dotnet_ok=True))
    monkeypatch.setattr(main, "ask_yes_no", lambda _message: False)
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert main.main([]) == 1
    assert opened == []


def test_self_check_does_not_need_the_window(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(main, "check_runtime", lambda: pytest.fail("checked WebView2"))
    main.main(["--self-check"])
    assert '"version"' in capsys.readouterr().out
