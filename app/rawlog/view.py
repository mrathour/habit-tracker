"""The raw log's remembered sort, column widths and hidden columns (PLAN.md 8, 11).

Kept in the ``raw_log_view`` setting. A damaged part falls back to its default on its own, so a
bad width never loses the sort. Columns that no longer exist are kept in the setting (they may
come back with another mapping) and are ignored by the table.
"""

from __future__ import annotations

from typing import Final, Literal, TypedDict, cast

from app.db.settings import Settings
from app.errors import AppError

VIEW_KEY: Final = "raw_log_view"
MIN_WIDTH: Final = 48
MAX_WIDTH: Final = 1200
MAX_COLUMNS: Final = 300
MAX_KEY_LENGTH: Final = 200

Direction = Literal["asc", "desc"]


class RawLogError(AppError):
    state = "invalid_request"


class SortSpec(TypedDict):
    column: str
    direction: Direction


class ViewPrefs(TypedDict):
    sort: SortSpec
    widths: dict[str, int]
    hidden: list[str]


DEFAULT_SORT: Final[SortSpec] = {"column": "start", "direction": "desc"}


def read(settings: Settings) -> ViewPrefs:
    stored = settings.get(VIEW_KEY)
    value = stored if isinstance(stored, dict) else {}
    try:
        sort = parse_sort(value.get("sort"))
    except RawLogError:
        sort = dict(DEFAULT_SORT)  # type: ignore[assignment]
    try:
        widths = _widths(value.get("widths", {}))
    except RawLogError:
        widths = {}
    try:
        hidden = _hidden(value.get("hidden", []))
    except RawLogError:
        hidden = []
    return {"sort": sort, "widths": widths, "hidden": hidden}


def update(settings: Settings, changes: object) -> ViewPrefs:
    """Replace the parts named in ``changes`` (``sort``, ``widths``, ``hidden``)."""
    if not isinstance(changes, dict) or not changes:
        raise RawLogError("The raw log's view settings were sent in an unexpected form.")
    unknown = set(changes) - {"sort", "widths", "hidden"}
    if unknown:
        raise RawLogError("Unknown raw log view setting.", detail=", ".join(sorted(unknown)))
    prefs = read(settings)
    if "sort" in changes:
        prefs["sort"] = parse_sort(changes["sort"])
    if "widths" in changes:
        prefs["widths"] = _widths(changes["widths"])
    if "hidden" in changes:
        prefs["hidden"] = _hidden(changes["hidden"])
    settings.set(VIEW_KEY, prefs)
    return prefs


def parse_sort(value: object) -> SortSpec:
    if not isinstance(value, dict):
        raise RawLogError("The sort order was sent in an unexpected form.")
    column = value.get("column")
    direction = value.get("direction")
    if not _is_key(column) or direction not in ("asc", "desc"):
        raise RawLogError("The sort order was sent in an unexpected form.")
    return {"column": cast(str, column), "direction": cast(Direction, direction)}


def _widths(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or len(value) > MAX_COLUMNS:
        raise RawLogError("The column widths were sent in an unexpected form.")
    widths: dict[str, int] = {}
    for key, width in value.items():
        if not _is_key(key) or not isinstance(width, int | float) or isinstance(width, bool):
            raise RawLogError("The column widths were sent in an unexpected form.")
        widths[key] = int(min(MAX_WIDTH, max(MIN_WIDTH, round(width))))
    return widths


def _hidden(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_COLUMNS:
        raise RawLogError("The hidden columns were sent in an unexpected form.")
    hidden: list[str] = []
    for key in value:
        if not _is_key(key):
            raise RawLogError("The hidden columns were sent in an unexpected form.")
        if key not in hidden:
            hidden.append(key)
    return hidden


def _is_key(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_KEY_LENGTH
