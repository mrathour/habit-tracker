"""Connecting to Notion: pasted tokens, OAuth sign-in, the database picker and logout."""

from __future__ import annotations

import html
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from app.db import Database, open_database
from app.db.settings import Settings
from app.errors import AppError
from app.notion.client import NotionReader, RateLimiter
from app.notion.connection import (
    ConfirmationRequiredError,
    ConnectionService,
    InvalidTokenError,
)
from app.notion.credentials import SERVICE_NAME, CredentialStore
from app.notion.errors import NotConnectedError, OfflineError, TokenServiceUnreachableError
from app.notion.handoff import TokenGrant, b64url_decode
from app.notion.service_client import StartResult
from app.notion.tokens import TokenManager
from app.paths import AppPaths
from app.redaction import Secret
from tests.support.fake_notion import FakeNotion
from tests.support.handoff_reference import plaintext_json, seal
from tests.support.memory_keyring import MemoryKeyring

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ACCOUNT = "notion-test"


class InstantLimiter(RateLimiter):
    def wait(self) -> None:
        return


@dataclass
class FakeTokenService:
    """Stands in for the deployed Worker: issues states and seals results like it does."""

    reachable: bool = True
    revoke_fails: bool = False
    public_key: str | None = None
    state: str = "test-state.signature"
    revoked: list[str] = field(default_factory=list)

    def start(self, port: int, public_key: str) -> StartResult:
        if not self.reachable:
            raise TokenServiceUnreachableError("start signing in")
        self.public_key = public_key
        return StartResult(self.state, "https://notion.test/authorize?x=1", time.time())

    def seal(self, body: dict[str, Any]) -> str:
        assert self.public_key is not None
        return seal(b64url_decode(self.public_key), self.state, plaintext_json(body))

    def refresh(self, refresh_token: Secret) -> TokenGrant:  # pragma: no cover - not used here
        raise AssertionError("no refresh expected")

    def revoke(self, token: Secret) -> None:
        if self.revoke_fails:
            raise TokenServiceUnreachableError("disconnect from Notion")
        self.revoked.append(token.reveal())


@dataclass
class Harness:
    service: ConnectionService
    notion: FakeNotion
    tokens: TokenManager
    token_service: FakeTokenService
    settings: Settings
    database: Database
    events: list[tuple[str, Any]]
    done: threading.Event
    opened: list[str]

    def wait_done(self, timeout: float = 10) -> dict[str, Any]:
        assert self.done.wait(timeout), "no connect:done event"
        return next(payload for name, payload in self.events if name == "connect:done")

    def deliver(self, query: str, path: str = "/done") -> httpx.Response:
        port = self.service._sign_in.listener.port  # type: ignore[union-attr]
        return httpx.get(f"http://127.0.0.1:{port}{path}?{query}", timeout=5)

    def deliver_result(self, body: dict[str, Any]) -> httpx.Response:
        envelope = self.token_service.seal(body)
        return self.deliver(f"state={self.token_service.state}&payload={envelope}")


def icon_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith(".png"):
        return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
    return httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"})


@pytest.fixture
def harness(app_paths: AppPaths) -> Iterator[Harness]:
    database = open_database(app_paths.database)
    notion = FakeNotion()
    token_service = FakeTokenService()
    tokens = TokenManager(CredentialStore(ACCOUNT), token_service)  # type: ignore[arg-type]

    def make_reader(manager: TokenManager) -> NotionReader:
        return NotionReader(
            manager,
            http=httpx.Client(transport=httpx.MockTransport(notion.handle)),
            base_url="https://api.notion.test",
            limiter=InstantLimiter(),
            sleep=lambda _s: None,
        )

    events: list[tuple[str, Any]] = []
    done = threading.Event()

    def emit(name: str, payload: object) -> None:
        events.append((name, payload))
        if name == "connect:done":
            done.set()

    opened: list[str] = []
    settings = Settings(database.connection)
    service = ConnectionService(
        tokens=tokens,
        reader=make_reader(tokens),
        service=token_service,  # type: ignore[arg-type]
        settings=settings,
        db=database.connection,
        emit=emit,
        make_reader=make_reader,
        open_browser=opened.append,
        http=httpx.Client(transport=httpx.MockTransport(icon_handler)),
        sign_in_timeout_s=3,
    )
    yield Harness(service, notion, tokens, token_service, settings, database, events, done, opened)
    service.cancel_sign_in()
    database.close()


