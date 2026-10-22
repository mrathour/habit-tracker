"""Auto-matching Notion columns to app fields (PLAN.md 4.2).

Columns are matched **by type first, then by name**:

1. Only columns of a compatible type are candidates. Among them, a field prefers its earlier types
   (the title over a text column for Task name, a unique ID over a number for Display ID).
2. Names are compared by keyword in three tiers: a whole word or phrase ("Start Time" → start),
   a word that begins with a keyword ("StartTime", "MinuteSpent" → minute), and a near spelling
   ("Strat"). Names are split at spaces, symbols and camelCase first.

Each column is used for at most one field (except a date range, which gives both Start and End).
Optional fields are filled only with evidence: a matching name, or a type that identifies the
field on its own (the title, the only unique ID, the only relation). Required fields consider
every date column.

**Ties are never guessed.** When the best candidates for a field are equally good, the field is
marked "choose" with those candidates, and nothing is selected.

**Date ranges.** One date column can hold a session as a range (Start → End). When no date column
has an end-like name, Start matched a single column, and the sample rows show that column holding
ranges, End is matched to the end of that range.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final, Literal, NotRequired, TypedDict

from app.mapping.fields import FIELDS, FIELDS_BY_KEY, AppField, DatePart, FieldKey
from app.mapping.properties import Property

MatchStatus = Literal["matched", "choose", "missing", "unused"]

#: Keywords per field. A tuple of several words is a phrase that must appear in order.
KEYWORDS: Final[dict[FieldKey, tuple[tuple[str, ...], ...]]] = {
    "start": (
        ("start",), ("starts",), ("started",), ("starting",), ("begin",), ("began",),
        ("beginning",), ("from",), ("clock", "in"), ("check", "in"), ("punch", "in"),
        ("time", "in"),
    ),
    "end": (
        ("end",), ("ends",), ("ended",), ("ending",), ("stop",), ("stopped",), ("finish",),
        ("finished",), ("until",), ("till",), ("clock", "out"), ("check", "out"),
        ("punch", "out"), ("time", "out"),
    ),
    "task_name": (("name",), ("task",), ("title",), ("activity",), ("description",), ("what",)),
    "parent_task": (("parent",), ("task",), ("project",), ("goal",), ("epic",)),
    "display_id": (("id",), ("no",), ("number",), ("num",), ("ref",), ("index",)),
    "logged_minutes": (
        ("min",), ("mins",), ("minute",), ("minutes",), ("duration",), ("spent",), ("logged",),
        ("length",),
    ),
}  # fmt: skip

#: Shortest keyword that may match the beginning of a longer word ("StartTime").
PREFIX_MIN_CHARS: Final = 3
#: Shortest keyword and word compared by spelling, and how similar they must be.
FUZZY_MIN_CHARS: Final = 4
FUZZY_MIN_RATIO: Final = 0.8


class FieldRef(TypedDict):
    """Where an app field's value comes from. Dates also say which part of the value."""

    property_id: str
    part: NotRequired[DatePart]


@dataclass(frozen=True, slots=True)
class ColumnEvidence:
    """What the sample rows showed about a column."""

    #: At least one sample value is a date range.
    has_range: bool = False
    #: The types a formula evaluated to in the samples (number, string, boolean, date).
    formula_types: frozenset[str] = frozenset()


NO_EVIDENCE: Final = ColumnEvidence()


@dataclass(frozen=True, slots=True)
class FieldMatch:
    status: MatchStatus
    ref: FieldRef | None = None
    #: For "choose": the equally good candidates, by property ID.
    choose_from: tuple[str, ...] = ()
    #: End time taken from the end of the Start column's date range.
    from_range: bool = False


@dataclass(frozen=True, slots=True)
class _Candidate:
    prop: Property
    #: Compared as a whole: type preference first, then the name tier.
    key: tuple[int, int]


