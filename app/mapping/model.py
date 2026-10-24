"""The saved mapping, kept in the ``mapping`` settings key (PLAN.md 11).

Shape (version 1)::

    {
      "version": 1,
      "fields": {
        "start": {"property_id": "abc", "part": "start"},
        "end": {"property_id": "abc", "part": "end"},      # end of a date range in "abc"
        "task_name": {"property_id": "title"},
        "logged_minutes": null,                              # "Not used"
        ...
      },
      "extra": ["xyz"],
      "names_at_save": {"abc": "Session", "title": "Name", "xyz": "Mood"},
      "known_columns": ["abc", "title", "xyz", "def"],
      "saved_at": "2026-10-22T10:00:00.000Z"
    }

Mappings are **by property ID**, so renaming a column in Notion never breaks them.
``names_at_save`` only words messages such as "“End Time” no longer exists"; it is never used to
find a column.

``known_columns`` lists every column the user saw when saving, plus columns they chose to ignore
later. A column that appears afterwards (for example once a related database is shared with the
connection, issue #12) and fits an unused optional field is offered to the user
(``app/mapping/suggest.py``). Mappings saved before this key existed have it as ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, TypedDict, cast

from app.errors import AppError
from app.mapping.fields import FIELDS, FIELDS_BY_KEY, FieldKey
from app.mapping.matcher import FieldRef, compatible
from app.mapping.properties import Property, is_readable, type_label

MAPPING_VERSION: Final = 1


class StoredMapping(TypedDict):
    version: int
    fields: dict[FieldKey, FieldRef | None]
    extra: list[str]
    names_at_save: dict[str, str]
    #: Every column present at save, plus dismissed suggestions; None for older mappings.
    known_columns: list[str] | None
    saved_at: str


class MappingFormatError(AppError):
    """The saved mapping can't be read: it is damaged or from a newer app version."""

    state = "mapping_invalid"


class MappingChoiceError(AppError):
    """The mapping the user chose can't be saved. The message lists every reason."""

    state = "mapping_invalid"

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = list(problems)


def parse_mapping(value: object) -> StoredMapping:
    """Read a stored mapping, refusing anything that isn't a well-formed version 1 mapping."""
    if not isinstance(value, dict):
        raise MappingFormatError("The saved column mapping is damaged. Map the columns again.")
    version = value.get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version > MAPPING_VERSION:
        raise MappingFormatError(
            "The saved column mapping was made by a newer version of Habit Tracker. Update the "
            "app, or map the columns again."
        )
    if isinstance(version, bool) or version != MAPPING_VERSION:
        raise MappingFormatError("The saved column mapping is damaged. Map the columns again.")
    raw_fields = value.get("fields")
    extra = value.get("extra", [])
    names = value.get("names_at_save", {})
    saved_at = value.get("saved_at", "")
    known = value.get("known_columns")
    if known is not None and (
        not isinstance(known, list) or not all(isinstance(item, str) for item in known)
    ):
        raise MappingFormatError("The saved column mapping is damaged. Map the columns again.")
    if (
        not isinstance(raw_fields, dict)
        or not isinstance(extra, list)
        or not all(isinstance(item, str) for item in extra)
        or not isinstance(names, dict)
        or not isinstance(saved_at, str)
    ):
        raise MappingFormatError("The saved column mapping is damaged. Map the columns again.")
    fields: dict[FieldKey, FieldRef | None] = {}
    for field in FIELDS:
        ref = raw_fields.get(field.key)
        if ref is not None and not _is_ref(ref):
            raise MappingFormatError("The saved column mapping is damaged. Map the columns again.")
        fields[field.key] = cast("FieldRef | None", ref)
    return {
        "version": MAPPING_VERSION,
        "fields": fields,
        "extra": list(dict.fromkeys(extra)),
        "names_at_save": {str(k): str(v) for k, v in names.items() if isinstance(v, str)},
        "known_columns": list(dict.fromkeys(known)) if known is not None else None,
        "saved_at": saved_at,
    }