def ok_body(token: str, icon: str | None = "https://icons.test/w.png") -> dict[str, Any]:
    return {
        "v": 1,
        "exp": int(time.time()) + 120,
        "result": "ok",
        "token": {
            "access_token": token,
            "refresh_token": "nrt_" + "r" * 32,
            "bot_id": "bot-1",
            "workspace_id": "ws-1",
            "workspace_name": "Mayank's Notion",
            "workspace_icon": icon,
        },
    }


def insert_entry(database: Database) -> None:
    stamp = "2026-10-17T12:00:00.000Z"
    with database.connection:
        database.connection.execute(
            "INSERT INTO work_logs (page_id, created_time, last_edited_time, synced_at)"
            " VALUES ('p1', ?, ?, ?)",
            (stamp, stamp, stamp),
        )


# --- Not connected ----------------------------------------------------------------------------


def test_starts_disconnected(harness: Harness) -> None:
    info = harness.service.info()
    assert info["connected"] is False
    assert info["auth_kind"] is None
    with pytest.raises(NotConnectedError):
        harness.service.list_data_sources()


# --- Pasted tokens ----------------------------------------------------------------------------


def test_internal_token_is_validated_then_stored(harness: Harness) -> None:
    token = harness.notion.issue_token()
    info = harness.service.connect_with_token("internal", f"  {token}  ")
    assert info["connected"] is True
    assert info["auth_kind"] == "internal"
    assert info["workspace_name"] == "Test Workspace"
    stored = json.loads(MemoryKeyring.store[(SERVICE_NAME, ACCOUNT)])
    assert stored["kind"] == "internal"
    assert stored["access_token"] == token
    assert harness.settings.get("auth_kind") == "internal"
    # The token itself never reaches the database.
    assert token not in json.dumps(harness.settings.all())


def test_personal_access_token_shows_the_person(harness: Harness) -> None:
    harness.notion.me_type = "person"
    info = harness.service.connect_with_token("pat", harness.notion.issue_token())
    assert info["auth_kind"] == "pat"
    assert info["account_name"] == "Mayank"
    assert info["workspace_name"] is None


def test_rejected_token_stores_nothing(harness: Harness) -> None:
    with pytest.raises(InvalidTokenError, match="didn't accept that token"):
        harness.service.connect_with_token("pat", "ntn_not_a_real_token_0123456789")
    assert (SERVICE_NAME, ACCOUNT) not in MemoryKeyring.store
    assert harness.service.info()["connected"] is False


@pytest.mark.parametrize("token", ["", "   ", "ntn_two parts", "x" * 600, None, 12])
def test_malformed_tokens_are_refused_before_calling_notion(
    harness: Harness, token: object
) -> None:
    with pytest.raises(InvalidTokenError):
        harness.service.connect_with_token("pat", token)
    assert harness.notion.requests == []


def test_unknown_token_kind_is_refused(harness: Harness) -> None:
    with pytest.raises(AppError, match="internal integration token or a personal access token"):
        harness.service.connect_with_token("oauth", harness.notion.issue_token())


def test_offline_while_validating(harness: Harness) -> None:
    harness.notion.next_failures.append(httpx.ConnectError("offline"))
    with pytest.raises(OfflineError):
        harness.service.connect_with_token("pat", harness.notion.issue_token())
    assert harness.service.info()["connected"] is False


# --- OAuth sign-in ----------------------------------------------------------------------------


def test_sign_in_end_to_end(harness: Harness) -> None:
    started = harness.service.start_sign_in()
    assert started["reopened"] is False
    assert harness.opened == ["https://notion.test/authorize?x=1"]
    assert ("connect:waiting", {"timeout_s": 3}) in harness.events

    token = harness.notion.issue_token()
    page = harness.deliver_result(ok_body(token))
    assert page.status_code == 200
    assert "Connected to Notion" in page.text
    assert token not in page.text
    assert page.headers["Cache-Control"] == "no-store"

    done = harness.wait_done()
    assert done["result"] == "connected"
    assert done["connection"]["workspace_name"] == "Mayank's Notion"
    icon = done["connection"]["workspace_icon"]
    assert icon["type"] == "image"
    assert icon["value"].startswith("data:image/png;base64,")
    stored = json.loads(MemoryKeyring.store[(SERVICE_NAME, ACCOUNT)])
    assert stored["kind"] == "oauth"
    assert stored["refresh_token"].startswith("nrt_")


