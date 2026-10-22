"""CSV export of the raw log (PLAN.md 8)."""

from __future__ import annotations

import csv
import io
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.api import Api, AppContext
from app.db import Database, open_database
from app.db.settings import Settings
from app.events import EventChannel
from app.main import save_dialog
from app.paths import AppPaths
from app.rawlog.export import Cell, ExportError, guard, safe_file_name, write_csv
from app.rawlog.service import RawLogService
from app.rawlog.view import RawLogError
from tests.support.rawlog_data import known_set

NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
INDIA = "Asia/Kolkata"
ALL_COLUMNS = [
    "display_id",
    "task_name",
    "start",
    "end",
    "duration",
    "logged_minutes",
    "parent_task",
    "extra:notes",
    "extra:score",
    "extra:due",
    "extra:rel",
    "overlap",
    "issues",
]


@pytest.fixture
def db(app_paths: AppPaths) -> Iterator[Database]:
    database = open_database(app_paths.database)
    known_set(database)
    yield database
    database.close()


@pytest.fixture
def service(db: Database) -> RawLogService:
    return RawLogService(db=db.connection, settings=Settings(db.connection), clock=lambda: NOW)


class Chooser:
    """Stands in for the Save dialog: records the suggested name, returns ``answer``."""

    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.suggested: list[str] = []

    def __call__(self, suggested: str) -> str | None:
        self.suggested.append(suggested)
        return self.answer


def export(
    service: RawLogService,
    target: Path | None,
    columns: list[str] = ALL_COLUMNS,
    **request: Any,
) -> dict[str, Any]:
    body = {"time_zone": INDIA} | request
    chooser = Chooser(str(target) if target else None)
    result = dict(service.export(body, columns, chooser))
    result["suggested"] = chooser.suggested
    return result


def read_rows(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "the file starts with a UTF-8 BOM for Excel"
    text = raw[3:].decode("utf-8")
    return list(csv.reader(io.StringIO(text, newline="")))


def test_exports_the_rows_and_columns_on_screen(service: RawLogService, tmp_path: Path) -> None:
    target = tmp_path / "log.csv"
    result = export(service, target)
    assert result["status"] == "saved"
    assert result["rows"] == 6
    assert result["path"] == str(target.resolve())
    assert result["suggested"] == ["Work Log (test) raw log 2026-10-22.csv"]
    rows = read_rows(target)
    assert rows[0] == [
        "ID",
        "Task name",
        "Start (Asia/Kolkata)",
        "End (Asia/Kolkata)",
        "Duration (min)",
        "Logged minutes",
        "Parent task",
        "Notes",
        "Score",
        "Due (Asia/Kolkata)",
        "Related",
        "Overlap (min)",
        "Issues",
    ]
    # Newest start first, as on screen.
    assert [row[0] for row in rows[1:]] == ["3", "10", "2", "1", "WL-4", ""]
    p1 = rows[4]
    assert p1 == [
        "1",
        "Write docs",
        "2026-10-20 09:00",
        "2026-10-20 10:30",
        "90",
        "90",
        "https://www.notion.so/t1",
        'Commas, "quotes"\nand a second line',
        "4",
        "2026-10-25 09:30",
        "https://www.notion.so/r1\nhttps://www.notion.so/r2",
        "30",
        "",
    ]
    p2 = rows[3]
    assert p2[1] == ""  # a blank task name stays blank
    assert p2[6] == "https://www.notion.so/t2\nhttps://www.notion.so/t1"
    p3 = rows[2]
    assert p3[1] == "Réunion équipe"
    assert p3[2:4] == ["2026-10-21 23:00", "2026-10-22 01:00"]  # crosses midnight
    assert p3[7] == "日本語のメモ"
    assert p3[9] == "2026-10-30"  # a date without a time
    assert p3[12] == "Logged 200 min, but Start → End is 120 min."
    p4 = rows[1]
    assert p4[3] == ""  # no end time
    assert p4[4] == ""  # so no duration


def test_csv_quoting_and_line_ends(service: RawLogService, tmp_path: Path) -> None:
    target = tmp_path / "log.csv"
    export(service, target, ["display_id", "extra:notes"], filters={"search": "write"})
    raw = target.read_bytes()[3:].decode("utf-8")
    assert raw == 'ID,Notes\r\n1,"Commas, ""quotes""\nand a second line"\r\n'


def test_formulas_are_neutralised_but_negative_numbers_stay(
    service: RawLogService, tmp_path: Path
) -> None:
    target = tmp_path / "log.csv"
    export(service, target, ["task_name", "extra:score"])
    rows = read_rows(target)
    names = {row[0] for row in rows[1:]}
    assert "'=SUM(A1)" in names
    assert "-2" in {row[1] for row in rows[1:]}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+44 20", "'+44 20"),
        ("-rm", "'-rm"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("safe", "safe"),
        ("", ""),
    ],
)
def test_guard(text: str, expected: str) -> None:
    assert guard(Cell(text)) == expected
    assert guard(Cell(text, formula_safe=True)) == text


