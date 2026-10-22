"""Writing the raw log to a CSV file (PLAN.md 8).

* **Excel-friendly:** UTF-8 with a BOM (so Excel reads non-English text correctly), CRLF line
  ends, and every field quoted when it holds a comma, quote or line break.
* **No formulas:** text a spreadsheet would run as a formula (starting with ``=``, ``+``, ``-``,
  ``@``, a tab or a carriage return) is prefixed with ``'``. Numbers and dates the app writes
  itself are left alone, so "-5" stays a number.
* **All or nothing:** the file is written next to the target under a temporary name and then
  moved into place, so a failed save never leaves a half-written file or damages the old one.
"""

from __future__ import annotations

import contextlib
import csv
import re
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.errors import AppError

ENCODING: Final = "utf-8-sig"
FORMULA_START: Final = ("=", "+", "-", "@", "\t", "\r")
#: Characters Windows doesn't allow in file names, and control characters.
_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ExportError(AppError):
    state = "export_failed"


@dataclass(frozen=True, slots=True)
class Cell:
    text: str
    #: A number or date the app wrote: never prefixed (see the module docstring).
    formula_safe: bool = False


def guard(cell: Cell) -> str:
    if not cell.formula_safe and cell.text.startswith(FORMULA_START):
        return "'" + cell.text
    return cell.text


def write_csv(target: Path, header: Sequence[str], rows: Iterable[Sequence[Cell]]) -> int:
    """Write the file and return the number of data rows. Raises :class:`ExportError`."""
    target = target.resolve()
    written = 0
    temp: Path | None = None
    try:
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed below, then moved
            mode="w",
            encoding=ENCODING,
            newline="",
            dir=target.parent,
            prefix=f".{target.stem[:40]}-",
            suffix=".tmp",
            delete=False,
        )
        temp = Path(handle.name)
        with handle:
            writer = csv.writer(handle, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
            writer.writerow([guard(Cell(name)) for name in header])
            for row in rows:
                writer.writerow([guard(cell) for cell in row])
                written += 1
        temp.replace(target)
        temp = None
    except PermissionError as exc:
        raise ExportError(
            f"“{target.name}” couldn't be saved. It may be open in another program, such as "
            "Excel, or you may not be allowed to save in that folder. Close the file or choose "
            "another place, then try again.",
            detail=f"{target}: {exc.strerror or exc}",
        ) from exc
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ExportError(
            f"“{target.name}” couldn't be saved: {reason}.", detail=f"{target}: {exc}"
        ) from exc
    finally:
        if temp is not None:
            with contextlib.suppress(OSError):
                temp.unlink()
    return written


def safe_file_name(name: str) -> str:
    """``name`` with characters Windows doesn't allow replaced, ending in ``.csv``."""
    cleaned = _UNSAFE_NAME.sub("-", name).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned) or "Raw log"
    return cleaned if cleaned.lower().endswith(".csv") else f"{cleaned}.csv"