def test_emoji_workspace_icon(harness: Harness) -> None:
    harness.service.start_sign_in()
    harness.deliver_result(ok_body(harness.notion.issue_token(), icon="🎯"))
    assert harness.wait_done()["connection"]["workspace_icon"] == {"type": "emoji", "value": "🎯"}


@pytest.mark.parametrize("icon", ["https://icons.test/not-an-image.html", None])
def test_unusable_icons_fall_back_to_a_letter(harness: Harness, icon: str | None) -> None:
    harness.service.start_sign_in()
    harness.deliver_result(ok_body(harness.notion.issue_token(), icon=icon))
    assert harness.wait_done()["connection"]["workspace_icon"] is None


@pytest.mark.parametrize(
    ("error", "result", "page_title"),
    [
        ("access_denied", "access_denied", "Sign-in cancelled"),
        ("notion_unreachable", "service_unreachable", "Notion couldn't be reached"),
        ("notion_error", "notion_error", "Notion couldn't complete the sign-in"),
    ],
)
def test_sign_in_failures_reach_the_app_at_once(
    harness: Harness, error: str, result: str, page_title: str
) -> None:
    harness.service.start_sign_in()
    page = harness.deliver_result(
        {"v": 1, "exp": int(time.time()) + 120, "result": "error", "error": error}
    )
    assert page_title in html.unescape(page.text)
    assert harness.wait_done()["result"] == result
    assert harness.service.info()["connected"] is False


def test_expired_hand_off(harness: Harness) -> None:
    harness.service.start_sign_in()
    page = harness.deliver_result(
        {"v": 1, "exp": int(time.time()) - 5, "result": "error", "error": "access_denied"}
    )
    assert "This sign-in expired" in html.unescape(page.text)
    assert harness.wait_done()["result"] == "expired"


def test_tampered_hand_off_is_an_error(harness: Harness) -> None:
    harness.service.start_sign_in()
    harness.deliver(f"state={harness.token_service.state}&payload=AAAA")
    assert harness.wait_done()["result"] == "error"
    assert harness.service.info()["connected"] is False


def test_stray_requests_do_not_end_sign_in(harness: Harness) -> None:
    harness.service.start_sign_in()
    assert harness.deliver("x=1", path="/favicon.ico").status_code == 404
    assert harness.deliver("state=wrong&payload=AAAA").status_code == 400
    assert not harness.done.is_set()
    harness.deliver_result(ok_body(harness.notion.issue_token()))
    assert harness.wait_done()["result"] == "connected"


def test_second_hand_off_is_refused(harness: Harness) -> None:
    harness.service.start_sign_in()
    harness.deliver_result(ok_body(harness.notion.issue_token()))
    harness.wait_done()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            replay = harness.deliver_result(ok_body(harness.notion.issue_token()))
        except httpx.TransportError:
            return  # The listener has closed: a replay can't even connect.
        # While it is still closing, a second hand-off is refused, never decrypted.
        assert replay.status_code == 400
        time.sleep(0.1)
    pytest.fail("the listener stayed open after the hand-off")


def test_cancel_from_the_app(harness: Harness) -> None:
    harness.service.start_sign_in()
    harness.service.cancel_sign_in()
    assert harness.wait_done()["result"] == "cancelled"
    harness.service.cancel_sign_in()  # cancelling twice is harmless


def test_timeout_when_the_browser_is_closed(harness: Harness) -> None:
    harness.service.start_sign_in()
    assert harness.wait_done(timeout=10)["result"] == "timeout"


def test_service_down_when_starting(harness: Harness) -> None:
    harness.token_service.reachable = False
    with pytest.raises(TokenServiceUnreachableError):
        harness.service.start_sign_in()
    assert harness.opened == []
    # A new attempt is possible afterwards.
    harness.token_service.reachable = True
    assert harness.service.start_sign_in()["reopened"] is False


def test_starting_again_reopens_the_same_sign_in(harness: Harness) -> None:
    first = harness.service.start_sign_in()
    second = harness.service.start_sign_in()
    assert second == {"port": first["port"], "reopened": True}
    assert len(harness.opened) == 2


# --- Database picker --------------------------------------------------------------------------


def connect_pat(harness: Harness) -> None:
    harness.service.connect_with_token("pat", harness.notion.issue_token())


