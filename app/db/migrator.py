"""Versioned schema migrations.

Migrations are SQL files in ``app/db/migrations/`` named ``NNNN_short_name.sql``, numbered from
0001 with no gaps. Each one runs in its own transaction together with its bookkeeping row, so a
migration is either fully applied or not applied at all.

The ``schema_migrations`` table records what has been applied, with a checksum of each file.
``PRAGMA user_version`` mirrors the latest version so the schema version is visible to any
SQLite tool. Running :func:`migrate` again is always safe: it applies only what is missing.

Rules for writing migrations:

* Never edit a migration that has been merged to ``main``; add a new one. The checksum check
  refuses to run against a database whose applied migrations no longer match their files.
* Don't use transaction statements (``BEGIN``, ``COMMIT``, ``SAVEPOINT``...); the runner owns
  the transaction.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Final

from app.db.connection import transaction
from app.errors import AppError

logger = logging.getLogger(__name__)

MIGRATIONS_PACKAGE: Final = "app.db"
MIGRATIONS_DIR: Final = "migrations"

_FILE_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_TRANSACTION_STATEMENT = re.compile(
    r"^\s*(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE)\b", re.IGNORECASE | re.MULTILINE
)
_LINE_COMMENT = re.compile(r"--[^\n]*")

_BOOKKEEPING_DDL: Final = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY NOT NULL,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL
) STRICT
"""


class MigrationError(AppError):
    """The database schema couldn't be brought up to date."""


class DatabaseTooNewError(MigrationError):
    """The database was migrated by a newer version of the app."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        normalized = self.sql.replace("\r\n", "\n")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @property
    def label(self) -> str:
        return f"{self.version:04d}_{self.name}"


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied: tuple[int, ...]
    current_version: int


def validate(migrations: Sequence[Migration]) -> None:
    """Check numbering and content rules. Raises ``ValueError`` for a malformed set."""
    versions = [m.version for m in migrations]
    expected = list(range(1, len(migrations) + 1))
    if versions != expected:
        raise ValueError(
            f"Migrations must be numbered 1..{len(migrations)} with no gaps: {versions}"
        )
    for migration in migrations:
        if not migration.sql.strip():
            raise ValueError(f"Migration {migration.label} is empty")
        if _TRANSACTION_STATEMENT.search(_LINE_COMMENT.sub("", migration.sql)):
            raise ValueError(f"Migration {migration.label} must not contain transaction statements")


def discover() -> list[Migration]:
    """Load the migrations bundled with the app, sorted by version."""
    folder = resources.files(MIGRATIONS_PACKAGE).joinpath(MIGRATIONS_DIR)
    migrations: list[Migration] = []
    for entry in folder.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        match = _FILE_NAME.match(entry.name)
        if match is None:
            raise ValueError(f"Badly named migration file: {entry.name}")
        migrations.append(
            Migration(
                version=int(match["version"]),
                name=match["name"],
                sql=entry.read_text(encoding="utf-8"),
            )
        )
    migrations.sort(key=lambda m: m.version)
    validate(migrations)
    return migrations


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _applied(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    rows = conn.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version")
    return {int(row["version"]): row for row in rows}


def _check_history(applied: dict[int, sqlite3.Row], known: dict[int, Migration]) -> None:
    newer = sorted(v for v in applied if v not in known)
    if newer:
        raise DatabaseTooNewError(
            "Your local data was created by a newer version of Habit Tracker. "
            "Install the latest version to open it.",
            detail=f"Database schema version {max(newer)}; this app supports up to {len(known)}.",
        )
    for version, row in applied.items():
        if row["checksum"] != known[version].checksum:
            raise MigrationError(
                "Your local data doesn't match this version of Habit Tracker.",
                detail=f"Migration {known[version].label} has changed since it was applied.",
            )


def migrate(
    conn: sqlite3.Connection, migrations: Iterable[Migration] | None = None
) -> MigrationResult:
    """Apply every pending migration in order. Safe to call on every start."""
    ordered = sorted(discover() if migrations is None else migrations, key=lambda m: m.version)
    validate(ordered)
    known = {m.version: m for m in ordered}

    conn.execute(_BOOKKEEPING_DDL)
    _check_history(_applied(conn), known)

    newly_applied: list[int] = []
    for migration in ordered:
        with transaction(conn):
            # Re-read inside the write lock in case another connection migrated meanwhile.
            if migration.version in _applied(conn):
                continue
            logger.info("Applying database migration %s", migration.label)
            try:
                conn.executescript(migration.sql)
            except sqlite3.Error as exc:
                raise MigrationError(
                    "Your local data couldn't be updated for this version of Habit Tracker.",
                    detail=f"Migration {migration.label} failed: {exc}",
                ) from exc
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at)"
                " VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum, _utc_now()),
            )
            conn.execute(f"PRAGMA user_version = {int(migration.version)}")
        newly_applied.append(migration.version)

    version = current_version(conn)
    if newly_applied:
        logger.info("Database is at schema version %d", version)
    return MigrationResult(applied=tuple(newly_applied), current_version=version)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
