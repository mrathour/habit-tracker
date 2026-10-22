"""The raw log's filters (PLAN.md 8). Every filter that is set must match.

The UI sends::

    {
      "date_from": "2026-10-01", "date_to": "2026-10-22",   # local start date, inclusive
      "search": "docs",                                      # task name contains
      "parents": ["<page id>", ...],                         # links any of these pages
      "no_parent": true,                                     # or: links no page
      "duration_min": 30, "duration_max": 120,               # minutes, End minus Start
      "issues": "any" | "none",
      "issue_codes": ["missing_time", ...],                  # has any of these issues
      "overlaps": true,                                      # overlaps another session
      "extra": {"<property id>": {"op": "contains", "value": "x"}, ...}
    }

Extra field filters by ``op``: ``empty``, ``not_empty``, ``contains`` (``value``), ``range``
(``min``/``max``), ``is`` (``value``: true/false), ``any_of`` (``values``) and ``dates``
(``from``/``to``). Each op is accepted only for the columns whose filter offers it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final, Literal, get_args

from app.rawlog.extras import ExtraValue, FilterKind
from app.rawlog.snapshot import LogRow, Snapshot
from app.rawlog.view import RawLogError
from app.validation.checks import IssueCode

MAX_TEXT: Final = 500
MAX_VALUES: Final = 1000

ISSUE_CODES: Final = frozenset(get_args(IssueCode))

#: Which extra-field ops each filter kind accepts ("empty" and "not_empty" always work).
OPS_BY_KIND: Final[dict[FilterKind, frozenset[str]]] = {
    "text": frozenset({"contains"}),
    "number": frozenset({"range"}),
    "checkbox": frozenset({"is"}),
    "options": frozenset({"any_of"}),
    "date": frozenset({"dates"}),
    "presence": frozenset(),
}

Op = Literal["empty", "not_empty", "contains", "range", "is", "any_of", "dates"]


@dataclass(frozen=True, slots=True)
class ExtraFilter:
    property_id: str
    op: Op
    text: str = ""
    low: float | None = None
    high: float | None = None
    flag: bool | None = None
    values: frozenset[str] = frozenset()
    first: date | None = None
    last: date | None = None

    def matches(self, value: ExtraValue) -> bool:
        if self.op == "empty":
            return value.empty
        if self.op == "not_empty":
            return not value.empty
        if value.empty:
            return False
        if self.op == "contains":
            return self.text in value.search
        if self.op == "range":
            return value.number is not None and _within(value.number, self.low, self.high)
        if self.op == "is":
            return value.flag is self.flag
        if self.op == "any_of":
            return any(option in self.values for option in value.options)
        return value.day is not None and _within(value.day, self.first, self.last)


@dataclass(frozen=True, slots=True)
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    search: str = ""
    parents: frozenset[str] = frozenset()
    no_parent: bool = False
    duration_min: float | None = None
    duration_max: float | None = None
    issues: Literal["any", "none"] | None = None
    issue_codes: frozenset[str] = frozenset()
    overlaps: bool = False
    extra: tuple[ExtraFilter, ...] = field(default_factory=tuple)

    @property
    def active(self) -> bool:
        return self != Filters()

    def matches(self, row: LogRow) -> bool:
        if (self.date_from or self.date_to) and (
            row.day is None or not _within(row.day, self.date_from, self.date_to)
        ):
            return False
        if self.search and self.search not in row.search:
            return False
        if self.no_parent and row.parent_ids:
            return False
        if self.parents and not any(p in self.parents for p in row.parent_ids):
            return False
        if self.duration_min is not None or self.duration_max is not None:
            if row.duration is None:
                return False
            if not _within(row.duration, self.duration_min, self.duration_max):
                return False
        if self.issues == "any" and not row.issues:
            return False
        if self.issues == "none" and row.issues:
            return False
        if self.issue_codes and not (row.codes & self.issue_codes):
            return False
        if self.overlaps and row.overlap_minutes <= 0:
            return False
        return all(f.matches(row.extra_value(f.property_id)) for f in self.extra)


def parse(value: object, snapshot: Snapshot) -> Filters:
    """Read the UI's filters, refusing anything malformed or not offered by the column."""
    if value is None:
        return Filters()
    if not isinstance(value, dict):
        raise RawLogError("The filters were sent in an unexpected form.")
    known = {
        "date_from",
        "date_to",
        "search",
        "parents",
        "no_parent",
        "duration_min",
        "duration_max",
        "issues",
        "issue_codes",
        "overlaps",
        "extra",
    }
    unknown = set(value) - known
    if unknown:
        raise RawLogError("Unknown filter.", detail=", ".join(sorted(unknown)))
    date_from = _date(value.get("date_from"), "start date")
    date_to = _date(value.get("date_to"), "end date")
    if date_from and date_to and date_to < date_from:
        raise RawLogError("The date range ends before it starts.")
    duration_min = _minutes(value.get("duration_min"), "shortest duration")
    duration_max = _minutes(value.get("duration_max"), "longest duration")
    if duration_min is not None and duration_max is not None and duration_max < duration_min:
        raise RawLogError("The longest duration is shorter than the shortest.")
    issues = value.get("issues")
    if issues not in (None, "any", "none"):
        raise RawLogError("The issues filter was sent in an unexpected form.")
    codes = _strings(value.get("issue_codes"), "issue types")
    if not codes <= ISSUE_CODES:
        raise RawLogError("Unknown issue type.", detail=", ".join(sorted(codes - ISSUE_CODES)))
    no_parent = _flag(value.get("no_parent"), "parent task filter")
    parents = _strings(value.get("parents"), "parent tasks")
    if no_parent and parents:
        raise RawLogError("Choose parent tasks or entries without one, not both.")
    return Filters(
        date_from=date_from,
        date_to=date_to,
        search=_text(value.get("search"), "search"),
        parents=parents,
        no_parent=no_parent,
        duration_min=duration_min,
        duration_max=duration_max,
        issues=issues,
        issue_codes=codes,
        overlaps=_flag(value.get("overlaps"), "overlap filter"),
        extra=_extras(value.get("extra"), snapshot),
    )


