"""The schema check that runs before every sync (PLAN.md 6.3).

:func:`check_schema` compares the saved mapping with the data source's current columns:

* **Blocking** (the sync doesn't start, and the app opens the mapping screen): there is no usable
  mapping, the columns can't be read, or a required field's column is gone or changed to a type
  it can't use.
* **Warnings** (the sync continues without that field): an optional field's or an extra field's
  column is gone or changed to a type it can't use.

Problems in individual entries are validation's business and never appear here (PLAN.md 5).
Columns are found by property ID, so a renamed column is not a problem; renames are reported
separately so the screens can show the new names.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from app.errors import AppError
from app.mapping.fields import FIELDS, AppField
from app.mapping.matcher import FieldRef, compatible
from app.mapping.model import StoredMapping, parse_mapping
from app.mapping.properties import Property, is_readable, schema_properties, type_label

SchemaIssueCode = Literal[
    "mapping_missing",
    "mapping_invalid",
    "schema_unreadable",
    "required_missing",
    "required_type_changed",
    "optional_missing",
    "optional_type_changed",
    "extra_missing",
    "extra_unreadable",
]


class SchemaIssueDict(TypedDict):
    code: SchemaIssueCode
    field: str | None
    property_id: str | None
    message: str


class RenameDict(TypedDict):
    property_id: str
    old_name: str
    new_name: str


class SchemaCheckDict(TypedDict):
    ok: bool
    blocking: list[SchemaIssueDict]
    warnings: list[SchemaIssueDict]
    renamed: list[RenameDict]


@dataclass(frozen=True, slots=True)
class SchemaIssue:
    code: SchemaIssueCode
    message: str
    #: The app field affected, or None for extra fields and problems with the whole mapping.
    field: str | None = None
    property_id: str | None = None

    def to_dict(self) -> SchemaIssueDict:
        return {
            "code": self.code,
            "field": self.field,
            "property_id": self.property_id,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class SchemaCheck:
    blocking: list[SchemaIssue] = field(default_factory=list)
    warnings: list[SchemaIssue] = field(default_factory=list)
    #: Mapped columns whose names changed in Notion: (property ID, name at save, name now).
    renamed: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the sync may start (warnings allowed)."""
        return not self.blocking

    def to_dict(self) -> SchemaCheckDict:
        return {
            "ok": self.ok,
            "blocking": [issue.to_dict() for issue in self.blocking],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "renamed": [
                {"property_id": pid, "old_name": old, "new_name": new}
                for pid, old, new in self.renamed
            ],
        }


def check_schema(mapping: object, data_source: Mapping[str, Any]) -> SchemaCheck:
    """Check a saved mapping (the raw ``mapping`` setting) against a data source's schema."""
    if mapping is None:
        return SchemaCheck(
            blocking=[
                SchemaIssue(
                    "mapping_missing",
                    "The columns haven't been mapped yet. Open the mapping screen to choose "
                    "which Notion columns Habit Tracker reads.",
                )
            ]
        )
    try:
        saved = parse_mapping(mapping)
    except AppError as exc:
        return SchemaCheck(blocking=[SchemaIssue("mapping_invalid", exc.user_message)])
    try:
        props = schema_properties(data_source)
    except AppError as exc:
        return SchemaCheck(blocking=[SchemaIssue("schema_unreadable", exc.user_message)])

    by_id = {p.id: p for p in props}
    result = SchemaCheck()
    for app_field in FIELDS:
        ref = saved["fields"].get(app_field.key)
        if ref is None:
            if app_field.required:
                result.blocking.append(
                    SchemaIssue(
                        "mapping_invalid",
                        f"No column is chosen for {app_field.label}, which is required. Choose "
                        "one on the mapping screen.",
                        field=app_field.key,
                    )
                )
            continue
        if _shares_missing_start(app_field, ref, saved, by_id):
            continue  # the Start column's own issue already explains it
        issue = _field_issue(app_field, ref, saved, by_id)
        if issue is not None:
            (result.blocking if app_field.required else result.warnings).append(issue)
    for prop_id in saved["extra"]:
        issue = _extra_issue(prop_id, saved, by_id)
        if issue is not None:
            result.warnings.append(issue)
    for prop_id, old_name in saved["names_at_save"].items():
        current = by_id.get(prop_id)
        if current is not None and current.name != old_name:
            result.renamed.append((prop_id, old_name, current.name))
    return result


