"""Draw the Habit Tracker icon (512x512 PNG) with only the standard library.

Regenerate: uv run python -I service/scripts/make_icon.py service/pages/icon.png
"""

import struct
import sys
import zlib
from pathlib import Path

N = 512
BG = (47, 111, 94)  # --accent
FG = (255, 255, 255)
RADIUS = 104


def inside_rounded(x, y):
    cx = min(max(x, RADIUS), N - 1 - RADIUS)
    cy = min(max(y, RADIUS), N - 1 - RADIUS)
    return (x - cx) ** 2 + (y - cy) ** 2 <= RADIUS**2


# Five bars rising left to right, like a streak of daily totals.
bars = []
width, gap, left, base = 52, 22, 82, 392
for i, h in enumerate([96, 152, 120, 208, 272]):
    x0 = left + i * (width + gap)
    bars.append((x0, base - h, x0 + width, base))


def in_bar(x, y):
    for x0, y0, x1, y1 in bars:
        if x0 <= x < x1 and y0 <= y < y1:
            # round the top corners of each bar
            r = width // 2
            if y < y0 + r:
                cx = min(max(x, x0 + r), x1 - 1 - r)
                return (x - cx) ** 2 + (y - (y0 + r)) ** 2 <= r * r
            return True
    return False


rows = bytearray()
for y in range(N):
    rows.append(0)
    for x in range(N):
        if not inside_rounded(x, y):
            rows += bytes((0, 0, 0, 0))
        elif in_bar(x, y):
            rows += bytes((*FG, 255))
        else:
            rows += bytes((*BG, 255))


def chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    + chunk(b"IEND", b"")
)
Path(sys.argv[1]).write_bytes(png)