def test_column_order_and_subset_follow_the_screen(service: RawLogService, tmp_path: Path) -> None:
    target = tmp_path / "log.csv"
    export(
        service,
        target,
        ["issues", "task_name", "duration"],
        filters={"issues": "any"},
        sort={"column": "task_name", "direction": "asc"},
    )
    rows = read_rows(target)
    assert rows[0] == ["Issues", "Task name", "Duration (min)"]
    assert [row[1] for row in rows[1:]] == ["'=SUM(A1)", "Backwards", "No end", "Réunion équipe"]


def test_times_follow_the_time_zone_sent(service: RawLogService, tmp_path: Path) -> None:
    target = tmp_path / "log.csv"
    export(service, target, ["start"], time_zone="America/New_York", filters={"search": "write"})
    assert read_rows(target) == [["Start (America/New_York)"], ["2026-10-19 23:30"]]


def test_a_missing_extension_gets_csv(service: RawLogService, tmp_path: Path) -> None:
    result = export(service, tmp_path / "plain", ["task_name"])
    assert result["path"] == str((tmp_path / "plain.csv").resolve())
    assert (tmp_path / "plain.csv").exists()


def test_nothing_to_export(service: RawLogService, tmp_path: Path) -> None:
    result = export(service, tmp_path / "x.csv", filters={"search": "no such task"})
    assert result["status"] == "empty"
    assert result["suggested"] == []  # the dialog never opens
    assert not (tmp_path / "x.csv").exists()


def test_cancelling_the_dialog(service: RawLogService) -> None:
    result = export(service, None)
    assert result["status"] == "cancelled"
    assert result["path"] is None
    assert len(result["suggested"]) == 1


@pytest.mark.parametrize("columns", [[], "task_name", ["task_name", "extra:gone"], [5]])
def test_bad_columns_are_refused(service: RawLogService, columns: Any, tmp_path: Path) -> None:
    with pytest.raises(RawLogError):
        service.export({"time_zone": INDIA}, columns, Chooser(str(tmp_path / "x.csv")))


