"""Extra field values in the raw log: what is shown, filtered, sorted and exported (PLAN.md 8).

Values arrive normalised by type (``app/sync/values.py``). Each becomes an :class:`ExtraValue`
holding everything the table needs, so the filters, the sort, the screen and the CSV file all
read the same value. A column's filter follows its Notion type:

=====================================================  ==========================================
Notion type                                            Filter
=====================================================  ==========================================
title, rich_text, url, email, phone_number,            contains
unique_id, place, files
number                                                 min / max
checkbox                                               yes / no
select, status, verification, multi_select             any of the chosen options
date, created_time, last_edited_time                   a range of local dates
people, created_by, last_edited_by, relation           empty or not (names and titles aren't read)
formula                                                by its result: number, text, checkbox, date
rollup                                                 number, date, or contains for a list
=====================================================  ==========================================

Every column can also be filtered on "is empty" and "has a value".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Final, Literal, NotRequired, TypedDict
from zoneinfo import ZoneInfo

from app.sync.store import notion_url

FilterKind = Literal["text", "number", "checkbox", "options", "date", "presence"]

TEXT_TYPES: Final = frozenset(
    {"title", "rich_text", "url", "email", "phone_number", "unique_id", "place", "files"}
)
OPTION_TYPES: Final = frozenset({"select", "status", "verification", "multi_select"})
DATE_TYPES: Final = frozenset({"date", "created_time", "last_edited_time"})
PRESENCE_TYPES: Final = frozenset({"people", "created_by", "last_edited_by", "relation"})

#: How a formula's result type is filtered.
_FORMULA_KINDS: Final[dict[str, FilterKind]] = {
    "number": "number",
    "string": "text",
    "boolean": "checkbox",
    "date": "date",
}

#: Sort keys put values of different shapes in a fixed order, so a column never compares a
#: number with text (a formula's result type can differ between entries).
_NUMBER, _DATE, _FLAG, _TEXT = 0, 1, 2, 3


class MomentCell(TypedDict):
    utc: str | None
    date: str
    has_time: bool


class ExtraCell(TypedDict):
    """What the table shows: text, a date (formatted by the UI in local time) or links."""

    text: str
    start: NotRequired[MomentCell]
    end: NotRequired[MomentCell | None]
    links: NotRequired[list[str]]


@dataclass(frozen=True, slots=True)
class ExtraValue:
    empty: bool
    #: Plain text, used by "contains" (casefolded copy in ``search``).
    text: str = ""
    search: str = ""
    number: float | None = None
    flag: bool | None = None
    options: tuple[str, ...] = ()
    #: The local date (of a range's start), for date filters.
    day: date | None = None
    sort: tuple[int, Any] | None = None
    cell: ExtraCell | None = None
    #: The CSV cell. Dates are local "YYYY-MM-DD HH:MM".
    csv: str = ""
    #: ``csv`` is a number or date the app wrote, so it is never guarded against formulas
    #: (a negative number such as "-5" stays a number).
    formula_safe: bool = False


EMPTY: Final = ExtraValue(empty=True)


def read_extra(kind: str, value: Any, zone: ZoneInfo) -> ExtraValue:  # noqa: ANN401
    """Turn one stored extra value of Notion type ``kind`` into an :class:`ExtraValue`."""
    if value is None:
        return EMPTY
    if kind in ("title", "rich_text", "url", "email", "phone_number", "unique_id"):
        return _text(value) if isinstance(value, str) else EMPTY
    if kind in ("select", "status", "verification"):
        return _options([value]) if isinstance(value, str) else EMPTY
    if kind == "multi_select":
        return (
            _options([v for v in value if isinstance(v, str)]) if isinstance(value, list) else EMPTY
        )
    if kind == "number":
        return _number(value)
    if kind == "checkbox":
        return _flag(value is True)
    if kind == "date":
        return _date(value, zone)
    if kind in ("created_time", "last_edited_time"):
        if not isinstance(value, str):
            return EMPTY
        return _date({"start": {"utc": value, "date": value[:10], "has_time": True}}, zone)
    if kind == "files":
        names = [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
        return _text(", ".join(names), csv="\n".join(names)) if names else EMPTY
    if kind in ("people", "created_by", "last_edited_by"):
        people = value if isinstance(value, list) else [value]
        count = sum(1 for p in people if isinstance(p, str) and p)
        if not count:
            return EMPTY
        label = "1 person" if count == 1 else f"{count} people"
        return _presence(label, count)
    if kind == "relation":
        ids = [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []
        if not ids:
            return EMPTY
        urls = [notion_url(page_id) for page_id in ids]
        label = "1 linked page" if len(ids) == 1 else f"{len(ids)} linked pages"
        return _presence(label, len(ids), links=urls)
    if kind == "place":
        return _text(_place_text(value)) if isinstance(value, dict) else EMPTY
    if kind == "formula":
        if not isinstance(value, dict):
            return EMPTY
        inner = value.get("value")
        result = value.get("type")
        if result == "number":
            return read_extra("number", inner, zone)
        if result == "boolean":
            return read_extra("checkbox", inner, zone)
        if result == "date":
            return read_extra("date", inner, zone)
        return read_extra("rich_text", inner, zone)
    if kind == "rollup":
        if isinstance(value, bool):
            return _flag(value)
        if isinstance(value, int | float):
            return _number(value)
        if isinstance(value, dict) and "start" in value:
            return _date(value, zone)
        text = _generic_text(value, zone)
        return _text(text) if text else EMPTY
    text = _generic_text(value, zone)
    return _text(text) if text else EMPTY


def filter_kind(kind: str, values: Iterable[Any]) -> FilterKind:
    """The filter a column of Notion type ``kind`` offers, given its stored values."""
    if kind in TEXT_TYPES:
        return "text"
    if kind == "number":
        return "number"
    if kind == "checkbox":
        return "checkbox"
    if kind in OPTION_TYPES:
        return "options"
    if kind in DATE_TYPES:
        return "date"
    if kind in PRESENCE_TYPES:
        return "presence"
    if kind == "formula":
        results = Counter(
            v.get("type") for v in values if isinstance(v, dict) and v.get("value") is not None
        )
        common = results.most_common(1)
        return _FORMULA_KINDS.get(str(common[0][0]), "text") if common else "text"
    if kind == "rollup":
        shapes = Counter(_rollup_shape(v) for v in values if v is not None)
        shape = shapes.most_common(1)
        return shape[0][0] if shape else "text"
    return "text"


def local_text(moment: MomentCell, zone: ZoneInfo) -> str:
    """'2026-10-17 17:41' in ``zone``, or the date alone when there's no time."""
    if moment["has_time"] and moment["utc"]:
        local = datetime.fromisoformat(moment["utc"]).astimezone(zone)
        return local.strftime("%Y-%m-%d %H:%M")
    return moment["date"]


