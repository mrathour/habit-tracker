"""``--uninstall-cleanup``: the uninstaller's "also delete my data and Notion sign-in" option."""

from __future__ import annotations

from pathlib import Path

import keyring
import pytest

from app import main
from app.db import open_database
from app.notion.credentials import SERVICE_NAME, CredentialStore, StoredCredential, utc_now
from app.paths import AppPaths
from app.redaction import Secret
from app.uninstall import Outcome, remove_local_data, run_cleanup
from tests.support.memory_keyring import MemoryKeyring


class FakeService:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.revoked: list[str] = []
        self.closed = False

    def revoke(self, token: Secret) -> None:
        if self.fails:
            raise ConnectionError("offline")
        self.revoked.append(token.reveal())

    def close(self) -> None:
        self.closed = True


def store_credential(paths: AppPaths, kind: str) -> None:
    CredentialStore(paths.credential_account).save(
        StoredCredential(
            kind=kind,  # type: ignore[arg-type]
            access_token=Secret("ntn_access_for_uninstall_test"),
            refresh_token=Secret("nrt_refresh_for_uninstall_test") if kind == "oauth" else None,
            obtained_at=utc_now(),
        )
    )


def make_data(paths: AppPaths) -> None:
    paths.ensure()
    open_database(paths.database).close()
    (paths.logs_dir / "habit-tracker.log").write_text("log", encoding="utf-8")
    (paths.logs_dir / "habit-tracker.log.1").write_text("old log", encoding="utf-8")
    paths.database.with_name(paths.database.name + "-wal").write_text("", encoding="utf-8")


def run(paths: AppPaths, service: FakeService) -> int:
    return run_cleanup(paths, service)  # type: ignore[arg-type]


def test_notion_sign_in_is_cancelled_then_everything_deleted(app_paths: AppPaths) -> None:
    make_data(app_paths)
    store_credential(app_paths, "oauth")
    service = FakeService()
    assert run(app_paths, service) == Outcome.DONE
    assert service.revoked == ["ntn_access_for_uninstall_test"]
    assert service.closed
    assert MemoryKeyring.store == {}
    assert not app_paths.root.exists()


def test_offline_still_deletes_and_reports_it(app_paths: AppPaths) -> None:
    make_data(app_paths)
    store_credential(app_paths, "oauth")
    code = run(app_paths, FakeService(fails=True))
    assert code == Outcome.NOT_REVOKED
    assert MemoryKeyring.store == {}
    assert not app_paths.root.exists()


@pytest.mark.parametrize(
    ("kind", "flag"), [("internal", Outcome.PASTED_INTERNAL), ("pat", Outcome.PASTED_PAT)]
)
def test_pasted_tokens_are_deleted_and_explained(
    app_paths: AppPaths, kind: str, flag: Outcome
) -> None:
    make_data(app_paths)
    store_credential(app_paths, kind)
    service = FakeService()
    assert run(app_paths, service) == flag
    assert service.revoked == []  # the app can't cancel pasted tokens
    assert MemoryKeyring.store == {}


def test_nothing_stored_is_fine(app_paths: AppPaths) -> None:
    assert run(app_paths, FakeService()) == Outcome.DONE
    assert not app_paths.root.exists()


def test_never_connected_and_no_folder(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "never-created")
    assert run(paths, FakeService()) == Outcome.DONE


def test_damaged_entry_is_still_deleted(app_paths: AppPaths) -> None:
    keyring.set_password(SERVICE_NAME, app_paths.credential_account, "{not json")
    assert run(app_paths, FakeService()) == Outcome.DONE
    assert MemoryKeyring.store == {}


def test_credential_manager_failure_is_reported(
    app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_credential(app_paths, "internal")

    def refuse(*_args: object) -> None:
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(keyring, "delete_password", refuse)
    code = run(app_paths, FakeService())
    assert code & Outcome.CREDENTIAL_KEPT
    assert code & Outcome.PASTED_INTERNAL


def test_only_the_apps_own_files_are_deleted(tmp_path: Path) -> None:
    """A data folder set with HABIT_TRACKER_HOME may hold other files: those stay."""
    paths = AppPaths(tmp_path / "shared", instance_id="abc")
    make_data(paths)
    keep = paths.root / "my notes.txt"
    keep.write_text("mine", encoding="utf-8")
    assert remove_local_data(paths) == Outcome.DONE
    assert keep.read_text(encoding="utf-8") == "mine"
    assert sorted(p.name for p in paths.root.iterdir()) == ["my notes.txt"]


def test_read_only_log_files_are_deleted(app_paths: AppPaths) -> None:
    make_data(app_paths)
    (app_paths.logs_dir / "habit-tracker.log.1").chmod(0o444)
    assert remove_local_data(app_paths) == Outcome.DONE
    assert not app_paths.root.exists()


def test_locked_database_is_reported(app_paths: AppPaths) -> None:
    make_data(app_paths)
    database = open_database(app_paths.database)  # open, so Windows won't delete it
    try:
        code = remove_local_data(app_paths)
    finally:
        database.close()
    if code:  # Windows refuses to delete an open file
        assert code == Outcome.DATA_KEPT
        assert app_paths.database.exists()


def test_unexpected_failure_returns_failed(
    app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(_paths: AppPaths) -> Outcome:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.uninstall.remove_local_data", explode)
    service = FakeService()
    assert run(app_paths, service) == Outcome.FAILED
    assert service.closed


def test_command_line_entry(monkeypatch: pytest.MonkeyPatch, app_paths: AppPaths) -> None:
    """``--uninstall-cleanup`` runs before logging is set up, so it never recreates the folder."""
    calls: list[str] = []

    def cleanup() -> int:
        calls.append("x")
        return 6

    monkeypatch.setattr(main, "cleanup_from_installer", cleanup)
    monkeypatch.setattr(main, "configure_logging", lambda *_a, **_k: pytest.fail("logged"))
    assert main.main(["--uninstall-cleanup"]) == 6
    assert calls == ["x"]
