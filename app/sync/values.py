"""Turning a Notion page into a local entry, following the saved mapping (PLAN.md 4, 11).

Fields are found by **property ID**: a page's ``properties`` are keyed by column name, so they are
re-indexed by each value's ``id`` first. Dates read the part their mapping names (``start``, or
``end`` for the end of a range) and are converted to UTC.

Extra fields are kept as ``{property_id: {name, type, value}}`` with ``value`` normalised by type,
ready for the raw log's filters (Phase 7):

==================================  =========================================================
Notion type                         Stored value
==================================  =========================================================
title, rich_text, url, email,       text, or null when empty
phone_number, select, status
number                              number, or null
checkbox                            true / false
multi_select                        list of option names
date                                ``{start, end}``, each ``{utc, date, has_time}``, or null
created_time, last_edited_time      ISO 8601 UTC text
people                              list of user IDs (names aren't requested from Notion)
created_by, last_edited_by          user ID
files                               list of file names (Notion's file links expire)
relation                            list of linked page IDs (complete, past 25)
unique_id                           text such as "WL-6"
formula                             ``{type, value}`` with the value normalised as above
rollup                              number, date, or list of normalised values
verification                        state text ("verified", "unverified", "expired")
place                               ``{name, address, lat, lon}``
==================================  =========================================================

A value that can't be read (missing from the page, a different type than the schema says, or a
rollup Notion couldn't calculate) is stored as null and reported as an Unreadable extra field
issue on that entry only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.mapping.model import StoredMapping
from app.mapping.properties import Property, is_readable
from app.notion.dates import Moment, parse_date_value, parse_moment
from app.validation.checks import Issue, Unreadable, validate_entry


class UnreadableValueError(Exception):
    """A value that can't be read. The message is the reason, written for the user."""


@dataclass(frozen=True, slots=True)
class Entry:
    page_id: str
    display_id: str | None
    task_name: str | None
    start: Moment | None
    end: Moment | None
    parent_task_ids: list[str]
    logged_minutes: float | None
    extra_fields: dict[str, dict[str, Any]]
    issues: list[Issue]
    created_time: str
    last_edited_time: str

    @property
    def parent_task_id(self) -> str | None:
        """The first linked page: shown as the parent task. All links are kept."""
        return self.parent_task_ids[0] if self.parent_task_ids else None