def name_tokens(name: str) -> list[str]:
    """Lower-case words of a column name, split at symbols, spaces, digits and camelCase."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = re.sub(r"(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])", " ", spaced)
    return [word for word in re.split(r"[\W_]+", spaced.lower()) if word]


def name_tier(field: FieldKey, name: str) -> int:
    """How well a name suggests a field: 3 exact word, 2 word prefix, 1 near spelling, 0 none."""
    words = name_tokens(name)
    best = 0
    for phrase in KEYWORDS[field]:
        if _contains(words, phrase):
            return 3
        if len(phrase) != 1:
            continue
        keyword = phrase[0]
        if len(keyword) >= PREFIX_MIN_CHARS and any(w.startswith(keyword) for w in words):
            best = max(best, 2)
        elif len(keyword) >= FUZZY_MIN_CHARS and any(
            len(w) >= FUZZY_MIN_CHARS
            and SequenceMatcher(None, w, keyword).ratio() >= FUZZY_MIN_RATIO
            for w in words
        ):
            best = max(best, 1)
    return best


def compatible(field: AppField, prop: Property, evidence: ColumnEvidence = NO_EVIDENCE) -> bool:
    """Whether a column's type can feed a field.

    A formula's result type isn't in the schema, so a formula counts as a number unless its
    sample values showed some other type.
    """
    if prop.type not in field.types:
        return False
    if prop.type == "formula":
        return evidence.formula_types <= {"number"}
    return True


def match_columns(
    props: Sequence[Property], evidence: Mapping[str, ColumnEvidence] | None = None
) -> dict[FieldKey, FieldMatch]:
    """Suggest a column for every app field."""
    seen = evidence or {}
    results: dict[FieldKey, FieldMatch] = {}
    claimed: set[str] = set()
    dates = [p for p in props if p.type == "date"]
    end_named = any(name_tier("end", p.name) > 0 for p in dates)
    any_range = any(seen.get(p.id, NO_EVIDENCE).has_range for p in dates)
    defer_end = any_range and not end_named

    fields = [f for f in FIELDS if not (defer_end and f.key == "end")]
    _assign(fields, props, seen, claimed, results)
    if defer_end:
        start = results["start"]
        start_id = start.ref["property_id"] if start.ref else None
        if start.status == "matched" and start_id and seen.get(start_id, NO_EVIDENCE).has_range:
            results["end"] = FieldMatch(
                "matched", {"property_id": start_id, "part": "end"}, from_range=True
            )
        else:
            _assign([FIELDS_BY_KEY["end"]], props, seen, claimed, results)
    return {field.key: results[field.key] for field in FIELDS}


def _assign(
    fields: Iterable[AppField],
    props: Sequence[Property],
    evidence: Mapping[str, ColumnEvidence],
    claimed: set[str],
    results: dict[FieldKey, FieldMatch],
) -> None:
    """Settle the most confident field first, so a strong match is never taken by a weak one."""
    remaining = list(fields)
    while remaining:
        best: tuple[AppField, list[_Candidate]] | None = None
        for field in remaining:
            ranked = _ranked(field, props, evidence, claimed)
            if ranked and (best is None or ranked[0].key > best[1][0].key):
                best = (field, ranked)
        if best is None:
            break
        field, ranked = best
        remaining.remove(field)
        top = [c for c in ranked if c.key == ranked[0].key]
        if len(top) > 1:
            results[field.key] = FieldMatch("choose", choose_from=tuple(c.prop.id for c in top))
            continue
        chosen = top[0].prop
        claimed.add(chosen.id)
        results[field.key] = FieldMatch("matched", ref=_ref(field, chosen.id))
    for field in remaining:
        results[field.key] = FieldMatch("missing" if field.required else "unused")


def _ranked(
    field: AppField,
    props: Sequence[Property],
    evidence: Mapping[str, ColumnEvidence],
    claimed: set[str],
) -> list[_Candidate]:
    usable = [p for p in props if compatible(field, p, evidence.get(p.id, NO_EVIDENCE))]
    candidates: list[_Candidate] = []
    for prop in usable:
        if prop.id in claimed:
            continue
        tier = name_tier(field.key, prop.name)
        evident = prop.type in field.self_evident and sum(p.type == prop.type for p in usable) == 1
        if not (field.required or tier > 0 or evident):
            continue
        candidates.append(_Candidate(prop, (-field.types.index(prop.type), tier)))
    return sorted(candidates, key=lambda c: c.key, reverse=True)


def _ref(field: AppField, property_id: str) -> FieldRef:
    if field.types == ("date",):
        return {"property_id": property_id, "part": "start"}
    return {"property_id": property_id}


def _contains(words: Sequence[str], phrase: tuple[str, ...]) -> bool:
    size = len(phrase)
    return any(tuple(words[i : i + size]) == phrase for i in range(len(words) - size + 1))
