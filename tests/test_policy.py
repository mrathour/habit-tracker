"""Privacy-policy change notices (PLAN.md 13)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from app.api import Api, AppContext
from app.db import Database, open_database
from app.db.settings import Settings
from app.errors import AppError
from app.events import EventChannel
from app.paths import AppPaths
from app.policy import (
    ACKNOWLEDGED_KEY,
    POLICY_FILE,
    BundledPolicy,
    PolicyChange,
    PolicyFileError,
    PolicyNotAcknowledgedError,
    PolicyService,
    load_policy,
)

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def policy(version: int) -> BundledPolicy:
    changes = tuple(
        PolicyChange(v, f"2026-1{v - 1}-01", (f"Change number {v}.",))
        for v in range(1, version + 1)
    )
    return BundledPolicy(version=version, url="https://example.test/privacy", changes=changes)


@pytest.fixture
def database(app_paths: AppPaths) -> Iterator[Database]:
    db = open_database(app_paths.database)
    yield db
    db.close()


@pytest.fixture
def settings(database: Database) -> Settings:
    return Settings(database.connection)


def service(settings: Settings, version: int, *, connected: bool = False) -> PolicyService:
    return PolicyService(settings=settings, has_connected=lambda: connected, policy=policy(version))


# --- The bundled file ---------------------------------------------------------------------


def test_the_bundled_policy_file_is_valid() -> None:
    bundled = load_policy()
    assert bundled.version >= 1
    assert bundled.url == "https://habit-tracker.mrathour.workers.dev/privacy"
    assert bundled.changes[-1].version == bundled.version
    assert POLICY_FILE.parent.name == "app"


def test_the_packaging_test_policy_is_newer_than_the_bundled_one() -> None:
    """The file used for the "newer policy" test build (PLAN.md 15) stays one version ahead."""
    test_policy = load_policy(PACKAGING / "test-policy.json")
    assert test_policy.version == load_policy().version + 1
    assert test_policy.url == load_policy().url


def write(tmp_path: Path, body: Any) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


GOOD: dict[str, Any] = {
    "version": 2,
    "url": "https://example.test/privacy",
    "changes": [
        {"version": 1, "date": "2026-10-18", "summary": ["First."]},
        {"version": 2, "date": "2026-11-01", "summary": ["Second.", "And more."]},
    ],
}


def test_load_a_good_file(tmp_path: Path) -> None:
    loaded = load_policy(write(tmp_path, GOOD))
    assert loaded.version == 2
    assert [c.version for c in loaded.changes_after(1)] == [2]
    assert loaded.changes[1].summary == ("Second.", "And more.")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {**GOOD, "version": 0},
        {**GOOD, "version": True},
        {**GOOD, "version": "2"},
        {**GOOD, "url": "http://example.test/privacy"},
        {**GOOD, "changes": {}},
        {**GOOD, "changes": [1]},
        {**GOOD, "version": 3},  # no summary for the bundled version
        {**GOOD, "changes": list(reversed(GOOD["changes"]))},
        {**GOOD, "changes": [GOOD["changes"][0], GOOD["changes"][0], GOOD["changes"][1]]},
        {**GOOD, "changes": [{"version": 2, "date": "2026-11-01", "summary": []}]},
        {**GOOD, "changes": [{"version": 2, "date": "2026-11-01", "summary": ["  "]}]},
        {**GOOD, "changes": [{"version": 2, "date": "soon", "summary": ["x"]}]},
    ],
)
def test_malformed_files_are_refused(tmp_path: Path, body: Any) -> None:
    with pytest.raises(PolicyFileError):
        load_policy(write(tmp_path, body))


def test_unreadable_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PolicyFileError):
        load_policy(path)
    with pytest.raises(PolicyFileError):
        load_policy(tmp_path / "missing.json")


# --- When the notice shows ----------------------------------------------------------------


def test_fresh_install_shows_no_notice(settings: Settings) -> None:
    policies = service(settings, 3)
    assert policies.acknowledged_version() is None
    assert policies.notice() is None
    policies.require_acknowledged()  # nothing is blocked


def test_connecting_saves_the_bundled_version(settings: Settings) -> None:
    service(settings, 1).record_connected()
    assert settings.get(ACKNOWLEDGED_KEY) == 1
    assert service(settings, 1, connected=True).notice() is None


def test_newer_build_shows_the_changes_since_the_acknowledged_version(
    settings: Settings,
) -> None:
    settings.set(ACKNOWLEDGED_KEY, 1)
    notice = service(settings, 3, connected=True).notice()
    assert notice is not None
    assert notice["version"] == 3
    assert notice["acknowledged_version"] == 1
    assert notice["url"] == "https://example.test/privacy"
    assert [c["version"] for c in notice["changes"]] == [2, 3]
    assert notice["changes"][0]["summary"] == ["Change number 2."]


def test_notice_blocks_until_acknowledged_then_never_shows_again(settings: Settings) -> None:
    settings.set(ACKNOWLEDGED_KEY, 1)
    policies = service(settings, 2, connected=True)
    with pytest.raises(PolicyNotAcknowledgedError) as caught:
        policies.require_acknowledged()
    assert caught.value.state == "policy_notice"
    policies.acknowledge(2)
    assert settings.get(ACKNOWLEDGED_KEY) == 2
    assert policies.notice() is None
    policies.require_acknowledged()
    # A relaunch of the same build shows nothing either.
    assert service(settings, 2, connected=True).notice() is None


@pytest.mark.parametrize("version", [1, 3, "2", None, True, 2.0])
def test_only_the_shown_version_can_be_acknowledged(settings: Settings, version: object) -> None:
    settings.set(ACKNOWLEDGED_KEY, 1)
    policies = service(settings, 2, connected=True)
    with pytest.raises(AppError):
        policies.acknowledge(version)
    assert settings.get(ACKNOWLEDGED_KEY) == 1


def test_connected_before_notices_existed_counts_as_the_first_version(
    settings: Settings,
) -> None:
    assert service(settings, 1, connected=True).notice() is None
    notice = service(settings, 2, connected=True).notice()
    assert notice is not None
    assert notice["acknowledged_version"] == 1
    assert [c["version"] for c in notice["changes"]] == [2]


def test_damaged_setting_falls_back(settings: Settings) -> None:
    settings.set(ACKNOWLEDGED_KEY, "two")
    assert service(settings, 2).notice() is None  # never connected: a fresh install
    notice = service(settings, 2, connected=True).notice()
    assert notice is not None
    assert notice["acknowledged_version"] == 1


def test_an_older_build_never_lowers_the_saved_version(settings: Settings) -> None:
    settings.set(ACKNOWLEDGED_KEY, 3)
    older = service(settings, 2, connected=True)
    assert older.notice() is None
    older.record_connected()
    assert settings.get(ACKNOWLEDGED_KEY) == 3


# --- The bridge ---------------------------------------------------------------------------


class Sync:
    started = 0

    def start(self, kind: object) -> dict[str, object]:
        self.started += 1
        return {"kind": kind}


class Connection:
    calls = 0

    def connect_with_token(self, kind: object, token: object) -> dict[str, object]:
        self.calls += 1
        return {}

    def start_sign_in(self) -> dict[str, object]:
        self.calls += 1
        return {}


def test_bridge_blocks_syncing_and_connecting_until_acknowledged(
    app_paths: AppPaths, database: Database, settings: Settings
) -> None:
    settings.set(ACKNOWLEDGED_KEY, 1)
    sync, connection = Sync(), Connection()
    context = AppContext(
        mode="normal",
        paths=app_paths,
        database=database,
        events=EventChannel(),
        policy=service(settings, 2, connected=True),
        sync=sync,  # type: ignore[arg-type]
        connection=connection,  # type: ignore[arg-type]
    )
    api = Api(context)

    notice: dict[str, Any] = dict(api.get_policy_notice())
    assert notice["ok"] is True
    assert notice["data"]["version"] == 2
    assert api.get_app_info()["data"]["policy_version"] == 2  # type: ignore[typeddict-item]

    blocked: list[dict[str, Any]] = [
        dict(api.start_sync("auto")),
        dict(api.connect_with_token("internal", "x")),
        dict(api.start_sign_in()),
    ]
    for response in blocked:
        assert response["ok"] is False
        assert response["error"]["code"] == "policy_notice"
    assert sync.started == 0
    assert connection.calls == 0

    wrong = api.acknowledge_policy(1)
    assert wrong["ok"] is False
    assert api.acknowledge_policy(2)["ok"] is True
    assert api.get_policy_notice() == {"ok": True, "data": None}
    assert api.start_sync("auto")["ok"] is True
    assert sync.started == 1


def test_bridge_without_a_started_app(app_paths: AppPaths) -> None:
    api = Api(AppContext(mode="normal", paths=app_paths, database=None, events=EventChannel()))
    assert api.get_policy_notice()["ok"] is False
    assert api.get_app_info()["data"]["policy_version"] is None  # type: ignore[typeddict-item]


# --- The real "connected before" check (issue #13) -----------------------------------------
#
# These go through ``build_services``, so they test the check the app actually uses, not a
# stand-in. The build bundles policy version 2 (packaging/test-policy.json), as the policytest
# build does.


@pytest.fixture
def newer_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.policy.POLICY_FILE", PACKAGING / "test-policy.json")


def real_service(app_paths: AppPaths, database: Database) -> PolicyService:
    from app.main import build_services

    return build_services(app_paths, database, EventChannel()).policy


def add_entry(app_paths: AppPaths, database: Database, settings: Settings) -> None:
    """An entry kept after disconnecting with "keep local data"."""
    database.connection.execute(
        "INSERT INTO work_logs (page_id, issues, extra_fields, parent_task_ids, created_time,"
        " last_edited_time, synced_at) VALUES ('p1', '[]', '{}', '[]',"
        " '2026-10-01T00:00:00.000Z', '2026-10-01T00:00:00.000Z', '2026-10-01T00:00:00.000Z')"
    )
    database.connection.commit()


def save_sign_in(app_paths: AppPaths, database: Database, settings: Settings) -> None:
    from app.notion.credentials import CredentialStore, StoredCredential
    from app.redaction import Secret

    CredentialStore.for_paths(app_paths).save(
        StoredCredential(kind="internal", access_token=Secret("not-a-real-token"))
    )


def connected_via_oauth(app_paths: AppPaths, database: Database, settings: Settings) -> None:
    settings.set("auth_kind", "oauth")


def chose_a_work_log(app_paths: AppPaths, database: Database, settings: Settings) -> None:
    settings.set("database_id", "db-1")


def everything(app_paths: AppPaths, database: Database, settings: Settings) -> None:
    save_sign_in(app_paths, database, settings)
    settings.set_many({"auth_kind": "oauth", "database_id": "db-1", "mapping": {"version": 1}})
    add_entry(app_paths, database, settings)


#: What a copy from before Phase 8 can have left behind, each enough on its own.
UPGRADES: dict[str, Callable[[AppPaths, Database, Settings], None]] = {
    "a saved sign-in": save_sign_in,
    "how it connected": connected_via_oauth,
    "a chosen work log": chose_a_work_log,
    "entries kept after disconnecting": add_entry,
    "everything": everything,
}


@pytest.mark.usefixtures("newer_build")
@pytest.mark.parametrize("left_behind", list(UPGRADES))
def test_an_upgrade_with_no_recorded_version_counts_as_version_1(
    app_paths: AppPaths, database: Database, settings: Settings, left_behind: str
) -> None:
    """A copy from before Phase 8 has no acknowledged_policy_version at all."""
    UPGRADES[left_behind](app_paths, database, settings)
    assert settings.get(ACKNOWLEDGED_KEY) is None
    policies = real_service(app_paths, database)
    assert policies.acknowledged_version() == 1
    notice = policies.notice()
    assert notice is not None
    assert notice["acknowledged_version"] == 1
    assert [c["version"] for c in notice["changes"]] == [2]
    with pytest.raises(PolicyNotAcknowledgedError):
        policies.require_acknowledged()
    policies.acknowledge(2)
    assert settings.get(ACKNOWLEDGED_KEY) == 2
    assert real_service(app_paths, database).notice() is None


@pytest.mark.usefixtures("newer_build")
def test_a_truly_empty_install_shows_nothing_and_records_the_version_on_connecting(
    app_paths: AppPaths, database: Database, settings: Settings
) -> None:
    policies = real_service(app_paths, database)
    assert policies.acknowledged_version() is None
    assert policies.notice() is None
    policies.require_acknowledged()  # nothing is blocked
    policies.record_connected()
    assert settings.get(ACKNOWLEDGED_KEY) == 2
    assert real_service(app_paths, database).notice() is None


@pytest.mark.usefixtures("newer_build")
def test_preferences_left_after_clearing_local_data_are_a_fresh_install(
    app_paths: AppPaths, database: Database, settings: Settings
) -> None:
    """Disconnecting with "clear local data" removes the connection, the work log and the
    entries but keeps preferences. Connecting again shows the policy where Connect links it,
    so no notice is needed (this was the copy used in the first Step 6 run)."""
    settings.set_many({"streak_threshold_minutes": 30, "raw_log_view": {"hidden": []}})
    policies = real_service(app_paths, database)
    assert policies.notice() is None
    policies.record_connected()
    assert settings.get(ACKNOWLEDGED_KEY) == 2


@pytest.mark.usefixtures("newer_build")
def test_a_recorded_version_wins_over_the_upgrade_rule(
    app_paths: AppPaths, database: Database, settings: Settings
) -> None:
    settings.set_many({"auth_kind": "oauth", ACKNOWLEDGED_KEY: 2})
    assert real_service(app_paths, database).notice() is None