def values_by_id(page: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = page.get("properties")
    if not isinstance(values, dict):
        return {}
    return {
        str(value["id"]): value
        for value in values.values()
        if isinstance(value, dict) and isinstance(value.get("id"), str)
    }


def relations_to_complete(page: Mapping[str, Any], property_ids: set[str]) -> list[str]:
    """Relation properties among ``property_ids`` that hold more links than the page shows."""
    return [
        pid
        for pid, value in values_by_id(page).items()
        if pid in property_ids and value.get("type") == "relation" and value.get("has_more")
    ]


def read_entry(
    page: Mapping[str, Any], mapping: StoredMapping, columns: Mapping[str, Property]
) -> Entry:
    """Build the local entry for one page and validate it.

    Bad values become issues on the entry. Only a page without valid timestamps (which Notion
    always sends) raises :class:`UnreadableValueError`: the sync then skips it, and never
    removes its local copy.
    """
    values = values_by_id(page)
    fields = mapping["fields"]

    def value_of(key: str) -> dict[str, Any] | None:
        ref = fields.get(key)  # type: ignore[call-overload]
        return values.get(ref["property_id"]) if ref else None

    start_ref, end_ref = fields.get("start"), fields.get("end")
    start = _moment(value_of("start"), start_ref.get("part", "start") if start_ref else "start")
    end = _moment(value_of("end"), end_ref.get("part", "start") if end_ref else "start")
    unreadable: list[Unreadable] = []
    extras: dict[str, dict[str, Any]] = {}
    for prop_id in mapping["extra"]:
        column = columns.get(prop_id)
        if column is None or not is_readable(column.type):
            continue  # the schema check already warned; the field is skipped this sync
        try:
            value = normalise(values.get(prop_id), column.type)
        except UnreadableValueError as exc:
            unreadable.append(Unreadable(prop_id, column.name, str(exc)))
            value = None
        extras[prop_id] = {"name": column.name, "type": column.type, "value": value}
    logged = _logged_minutes(value_of("logged_minutes"))
    end_from_range = bool(end_ref and end_ref.get("part") == "end")
    return Entry(
        page_id=str(page.get("id")),
        display_id=_display_id(value_of("display_id")),
        task_name=_text(value_of("task_name")),
        start=start,
        end=end,
        parent_task_ids=_relation_ids(value_of("parent_task")),
        logged_minutes=logged,
        extra_fields=extras,
        issues=validate_entry(
            start=start,
            end=end,
            end_from_range=end_from_range,
            logged_minutes=logged,
            unreadable=unreadable,
        ),
        created_time=_timestamp(page.get("created_time")),
        last_edited_time=_timestamp(page.get("last_edited_time")),
    )


# --- mapped fields ----------------------------------------------------------------------------


def _moment(value: dict[str, Any] | None, part: str) -> Moment | None:
    if not value or value.get("type") != "date":
        return None
    parsed = parse_date_value(value.get("date"))
    if parsed is None:
        return None
    return parsed.end if part == "end" else parsed.start


def _text(value: dict[str, Any] | None) -> str | None:
    if not value or value.get("type") not in ("title", "rich_text"):
        return None
    return _rich_text(value.get(value["type"]))


def _display_id(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    if value.get("type") == "unique_id":
        return _unique_id(value.get("unique_id"))
    if value.get("type") == "number":
        number = value.get("number")
        return _number_text(number) if _is_number(number) else None
    return None


def _logged_minutes(value: dict[str, Any] | None) -> float | None:
    if not value:
        return None
    if value.get("type") == "number":
        number = value.get("number")
    elif value.get("type") == "formula":
        inner = value.get("formula")
        # A formula that evaluates to anything but a number has no minutes to compare.
        number = inner.get("number") if isinstance(inner, dict) else None
    else:
        return None
    return float(number) if isinstance(number, int | float) and _is_number(number) else None


def _relation_ids(value: dict[str, Any] | None) -> list[str]:
    if not value or value.get("type") != "relation":
        return []
    links = value.get("relation")
    if not isinstance(links, list):
        return []
    return list(
        dict.fromkeys(
            str(link["id"]) for link in links if isinstance(link, dict) and link.get("id")
        )
    )


def _timestamp(value: object) -> str:
    moment = parse_moment(value)
    if moment is None or moment.utc is None:
        raise UnreadableValueError(f"Notion sent a page without a valid timestamp ({value!r}).")
    return moment.utc


# --- extra fields -----------------------------------------------------------------------------


def normalise(value: object, expected: str) -> Any:  # noqa: ANN401 - JSON value by design
    """The stored form of one extra field's value. Raises :class:`UnreadableValueError`."""
    if not isinstance(value, dict):
        raise UnreadableValueError("Notion didn't send a value for it.")
    kind = value.get("type")
    if kind != expected:
        raise UnreadableValueError(
            f"Notion sent a {kind or 'unknown'} value where a {expected} was expected."
        )
    return _normalise_inner(kind, value.get(kind))


def _normalise_inner(kind: str, inner: Any) -> Any:  # noqa: ANN401
    if kind in ("title", "rich_text"):
        return _rich_text(inner)
    if kind in ("url", "email", "phone_number"):
        return inner if isinstance(inner, str) and inner.strip() else None
    if kind in ("select", "status"):
        return _name(inner)
    if kind == "number":
        return inner if _is_number(inner) else None
    if kind == "checkbox":
        return inner is True
    if kind == "multi_select":
        return [name for name in (_name(o) for o in _list(inner)) if name]
    if kind == "date":
        return _date(inner)
    if kind in ("created_time", "last_edited_time"):
        moment = parse_moment(inner)
        if moment is None:
            raise UnreadableValueError("its timestamp isn't a valid date.")
        return moment.utc
    if kind == "people":
        return [str(p["id"]) for p in _list(inner) if isinstance(p, dict) and p.get("id")]
    if kind in ("created_by", "last_edited_by"):
        return str(inner["id"]) if isinstance(inner, dict) and inner.get("id") else None
    if kind == "files":
        return [name for name in (_name(f) for f in _list(inner)) if name]
    if kind == "relation":
        return [str(r["id"]) for r in _list(inner) if isinstance(r, dict) and r.get("id")]
    if kind == "unique_id":
        return _unique_id(inner)
    if kind == "formula":
        return _formula(inner)
    if kind == "rollup":
        return _rollup(inner)
    if kind == "verification":
        state = inner.get("state") if isinstance(inner, dict) else None
        return state if isinstance(state, str) else None
    if kind == "place":
        if inner is None:
            return None
        if not isinstance(inner, dict):
            raise UnreadableValueError("the place isn't in a form Habit Tracker recognises.")
        return {key: inner.get(key) for key in ("name", "address", "lat", "lon")}
    raise UnreadableValueError(f"Habit Tracker can't read {kind} values.")


def _date(inner: object) -> dict[str, Any] | None:
    if inner is None:
        return None
    parsed = parse_date_value(inner)
    if parsed is None:
        raise UnreadableValueError("its date isn't in a form Habit Tracker recognises.")
    return {
        "start": _moment_dict(parsed.start),
        "end": _moment_dict(parsed.end) if parsed.end else None,
    }


def _moment_dict(moment: Moment) -> dict[str, Any]:
    return {"utc": moment.utc, "date": moment.date, "has_time": moment.has_time}


def _formula(inner: object) -> dict[str, Any] | None:
    if not isinstance(inner, dict):
        raise UnreadableValueError("its formula result is missing.")
    kind = inner.get("type")
    if kind not in ("number", "string", "boolean", "date"):
        raise UnreadableValueError(f"its formula gave a {kind or 'missing'} result.")
    result = inner.get(kind)
    if kind == "date":
        return {"type": "date", "value": _date(result)}
    if kind == "number":
        return {"type": "number", "value": result if _is_number(result) else None}
    if kind == "boolean":
        return {"type": "boolean", "value": result is True}
    return {"type": "string", "value": result if isinstance(result, str) else None}


def _rollup(inner: object) -> Any:  # noqa: ANN401 - JSON value by design
    if not isinstance(inner, dict):
        raise UnreadableValueError("its rollup result is missing.")
    kind = inner.get("type")
    if kind == "number":
        number = inner.get("number")
        return number if _is_number(number) else None
    if kind == "date":
        return _date(inner.get("date"))
    if kind == "array":
        items = []
        for item in _list(inner.get("array")):
            item_kind = item.get("type") if isinstance(item, dict) else None
            if not isinstance(item_kind, str):
                raise UnreadableValueError("one of its rolled-up values is malformed.")
            items.append(_normalise_inner(item_kind, item.get(item_kind)))
        return items
    if kind == "incomplete":
        raise UnreadableValueError("Notion couldn't finish calculating the rollup.")
    raise UnreadableValueError("Notion can't calculate this rollup through its API.")


# --- small helpers ----------------------------------------------------------------------------


def _rich_text(inner: object) -> str | None:
    text = "".join(
        str(part.get("plain_text", "")) for part in _list(inner) if isinstance(part, dict)
    ).strip()
    return text or None


def _name(item: object) -> str | None:
    name = item.get("name") if isinstance(item, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _number_text(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _unique_id(inner: object) -> str | None:
    if not isinstance(inner, dict) or not _is_number(inner.get("number")):
        return None
    prefix = inner.get("prefix")
    number = _number_text(inner.get("number"))
    return f"{prefix}-{number}" if isinstance(prefix, str) and prefix else number
