"""The ``settings`` table: JSON values by key (PLAN.md 11). Never holds tokens (PLAN.md 12.5)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from typing import Final

from app.db.connection import lock_for, transaction

#: Where the app reads Notion from.
SOURCE_KEYS: Final = ("database_id", "data_source_id", "database_title")
#: Which connection is stored in Credential Manager, and the workspace it belongs to.
CONNECTION_KEYS: Final = (
    "auth_kind",
    "workspace_id",
    "workspace_name",
    "workspace_icon",
    "account_name",
)
#: The column mapping (PLAN.md 4) and the flag set when it changes after the first save.
MAPPING_KEY: Final = "mapping"
FULL_SYNC_REQUIRED_KEY: Final = "full_sync_required"
#: New columns that fit an unused optional field, found by the last sync's schema check.
MAPPING_SUGGESTIONS_KEY: Final = "mapping_suggestions"
#: Data that belongs to one Notion database: cleared with "clear local data".
SOURCE_DATA_KEYS: Final = (
    *SOURCE_KEYS,
    MAPPING_KEY,
    FULL_SYNC_REQUIRED_KEY,
    MAPPING_SUGGESTIONS_KEY,
    "last_successful_sync",
    "last_full_sync",
    "last_sync_result",
    "pending_removal",
)

#: Words a token must never be stored under, as a guard against mistakes.
_FORBIDDEN_FRAGMENTS: Final = ("token", "secret", "password")


class Settings:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = lock_for(conn)

    def get(self, key: str, default: object = None) -> object:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def get_str(self, key: str) -> str | None:
        value = self.get(key)
        return value if isinstance(value, str) else None

    def set_many(self, values: dict[str, object]) -> None:
        """Write several keys in one transaction. A value of None deletes the key."""
        for key in values:
            if any(fragment in key.lower() for fragment in _FORBIDDEN_FRAGMENTS):
                raise ValueError(f"settings never store secrets: refusing key {key!r}")
        with self._lock, transaction(self._conn):
            for key, value in values.items():
                if value is None:
                    self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                else:
                    self._conn.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?)"
                        " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)),
                    )

    def set(self, key: str, value: object) -> None:
        self.set_many({key: value})

    def delete(self, keys: Iterable[str]) -> None:
        self.set_many(dict.fromkeys(keys))

    def all(self) -> dict[str, object]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}
