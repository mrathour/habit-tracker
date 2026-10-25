"""THIRD_PARTY_NOTICES.txt for the installer (packaging/third_party_notices.py, PLAN.md 13).

The Python side runs against this environment's installed metadata. The UI side uses a small
node_modules tree here, because CI's Python job doesn't install the UI's packages; the
installer job runs the real thing through packaging/build.ps1.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "packaging" / "third_party_notices.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("third_party_notices", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["third_party_notices"] = module
    spec.loader.exec_module(module)
    return module


notices = load()


def package(root: Path, path: str, manifest: dict[str, Any], files: dict[str, str]) -> None:
    folder = root / path
    folder.mkdir(parents=True)
    (folder / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, text in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


@pytest.fixture
def ui(tmp_path: Path) -> Path:
    """A UI folder: two production packages (one nested, one with a licenses/ folder) and a
    development-only one."""
    root = tmp_path / "ui"
    lock = {
        "packages": {
            "": {"name": "habit-tracker-ui"},
            "node_modules/charts": {"version": "6.1.0"},
            "node_modules/charts/node_modules/tslib": {"version": "2.3.0"},
            "node_modules/vitest": {"version": "4.0.0", "dev": True},
        }
    }
    root.mkdir()
    (root / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    package(
        root,
        "node_modules/charts",
        {
            "name": "charts",
            "version": "6.1.0",
            "license": "Apache-2.0",
            "repository": {"url": "git+https://example.test/charts.git"},
        },
        {
            "LICENSE": "Apache License text",
            "NOTICE": "Charts notice",
            "licenses/LICENSE-d3": "d3 BSD text",
        },
    )
    package(
        root,
        "node_modules/charts/node_modules/tslib",
        {"name": "tslib", "version": "2.3.0", "license": "0BSD"},
        {"LICENSE.txt": "0BSD text"},
    )
    package(root, "node_modules/vitest", {"name": "vitest", "version": "4.0.0"}, {})
    return root


# --- Python -------------------------------------------------------------------------------------


def test_runtime_packages_are_the_apps_not_the_tools() -> None:
    names = {d.metadata["Name"].lower().replace("_", "-") for d in notices.runtime_distributions()}
    assert {"pywebview", "keyring", "notion-client", "cryptography", "tzdata", "httpx"} <= names
    assert not names & {"pytest", "mypy", "ruff", "pyinstaller", "pre-commit", "habit-tracker"}
    # Platform markers are honoured: macOS and Linux back ends are left out on Windows.
    if sys.platform == "win32":
        assert not any(n.startswith("pyobjc") for n in names)
        assert "pythonnet" in names


def test_every_runtime_package_has_a_license() -> None:
    for dist in notices.runtime_distributions():
        component = notices.python_component(dist)
        assert component.texts or component.license, component.name


def test_a_package_without_a_license_file_still_says_what_it_declares() -> None:
    component = notices.Component("tool", "1.0", "MIT License", "", ())
    assert "ships no license file. Its metadata declares the MIT License." in component.render()


def test_the_python_runtime_is_covered() -> None:
    runtime = notices.python_runtime()
    assert runtime.license == "Python Software Foundation License"
    assert "PYTHON SOFTWARE FOUNDATION LICENSE" in runtime.texts[0][1].upper()


# --- The UI bundle ------------------------------------------------------------------------------


def test_ui_packages_are_the_production_ones_with_every_license_file(ui: Path) -> None:
    found = {c.name: c for c in notices.ui_packages(ui)}
    assert set(found) == {"charts", "tslib"}
    charts = found["charts"]
    assert charts.license == "Apache-2.0"
    assert charts.source == "git+https://example.test/charts.git"
    assert [name for name, _ in charts.texts] == ["LICENSE", "NOTICE", "licenses/LICENSE-d3"]
    assert found["tslib"].texts == (("LICENSE.txt", "0BSD text"),)


# --- The file -----------------------------------------------------------------------------------


def test_the_file_lists_everything(ui: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notices, "ROOT", ui.parent)
    text = notices.build_notices(include_bootloader=False)
    assert text.startswith("Third-party software in Habit Tracker")
    assert "MIT License (LICENSE.txt)" in text
    assert "VCRUNTIME140.dll" in text
    assert "MicrosoftEdgeWebview2Setup.exe" in text
    for name in ("Python 3.", "pywebview", "keyring", "charts 6.1.0", "tslib 2.3.0"):
        assert name in text
    assert "d3 BSD text" in text


def test_a_package_with_no_license_at_all_stops_the_build(
    ui: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package(ui, "node_modules/mystery", {"name": "mystery", "version": "1.0.0"}, {})
    lock = json.loads((ui / "package-lock.json").read_text(encoding="utf-8"))
    lock["packages"]["node_modules/mystery"] = {"version": "1.0.0"}
    (ui / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(notices, "ROOT", ui.parent)
    with pytest.raises(notices.NoticeError, match=r"mystery 1\.0\.0"):
        notices.build_notices(include_bootloader=False)


def test_main_writes_the_file(tmp_path: Path, ui: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        notices, "build_notices", lambda: notices.HEADER.format(rule=notices.RULE) + "body\n"
    )
    target = tmp_path / "out" / "THIRD_PARTY_NOTICES.txt"
    assert notices.main(["third_party_notices.py", str(target)]) == 0
    raw = target.read_bytes()
    assert raw.startswith(b"Third-party software in Habit Tracker\r\n")
    assert notices.main(["third_party_notices.py"]) == 2