def test_empty_workspace(harness: Harness) -> None:
    connect_pat(harness)
    page = harness.service.list_data_sources()
    assert page["groups"] == []
    assert page["next_cursor"] is None
    assert page["sharing_help_url"].startswith("https://")


def test_databases_with_several_data_sources_are_grouped(harness: Harness) -> None:
    log = harness.notion.add_database("Work Log", ["Sessions", "Archive"])
    harness.notion.add_database("Reading List")
    log.icon = {"type": "emoji", "emoji": "⏱️"}
    connect_pat(harness)
    groups = {g["title"]: g for g in harness.service.list_data_sources()["groups"]}
    assert set(groups) == {"Work Log", "Reading List"}
    assert [s["name"] for s in groups["Work Log"]["data_sources"]] == ["Sessions", "Archive"]
    assert groups["Work Log"]["icon_emoji"] == "⏱️"
    # Database titles are fetched once per database, not once per data source.
    database_calls = [r for r in harness.notion.requests if "/v1/databases/" in r.url.path]
    assert len(database_calls) == 2


def test_pagination(harness: Harness) -> None:
    for i in range(5):
        harness.notion.add_database(f"DB {i}")
    harness.notion.page_size = 2
    connect_pat(harness)
    first = harness.service.list_data_sources()
    assert len(first["groups"]) == 2
    assert first["next_cursor"] == "2"
    second = harness.service.list_data_sources(first["next_cursor"])
    third = harness.service.list_data_sources(second["next_cursor"])
    assert third["next_cursor"] is None
    titles = [g["title"] for page in (first, second, third) for g in page["groups"]]
    assert titles == [f"DB {i}" for i in range(5)]


def test_title_falls_back_when_the_database_is_not_readable(harness: Harness) -> None:
    database = harness.notion.add_database("Hidden parent", ["Visible source"])
    connect_pat(harness)
    harness.notion.unreadable_databases.add(database.id)
    groups = harness.service.list_data_sources()["groups"]
    assert groups[0]["title"] == "Visible source"


def test_choosing_saves_the_settings(harness: Harness) -> None:
    database = harness.notion.add_database("Work Log (test)")
    connect_pat(harness)
    info = harness.service.choose_data_source(database.id, database.data_source_ids[0])
    assert info["database_id"] == database.id
    assert info["data_source_id"] == database.data_source_ids[0]
    assert info["database_title"] == "Work Log (test)"
    assert harness.settings.get("auth_kind") == "pat"


def test_choosing_a_mismatched_data_source_is_refused(harness: Harness) -> None:
    a = harness.notion.add_database("A")
    b = harness.notion.add_database("B")
    connect_pat(harness)
    with pytest.raises(AppError, match="doesn't belong"):
        harness.service.choose_data_source(a.id, b.data_source_ids[0])


def test_switching_databases_asks_before_removing_entries(harness: Harness) -> None:
    first = harness.notion.add_database("First")
    second = harness.notion.add_database("Second")
    connect_pat(harness)
    harness.service.choose_data_source(first.id, first.data_source_ids[0])
    insert_entry(harness.database)
    harness.settings.set("mapping", {"start": "abc"})
    with pytest.raises(ConfirmationRequiredError, match="removes the 1 entries copied from First"):
        harness.service.choose_data_source(second.id, second.data_source_ids[0])
    info = harness.service.choose_data_source(second.id, second.data_source_ids[0], True)
    assert info["database_title"] == "Second"
    count = harness.database.connection.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0]
    assert count == 0
    assert harness.settings.get("mapping") is None


def test_choosing_the_same_database_again_keeps_entries(harness: Harness) -> None:
    db = harness.notion.add_database("Same")
    connect_pat(harness)
    harness.service.choose_data_source(db.id, db.data_source_ids[0])
    insert_entry(harness.database)
    harness.service.choose_data_source(db.id, db.data_source_ids[0])
    count = harness.database.connection.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0]
    assert count == 1


# --- Logout -----------------------------------------------------------------------------------


def sign_in(harness: Harness) -> str:
    harness.service.start_sign_in()
    token = harness.notion.issue_token()
    harness.deliver_result(ok_body(token))
    assert harness.wait_done()["result"] == "connected"
    harness.done.clear()
    return token


