"""The mapping review screen's data, and saving the mapping (PLAN.md 4.2).

:meth:`MappingService.review` reads the chosen data source's columns (``GET /v1/data_sources``)
and its 25 most recently created rows (one ``POST .../query``, a read), then returns:

* every column, with its type, whether it can be read (and why not), and up to three sample
  values from those rows;
* every app field, with the compatible columns it may use and its current selection: the saved
  mapping laid over today's columns, or on first setup the auto-matcher's suggestion;
* for a saved mapping, the schema check (PLAN.md 6.3) and any renamed columns;
* columns the sample rows hold but the schema leaves out. Notion leaves a relation out of the
  schema while the database it links to isn't shared with the connection (issue #12); Parent
  task link then explains how to share it.

:meth:`MappingService.save` checks the user's choice against a fresh copy of the schema and
saves it. Changing a saved mapping sets ``full_sync_required``: existing entries need the new
columns, which only a full sync brings (PLAN.md 4.2). Phase 5 runs it and clears the flag.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal, TypedDict

from app.db.settings import (
    FULL_SYNC_REQUIRED_KEY,
    MAPPING_KEY,
    MAPPING_SUGGESTIONS_KEY,
    Settings,
)
from app.errors import AppError
from app.mapping.fields import FIELDS, AppField, DatePart, FieldKey
from app.mapping.matcher import (
    NO_EVIDENCE,
    ColumnEvidence,
    FieldMatch,
    FieldRef,
    compatible,
    match_columns,
)
from app.mapping.model import (
    StoredMapping,
    build_mapping,
    parse_mapping,
    same_choice,
    validate_choice,
)
from app.mapping.properties import (
    Property,
    Sample,
    column_note,
    formula_result_type,
    has_date_without_time,
    is_range,
    is_readable,
    sample_of,
    schema_properties,
    type_label,
    unusable_reason,
)
from app.mapping.suggest import SuggestionDict, stored_suggestions
from app.notion.client import NotionReader
from app.notion.dates import utc_iso
from app.notion.errors import NotConnectedError, NotionRequestError
from app.notion.tokens import TokenManager
from app.sync.schema_check import SchemaCheckDict, check_schema

logger = logging.getLogger(__name__)

#: How many of the most recently created rows are read for sample values.
SAMPLE_ROWS: Final = 25
#: Sample values shown per column.
SAMPLES_PER_COLUMN: Final = 3

FieldStatus = Literal[
    "auto", "saved", "choose", "missing", "removed", "type_changed", "unused", "new_column"
]


class NoDatabaseError(AppError):
    state = "no_database"

    def __init__(self) -> None:
        super().__init__("Choose your work log database first.")


class SourceUnavailableError(AppError):
    """The chosen data source was deleted or is no longer shared with the connection."""

    state = "source_unavailable"


class ColumnInfo(TypedDict):
    id: str
    name: str
    type: str
    type_label: str
    readable: bool
    #: Why the column can't be used at all (buttons, unsupported types).
    reason: str | None
    #: How a readable type is kept, when that isn't obvious.
    note: str | None
    samples: list[Sample]
    #: Sample rows in which this column has a value.
    filled: int
    has_range: bool
    #: Sample values with a date but no time.
    dates_without_time: int
    formula_types: list[str]


class FieldOption(TypedDict):
    property_id: str
    part: DatePart | None
    label: str


class FieldReview(TypedDict):
    key: FieldKey
    label: str
    required: bool
    description: str
    #: The kind of column the field needs, e.g. "Date" or "Title or Text".
    needs: str
    selection: FieldRef | None
    status: FieldStatus
    #: For "choose": the equally good candidates.
    choose_from: list[str]
    options: list[FieldOption]
    #: Why the field has no column (removed, changed type, or missing from the database).
    message: str | None
    #: What a required field needs when the database has no column for it.
    missing_help: str | None
    #: Parent task link with no relation column in sight: how to share the linked database.
    share_help: str | None


class HiddenColumn(TypedDict):
    name: str
    type: str
    type_label: str


class FullSyncFlag(TypedDict):
    since: str
    reason: str


class MappingReview(TypedDict):
    data_source_id: str
    database_title: str | None
    columns: list[ColumnInfo]
    fields: list[FieldReview]
    extra: list[str]
    saved: bool
    saved_at: str | None
    rows_sampled: int
    sample_limit: int
    full_sync_required: FullSyncFlag | None
    schema_check: SchemaCheckDict | None
    #: Columns in the sample rows that the schema leaves out (see the module docstring).
    hidden_columns: list[HiddenColumn]


class SaveResult(TypedDict):
    changed: bool
    full_sync_required: FullSyncFlag | None


CHANGE_REASON: Final = "The column mapping changed, so entries already copied need the new columns."


class MappingService:
    def __init__(
        self,
        *,
        tokens: TokenManager,
        reader: NotionReader,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._tokens = tokens
        self._reader = reader
        self._settings = settings
        self._clock = clock

    # --- review -------------------------------------------------------------------------

    def review(self) -> MappingReview:
        source_id = self._source_id()
        source = self._fetch(lambda: self._reader.retrieve_data_source(source_id))
        props = schema_properties(source)
        rows = self._sample_rows(source_id)
        columns = [_column_info(prop, rows) for prop in props]
        hidden = _hidden_columns(props, rows)
        evidence = {c["id"]: _evidence(c) for c in columns}
        stored = self._settings.get(MAPPING_KEY)
        saved = _parse_or_none(stored)
        check = check_schema(stored, source) if stored is not None else None
        if saved is not None and check is not None:
            fields = _saved_fields(saved, props, evidence, check.to_dict())
            extra = [
                pid
                for pid in saved["extra"]
                if any(p.id == pid and is_readable(p.type) for p in props)
            ]
        else:
            fields = _suggested_fields(match_columns(props, evidence), props, evidence)
            extra = []
        _add_missing_help(fields, props)
        _add_share_help(fields, props, hidden)
        return {
            "data_source_id": source_id,
            "database_title": self._settings.get_str("database_title"),
            "columns": columns,
            "fields": fields,
            "extra": extra,
            "saved": saved is not None,
            "saved_at": saved["saved_at"] if saved else None,
            "rows_sampled": len(rows),
            "sample_limit": SAMPLE_ROWS,
            "full_sync_required": self.full_sync_flag(),
            "schema_check": check.to_dict() if check is not None else None,
            "hidden_columns": hidden,
        }

    def full_sync_flag(self) -> FullSyncFlag | None:
        value = self._settings.get(FULL_SYNC_REQUIRED_KEY)
        if (
            isinstance(value, dict)
            and isinstance(value.get("since"), str)
            and isinstance(value.get("reason"), str)
        ):
            return {"since": value["since"], "reason": value["reason"]}
        return None

    # --- save ---------------------------------------------------------------------------

    def save(self, fields: object, extra: object) -> SaveResult:
        source_id = self._source_id()
        source = self._fetch(lambda: self._reader.retrieve_data_source(source_id))
        props = schema_properties(source)
        chosen, extras = validate_choice(fields, extra, props)
        mapping = build_mapping(chosen, extras, props, utc_iso(self._clock()))
        previous = _parse_or_none(self._settings.get(MAPPING_KEY))
        had_mapping = self._settings.get(MAPPING_KEY) is not None
        changed = had_mapping and (previous is None or not same_choice(previous, mapping))
        flag = self.full_sync_flag()
        if changed and flag is None:
            flag = {"since": mapping["saved_at"], "reason": CHANGE_REASON}
        self._settings.set_many(
            {MAPPING_KEY: mapping, FULL_SYNC_REQUIRED_KEY: flag, MAPPING_SUGGESTIONS_KEY: None}
        )
        if not had_mapping:
            outcome = "first save"
        elif changed:
            outcome = "changed; full sync required"
        else:
            outcome = "unchanged"
        logger.info("Saved the column mapping (%s)", outcome)
        return {"changed": changed, "full_sync_required": flag}

    def dismiss_suggestion(self, property_id: object) -> list[SuggestionDict]:
        """Stop offering a new column: it joins ``known_columns``. Returns the offers left."""
        if not isinstance(property_id, str) or not property_id:
            raise AppError("That suggestion was sent in an unexpected form.")
        saved = _parse_or_none(self._settings.get(MAPPING_KEY))
        remaining = [
            s for s in stored_suggestions(self._settings) if s["property_id"] != property_id
        ]
        updates: dict[str, object] = {MAPPING_SUGGESTIONS_KEY: remaining or None}
        if saved is not None:
            known = saved["known_columns"]
            if known is None:
                known = list(saved["names_at_save"])
            if property_id not in known:
                known = [*known, property_id]
            updates[MAPPING_KEY] = {**saved, "known_columns": known}
        self._settings.set_many(updates)
        logger.info("Dismissed a new-column suggestion")
        return remaining

    # --- plumbing -----------------------------------------------------------------------

    def _source_id(self) -> str:
        if self._tokens.credential() is None:
            raise NotConnectedError
        source_id = self._settings.get_str("data_source_id")
        if not source_id:
            raise NoDatabaseError
        return source_id

    def _fetch(self, request: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return request()
        except NotionRequestError as exc:
            if exc.code == "object_not_found":
                title = self._settings.get_str("database_title")
                name = f"“{title}”" if title else "your work log"
                raise SourceUnavailableError(
                    f"Habit Tracker can't open {name} any more. It may have been deleted or "
                    "moved, or it's no longer shared with the connection. Choose the database "
                    "again.",
                    detail=exc.detail,
                ) from exc
            raise

    def _sample_rows(self, source_id: str) -> list[dict[str, Any]]:
        page = self._fetch(
            lambda: self._reader.query_data_source(
                source_id,
                page_size=SAMPLE_ROWS,
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
            )
        )
        results = page.get("results")
        if not isinstance(results, list):
            return []
        return [
            row
            for row in results
            if isinstance(row, dict)
            and row.get("object") == "page"
            and isinstance(row.get("properties"), dict)
        ][:SAMPLE_ROWS]


# --- columns ------------------------------------------------------------------------------


def _values_by_id(row: Mapping[str, Any]) -> dict[str, Any]:
    values = row.get("properties")
    if not isinstance(values, dict):
        return {}
    return {
        str(value["id"]): value
        for value in values.values()
        if isinstance(value, dict) and isinstance(value.get("id"), str)
    }


def _column_info(prop: Property, rows: Sequence[Mapping[str, Any]]) -> ColumnInfo:
    readable = is_readable(prop.type)
    samples: list[Sample] = []
    filled = 0
    has_range = False
    without_time = 0
    formula_types: set[str] = set()
    for row in rows:
        value = _values_by_id(row).get(prop.id)
        sample = sample_of(value) if readable else None
        if sample is None:
            continue
        filled += 1
        has_range = has_range or is_range(value)
        without_time += has_date_without_time(value)
        result_type = formula_result_type(value)
        if result_type:
            formula_types.add(result_type)
        if len(samples) < SAMPLES_PER_COLUMN:
            samples.append(sample)
    return {
        "id": prop.id,
        "name": prop.name,
        "type": prop.type,
        "type_label": type_label(prop.type),
        "readable": readable,
        "reason": unusable_reason(prop.type),
        "note": column_note(prop.type) if readable else None,
        "samples": samples,
        "filled": filled,
        "has_range": has_range,
        "dates_without_time": without_time,
        "formula_types": sorted(formula_types),
    }


def _evidence(column: ColumnInfo) -> ColumnEvidence:
    return ColumnEvidence(
        has_range=column["has_range"], formula_types=frozenset(column["formula_types"])
    )


# --- fields -------------------------------------------------------------------------------


def _options(
    app_field: AppField, props: Sequence[Property], evidence: Mapping[str, ColumnEvidence]
) -> list[FieldOption]:
    options: list[FieldOption] = []
    date_field = app_field.types == ("date",)
    for prop in props:
        if compatible(app_field, prop, evidence.get(prop.id, NO_EVIDENCE)):
            options.append(
                {
                    "property_id": prop.id,
                    "part": "start" if date_field else None,
                    "label": prop.name,
                }
            )
    if app_field.key == "end":
        options += [
            {
                "property_id": prop.id,
                "part": "end",
                "label": f"End of the date range in “{prop.name}”",
            }
            for prop in props
            if prop.type == "date"
        ]
    return options


def _review(
    app_field: AppField,
    props: Sequence[Property],
    evidence: Mapping[str, ColumnEvidence],
    *,
    selection: FieldRef | None,
    status: FieldStatus,
    choose_from: Sequence[str] = (),
    message: str | None = None,
) -> FieldReview:
    return {
        "key": app_field.key,
        "label": app_field.label,
        "required": app_field.required,
        "description": app_field.description,
        "needs": " or ".join(type_label(kind) for kind in app_field.types),
        "selection": selection,
        "status": status,
        "choose_from": list(choose_from),
        "options": _options(app_field, props, evidence),
        "message": message,
        "missing_help": None,
        "share_help": None,
    }


def _suggested_fields(
    matches: Mapping[FieldKey, FieldMatch],
    props: Sequence[Property],
    evidence: Mapping[str, ColumnEvidence],
) -> list[FieldReview]:
    statuses: dict[str, FieldStatus] = {
        "matched": "auto",
        "choose": "choose",
        "missing": "missing",
        "unused": "unused",
    }
    return [
        _review(
            app_field,
            props,
            evidence,
            selection=matches[app_field.key].ref,
            status=statuses[matches[app_field.key].status],
            choose_from=matches[app_field.key].choose_from,
        )
        for app_field in FIELDS
    ]


def _saved_fields(
    saved: StoredMapping,
    props: Sequence[Property],
    evidence: Mapping[str, ColumnEvidence],
    check: SchemaCheckDict,
) -> list[FieldReview]:
    issues = {
        issue["field"]: issue for issue in check["blocking"] + check["warnings"] if issue["field"]
    }
    by_id = {p.id: p for p in props}
    reviews: list[FieldReview] = []
    for app_field in FIELDS:
        ref = saved["fields"].get(app_field.key)
        issue = issues.get(app_field.key)
        if ref is None:
            status: FieldStatus = "missing" if app_field.required else "unused"
            reviews.append(
                _review(app_field, props, evidence, selection=None, status=status, message=None)
            )
        elif ref["property_id"] not in by_id:
            reviews.append(
                _review(
                    app_field,
                    props,
                    evidence,
                    selection=None,
                    status="removed",
                    message=issue["message"] if issue else None,
                )
            )
        elif issue is not None or not compatible(app_field, by_id[ref["property_id"]]):
            reviews.append(
                _review(
                    app_field,
                    props,
                    evidence,
                    selection=None,
                    status="type_changed",
                    message=issue["message"] if issue else None,
                )
            )
        else:
            reviews.append(_review(app_field, props, evidence, selection=ref, status="saved"))
    for suggestion in check["suggestions"]:
        review = next(r for r in reviews if r["key"] == suggestion["field"])
        if review["selection"] is None and review["status"] == "unused":
            review["selection"] = {"property_id": suggestion["property_id"]}
            review["status"] = "new_column"
            review["message"] = (
                f"“{suggestion['column_name']}” appeared in Notion after you saved the mapping, "
                f"so it's selected for {review['label']}. Save the mapping to start using it, or "
                "choose “Not used”."
            )
    _drop_orphaned_range_end(reviews)
    return reviews


def _drop_orphaned_range_end(reviews: list[FieldReview]) -> None:
    """A range end whose Start column was removed or changed has nothing left to point at."""
    start = next(r for r in reviews if r["key"] == "start")
    end = next(r for r in reviews if r["key"] == "end")
    selection = end["selection"]
    if selection and selection.get("part") == "end" and start["selection"] is None:
        end["selection"] = None
        end["status"] = start["status"]
        end["message"] = (
            "End time came from the end of the date range in the Start time column, which "
            "can't be used any more. Choose the columns again."
        )


def _add_missing_help(reviews: list[FieldReview], props: Sequence[Property]) -> None:
    """Explain exactly what the database needs when a required field has no column."""
    dates = [p for p in props if p.type == "date"]
    start_review = next(r for r in reviews if r["key"] == "start")
    start_ref = start_review["selection"]
    start_name = next(
        (p.name for p in dates if start_ref and p.id == start_ref["property_id"]), None
    )
    for review in reviews:
        if not review["required"]:
            continue
        if review["key"] == "start":
            review["missing_help"] = (
                "Your database has no Date column, so there's nothing to use as the start time. "
                "In Notion, add a Date column for when each session starts and turn on “Include "
                "time”. Add a second Date column for when it ends, or record each session as a "
                "date range in that one column."
                if not dates
                else None
            )
        elif not dates:
            review["missing_help"] = (
                "Your database also needs a Date column for when each session ends: a second "
                "Date column with “Include time” turned on, or an end date inside the start "
                "column (a date range)."
            )
        elif len(dates) == 1:
            column = start_name or dates[0].name
            review["missing_help"] = (
                "Your database needs a second Date column to use as the end time. In Notion, add "
                "a Date column for when each session ends and turn on “Include time”. Or, if "
                f"“{column}” holds each session as a date range (start → end), choose “End of "
                f"the date range in “{column}”” for End time."
            )


def _hidden_columns(
    props: Sequence[Property], rows: Sequence[Mapping[str, Any]]
) -> list[HiddenColumn]:
    """Columns the sample rows hold that the schema leaves out, in the rows' order."""
    known = {p.id for p in props}
    hidden: dict[str, HiddenColumn] = {}
    for row in rows:
        values = row.get("properties")
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            if not isinstance(value, dict):
                continue
            pid, kind = value.get("id"), value.get("type")
            if isinstance(pid, str) and isinstance(kind, str) and pid not in known:
                hidden.setdefault(
                    pid, {"name": str(name), "type": kind, "type_label": type_label(kind)}
                )
    return list(hidden.values())


def _add_share_help(
    reviews: list[FieldReview], props: Sequence[Property], hidden: Sequence[HiddenColumn]
) -> None:
    """Parent task link can't be offered a relation Notion hides: say how to make it visible."""
    if any(p.type == "relation" for p in props):
        return
    review = next(r for r in reviews if r["key"] == "parent_task")
    steps = (
        "In Notion, open that database, choose ••• → Connections, and add Habit Tracker. Then "
        "click “Check again”."
    )
    names = [f"“{c['name']}”" for c in hidden if c["type"] == "relation"]
    if names:
        review["share_help"] = (
            f"Notion is hiding the relation column {' and '.join(names)} because the database "
            f"it links to isn't shared with Habit Tracker. {steps}"
        )
    else:
        review["share_help"] = (
            "Habit Tracker can't see a relation column in this database. If your sessions link "
            "to tasks in another database, such as a task tracker, Notion hides that column "
            f"until the other database is shared with Habit Tracker too. {steps}"
        )


def _parse_or_none(value: object) -> StoredMapping | None:
    if value is None:
        return None
    try:
        return parse_mapping(value)
    except AppError:
        return None
