from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db import open_database
from app.db.connection import connect, transaction
from app.db.migrator import (
    DatabaseTooNewError,
    Migration,
    MigrationError,
    current_version,
    discover,
    migrate,
    validate,
)
from app.errors import AppError

# PLAN.md section 11: work_logs columns in order, with their declared types.
WORK_LOGS_COLUMNS = [
    ("page_id", "TEXT"),
    ("display_id", "TEXT"),
    ("task_name", "TEXT"),
    ("start_utc", "TEXT"),
    ("end_utc", "TEXT"),
    ("parent_task_id", "TEXT"),
    ("logged_minutes", "REAL"),
    ("extra_fields", "TEXT"),
    ("issues", "TEXT"),
    ("created_time", "TEXT"),
    ("last_edited_time", "TEXT"),
    ("synced_at", "TEXT"),
]

UTC = "2026-10-17T12:11:00.000Z"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


def schema_dump(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type, name"
    )
    return [tuple(row) for row in rows]


def insert_log(conn: sqlite3.Connection, **overrides: object) -> None:
    row: dict[str, object] = {
        "page_id": "page-1",
        "start_utc": UTC,
        "end_utc": UTC,
        "created_time": UTC,
        "last_edited_time": UTC,
        "synced_at": UTC,
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO work_logs ({columns}) VALUES ({placeholders})", tuple(row.values()))  # noqa: S608


# --- A new database ---------------------------------------------------------------------------


def test_new_database_migrates_to_latest(conn: sqlite3.Connection) -> None:
    latest = len(discover())
    result = migrate(conn)
    assert result.applied == tuple(range(1, latest + 1))
    assert result.current_version == latest
    assert current_version(conn) == latest
    rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
    assert [(r["version"], r["name"]) for r in rows] == [(m.version, m.name) for m in discover()]


def test_schema_matches_plan(conn: sqlite3.Connection) -> None:
    migrate(conn)
    columns = [(r["name"], r["type"]) for r in conn.execute("PRAGMA table_info(work_logs)")]
    assert columns == WORK_LOGS_COLUMNS
    primary = [r["name"] for r in conn.execute("PRAGMA table_info(work_logs)") if r["pk"]]
    assert primary == ["page_id"]

    indexes = {
        r["name"]: [c["name"] for c in conn.execute(f"PRAGMA index_info({r['name']})")]
        for r in conn.execute("PRAGMA index_list(work_logs)")
        if r["origin"] == "c"
    }
    assert indexes == {
        "idx_work_logs_start_utc": ["start_utc"],
        "idx_work_logs_parent_task_id": ["parent_task_id"],
    }

    settings = [
        (r["name"], r["type"], r["pk"]) for r in conn.execute("PRAGMA table_info(settings)")
    ]
    assert settings == [("key", "TEXT", 1), ("value", "TEXT", 0)]

    strict = {
        r["name"]: r["strict"] for r in conn.execute("PRAGMA table_list") if r["schema"] == "main"
    }
    assert strict["work_logs"] == 1
    assert strict["settings"] == 1


def test_defaults_for_json_columns(conn: sqlite3.Connection) -> None:
    migrate(conn)
    insert_log(conn)
    row = conn.execute("SELECT extra_fields, issues FROM work_logs").fetchone()
    assert (row["extra_fields"], row["issues"]) == ("{}", "[]")


# --- Re-running -------------------------------------------------------------------------------


def test_rerunning_is_a_no_op(conn: sqlite3.Connection) -> None:
    migrate(conn)
    before = schema_dump(conn)
    insert_log(conn, task_name="kept")
    conn.execute("INSERT INTO settings (key, value) VALUES ('week_start', '\"monday\"')")

    for _ in range(3):
        result = migrate(conn)
        assert result.applied == ()

    assert schema_dump(conn) == before
    assert conn.execute("SELECT task_name FROM work_logs").fetchone()[0] == "kept"
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(discover())


def test_reopening_a_database_file(tmp_path: Path) -> None:
    path = tmp_path / "habit_tracker.db"
    first = open_database(path)
    assert first.migration.applied == (1,)
    insert_log(first.connection)
    first.close()

    second = open_database(path)
    assert second.migration.applied == ()
    assert second.schema_version == len(discover())
    assert second.connection.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0] == 1
    assert second.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert second.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    second.close()


def test_new_migrations_apply_on_top_of_existing_data(conn: sqlite3.Connection) -> None:
    base = discover()
    migrate(conn, base)
    insert_log(conn)
    extra = Migration(
        version=len(base) + 1,
        name="add_note",
        sql="ALTER TABLE work_logs ADD COLUMN note TEXT;",
    )
    result = migrate(conn, [*base, extra])
    assert result.applied == (extra.version,)
    assert conn.execute("SELECT note FROM work_logs").fetchone()[0] is None


# --- Failures ---------------------------------------------------------------------------------


