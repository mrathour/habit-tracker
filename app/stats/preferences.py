"""Dashboard preferences, kept in ``settings`` (PLAN.md 11): streak threshold, week start, the
midnight rule and the overlap rule. Missing or damaged values fall back to the defaults."""

from __future__ import annotations

from typing import Final, Literal, TypedDict, cast

from app.db.settings import Settings
from app.errors import AppError

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MidnightRule = Literal["split", "start_date"]
OverlapRule = Literal["once", "sum"]

WEEKDAYS: Final[tuple[Weekday, ...]] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
MAX_THRESHOLD_MINUTES: Final = 24 * 60

THRESHOLD_KEY: Final = "streak_threshold_minutes"
WEEK_START_KEY: Final = "week_start"
MIDNIGHT_RULE_KEY: Final = "midnight_rule"
OVERLAP_RULE_KEY: Final = "overlap_rule"


class Preferences(TypedDict):
    #: 0 means any time at all (more than 0 minutes); otherwise a day needs at least this many.
    streak_threshold_minutes: int
    week_start: Weekday
    midnight_rule: MidnightRule
    overlap_rule: OverlapRule


DEFAULTS: Final[Preferences] = {
    "streak_threshold_minutes": 0,
    "week_start": "monday",
    "midnight_rule": "split",
    "overlap_rule": "once",
}


class PreferenceError(AppError):
    state = "invalid_preference"


def read(settings: Settings) -> Preferences:
    threshold = settings.get(THRESHOLD_KEY)
    week_start = settings.get(WEEK_START_KEY)
    midnight = settings.get(MIDNIGHT_RULE_KEY)
    overlap = settings.get(OVERLAP_RULE_KEY)
    return {
        "streak_threshold_minutes": (
            cast("int", threshold)
            if _valid_threshold(threshold)
            else DEFAULTS["streak_threshold_minutes"]
        ),
        "week_start": (week_start if week_start in WEEKDAYS else DEFAULTS["week_start"]),
        "midnight_rule": (
            midnight if midnight in ("split", "start_date") else DEFAULTS["midnight_rule"]
        ),
        "overlap_rule": (overlap if overlap in ("once", "sum") else DEFAULTS["overlap_rule"]),
    }


def update(settings: Settings, changes: object) -> Preferences:
    """Apply a partial update from the Settings screen, refusing anything invalid."""
    if not isinstance(changes, dict) or not changes:
        raise PreferenceError("Nothing to change.")
    values: dict[str, object] = {}
    for key, value in changes.items():
        if key == THRESHOLD_KEY:
            if not _valid_threshold(value):
                raise PreferenceError(
                    f"The streak threshold must be a whole number of minutes from 0 to "
                    f"{MAX_THRESHOLD_MINUTES}."
                )
        elif key == WEEK_START_KEY:
            if value not in WEEKDAYS:
                raise PreferenceError("Choose a day of the week for the week to start on.")
        elif key == MIDNIGHT_RULE_KEY:
            if value not in ("split", "start_date"):
                raise PreferenceError("Choose how to count sessions that cross midnight.")
        elif key == OVERLAP_RULE_KEY:
            if value not in ("once", "sum"):
                raise PreferenceError("Choose how to count overlapping sessions.")
        else:
            raise PreferenceError("Unknown dashboard setting.", detail=repr(key))
        values[key] = value
    settings.set_many(values)
    return read(settings)


def _valid_threshold(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_THRESHOLD_MINUTES
    )
