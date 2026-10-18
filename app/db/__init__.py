"""Local SQLite storage: connections, schema migrations and (later) queries."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.db.connection import connect, transaction
from app.db.migrator import MigrationError, MigrationResult, migrate
from app.errors import AppError

__all__ = ["Database", "MigrationError", "connect", "open_database", "transaction"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Database:
    path: Path
    connection: sqlite3.Connection
    migration: MigrationResult

    @property
    def schema_version(self) -> int:
        return self.migration.current_version

    def close(self) -> None:
        self.connection.close()


def open_database(path: Path) -> Database:
    """Open (creating if needed) and migrate the local database."""
    try:
        conn = connect(path)
    except sqlite3.Error as exc:
        raise _readable_error(path, exc) from exc
    try:
        result = migrate(conn)
    except MigrationError:
        conn.close()
        raise
    except sqlite3.Error as exc:
        conn.close()
        raise _readable_error(path, exc) from exc
    logger.info("Opened database %s (schema version %d)", path, result.current_version)
    return Database(path=path, connection=conn, migration=result)


_DAMAGED = {"SQLITE_NOTADB", "SQLITE_CORRUPT"}


def _readable_error(path: Path, exc: sqlite3.Error) -> AppError:
    if getattr(exc, "sqlite_errorname", None) in _DAMAGED:
        return AppError(
            "Your local data file is damaged or isn't a Habit Tracker database.",
            detail=f"{path}: {exc}",
        )
    # Permissions, a full disk, or another program holding a lock.
    return AppError("Your local data couldn't be opened.", detail=f"{path}: {exc}")
