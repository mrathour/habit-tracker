"""Write THIRD_PARTY_NOTICES.txt: the licenses of everything the installer ships besides our code.

The installer puts it, with Habit Tracker's own LICENSE, next to HabitTracker.exe. MIT, BSD and
Apache-2.0 all require their license text to travel with copies of the software, and a
PyInstaller build carries the Python runtime, every runtime package and the bundled UI. So the
file covers:

* the Python runtime (PSF License) and PyInstaller's bootloader (GPL with an exception that
  allows any license for the built app);
* every Python package Habit Tracker needs at run time on this platform, found by walking its
  requirements from the installed metadata;
* every npm package in the UI bundle: the production packages in ``ui/package-lock.json``;
* Microsoft's WebView2 bootstrapper, which the installer runs but doesn't install.

Run by ``packaging/build.ps1`` (``uv run --group build``)::

    uv run --group build python packaging/third_party_notices.py build/THIRD_PARTY_NOTICES.txt

It refuses to write the file if a package has no license text and declares no license.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "habit-tracker"
LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT)", re.IGNORECASE)
RULE = "=" * 78


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    version: str
    license: str
    source: str
    texts: tuple[tuple[str, str], ...]  # (file name, text)

    def render(self) -> str:
        declared = self.license or "see the license text below"
        lines = [RULE, f"{self.name} {self.version}".rstrip(), f"License: {declared}"]
        if self.source:
            lines.append(f"Source: {self.source}")
        lines.append(RULE)
        if self.texts:
            for file_name, text in self.texts:
                lines += ["", f"--- {file_name} ---", "", text.strip()]
        else:
            lines += [
                "",
                f"This package ships no license file. Its metadata declares the {self.license}.",
            ]
        return "\n".join(lines) + "\n"


class NoticeError(RuntimeError):
    """A component has no license text and declares no license."""


# --- Python ------------------------------------------------------------------------------------


def runtime_distributions(root: str = PROJECT) -> list[metadata.Distribution]:
    """Every installed distribution the project needs at run time here, without the project."""
    seen: dict[str, metadata.Distribution] = {}
    queue = [canonicalize_name(root)]
    while queue:
        name = queue.pop()
        dist = metadata.distribution(name)
        for spec in dist.requires or []:
            requirement = Requirement(spec)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            child = canonicalize_name(requirement.name)
            if child not in seen and child != canonicalize_name(root):
                try:
                    seen[child] = metadata.distribution(child)
                except metadata.PackageNotFoundError as exc:
                    raise NoticeError(f"{child} is required but not installed") from exc
                queue.append(child)
    return sorted(seen.values(), key=lambda d: canonicalize_name(d.metadata["Name"]))


def declared_license(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expression = md.get("License-Expression")
    if expression:
        return str(expression)
    classifiers = [
        c.split(" :: ")[-1] for c in md.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    if classifiers:
        return ", ".join(classifiers)
    text = (md.get("License") or "").strip()
    return text.splitlines()[0] if text else ""


def python_component(dist: metadata.Distribution) -> Component:
    texts = []
    for file in sorted(dist.files or [], key=str):
        if LICENSE_FILE.search(file.name) and "dist-info" in str(file):
            texts.append(
                (file.name, Path(str(dist.locate_file(file))).read_text("utf-8", "replace"))
            )
    md = dist.metadata
    source = next(
        (u.split(", ", 1)[-1] for u in md.get_all("Project-URL") or [] if "source" in u.lower()),
        md.get("Home-page") or "",
    )
    return Component(
        str(md["Name"]),
        dist.version,
        declared_license(dist),
        str(source),
        tuple(texts),
    )


def python_runtime() -> Component:
    license_txt = Path(sys.base_prefix) / "LICENSE.txt"
    if not license_txt.exists():
        raise NoticeError(f"the Python runtime's license isn't at {license_txt}")
    version = ".".join(map(str, sys.version_info[:3]))
    return Component(
        "Python",
        version,
        "Python Software Foundation License",
        "https://www.python.org/",
        (("LICENSE.txt", license_txt.read_text("utf-8", "replace")),),
    )


def pyinstaller_bootloader() -> Component:
    dist = metadata.distribution("pyinstaller")
    component = python_component(dist)
    return Component(
        "PyInstaller bootloader",
        dist.version,
        "GPL-2.0-or-later WITH the PyInstaller bootloader exception, which allows the built "
        "app to be distributed under any license",
        "https://github.com/pyinstaller/pyinstaller",
        component.texts,
    )


# --- The UI bundle -----------------------------------------------------------------------------


def ui_packages(ui: Path | None = None) -> Iterator[Component]:
    ui = ui or ROOT / "ui"
    lock = json.loads((ui / "package-lock.json").read_text("utf-8"))
    for path, entry in sorted(lock["packages"].items()):
        if not path.startswith("node_modules/") or entry.get("dev") or entry.get("devOptional"):
            continue
        folder = ui / path
        manifest = json.loads((folder / "package.json").read_text("utf-8"))
        files = sorted(f for f in folder.iterdir() if f.is_file() and LICENSE_FILE.search(f.name))
        bundled = folder / "licenses"  # ECharts keeps third-party licenses here
        if bundled.is_dir():
            files += [f for f in sorted(bundled.rglob("*")) if f.is_file()]
        repository = manifest.get("repository")
        source = repository.get("url", "") if isinstance(repository, dict) else repository or ""
        yield Component(
            manifest["name"],
            manifest.get("version", ""),
            str(manifest.get("license") or ""),
            str(source),
            tuple(
                (str(f.relative_to(folder)).replace("\\", "/"), f.read_text("utf-8", "replace"))
                for f in files
            ),
        )


# --- The file ----------------------------------------------------------------------------------

HEADER = """\
Third-party software in Habit Tracker
{rule}

Habit Tracker is distributed under the MIT License (LICENSE.txt). The installed app also
contains the software below, each under its own license, whose texts follow.

The app folder also holds Microsoft's Visual C++ runtime (VCRUNTIME140.dll and
VCRUNTIME140_1.dll), which comes with Python and is redistributable under Microsoft's Visual
Studio license terms.

The installer also runs Microsoft's Edge WebView2 Runtime bootstrapper
(MicrosoftEdgeWebview2Setup.exe) when the runtime is missing. It is Microsoft software,
distributed under Microsoft's WebView2 distribution terms
(https://developer.microsoft.com/microsoft-edge/webview2/), and is not installed with
Habit Tracker.

"""


def build_notices(*, include_bootloader: bool = True) -> str:
    components = [python_runtime()]
    if include_bootloader:
        components.append(pyinstaller_bootloader())
    components += [python_component(dist) for dist in runtime_distributions()]
    components += list(ui_packages())
    missing = [f"{c.name} {c.version}" for c in components if not c.texts and not c.license]
    if missing:
        raise NoticeError("no license found for: " + ", ".join(missing))
    sections = "\n".join(c.render() for c in components)
    return HEADER.format(rule=RULE) + sections


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: third_party_notices.py <output file>\n")
        return 2
    target = Path(argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_notices(), encoding="utf-8", newline="\r\n")
    sys.stdout.write(f"Wrote {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