def number_text(value: float) -> str:
    """12 → "12", 2.5 → "2.5", 0.1 + 0.2 → "0.3" (at most six decimals)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{round(value, 6):.6f}".rstrip("0").rstrip(".")


# --- builders ---------------------------------------------------------------------------------


def _text(text: str, *, csv: str | None = None) -> ExtraValue:
    stripped = text.strip()
    if not stripped:
        return EMPTY
    return ExtraValue(
        empty=False,
        text=stripped,
        search=stripped.casefold(),
        sort=(_TEXT, stripped.casefold()),
        cell={"text": stripped},
        csv=stripped if csv is None else csv,
    )


def _options(names: list[str]) -> ExtraValue:
    cleaned = [name.strip() for name in names if name.strip()]
    if not cleaned:
        return EMPTY
    text = ", ".join(cleaned)
    return ExtraValue(
        empty=False,
        text=text,
        search=text.casefold(),
        options=tuple(cleaned),
        sort=(_TEXT, text.casefold()),
        cell={"text": text},
        csv=text,
    )


def _number(value: object) -> ExtraValue:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return EMPTY
    text = number_text(value)
    return ExtraValue(
        empty=False,
        text=text,
        search=text,
        number=float(value),
        sort=(_NUMBER, float(value)),
        cell={"text": text},
        csv=text,
        formula_safe=True,
    )


def _flag(value: bool) -> ExtraValue:
    text = "Yes" if value else "No"
    return ExtraValue(
        empty=False,
        text=text,
        search=text.casefold(),
        flag=value,
        sort=(_FLAG, value),
        cell={"text": text},
        csv=text,
    )


def _presence(label: str, count: int, *, links: list[str] | None = None) -> ExtraValue:
    cell: ExtraCell = {"text": label}
    if links:
        cell["links"] = links
    return ExtraValue(
        empty=False,
        text=label,
        search=label.casefold(),
        sort=(_NUMBER, float(count)),
        cell=cell,
        csv="\n".join(links) if links else label,
    )


def _date(value: object, zone: ZoneInfo) -> ExtraValue:
    start = _moment(value.get("start")) if isinstance(value, dict) else None
    if start is None:
        return EMPTY
    end = _moment(value.get("end")) if isinstance(value, dict) else None
    text = local_text(start, zone)
    if end is not None:
        text = f"{text} → {local_text(end, zone)}"
    if start["has_time"] and start["utc"]:
        moment = datetime.fromisoformat(start["utc"])
        day = moment.astimezone(zone).date()
    else:
        day = date.fromisoformat(start["date"])
        moment = datetime.combine(day, time(0), tzinfo=zone).astimezone(UTC)
    cell: ExtraCell = {"text": text, "start": start, "end": end}
    return ExtraValue(
        empty=False,
        text=text,
        search=text.casefold(),
        day=day,
        sort=(_DATE, moment.timestamp()),
        cell=cell,
        csv=text,
        formula_safe=True,
    )


def _moment(value: object) -> MomentCell | None:
    if not isinstance(value, dict):
        return None
    day = value.get("date")
    utc = value.get("utc")
    if not isinstance(day, str):
        return None
    try:
        date.fromisoformat(day[:10])
        if utc is not None:
            datetime.fromisoformat(str(utc))
    except ValueError:
        return None
    return {
        "utc": utc if isinstance(utc, str) else None,
        "date": day[:10],
        "has_time": bool(value.get("has_time")) and isinstance(utc, str),
    }


def _place_text(value: dict[str, Any]) -> str:
    for key in ("name", "address"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text
    lat, lon = value.get("lat"), value.get("lon")
    if isinstance(lat, int | float) and isinstance(lon, int | float):
        return f"{number_text(lat)}, {number_text(lon)}"
    return ""


def _generic_text(value: Any, zone: ZoneInfo) -> str:  # noqa: ANN401 - a rolled-up JSON value
    """Text for a rolled-up value, whose items carry no type."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int | float):
        return number_text(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ", ".join(text for text in (_generic_text(v, zone) for v in value) if text)
    if isinstance(value, dict):
        if "start" in value:
            return _date(value, zone).text
        return _place_text(value)
    return str(value)


def _rollup_shape(value: object) -> FilterKind:
    if isinstance(value, bool):
        return "checkbox"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, dict) and "start" in value:
        return "date"
    return "text"
