"""Notion property types: what the app can read, and short sample values for the review screen.

The list follows Notion API 2026-03-11's property object. Every type has a readable label. Types
the app can't read (buttons, ``unsupported``, and anything newer than this list) come with the
reason, which the review screen shows next to the column.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, TypedDict

from app.errors import AppError
from app.notion.dates import Moment, parse_date_value

TYPE_LABELS: Final[dict[str, str]] = {
    "title": "Title",
    "rich_text": "Text",
    "number": "Number",
    "select": "Select",
    "multi_select": "Multi-select",
    "status": "Status",
    "date": "Date",
    "people": "Person",
    "files": "Files & media",
    "checkbox": "Checkbox",
    "url": "URL",
    "email": "Email",
    "phone_number": "Phone",
    "formula": "Formula",
    "relation": "Relation",
    "rollup": "Rollup",
    "created_time": "Created time",
    "created_by": "Created by",
    "last_edited_time": "Last edited time",
    "last_edited_by": "Last edited by",
    "unique_id": "ID",
    "verification": "Verification",
    "place": "Place",
    "button": "Button",
    "unsupported": "Unsupported",
}

#: Types whose values the app can read and keep as extra fields.
READABLE_TYPES: Final = frozenset(TYPE_LABELS) - {"button", "unsupported"}

#: The most characters of one sample value sent to the review screen.
SAMPLE_TEXT_MAX: Final = 80

_NOTES: Final[dict[str, str]] = {
    "people": "Shown as a count: Habit Tracker doesn't ask Notion for people's details.",
    "created_by": "Shown as a person count: Habit Tracker doesn't ask Notion for people's details.",
    "last_edited_by": (
        "Shown as a person count: Habit Tracker doesn't ask Notion for people's details."
    ),
    "relation": "Linked pages are kept as links; their titles aren't read.",
    "files": "Only file names are kept, because Notion's file links expire.",
}


class SchemaFormatError(AppError):
    """Notion's description of the database's columns couldn't be read."""

    state = "notion_error"


@dataclass(frozen=True, slots=True)
class Property:
    """One column of the data source, as its schema describes it."""

    id: str
    name: str
    type: str
    config: Mapping[str, Any]


class SampleMoment(TypedDict):
    utc: str | None
    date: str
    has_time: bool


class TextSample(TypedDict):
    kind: Literal["text"]
    text: str


class DateSample(TypedDict):
    kind: Literal["date"]
    start: SampleMoment
    end: SampleMoment | None


Sample = TextSample | DateSample


def type_label(kind: str) -> str:
    return TYPE_LABELS.get(kind) or kind.replace("_", " ").capitalize()


def is_readable(kind: str) -> bool:
    return kind in READABLE_TYPES


def unusable_reason(kind: str) -> str | None:
    """Why a column of this type can't be used at all, or None when it can be read."""
    if kind == "button":
        return "Buttons run actions in Notion and hold no value, so there's nothing to read."
    if kind == "unsupported":
        return (
            "Notion doesn't share this kind of property through its API, so Habit Tracker "
            "can't read it."
        )
    if kind not in READABLE_TYPES:
        return f"Habit Tracker doesn't know how to read {type_label(kind)} properties yet."
    return None


def column_note(kind: str) -> str | None:
    """A short note on how a readable type is kept, when that isn't obvious."""
    return _NOTES.get(kind)


def schema_properties(data_source: Mapping[str, Any]) -> list[Property]:
    """Every column in a data source, in the order Notion lists them."""
    properties = data_source.get("properties")
    if not isinstance(properties, dict):
        raise SchemaFormatError(
            "Notion sent the database's columns in a form Habit Tracker doesn't recognise.",
            detail="data source without a properties object",
        )
    result: list[Property] = []
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        prop_id, kind = spec.get("id"), spec.get("type")
        if not isinstance(prop_id, str) or not prop_id or not isinstance(kind, str):
            continue
        label = spec.get("name") if isinstance(spec.get("name"), str) else name
        config = spec.get(kind)
        result.append(
            Property(
                id=prop_id,
                name=str(label),
                type=kind,
                config=config if isinstance(config, dict) else {},
            )
        )
    return result


# --- sample values --------------------------------------------------------------------------


def sample_of(value: object) -> Sample | None:
    """A short, display-ready version of one property value; None when it is empty."""
    if not isinstance(value, dict):
        return None
    kind = value.get("type")
    if not isinstance(kind, str):
        return None
    inner = value.get(kind)
    if kind == "date":
        return _date_sample(inner)
    if kind in ("created_time", "last_edited_time"):
        return _date_sample({"start": inner}) if isinstance(inner, str) else None
    if kind == "formula":
        return _formula_sample(inner)
    if kind == "rollup":
        return _rollup_sample(inner)
    if kind == "relation" and value.get("has_more") is True and isinstance(inner, list):
        return _text(f"{len(inner)}+ linked pages")
    text = _text_of(kind, inner)
    return _text(text) if text else None


def is_range(value: object) -> bool:
    """True when a date property value holds a range (an end inside the same property)."""
    if not isinstance(value, dict) or value.get("type") != "date":
        return False
    parsed = parse_date_value(value.get("date"))
    return parsed is not None and parsed.end is not None


