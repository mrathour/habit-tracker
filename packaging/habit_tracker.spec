# PyInstaller build of Habit Tracker: one folder, windowed (PLAN.md 13).
#
# Run through packaging/build.ps1, which builds the UI first. By hand, from the repository root:
#     uv run --group build pyinstaller packaging/habit_tracker.spec --noconfirm
#
# HABIT_TRACKER_POLICY_FILE (build time only) bundles another policy file in place of
# app/policy.json, for the "newer policy" test build (packaging/test-policy.json). It never
# changes how a built app behaves at run time.

import os
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
VERSION = PROJECT["version"]
APP_NAME = "Habit Tracker"
EXE_NAME = "HabitTracker"

ui_index = ROOT / "ui" / "dist" / "index.html"
if not ui_index.is_file():
    raise SystemExit(f"{ui_index} is missing: run `npm --prefix ui run build` first.")

policy_file = Path(os.environ.get("HABIT_TRACKER_POLICY_FILE") or ROOT / "app" / "policy.json")
if not policy_file.is_file():
    raise SystemExit(f"Policy file not found: {policy_file}")
print(f"Bundling privacy policy file {policy_file}")

datas = [
    (str(ui_index), "ui/dist"),
    (str(ROOT / "app" / "db" / "migrations" / "*.sql"), "app/db/migrations"),
    (str(policy_file), "app"),
    *copy_metadata("habit-tracker"),  # __version__ comes from the package metadata
    # pywebview's injected scripts and its WebView2 DLLs; the Android library isn't needed.
    *[d for d in collect_data_files("webview") if not d[0].endswith(".jar")],
]
if policy_file.name != "policy.json":
    # Bundled under the name the app reads.
    staged = Path(workpath) / "policy" / "policy.json"  # noqa: F821 - provided by PyInstaller
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(policy_file.read_bytes())
    datas[2] = (str(staged), "app")

numbers = tuple(int(part) for part in VERSION.split(".")[:3]) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Mayank Rathour"),
                        StringStruct("FileDescription", APP_NAME),
                        StringStruct("FileVersion", VERSION),
                        StringStruct("InternalName", EXE_NAME),
                        StringStruct("LegalCopyright", "© 2026 Mayank Rathour"),
                        StringStruct("OriginalFilename", f"{EXE_NAME}.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["webview.platforms.winforms", "webview.platforms.edgechromium"],
    excludes=["tkinter", "pytest", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    icon=str(ROOT / "packaging" / "icon" / "app-icon.ico"),
    version=version_info,
    console=False,
    # UPX-packed files are a common antivirus false positive (PLAN.md 13).
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name=EXE_NAME,
)