def test_failed_migration_rolls_back_completely(conn: sqlite3.Connection) -> None:
    base = discover()
    migrate(conn, base)
    broken = Migration(
        version=len(base) + 1,
        name="broken",
        sql="CREATE TABLE half_done (id INTEGER) STRICT;\nCREATE TABLE oops (;",
    )
    with pytest.raises(MigrationError) as caught:
        migrate(conn, [*base, broken])
    assert "0002_broken" in (caught.value.detail or "")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
    assert "half_done" not in tables
    assert current_version(conn) == len(base)
    assert not conn.in_transaction


def test_changed_migration_is_refused(conn: sqlite3.Connection) -> None:
    base = discover()
    migrate(conn, base)
    edited = [Migration(m.version, m.name, m.sql + "\n-- edited") for m in base]
    with pytest.raises(MigrationError, match="doesn't match"):
        migrate(conn, edited)


def test_line_endings_do_not_change_the_checksum() -> None:
    lf = Migration(1, "x", "CREATE TABLE t (a TEXT);\n")
    crlf = Migration(1, "x", "CREATE TABLE t (a TEXT);\r\n")
    assert lf.checksum == crlf.checksum


def test_database_from_a_newer_app_is_refused(conn: sqlite3.Connection) -> None:
    base = discover()
    future = Migration(len(base) + 1, "future", "CREATE TABLE future (id INTEGER);")
    migrate(conn, [*base, future])
    with pytest.raises(DatabaseTooNewError, match="newer version"):
        migrate(conn, base)


def test_damaged_database_file_gives_a_readable_error(tmp_path: Path) -> None:
    path = tmp_path / "habit_tracker.db"
    path.write_bytes(b"not a database" * 200)
    with pytest.raises(AppError, match="damaged"):
        open_database(path)


@pytest.mark.parametrize(
    ("migrations", "message"),
    [
        ([Migration(2, "skip", "SELECT 1;")], "no gaps"),
        ([Migration(1, "a", "SELECT 1;"), Migration(1, "b", "SELECT 1;")], "no gaps"),
        ([Migration(1, "empty", "  \n")], "empty"),
        ([Migration(1, "tx", "BEGIN;\nCREATE TABLE t (a);\nCOMMIT;")], "transaction"),
        ([Migration(1, "sp", "savepoint x;")], "transaction"),
    ],
)
def test_validation_rejects_malformed_sets(migrations: list[Migration], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate(migrations)


def test_transaction_words_in_comments_are_allowed() -> None:
    validate([Migration(1, "ok", "-- BEGIN is mentioned here\nCREATE TABLE t (a TEXT);")])


def test_bundled_migration_files_are_well_formed() -> None:
    migrations = discover()
    assert migrations, "no migrations found"
    assert migrations[0].label == "0001_initial"


# --- Constraints ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column", ["start_utc", "end_utc", "created_time", "last_edited_time", "synced_at"]
)
@pytest.mark.parametrize(
    "value", ["2026-10-17T17:41:00+05:30", "2026-10-17 12:11:00", "2026-10-17", "yesterday"]
)
def test_timestamps_must_be_utc(conn: sqlite3.Connection, column: str, value: str) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_log(conn, **{column: value})


def test_missing_times_are_allowed(conn: sqlite3.Connection) -> None:
    # Entries with missing times are imported and flagged, never rejected (PLAN.md 5).
    migrate(conn)
    insert_log(conn, start_utc=None, end_utc=None)


def test_invalid_ranges_are_allowed(conn: sqlite3.Connection) -> None:
    migrate(conn)
    insert_log(conn, start_utc="2026-10-17T13:48:00.000Z", end_utc="2026-10-17T13:30:00.000Z")


@pytest.mark.parametrize(
    ("column", "value"),
    [("extra_fields", "not json"), ("extra_fields", "[]"), ("issues", "{}"), ("issues", "{")],
)
def test_json_columns_are_checked(conn: sqlite3.Connection, column: str, value: str) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_log(conn, **{column: value})


def test_strict_types(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_log(conn, logged_minutes="lots")


def test_settings_values_must_be_json(conn: sqlite3.Connection) -> None:
    migrate(conn)
    conn.execute("INSERT INTO settings (key, value) VALUES ('streak_threshold_minutes', '0')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO settings (key, value) VALUES ('week_start', 'monday')")


def test_transaction_helper_rolls_back(conn: sqlite3.Connection) -> None:
    migrate(conn)

    def write_then_fail() -> None:
        with transaction(conn):
            insert_log(conn)
            raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        write_then_fail()
    assert conn.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0] == 0
    with transaction(conn):
        insert_log(conn)
    assert conn.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0] == 1


def test_locked_or_unopenable_database_gives_a_readable_error(tmp_path: Path) -> None:
    # A folder where the database file should be: SQLite can't open it.
    path = tmp_path / "habit_tracker.db"
    path.mkdir()
    with pytest.raises(AppError, match="couldn't be opened"):
        open_database(path)