def validate_choice(
    fields: object, extra: object, props: Sequence[Property]
) -> tuple[dict[FieldKey, FieldRef | None], list[str]]:
    """Check a mapping chosen on the review screen against the current schema.

    Every problem is collected, so the message explains all of them at once.
    """
    if not isinstance(fields, dict) or not isinstance(extra, list):
        raise MappingChoiceError(["The mapping was sent in an unexpected form."])
    by_id = {p.id: p for p in props}
    problems: list[str] = []
    chosen: dict[FieldKey, FieldRef | None] = {}
    unknown = sorted(str(key) for key in fields if key not in FIELDS_BY_KEY)
    if unknown:
        problems.append(f"Unknown app fields: {', '.join(unknown)}.")
    for field in FIELDS:
        raw = fields.get(field.key)
        if raw is None:
            chosen[field.key] = None
            if field.required:
                problems.append(f"{field.label} is required: choose a Date column for it.")
            continue
        if not _is_ref(raw):
            problems.append(f"{field.label} was sent in an unexpected form.")
            continue
        ref = cast("FieldRef", raw)
        prop = by_id.get(ref["property_id"])
        if prop is None:
            problems.append(
                f"The column chosen for {field.label} no longer exists in Notion. Reload the "
                "columns and choose again."
            )
            continue
        if not compatible(field, prop):
            needs = " or ".join(type_label(kind) for kind in field.types)
            problems.append(
                f"“{prop.name}” is a {type_label(prop.type)} column, but {field.label} needs a "
                f"{needs} column."
            )
            continue
        part = ref.get("part")
        if field.types == ("date",):
            if part not in ("start", "end") or (field.key == "start" and part != "start"):
                problems.append(f"{field.label} must use the start of a date.")
                continue
        elif part is not None:
            problems.append(f"{field.label} was sent in an unexpected form.")
            continue
        chosen[field.key] = ref
    problems += _range_problems(chosen)
    problems += _duplicate_problems(chosen, by_id)
    extras = _valid_extra(extra, by_id, chosen, problems)
    if problems:
        raise MappingChoiceError(problems)
    return chosen, extras


def build_mapping(
    fields: Mapping[FieldKey, FieldRef | None],
    extra: Sequence[str],
    props: Sequence[Property],
    saved_at: str,
) -> StoredMapping:
    by_id = {p.id: p for p in props}
    used = [ref["property_id"] for ref in fields.values() if ref] + list(extra)
    return {
        "version": MAPPING_VERSION,
        "fields": {field.key: fields.get(field.key) for field in FIELDS},
        "extra": list(extra),
        "names_at_save": {pid: by_id[pid].name for pid in dict.fromkeys(used) if pid in by_id},
        "known_columns": [p.id for p in props],
        "saved_at": saved_at,
    }


def same_choice(a: StoredMapping, b: StoredMapping) -> bool:
    """Whether two mappings read the same columns the same way (names and times aside)."""
    return a["fields"] == b["fields"] and set(a["extra"]) == set(b["extra"])


def mapped_ids(mapping: StoredMapping) -> set[str]:
    return {ref["property_id"] for ref in mapping["fields"].values() if ref}


def _is_ref(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    prop_id = value.get("property_id")
    if not isinstance(prop_id, str) or not prop_id:
        return False
    extra_keys = set(value) - {"property_id", "part"}
    return not extra_keys and value.get("part", "start") in ("start", "end")


def _range_problems(chosen: Mapping[FieldKey, FieldRef | None]) -> list[str]:
    end = chosen.get("end")
    if not end or end.get("part") != "end":
        return []
    start = chosen.get("start")
    if not start or start["property_id"] != end["property_id"]:
        return ["The end of a date range can only be used with the column chosen for Start time."]
    return []


def _duplicate_problems(
    chosen: Mapping[FieldKey, FieldRef | None], by_id: Mapping[str, Property]
) -> list[str]:
    users: dict[str, list[str]] = {}
    for key, ref in chosen.items():
        if ref is None:
            continue
        if key == "end" and ref.get("part") == "end":
            continue  # the range's end shares the Start column by design
        users.setdefault(ref["property_id"], []).append(FIELDS_BY_KEY[key].label)
    return [
        f"“{by_id[pid].name}” is chosen for both {' and '.join(labels)}; each column can feed "
        "only one field."
        for pid, labels in users.items()
        if len(labels) > 1
    ]


def _valid_extra(
    extra: list[object],
    by_id: Mapping[str, Property],
    chosen: Mapping[FieldKey, FieldRef | None],
    problems: list[str],
) -> list[str]:
    mapped = {ref["property_id"] for ref in chosen.values() if ref}
    result: list[str] = []
    for item in extra:
        if not isinstance(item, str):
            problems.append("An additional field was sent in an unexpected form.")
            continue
        prop = by_id.get(item)
        if prop is None:
            problems.append(
                "An additional field no longer exists in Notion. Reload the columns and choose "
                "again."
            )
        elif not is_readable(prop.type):
            problems.append(f"“{prop.name}” can't be read, so it can't be an additional field.")
        elif item in mapped:
            problems.append(f"“{prop.name}” is already mapped to an app field.")
        elif item not in result:
            result.append(item)
    return result
