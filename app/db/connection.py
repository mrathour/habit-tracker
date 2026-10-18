"""SQLite connections.

Connections use explicit transaction control (``autocommit=True``): nothing is wrapped in a
transaction implicitly, and code that needs one uses :func:`transaction`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from app.errors import AppError

#: STRICT tables need 3.37; the JSON functions are built in from 3.38.
MIN_SQLITE_VERSION: Final = (3, 38, 0)
BUSY_TIMEOUT_MS: Final = 5000


def check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        needed = ".".join(map(str, MIN_SQLITE_VERSION))
        raise AppError(
            "This copy of Python's SQLite is too old for Habit Tracker.",
            detail=f"Found SQLite {sqlite3.sqlite_version}; {needed} or newer is required.",
        )


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database at ``path`` (``":memory:"`` for tests), creating it if needed.

    The connection may be used from any thread (bridge calls each run on their own thread), but
    callers must not interleave transactions on it from several threads at once.
    """
    check_sqlite_version()
    conn = sqlite3.connect(path, autocommit=True, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[None]:
    """Run the block in one transaction: commit on success, roll back on any exception.

    ``immediate`` takes the write lock up front, so the transaction can't fail half-way through
    because another connection started writing.
    """
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