def test_logout_revokes_then_keeps_local_data(harness: Harness) -> None:
    token = sign_in(harness)
    db = harness.notion.add_database("Work Log")
    harness.service.choose_data_source(db.id, db.data_source_ids[0])
    insert_entry(harness.database)
    result = harness.service.logout(False)
    assert result == {
        "kind": "oauth",
        "revoked": True,
        "revoke_error": None,
        "cleared_local_data": False,
    }
    assert harness.token_service.revoked == [token]
    assert (SERVICE_NAME, ACCOUNT) not in MemoryKeyring.store
    info = harness.service.info()
    assert info["connected"] is False
    assert info["workspace_name"] is None
    # Kept: the database choice and the entries, ready for reconnecting.
    assert info["database_id"] == db.id
    assert harness.database.connection.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0] == 1


def test_logout_can_clear_local_data(harness: Harness) -> None:
    sign_in(harness)
    db = harness.notion.add_database("Work Log")
    harness.service.choose_data_source(db.id, db.data_source_ids[0])
    insert_entry(harness.database)
    harness.settings.set("week_start", "monday")
    harness.service.logout(True)
    assert harness.service.info()["database_id"] is None
    assert harness.database.connection.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0] == 0
    assert harness.settings.get("week_start") == "monday"  # preferences stay


def test_revoke_failure_does_not_block_logout(harness: Harness) -> None:
    sign_in(harness)
    harness.token_service.revoke_fails = True
    result = harness.service.logout(False)
    assert result["revoked"] is False
    assert "sign-in service can't be reached" in str(result["revoke_error"])
    assert harness.service.info()["connected"] is False


def test_logout_of_a_pasted_token_does_not_call_the_service(harness: Harness) -> None:
    connect_pat(harness)
    result = harness.service.logout(False)
    assert result == {
        "kind": "pat",
        "revoked": None,
        "revoke_error": None,
        "cleared_local_data": False,
    }
    assert harness.token_service.revoked == []


def test_logout_needs_a_choice(harness: Harness) -> None:
    with pytest.raises(AppError, match="keep or clear"):
        harness.service.logout("yes")


def test_reconnect_after_logout(harness: Harness) -> None:
    connect_pat(harness)
    harness.service.logout(False)
    info = harness.service.connect_with_token("pat", harness.notion.issue_token())
    assert info["connected"] is True


# --- Settings guard ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["access_token", "client_secret", "Password"])
def test_settings_refuse_secret_keys(harness: Harness, key: str) -> None:
    with pytest.raises(ValueError, match="never store secrets"):
        harness.settings.set(key, "x")


def test_pasting_a_token_revokes_a_replaced_sign_in(harness: Harness) -> None:
    old = sign_in(harness)
    info = harness.service.connect_with_token("pat", harness.notion.issue_token())
    assert info["auth_kind"] == "pat"
    assert harness.token_service.revoked == [old]


def test_replacing_still_works_when_revoking_fails(harness: Harness) -> None:
    sign_in(harness)
    harness.token_service.revoke_fails = True
    assert harness.service.connect_with_token("pat", harness.notion.issue_token())["connected"]


def test_a_rejected_replacement_keeps_the_current_connection(harness: Harness) -> None:
    old = sign_in(harness)
    with pytest.raises(InvalidTokenError):
        harness.service.connect_with_token("pat", "ntn_rejected_0123456789")
    assert harness.token_service.revoked == []
    assert harness.tokens.access_token().reveal() == old


# --- Privacy policy (PLAN.md 13) -------------------------------------------------------------


def test_connecting_records_the_policy_version(harness: Harness) -> None:
    """Connecting is where the policy is linked, so both ways of connecting record it."""
    calls: list[str] = []
    harness.service._on_connected = lambda: calls.append("connected")
    harness.service.connect_with_token("internal", harness.notion.issue_token())
    assert calls == ["connected"]

    harness.service.start_sign_in()
    harness.deliver_result(ok_body(harness.notion.issue_token()))
    assert harness.wait_done()["result"] == "connected"
    assert calls == ["connected", "connected"]


def test_failed_connections_record_nothing(harness: Harness) -> None:
    calls: list[str] = []
    harness.service._on_connected = lambda: calls.append("connected")
    with pytest.raises(InvalidTokenError):
        harness.service.connect_with_token("internal", "ntn_" + "x" * 40)
    assert calls == []


def test_a_failure_to_record_the_policy_never_undoes_the_connection(harness: Harness) -> None:
    def fail() -> None:
        raise RuntimeError("disk full")

    harness.service._on_connected = fail
    info = harness.service.connect_with_token("internal", harness.notion.issue_token())
    assert info["connected"] is True
