"""Mapping reviews produced by the real Python service, for the UI's tests.

The UI tests read ``ui/src/test/mappingFixtures.json``, so they exercise exactly what Python
sends. ``tests/test_ui_fixtures.py`` fails when the file is out of date; regenerate it with::

    uv run python -m tests.support.ui_fixtures
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.db import open_database
from app.db.settings import Settings
from app.mapping.review import MappingService
from app.notion.client import NotionReader, RateLimiter
from app.notion.connection import ConnectionService
from app.notion.credentials import StoredCredential, utc_now
from app.notion.tokens import TokenManager
from app.redaction import Secret
from tests.support.fake_notion import FakeNotion
from tests.support.notion_schemas import (
    Schema,
    add_source,
    page,
    prop,
    rich,
    schema,
    when,
    without,
    work_log_rows,
    work_log_schema,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "ui" / "src" / "test" / "mappingFixtures.json"


class _InstantLimiter(RateLimiter):
    def wait(self) -> None:
        return


class _MemoryStore:
    def __init__(self) -> None:
        self.credential: StoredCredential | None = None

    def load(self) -> StoredCredential | None:
        return self.credential

    def save(self, credential: StoredCredential) -> None:
        self.credential = credential

    def delete(self) -> None:
        self.credential = None


def _review(
    title: str,
    properties: Schema,
    rows: list[dict[str, Any]],
    *,
    save_then: Schema | None = None,
    extra: list[str] | None = None,
) -> dict[str, Any]:
    """The review for a database; with ``save_then``, saved first and then the schema changed."""
    notion = FakeNotion()
    with tempfile.TemporaryDirectory() as folder:
        database = open_database(Path(folder) / "fixture.db")
        try:
            store = _MemoryStore()
            tokens = TokenManager(store, None)  # type: ignore[arg-type]
            tokens.replace_credential(
                StoredCredential(
                    kind="pat", access_token=Secret(notion.issue_token()), obtained_at=utc_now()
                )
            )
            reader = NotionReader(
                tokens,
                http=httpx.Client(transport=httpx.MockTransport(notion.handle)),
                base_url="https://api.notion.test",
                limiter=_InstantLimiter(),
            )
            settings = Settings(database.connection)
            connection = ConnectionService(
                tokens=tokens,
                reader=reader,
                service=None,  # type: ignore[arg-type]
                settings=settings,
                db=database.connection,
                emit=lambda _n, _p: None,
            )
            service = MappingService(
                tokens=tokens,
                reader=reader,
                settings=settings,
                clock=lambda: datetime(2026, 10, 22, 10, 0, tzinfo=UTC),
            )
            db, source_id = add_source(notion, title, properties, rows)
            connection.choose_data_source(db.id, source_id)
            review = service.review()
            if save_then is not None:
                fields = {f["key"]: f["selection"] for f in review["fields"]}
                service.save(fields, extra or [])
                notion.data_sources[source_id].properties = save_then
                review = service.review()
            # The fake gives data sources random IDs; pin it so the file is stable.
            return {**review, "data_source_id": "ds-1"}
        finally:
            database.close()


def build() -> dict[str, Any]:
    work_log = work_log_schema()
    extended = schema(
        work_log,
        prop("Mood", "mood", "select"),
        prop("Log it", "btn", "button"),
        prop("Legacy", "legacy", "unsupported"),
    )
    extended_rows = work_log_rows(extended)
    extended_rows[-1]["properties"]["Mood"]["select"] = {"name": "Focused"}
    no_end = without(work_log, "End Time")
    session = schema(prop("Name", "title", "title"), prop("Session", "s%3A1", "date"))
    session_rows = [
        page(
            session,
            {
                "Name": rich("Planning"),
                "Session": when("2026-10-21T09:00:00.000+05:30", "2026-10-21T10:15:00.000+05:30"),
            },
            created="2026-10-21T03:30:00.000Z",
        ),
        page(session, {"Session": when("2026-10-20")}, created="2026-10-20T03:30:00.000Z"),
    ]
    ambiguous = schema(
        prop("Name", "title", "title"),
        prop("Date", "d1", "date"),
        prop("Date 2", "d2", "date"),
        prop("Project", "p1", "relation"),
        prop("Task", "p2", "relation"),
    )
    changed = without(work_log_schema({"Start Time": "Began at"}), "End Time", "Mood")
    return {
        "workLog": _review("Work Log", extended, extended_rows),
        "noEnd": _review("Work Log (no end)", no_end, work_log_rows(no_end)),
        "range": _review("Sessions", session, session_rows),
        "ambiguous": _review("Ambiguous", ambiguous, []),
        "empty": _review("Work Log", work_log, []),
        "changed": _review(
            "Work Log",
            schema(work_log, prop("Mood", "mood", "select")),
            [],
            save_then=changed,
            extra=["mood"],
        ),
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


if __name__ == "__main__":
    FIXTURE_PATH.write_bytes(render().encode("utf-8"))