def _extras(value: object, snapshot: Snapshot) -> tuple[ExtraFilter, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise RawLogError("The additional field filters were sent in an unexpected form.")
    filters: list[ExtraFilter] = []
    for property_id, spec in value.items():
        column = snapshot.extra_columns.get(property_id)
        if column is None:
            raise RawLogError(
                "A filter names a field that isn't in the raw log.", detail=str(property_id)
            )
        if not isinstance(spec, dict):
            raise RawLogError(f"The filter on “{column.name}” was sent in an unexpected form.")
        op = spec.get("op")
        allowed = OPS_BY_KIND[column.filter] | {"empty", "not_empty"}
        if op not in allowed:
            raise RawLogError(f"“{column.name}” can't be filtered that way.", detail=repr(op))
        filters.append(_extra(property_id, op, spec, column.name))
    return tuple(filters)


def _extra(property_id: str, op: Op, spec: dict[str, Any], name: str) -> ExtraFilter:
    if op == "contains":
        text = _text(spec.get("value"), name)
        if not text:
            raise RawLogError(f"Type something to look for in “{name}”.")
        return ExtraFilter(property_id, op, text=text)
    if op == "range":
        low = _number(spec.get("min"), name)
        high = _number(spec.get("max"), name)
        if low is None and high is None:
            raise RawLogError(f"Enter a lowest or highest value for “{name}”.")
        if low is not None and high is not None and high < low:
            raise RawLogError(f"The highest value for “{name}” is below the lowest.")
        return ExtraFilter(property_id, op, low=low, high=high)
    if op == "is":
        flag = spec.get("value")
        if not isinstance(flag, bool):
            raise RawLogError(f"Choose yes or no for “{name}”.")
        return ExtraFilter(property_id, op, flag=flag)
    if op == "any_of":
        values = _strings(spec.get("values"), name)
        if not values:
            raise RawLogError(f"Choose at least one option for “{name}”.")
        return ExtraFilter(property_id, op, values=values)
    if op == "dates":
        first = _date(spec.get("from"), f"start date for “{name}”")
        last = _date(spec.get("to"), f"end date for “{name}”")
        if first is None and last is None:
            raise RawLogError(f"Choose a start or end date for “{name}”.")
        if first and last and last < first:
            raise RawLogError(f"The date range for “{name}” ends before it starts.")
        return ExtraFilter(property_id, op, first=first, last=last)
    return ExtraFilter(property_id, op)


def _within[T: (float, date)](value: T, low: T | None, high: T | None) -> bool:
    return (low is None or value >= low) and (high is None or value <= high)


def _date(value: object, what: str) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise RawLogError(f"The {what} wasn't sent as a date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RawLogError(f"The {what} isn't a valid date.", detail=value) from exc


def _number(value: object, what: str) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or value != value:  # NaN
        raise RawLogError(f"The value for “{what}” isn't a number.")
    return float(value)


def _minutes(value: object, what: str) -> float | None:
    minutes = _number(value, what)
    if minutes is not None and minutes < 0:
        raise RawLogError(f"The {what} can't be negative.")
    return minutes


def _text(value: object, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise RawLogError(f"The {what} text was sent in an unexpected form.")
    return value.strip().casefold()


def _flag(value: object, what: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise RawLogError(f"The {what} was sent in an unexpected form.")
    return value


def _strings(value: object, what: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if (
        not isinstance(value, list)
        or len(value) > MAX_VALUES
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise RawLogError(f"The {what} were sent in an unexpected form.")
    return frozenset(value)