def test_a_locked_file_is_explained_and_left_intact(
    service: RawLogService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "exports"
    folder.mkdir()
    target = folder / "log.csv"
    target.write_text("old contents", encoding="utf-8")

    def locked(self: Path, other: Path) -> Path:
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(ExportError, match="open in another program, such as Excel") as caught:
        export(service, target)
    assert caught.value.state == "export_failed"
    assert target.read_text(encoding="utf-8") == "old contents"
    assert [p.name for p in folder.iterdir()] == ["log.csv"]  # no temporary file left


@pytest.mark.skipif(sys.platform != "win32", reason="Windows locks files that are open")
def test_a_file_open_in_another_program(service: RawLogService, tmp_path: Path) -> None:
    target = tmp_path / "log.csv"
    target.write_text("old", encoding="utf-8")
    with target.open("r", encoding="utf-8"), pytest.raises(ExportError, match="Excel"):
        export(service, target)
    assert target.read_text(encoding="utf-8") == "old"


def test_a_folder_that_doesnt_exist(service: RawLogService, tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="couldn't be saved"):
        export(service, tmp_path / "missing" / "log.csv")


def test_overwriting_an_existing_file(service: RawLogService, tmp_path: Path) -> None:
    target = tmp_path / "log.csv"
    target.write_text("old", encoding="utf-8")
    export(service, target, ["task_name"])
    assert read_rows(target)[0] == ["Task name"]


def test_write_csv_counts_rows(tmp_path: Path) -> None:
    written = write_csv(tmp_path / "a.csv", ["A"], [[Cell("1")], [Cell("2")]])
    assert written == 2


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Work Log raw log 2026-10-22", "Work Log raw log 2026-10-22.csv"),
        ('A/B: "C"?', "A-B- -C--.csv"),
        ("   ", "Raw log.csv"),
        ("log.CSV", "log.CSV"),
    ],
)
def test_safe_file_names(name: str, expected: str) -> None:
    assert safe_file_name(name) == expected


# --- through the bridge --------------------------------------------------------------------


def make_api(app_paths: AppPaths, database: Database, **kw: Any) -> Api:
    rawlog = RawLogService(db=database.connection, settings=Settings(database.connection))
    context = AppContext(
        mode="normal",
        paths=app_paths,
        database=database,
        events=EventChannel(),
        rawlog=rawlog,
        **kw,
    )
    return Api(context)


def test_export_and_show_in_folder_through_the_bridge(
    app_paths: AppPaths, db: Database, tmp_path: Path
) -> None:
    revealed: list[Path] = []
    target = tmp_path / "out.csv"
    api = make_api(
        app_paths, db, choose_save_path=lambda _name: str(target), reveal_file=revealed.append
    )
    # Nothing exported yet: there's no file to show.
    assert api.show_exported_file()["ok"] is False
    response = api.export_raw_log({"time_zone": INDIA}, ["task_name"])
    assert response == {
        "ok": True,
        "data": {"status": "saved", "path": str(target.resolve()), "rows": 6},
    }
    assert api.show_exported_file() == {"ok": True, "data": None}
    assert revealed == [target.resolve()]


def test_export_errors_reach_the_ui_with_a_code(
    app_paths: AppPaths, db: Database, tmp_path: Path
) -> None:
    api = make_api(app_paths, db, choose_save_path=lambda _n: str(tmp_path / "no" / "x.csv"))
    response = api.export_raw_log({"time_zone": INDIA}, ["task_name"])
    assert response["ok"] is False
    assert response["error"]["code"] == "export_failed"  # type: ignore[typeddict-item]


def test_export_without_a_window(app_paths: AppPaths, db: Database) -> None:
    response = make_api(app_paths, db).export_raw_log({"time_zone": INDIA}, ["task_name"])
    assert response["ok"] is False


# --- the native dialog ---------------------------------------------------------------------


class DialogWindow:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def create_file_dialog(self, dialog_type: int, **kwargs: Any) -> object:
        self.calls.append({"type": dialog_type, **kwargs})
        return self.result


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("C:\\out\\log.csv", "C:\\out\\log.csv"),
        (("C:\\out\\log.csv",), "C:\\out\\log.csv"),
        (None, None),
        ((), None),
        ("", None),
    ],
)
def test_save_dialog(result: object, expected: str | None) -> None:
    import webview

    window = DialogWindow(result)
    assert save_dialog(window)("Work log.csv") == expected
    assert window.calls == [
        {
            "type": webview.FileDialog.SAVE,
            "save_filename": "Work log.csv",
            "file_types": ("CSV file (*.csv)", "All files (*.*)"),
        }
    ]
