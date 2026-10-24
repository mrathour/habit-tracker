"""New columns that fit an unused optional field (issue #12, PLAN.md 4.2).

A column can appear in the schema after the mapping was saved: added in Notion, or, for a
relation, made visible by sharing the related database with the connection (Notion leaves a
relation out of the schema until then). When the auto-matcher would pick such a column for an
optional field the saved mapping doesn't use, the app offers it on Home, in Settings and on the
mapping screen. Nothing changes until the user saves the mapping; dismissing the offer adds the
column to ``known_columns`` so it isn't offered again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict, TypeGuard

from app.db.settings import MAPPING_SUGGESTIONS_KEY, Settings
from app.mapping.fields import FIELDS_BY_KEY, FieldKey
from app.mapping.matcher import FieldRef, match_columns
from app.mapping.model import StoredMapping, mapped_ids
from app.mapping.properties import Property, type_label


class SuggestionDict(TypedDict):
    field: FieldKey
    field_label: str
    property_id: str
    column_name: str
    message: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    field: FieldKey
    ref: FieldRef
    column: Property

    def to_dict(self) -> SuggestionDict:
        label = FIELDS_BY_KEY[self.field].label
        return {
            "field": self.field,
            "field_label": label,
            "property_id": self.column.id,
            "column_name": self.column.name,
            "message": (
                f"Notion now shows the {type_label(self.column.type)} column "
                f"“{self.column.name}”, which fits {label}. Review the column mapping to use it."
            ),
        }


def suggestions(saved: StoredMapping, props: Sequence[Property]) -> list[Suggestion]:
    """Columns the saved mapping hasn't seen that the matcher would use for an unused field."""
    taken = mapped_ids(saved) | set(saved["extra"])
    known = set(saved["known_columns"]) if saved["known_columns"] is not None else None
    if known is None:
        # A mapping saved before ``known_columns`` existed: its own columns are all it knew.
        known = set(saved["names_at_save"])
    by_id = {p.id: p for p in props}
    result: list[Suggestion] = []
    for key, match in match_columns(props).items():
        app_field = FIELDS_BY_KEY[key]
        if app_field.required or saved["fields"].get(key) is not None:
            continue
        ref = match.ref
        if match.status != "matched" or ref is None:
            continue
        pid = ref["property_id"]
        if pid in taken or pid in known or pid not in by_id:
            continue
        result.append(Suggestion(key, ref, by_id[pid]))
    return result


def stored_suggestions(settings: Settings) -> list[SuggestionDict]:
    """The suggestions the last sync found, still waiting for the user."""
    value = settings.get(MAPPING_SUGGESTIONS_KEY)
    if not isinstance(value, list):
        return []
    return [item for item in value if _is_suggestion(item)]


def _is_suggestion(item: object) -> TypeGuard[SuggestionDict]:
    return (
        isinstance(item, dict)
        and item.get("field") in FIELDS_BY_KEY
        and all(
            isinstance(item.get(key), str)
            for key in ("field_label", "property_id", "column_name", "message")
        )
    )
