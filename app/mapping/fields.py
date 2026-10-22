"""The app fields a Notion column can be mapped to (PLAN.md 4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

FieldKey = Literal["start", "end", "task_name", "parent_task", "display_id", "logged_minutes"]
DatePart = Literal["start", "end"]


@dataclass(frozen=True, slots=True)
class AppField:
    key: FieldKey
    label: str
    required: bool
    #: Compatible Notion types, best first: matching prefers earlier types (PLAN.md 4.2).
    types: tuple[str, ...]
    description: str
    #: Types that identify this field on their own when the database has exactly one column of
    #: that type, with no help from the name (the title is always the task name).
    self_evident: tuple[str, ...] = ()


FIELDS: Final[tuple[AppField, ...]] = (
    AppField(
        "start",
        "Start time",
        required=True,
        types=("date",),
        description="When each work session starts. The date needs a time.",
    ),
    AppField(
        "end",
        "End time",
        required=True,
        types=("date",),
        description="When each work session ends. The date needs a time.",
    ),
    AppField(
        "task_name",
        "Task name",
        required=False,
        types=("title", "rich_text"),
        description='What you worked on. Blank names show as "Untitled" and are never flagged.',
        self_evident=("title",),
    ),
    AppField(
        "parent_task",
        "Parent task link",
        required=False,
        types=("relation",),
        description="The task each session belongs to, shown as a link to it in Notion.",
        self_evident=("relation",),
    ),
    AppField(
        "display_id",
        "Display ID",
        required=False,
        types=("unique_id", "number"),
        description="A short label for each entry in the raw log.",
        self_evident=("unique_id",),
    ),
    AppField(
        "logged_minutes",
        "Logged minutes",
        required=False,
        types=("number", "formula"),
        description=(
            "Minutes you logged by hand. Used only to check entries: durations always come from "
            "End minus Start."
        ),
    ),
)

FIELDS_BY_KEY: Final = {field.key: field for field in FIELDS}
REQUIRED_KEYS: Final = tuple(field.key for field in FIELDS if field.required)