def _column(saved: StoredMapping, prop_id: str) -> str:
    """ "column “End Time”", or just "column" when the name at save isn't known."""
    name = saved["names_at_save"].get(prop_id)
    return f"column “{name}”" if name else "column"


def _shares_missing_start(
    app_field: AppField, ref: FieldRef, saved: StoredMapping, by_id: Mapping[str, Property]
) -> bool:
    if app_field.key != "end" or ref.get("part") != "end":
        return False
    start = saved["fields"].get("start")
    if start is None or start["property_id"] != ref["property_id"]:
        return False
    prop = by_id.get(ref["property_id"])
    return prop is None or prop.type != "date"


def _field_issue(
    app_field: AppField, ref: FieldRef, saved: StoredMapping, by_id: Mapping[str, Property]
) -> SchemaIssue | None:
    prop_id = ref["property_id"]
    label = app_field.label
    prop = by_id.get(prop_id)
    is_range = app_field.key == "start" and _range_shares(saved, prop_id)
    used_for = "Start time and End time (as a date range)" if is_range else label
    if prop is None:
        if app_field.required:
            return SchemaIssue(
                "required_missing",
                f"The {_column(saved, prop_id)} used for {used_for} no longer exists "
                f"in Notion, so syncing can't start. Choose another column for {label} on the "
                "mapping screen.",
                field=app_field.key,
                property_id=prop_id,
            )
        return SchemaIssue(
            "optional_missing",
            f"The {_column(saved, prop_id)} used for {label} no longer exists in "
            f"Notion. Syncing continues without {label}; choose another column on the mapping "
            "screen to use it again.",
            field=app_field.key,
            property_id=prop_id,
        )
    if compatible(app_field, prop):
        return None
    needs = " or ".join(type_label(kind) for kind in app_field.types)
    if app_field.required:
        return SchemaIssue(
            "required_type_changed",
            f"The column “{prop.name}” used for {used_for} is now a {type_label(prop.type)} "
            f"column in Notion, but {label} needs a {needs} column, so syncing can't start. "
            f"Change it back to {needs} in Notion, or choose another column on the mapping "
            "screen.",
            field=app_field.key,
            property_id=prop_id,
        )
    return SchemaIssue(
        "optional_type_changed",
        f"The column “{prop.name}” used for {label} is now a {type_label(prop.type)} column, "
        f"which {label} can't use. Syncing continues without {label}; change it back to {needs} "
        "in Notion or choose another column on the mapping screen.",
        field=app_field.key,
        property_id=prop_id,
    )


def _range_shares(saved: StoredMapping, prop_id: str) -> bool:
    end = saved["fields"].get("end")
    return end is not None and end.get("part") == "end" and end["property_id"] == prop_id


def _extra_issue(
    prop_id: str, saved: StoredMapping, by_id: Mapping[str, Property]
) -> SchemaIssue | None:
    prop = by_id.get(prop_id)
    if prop is None:
        return SchemaIssue(
            "extra_missing",
            f"The additional {_column(saved, prop_id)} no longer exists in Notion. Syncing "
            "continues without it.",
            property_id=prop_id,
        )
    if not is_readable(prop.type):
        return SchemaIssue(
            "extra_unreadable",
            f"The additional field “{prop.name}” is now a {type_label(prop.type)} column, which "
            "Habit Tracker can't read. Syncing continues without it.",
            property_id=prop_id,
        )
    return None
