"""Build ``app-icon.ico`` and the website icon from ``app-icon.svg`` (PLAN.md 13).

Each size is drawn by Microsoft Edge in headless mode, so small sizes get the browser's own
anti-aliasing, and stored as a PNG image inside the ``.ico`` (supported since Windows Vista).
No extra Python packages are needed. Run it after changing the SVG, and commit both files:

    uv run python packaging/icon/make_icon.py
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVG = HERE / "app-icon.svg"
ICO = HERE / "app-icon.ico"
PNG = HERE / "app-icon.png"
#: The website's icon and the Notion integration's logo (docs/notion-integration.md).
SERVICE_ICON = HERE.parent.parent / "service" / "pages" / "icon.png"
SERVICE_ICON_SIZE = 512
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
EDGE_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Microsoft/Edge/Application/msedge.exe",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def find_edge() -> Path:
    for candidate in EDGE_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("Microsoft Edge wasn't found; it is needed to draw the icon.")


def render(edge: Path, size: int, work: Path) -> bytes:
    page = work / f"icon-{size}.html"
    shot = work / f"icon-{size}.png"
    page.write_text(
        "<!doctype html><html><body style='margin:0;background:transparent'>"
        f"<img src='{SVG.as_uri()}' width='{size}' height='{size}' style='display:block'>"
        "</body></html>",
        encoding="utf-8",
    )
    subprocess.run(  # noqa: S603 - a fixed local executable and arguments
        [
            str(edge),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--default-background-color=00000000",
            f"--user-data-dir={work / 'profile'}",
            f"--window-size={size},{size}",
            f"--screenshot={shot}",
            page.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    data = shot.read_bytes()
    width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
    if not data.startswith(PNG_SIGNATURE) or (width, height, depth, colour) != (size, size, 8, 6):
        raise SystemExit(f"Edge drew an unexpected image for {size}px: {width}x{height}")
    return data


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, data in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(data for _, data in images)


def main() -> int:
    edge = find_edge()
    with tempfile.TemporaryDirectory() as tmp:
        images = [(size, render(edge, size, Path(tmp))) for size in SIZES]
        service_icon = render(edge, SERVICE_ICON_SIZE, Path(tmp))
    ICO.write_bytes(build_ico(images))
    PNG.write_bytes(images[-1][1])
    SERVICE_ICON.write_bytes(service_icon)
    sys.stdout.write(
        f"Wrote {ICO.name} ({', '.join(str(s) for s, _ in images)} px), {PNG.name} "
        f"and {SERVICE_ICON.relative_to(HERE.parent.parent)}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