def has_date_without_time(value: object) -> bool:
    """True when a date property value has a start date but no time."""
    if not isinstance(value, dict) or value.get("type") != "date":
        return False
    parsed = parse_date_value(value.get("date"))
    return parsed is not None and not parsed.start.has_time


def formula_result_type(value: object) -> str | None:
    """The type a formula value evaluated to: number, string, boolean or date."""
    if not isinstance(value, dict) or value.get("type") != "formula":
        return None
    inner = value.get("formula")
    kind = inner.get("type") if isinstance(inner, dict) else None
    if not isinstance(kind, str) or not isinstance(inner, dict) or inner.get(kind) is None:
        return None
    return kind


def _text(text: str) -> TextSample:
    clean = " ".join(text.split())
    if len(clean) > SAMPLE_TEXT_MAX:
        clean = clean[: SAMPLE_TEXT_MAX - 1].rstrip() + "…"
    return {"kind": "text", "text": clean}


def _moment(moment: Moment) -> SampleMoment:
    return {"utc": moment.utc, "date": moment.date, "has_time": moment.has_time}


def _date_sample(inner: object) -> DateSample | None:
    parsed = parse_date_value(inner)
    if parsed is None:
        return None
    return {
        "kind": "date",
        "start": _moment(parsed.start),
        "end": _moment(parsed.end) if parsed.end else None,
    }


def _formula_sample(inner: object) -> Sample | None:
    if not isinstance(inner, dict):
        return None
    kind = inner.get("type")
    result = inner.get(kind) if isinstance(kind, str) else None
    if result is None:
        return None
    if kind == "date":
        return _date_sample(result)
    if kind == "boolean":
        return _text("Yes" if result else "No")
    if kind == "number":
        return _text(_number(result))
    return _text(str(result)) if str(result).strip() else None


def _rollup_sample(inner: object) -> Sample | None:
    if not isinstance(inner, dict):
        return None
    kind = inner.get("type")
    if kind == "number":
        number = inner.get("number")
        return _text(_number(number)) if number is not None else None
    if kind == "date":
        return _date_sample(inner.get("date"))
    if kind == "array":
        items = inner.get("array")
        if not isinstance(items, list) or not items:
            return None
        texts = [_plain(sample_of(item)) for item in items]
        shown = [text for text in texts if text]
        if not shown:
            return _text(_count(len(items), "item"))
        return _text(", ".join(shown))
    return None


def _plain(sample: Sample | None) -> str | None:
    if sample is None:
        return None
    if sample["kind"] == "text":
        return sample["text"]
    return sample["start"]["utc"] or sample["start"]["date"]


def _text_of(kind: str, inner: object) -> str | None:
    if kind in ("title", "rich_text"):
        return _rich_text(inner)
    if kind == "number":
        return _number(inner) if isinstance(inner, int | float) else None
    if kind in ("select", "status"):
        return _name(inner)
    if kind == "multi_select":
        names = [_name(option) for option in inner] if isinstance(inner, list) else []
        return ", ".join(name for name in names if name) or None
    if kind == "checkbox":
        return "Yes" if inner is True else "No"
    if kind in ("url", "email", "phone_number"):
        return inner if isinstance(inner, str) and inner.strip() else None
    if kind == "people":
        return _count(len(inner), "person", "people") if isinstance(inner, list) and inner else None
    if kind in ("created_by", "last_edited_by"):
        return "1 person" if isinstance(inner, dict) else None
    if kind == "files":
        names = [_name(item) for item in inner] if isinstance(inner, list) else []
        return ", ".join(name for name in names if name) or None
    if kind == "relation":
        return _relation(inner)
    if kind == "unique_id":
        return _unique_id(inner)
    if kind == "verification":
        state = inner.get("state") if isinstance(inner, dict) else None
        return str(state).capitalize() if isinstance(state, str) else None
    if kind == "place":
        return _place(inner)
    return None


def _rich_text(inner: object) -> str | None:
    if not isinstance(inner, list):
        return None
    text = "".join(
        str(part.get("plain_text", "")) for part in inner if isinstance(part, dict)
    ).strip()
    return text or None


def _number(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _name(item: object) -> str | None:
    name = item.get("name") if isinstance(item, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def _count(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _relation(inner: object) -> str | None:
    if not isinstance(inner, list) or not inner:
        return None
    return _count(len(inner), "linked page")


def _unique_id(inner: object) -> str | None:
    if not isinstance(inner, dict) or inner.get("number") is None:
        return None
    prefix = inner.get("prefix")
    number = _number(inner.get("number"))
    return f"{prefix}-{number}" if isinstance(prefix, str) and prefix else number


def _place(inner: object) -> str | None:
    if not isinstance(inner, dict):
        return None
    for key in ("name", "address"):
        text = inner.get(key)
        if isinstance(text, str) and text.strip():
            return text
    lat, lon = inner.get("lat"), inner.get("lon")
    if isinstance(lat, int | float) and isinstance(lon, int | float):
        return f"{lat:.4f}, {lon:.4f}"
    return None
