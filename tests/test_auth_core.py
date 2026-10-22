"""Credential storage, token renewal, the token-service client and the read-only Notion client."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

import httpx
import keyring
import keyring.errors
import pytest

from app.notion.client import NOTION_VERSION, NotionReader, RateLimiter
from app.notion.credentials import (
    MAX_BLOB_CHARS,
    SERVICE_NAME,
    AuthKind,
    CredentialStore,
    StoredCredential,
)
from app.notion.errors import (
    CredentialStoreError,
    NotConnectedError,
    NotionRequestError,
    OfflineError,
    PasteNewTokenError,
    ReconnectRequiredError,
    TokenServiceUnreachableError,
)
from app.notion.handoff import TokenGrant
from app.notion.service_client import TokenServiceClient, TokenServiceError
from app.notion.tokens import TokenManager
from app.paths import AppPaths
from app.redaction import REDACTED, Secret, redact
from tests.support.fake_notion import FakeNotion, notion_error
from tests.support.memory_keyring import MemoryKeyring

SERVICE = "https://service.test"


def oauth_credential(
    access: str = "ntn_access_1", refresh: str = "nrt_refresh_1"
) -> StoredCredential:
    return StoredCredential(
        kind="oauth", access_token=Secret(access), refresh_token=Secret(refresh), bot_id="bot-1"
    )


class FakeService:
    """Stands in for TokenServiceClient.refresh, counting calls and rotating tokens."""

    def __init__(self) -> None:
        self.calls = 0
        self.delay = 0.0
        self.error: Exception | None = None
        self.lock = threading.Lock()

    def refresh(self, refresh_token: Secret) -> TokenGrant:
        with self.lock:
            self.calls += 1
            n = self.calls
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return TokenGrant(
            access_token=Secret(f"ntn_access_{n + 1}"),
            refresh_token=Secret(f"nrt_refresh_{n + 1}"),
            bot_id="bot-1",
            workspace_id="ws",
            workspace_name="W",
            workspace_icon=None,
        )


def manager(
    store: CredentialStore | None = None,
) -> tuple[TokenManager, FakeService, CredentialStore]:
    store = store or CredentialStore("notion-test")
    service = FakeService()
    return TokenManager(store, service), service, store  # type: ignore[arg-type]


# --- Credential store -------------------------------------------------------------------------


def test_round_trip_through_the_keyring() -> None:
    store = CredentialStore("notion-test")
    assert store.load() is None
    store.save(oauth_credential())
    raw = MemoryKeyring.store[(SERVICE_NAME, "notion-test")]
    assert json.loads(raw)["kind"] == "oauth"
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token.reveal() == "ntn_access_1"
    assert loaded.refresh_token is not None
    assert loaded.refresh_token.reveal() == "nrt_refresh_1"
    assert loaded.can_refresh
    assert loaded.obtained_at.endswith("Z")


def test_pasted_tokens_have_no_refresh_token() -> None:
    store = CredentialStore("notion-test")
    store.save(StoredCredential(kind="pat", access_token=Secret("ntn_pat_value_0123456789")))
    loaded = store.load()
    assert loaded is not None
    assert loaded.kind == "pat"
    assert loaded.refresh_token is None
    assert not loaded.can_refresh


def test_credentials_never_show_their_tokens() -> None:
    shown = repr(oauth_credential("ntn_secretvalue_abcdef0123", "nrt_secretvalue_abcdef0123"))
    assert "secretvalue" not in shown
    assert REDACTED in shown


def test_damaged_entry_is_treated_as_missing(caplog: pytest.LogCaptureFixture) -> None:
    MemoryKeyring.store[(SERVICE_NAME, "notion-test")] = (
        '{"v": 1, "kind": "oauth", "access_token": "ntn_partial'
    )
    assert CredentialStore("notion-test").load() is None
    assert "damaged" in caplog.text
    assert "ntn_partial" not in caplog.text


@pytest.mark.parametrize(
    "blob",
    [
        '{"v": 2, "kind": "oauth", "access_token": "x"}',
        '{"v": 1, "kind": "magic", "access_token": "x"}',
        '{"v": 1, "kind": "oauth", "access_token": ""}',
        '{"v": 1, "kind": "oauth", "access_token": "x", "refresh_token": 5}',
        "[]",
    ],
)
def test_unexpected_entries_are_treated_as_missing(blob: str) -> None:
    MemoryKeyring.store[(SERVICE_NAME, "notion-test")] = blob
    assert CredentialStore("notion-test").load() is None


def test_oversized_credentials_are_refused() -> None:
    huge = oauth_credential("ntn_" + "a" * MAX_BLOB_CHARS)
    with pytest.raises(CredentialStoreError, match="couldn't save"):
        CredentialStore("notion-test").save(huge)


VAULT_OPERATIONS: dict[str, Callable[[CredentialStore], object]] = {
    "load": lambda store: store.load(),
    "save": lambda store: store.save(oauth_credential()),
    "delete": lambda store: store.delete(),
}


@pytest.mark.parametrize("operation", list(VAULT_OPERATIONS))
def test_vault_failures_become_readable_errors(operation: str) -> None:
    store = CredentialStore("notion-test")
    MemoryKeyring.fail_with = keyring.errors.KeyringError("vault locked")
    with pytest.raises(CredentialStoreError):
        VAULT_OPERATIONS[operation](store)


def test_delete_forgets_secrets_and_tolerates_missing_entry() -> None:
    store = CredentialStore("notion-test")
    store.delete()  # nothing stored: no error
    # A value no redaction pattern recognises, so only registration can mask it.
    opaque = "opaque-forget-me-12345"
    store.save(oauth_credential(opaque))
    assert redact(f"value {opaque}") == f"value {REDACTED}"
    store.delete()
    assert store.load() is None
    assert redact(f"value {opaque}") == f"value {opaque}"


def test_each_data_folder_gets_its_own_account() -> None:
    real = AppPaths.resolve({"APPDATA": "C:/AppData"})
    copy = AppPaths.resolve({"HABIT_TRACKER_HOME": "C:/somewhere/else"})
    assert real.credential_account == "notion"
    assert copy.credential_account.startswith("notion-")
    assert copy.credential_account != real.credential_account
    assert copy.instance_lock_name != real.instance_lock_name


# --- Token manager ----------------------------------------------------------------------------


def test_not_connected() -> None:
    tokens, _, _ = manager()
    assert tokens.credential() is None
    with pytest.raises(NotConnectedError):
        tokens.access_token()


def test_renewal_writes_before_use() -> None:
    tokens, service, store = manager()
    tokens.replace_credential(oauth_credential())
    renewed = tokens.renew_after_unauthorized(Secret("ntn_access_1"))
    assert renewed.reveal() == "ntn_access_2"
    stored = store.load()
    assert stored is not None
    assert stored.access_token.reveal() == "ntn_access_2"
    assert stored.refresh_token is not None
    assert stored.refresh_token.reveal() == "nrt_refresh_2"
    assert service.calls == 1


def test_parallel_401s_cause_exactly_one_renewal() -> None:
    tokens, service, _ = manager()
    tokens.replace_credential(oauth_credential())
    service.delay = 0.05
    results: list[str] = []
    lock = threading.Lock()

    def hit_401() -> None:
        token = tokens.renew_after_unauthorized(Secret("ntn_access_1"))
        with lock:
            results.append(token.reveal())

    threads = [threading.Thread(target=hit_401) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert service.calls == 1
    assert results == ["ntn_access_2"] * 10


def test_failed_save_keeps_the_pair_and_retries_before_any_use() -> None:
    tokens, service, store = manager()
    tokens.replace_credential(oauth_credential())
    MemoryKeyring.fail_with = keyring.errors.KeyringError("vault locked")
    with pytest.raises(CredentialStoreError):
        tokens.renew_after_unauthorized(Secret("ntn_access_1"))
    # Nothing may call Notion with the unsaved pair.
    with pytest.raises(CredentialStoreError):
        tokens.access_token()
    MemoryKeyring.fail_with = None
    assert tokens.access_token().reveal() == "ntn_access_2"
    stored = store.load()
    assert stored is not None
    assert stored.refresh_token is not None
    assert stored.refresh_token.reveal() == "nrt_refresh_2"
    assert service.calls == 1  # the renewal itself wasn't repeated


@pytest.mark.parametrize("kind", ["pat", "internal"])
def test_pasted_tokens_ask_for_a_new_token(kind: AuthKind) -> None:
    tokens, service, _ = manager()
    tokens.replace_credential(
        StoredCredential(kind=kind, access_token=Secret("ntn_pasted_0123456789"))
    )
    with pytest.raises(PasteNewTokenError):
        tokens.renew_after_unauthorized(Secret("ntn_pasted_0123456789"))
    assert service.calls == 0


def test_rejected_refresh_asks_to_reconnect() -> None:
    tokens, service, store = manager()
    tokens.replace_credential(oauth_credential())
    service.error = ReconnectRequiredError()
    with pytest.raises(ReconnectRequiredError):
        tokens.renew_after_unauthorized(Secret("ntn_access_1"))
    # Local state is untouched: the old pair stays until the user reconnects.
    stored = store.load()
    assert stored is not None
    assert stored.access_token.reveal() == "ntn_access_1"


def test_service_outage_during_renewal() -> None:
    tokens, service, _ = manager()
    tokens.replace_credential(oauth_credential())
    service.error = TokenServiceUnreachableError()
    with pytest.raises(TokenServiceUnreachableError, match="sign-in service can't be reached"):
        tokens.renew_after_unauthorized(Secret("ntn_access_1"))


def test_forget_returns_what_was_stored() -> None:
    tokens, _, store = manager()
    tokens.replace_credential(oauth_credential())
    previous = tokens.forget()
    assert previous is not None
    assert previous.access_token.reveal() == "ntn_access_1"
    assert store.load() is None
    assert tokens.credential() is None


def test_manager_loads_lazily_from_the_store() -> None:
    store = CredentialStore("notion-test")
    store.save(oauth_credential())
    tokens, _, _ = manager(store)
    assert tokens.access_token().reveal() == "ntn_access_1"


# --- Token-service client ---------------------------------------------------------------------


def service_client(handler: Callable[[httpx.Request], httpx.Response]) -> TokenServiceClient:
    return TokenServiceClient(SERVICE, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_start() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == f"{SERVICE}/start"
        assert json.loads(request.content) == {"port": 50000, "public_key": "pk"}
        assert "origin" not in request.headers
        return httpx.Response(
            200, json={"state": "s", "authorize_url": "https://a", "server_time": 5}
        )

    result = service_client(handler).start(50000, "pk")
    assert (result.state, result.authorize_url, result.server_time) == ("s", "https://a", 5.0)


def test_refresh_returns_a_grant() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"refresh_token": "nrt_old"}
        return httpx.Response(
            200,
            json={
                "access_token": "ntn_new",
                "refresh_token": "nrt_new",
                "bot_id": "b",
                "workspace_id": "w",
                "workspace_name": None,
                "workspace_icon": None,
            },
        )

    grant = service_client(handler).refresh(Secret("nrt_old"))
    assert grant.access_token.reveal() == "ntn_new"
    assert grant.refresh_token.reveal() == "nrt_new"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), ReconnectRequiredError),
        (httpx.Response(503, json={"error": "notion_unreachable"}), TokenServiceUnreachableError),
        (httpx.Response(502, json={"error": "notion_error"}), TokenServiceUnreachableError),
        (httpx.Response(429, json={"error": "rate_limited"}), TokenServiceUnreachableError),
        (httpx.Response(503, json={"error": "server_misconfigured"}), TokenServiceUnreachableError),
        (httpx.Response(400, json={"error": "invalid_request"}), TokenServiceError),
        (httpx.Response(200, text="<html>"), TokenServiceError),
        (httpx.Response(200, json={"access_token": "x"}), TokenServiceError),
    ],
)
def test_refresh_errors(response: httpx.Response, error: type[Exception]) -> None:
    with pytest.raises(error):
        service_client(lambda _r: response).refresh(Secret("nrt_old"))


def test_service_unreachable_never_mentions_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TokenServiceUnreachableError) as caught:
        service_client(handler).refresh(Secret("nrt_secret_refresh_value"))
    assert "nrt_secret_refresh_value" not in str(caught.value)
    assert "nrt_secret_refresh_value" not in (caught.value.detail or "")


def test_revoke_and_health() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"revoked": True})

    client = service_client(handler)
    client.revoke(Secret("ntn_x"))
    assert client.health()
    assert seen == ["/revoke", "/health"]


def test_health_reports_outage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    assert not service_client(handler).health()


# --- Read-only Notion client ------------------------------------------------------------------


class InstantLimiter(RateLimiter):
    def wait(self) -> None:
        return


def reader(fake: FakeNotion, tokens: TokenManager) -> NotionReader:
    return NotionReader(
        tokens,
        http=httpx.Client(transport=httpx.MockTransport(fake.handle)),
        base_url="https://api.notion.test",
        limiter=InstantLimiter(),
        sleep=lambda _s: None,
    )


def connected(
    fake: FakeNotion, kind: AuthKind = "pat"
) -> tuple[NotionReader, TokenManager, FakeService]:
    tokens, service, _ = manager()
    token = fake.issue_token()
    if kind == "oauth":
        tokens.replace_credential(oauth_credential(token, "nrt_refresh_1"))
    else:
        tokens.replace_credential(StoredCredential(kind=kind, access_token=Secret(token)))
    return reader(fake, tokens), tokens, service


def test_requests_send_the_api_version() -> None:
    fake = FakeNotion()
    notion, _, _ = connected(fake)
    assert notion.users_me()["type"] == "bot"
    assert fake.requests[-1].headers["Notion-Version"] == NOTION_VERSION == "2026-03-11"


def test_401_renews_once_and_retries() -> None:
    fake = FakeNotion()
    notion, tokens, service = connected(fake, "oauth")
    fake.valid_tokens.clear()  # Notion expired the access token
    fake.valid_tokens.add("ntn_access_2")  # the one the service will hand out
    assert notion.users_me()["type"] == "bot"
    assert service.calls == 1
    assert tokens.access_token().reveal() == "ntn_access_2"


def test_401_after_renewal_means_reconnect() -> None:
    fake = FakeNotion()
    notion, _, service = connected(fake, "oauth")
    fake.valid_tokens.clear()  # nothing will be accepted
    with pytest.raises(ReconnectRequiredError):
        notion.users_me()
    assert service.calls == 1


def test_401_on_a_pasted_token_asks_for_a_new_one() -> None:
    fake = FakeNotion()
    notion, _, service = connected(fake, "pat")
    fake.valid_tokens.clear()
    with pytest.raises(PasteNewTokenError):
        notion.users_me()
    assert service.calls == 0


def test_network_failure_means_offline() -> None:
    fake = FakeNotion()
    notion, _, _ = connected(fake)
    fake.next_failures.append(httpx.ConnectError("no route"))
    with pytest.raises(OfflineError):
        notion.users_me()


def test_post_reads_retry_server_errors() -> None:
    fake = FakeNotion()
    fake.add_database("Work Log")
    notion, _, _ = connected(fake)
    fake.next_failures += [
        notion_error(503, "service_unavailable"),
        notion_error(502, "bad_gateway"),
    ]
    assert len(notion.search_data_sources()["results"]) == 1
    assert len(fake.requests) == 3


def test_post_reads_give_up_after_retries() -> None:
    fake = FakeNotion()
    notion, _, _ = connected(fake)
    fake.next_failures += [notion_error(503, "service_unavailable")] * 3
    with pytest.raises(NotionRequestError):
        notion.search_data_sources()


def test_not_found_is_a_readable_error() -> None:
    fake = FakeNotion()
    notion, _, _ = connected(fake)
    with pytest.raises(NotionRequestError, match="isn't shared with Habit Tracker") as caught:
        notion.retrieve_database("missing")
    assert caught.value.status == 404


def test_reader_has_no_write_methods() -> None:
    public = {name for name in dir(NotionReader) if not name.startswith("_")}
    assert public == {
        "users_me",
        "search_data_sources",
        "retrieve_database",
        "retrieve_data_source",
        "query_data_source",
        "retrieve_property_item",
        "server_time",
        "forget_server_time",
        "close",
    }


def test_rate_limiter_spaces_requests() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(round(seconds, 3))
        now[0] += seconds

    limiter = RateLimiter(rate=3.0, clock=lambda: now[0], sleep=sleep)
    for _ in range(4):
        limiter.wait()
    assert slept == [0.333, 0.333, 0.333]
