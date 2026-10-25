"""The Notion connection: connect, status, the database picker and logout (PLAN.md 12).

Both ways of connecting end with a token in Credential Manager and non-secret details in
``settings``; the rest of the app doesn't care which path produced the token.

* **Pasted token** (12.4): an internal integration token or a personal access token, checked with
  a read-only ``GET /v1/users/me`` before anything is saved.
* **OAuth** (12.3): a one-time key and loopback listener, the token service's ``/start``, the
  system browser, and the encrypted hand-off. Progress is pushed to the UI as events.
"""

from __future__ import annotations

import base64
import logging
import re
import sqlite3
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, TypedDict

import httpx

from app.db.connection import lock_for
from app.db.settings import (
    CONNECTION_KEYS,
    FULL_SYNC_REQUIRED_KEY,
    MAPPING_KEY,
    SOURCE_DATA_KEYS,
    SOURCE_KEYS,
    Settings,
)
from app.errors import AppError
from app.notion.client import NotionReader
from app.notion.credentials import AuthKind, StoredCredential, utc_now
from app.notion.errors import (
    NotConnectedError,
    NotionRequestError,
    PasteNewTokenError,
)
from app.notion.handoff import HandoffError, OneTimeKey, ServerClock, SignInFailed, TokenGrant
from app.notion.loopback import BrowserPage, LoopbackListener
from app.notion.service_client import TokenServiceClient
from app.notion.tokens import TokenManager
from app.redaction import Secret

logger = logging.getLogger(__name__)

SIGN_IN_TIMEOUT_S: Final = 300.0
MAX_TOKEN_CHARS: Final = 512
MAX_ICON_BYTES: Final = 256 * 1024
ICON_TYPES: Final = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml")
SHARING_HELP_URL: Final = "https://habit-tracker.mrathour.workers.dev/support"

PastedKind = Literal["internal", "pat"]


class WorkspaceIcon(TypedDict):
    type: Literal["emoji", "image"]
    value: str


class ConnectionInfo(TypedDict):
    connected: bool
    auth_kind: AuthKind | None
    workspace_name: str | None
    workspace_icon: WorkspaceIcon | None
    account_name: str | None
    database_id: str | None
    data_source_id: str | None
    database_title: str | None
    #: A column mapping is saved for the chosen data source (PLAN.md 4).
    mapping_saved: bool
    #: Set when the mapping changed after its first save; a full sync clears it (Phase 5).
    full_sync_required: dict[str, str] | None


class DataSourceChoice(TypedDict):
    id: str
    name: str


class DatabaseGroup(TypedDict):
    database_id: str
    title: str
    icon_emoji: str | None
    data_sources: list[DataSourceChoice]


class DataSourcePage(TypedDict):
    groups: list[DatabaseGroup]
    next_cursor: str | None
    sharing_help_url: str


SignInResult = Literal[
    "connected",
    "cancelled",
    "access_denied",
    "expired",
    "timeout",
    "service_unreachable",
    "notion_error",
    "error",
]


class ConfirmationRequiredError(AppError):
    """The action would remove local data; the UI must ask first."""

    state = "confirm_replace"


class InvalidTokenError(AppError):
    """A pasted token is malformed or Notion rejected it."""

    state = "invalid_token"


@dataclass
class _SignIn:
    key: OneTimeKey
    listener: LoopbackListener
    state: str | None = None
    authorize_url: str | None = None
    clock: ServerClock | None = None
    finished: bool = False
    cancelled: bool = False


EventSink = Callable[[str, object], None]


class ConnectionService:
    def __init__(
        self,
        *,
        tokens: TokenManager,
        reader: NotionReader,
        service: TokenServiceClient,
        settings: Settings,
        db: sqlite3.Connection,
        emit: EventSink,
        make_reader: Callable[[TokenManager], NotionReader] | None = None,
        open_browser: Callable[[str], object] = lambda url: webbrowser.open(url),
        http: httpx.Client | None = None,
        sign_in_timeout_s: float = SIGN_IN_TIMEOUT_S,
        on_connected: Callable[[], None] | None = None,
    ) -> None:
        self._tokens = tokens
        self._reader = reader
        self._service = service
        self._settings = settings
        self._db = db
        self._emit = emit
        self._make_reader = make_reader
        self._open_browser = open_browser
        self._http = http or httpx.Client(timeout=10.0, follow_redirects=True)
        self._timeout = sign_in_timeout_s
        self._on_connected = on_connected
        self._lock = threading.Lock()
        self._sign_in: _SignIn | None = None
        self._titles: dict[str, tuple[str, str | None]] = {}

    # --- status -------------------------------------------------------------------------

    def info(self) -> ConnectionInfo:
        credential = self._tokens.credential()
        icon = self._settings.get("workspace_icon")
        return {
            "connected": credential is not None,
            "auth_kind": credential.kind if credential else None,
            "workspace_name": self._settings.get_str("workspace_name"),
            "workspace_icon": icon if _is_icon(icon) else None,  # type: ignore[typeddict-item]
            "account_name": self._settings.get_str("account_name"),
            "database_id": self._settings.get_str("database_id"),
            "data_source_id": self._settings.get_str("data_source_id"),
            "database_title": self._settings.get_str("database_title"),
            "mapping_saved": self._settings.get(MAPPING_KEY) is not None,
            "full_sync_required": _flag(self._settings.get(FULL_SYNC_REQUIRED_KEY)),
        }

    # --- pasted tokens (12.4) -------------------------------------------------------------

    def connect_with_token(self, kind: object, token: object) -> ConnectionInfo:
        if kind not in ("internal", "pat"):
            raise AppError(
                "Choose whether this is an internal integration token or a personal access token."
            )
        text = token.strip() if isinstance(token, str) else ""
        if not text:
            raise InvalidTokenError("Paste the token first.")
        if len(text) > MAX_TOKEN_CHARS or re.search(r"\s", text):
            raise InvalidTokenError(
                "That doesn't look like a Notion token. Copy it again from Notion and paste only "
                "the token."
            )
        secret = Secret(text)
        candidate = StoredCredential(kind=kind, access_token=secret, obtained_at=utc_now())
        me = self._check_token(candidate)
        details = _identity(me)
        # Validated: now it may be stored. A Notion sign-in it replaces is revoked first, so the
        # old access doesn't linger in Notion (a failure here never blocks the new connection).
        self._revoke_previous_oauth()
        self._tokens.replace_credential(candidate)
        self._settings.set_many(
            {
                "auth_kind": kind,
                "workspace_id": details["workspace_id"],
                "workspace_name": details["workspace_name"],
                "workspace_icon": None,
                "account_name": details["account_name"],
            }
        )
        logger.info("Connected to Notion with a pasted %s token", kind)
        self._connected()
        return self.info()

    def _revoke_previous_oauth(self) -> None:
        previous = self._tokens.credential()
        if previous is None or previous.kind != "oauth":
            return
        try:
            self._service.revoke(previous.access_token)
        except Exception as exc:  # noqa: BLE001 - replacing must not fail because of this
            logger.warning("Couldn't revoke the replaced connection: %s", type(exc).__name__)

    def _check_token(self, candidate: StoredCredential) -> dict[str, Any]:
        """Validate a token without storing it: a throwaway manager holds it in memory only."""
        scratch = TokenManager(_MemoryStore(candidate), self._service)
        reader = self._make_reader(scratch) if self._make_reader else None
        if reader is None:  # pragma: no cover - always injected by the app
            raise AppError("The app isn't set up to check tokens.")
        try:
            return reader.users_me()
        except PasteNewTokenError as exc:
            raise InvalidTokenError(
                "Notion didn't accept that token. Check that you copied all of it, that it "
                "hasn't expired, and that you chose the right kind of token.",
                detail="users/me returned 401",
            ) from exc
        finally:
            reader.close()

    # --- OAuth (12.3) ---------------------------------------------------------------------

    def start_sign_in(self) -> dict[str, object]:
        """Open Notion's consent page in the browser. The outcome arrives as events."""
        with self._lock:
            if self._sign_in is not None and not self._sign_in.finished:
                current = self._sign_in
                if current.authorize_url:
                    self._open_browser(current.authorize_url)
                return {"port": current.listener.port, "reopened": True}
            key = OneTimeKey()
            holder: dict[str, _SignIn] = {}
            listener = LoopbackListener(
                lambda: holder["flow"].state if "flow" in holder else None,
                lambda payload: self._on_payload(holder["flow"], payload),
            )
            flow = _SignIn(key=key, listener=listener)
            holder["flow"] = flow
            self._sign_in = flow
        listener.start()
        try:
            started = self._service.start(listener.port, key.public_key)
        except Exception:
            self._finish(flow, None)
            raise
        flow.state = started.state
        flow.authorize_url = started.authorize_url
        flow.clock = ServerClock.from_start(started.server_time)
        threading.Thread(target=self._watch, args=(flow,), name="oauth-wait", daemon=True).start()
        self._emit("connect:waiting", {"timeout_s": self._timeout})
        self._open_browser(started.authorize_url)
        return {"port": listener.port, "reopened": False}

    def cancel_sign_in(self) -> None:
        with self._lock:
            flow = self._sign_in
        if flow is None or flow.finished:
            return
        flow.cancelled = True
        self._finish(flow, "cancelled")

    def _watch(self, flow: _SignIn) -> None:
        arrived = flow.listener.wait(self._timeout)
        if not arrived and not flow.finished:
            self._finish(flow, "timeout")

    def _on_payload(self, flow: _SignIn, payload: str) -> BrowserPage:
        """Runs on the listener thread, once, for the matching /done request."""
        if flow.clock is None or flow.state is None:
            raise AppError("The sign-in result arrived before sign-in started.")
        try:
            result = flow.key.open(payload, state=flow.state, clock=flow.clock)
        except HandoffError as exc:
            outcome: SignInResult = "expired" if exc.code == "expired" else "error"
            self._finish(flow, outcome, close_listener=False)
            return _browser_page_for(outcome)
        if isinstance(result, SignInFailed):
            outcome = {
                "access_denied": "access_denied",
                "notion_unreachable": "service_unreachable",
            }.get(result.error, "notion_error")  # type: ignore[assignment]
            self._finish(flow, outcome, close_listener=False)
            return _browser_page_for(outcome)
        try:
            self._store_grant(result)
        except Exception as exc:
            logger.exception("Couldn't store the new Notion connection")
            self._finish(
                flow, "error", close_listener=False, message=getattr(exc, "user_message", None)
            )
            return _browser_page_for("error")
        self._finish(flow, "connected", close_listener=False)
        return BrowserPage(
            "Connected to Notion",
            f"Habit Tracker is connected to {result.workspace_name or 'your workspace'}. "
            "Return to Habit Tracker to choose your work log.",
            ok=True,
        )

    def _store_grant(self, grant: TokenGrant) -> None:
        credential = StoredCredential(
            kind="oauth",
            access_token=grant.access_token,
            refresh_token=grant.refresh_token,
            bot_id=grant.bot_id,
            obtained_at=utc_now(),
        )
        self._tokens.replace_credential(credential)  # Credential Manager first
        self._settings.set_many(
            {
                "auth_kind": "oauth",
                "workspace_id": grant.workspace_id,
                "workspace_name": grant.workspace_name,
                "workspace_icon": self._icon(grant.workspace_icon),
                "account_name": None,
            }
        )
        logger.info("Connected to Notion through OAuth")
        self._connected()

    def _connected(self) -> None:
        """Record that the user connected, where the privacy policy is linked (PLAN.md 13)."""
        if self._on_connected is None:
            return
        try:
            self._on_connected()
        except Exception:  # the connection itself succeeded
            logger.exception("Couldn't record the privacy policy version after connecting")

    def _finish(
        self,
        flow: _SignIn,
        outcome: SignInResult | None,
        *,
        close_listener: bool = True,
        message: str | None = None,
    ) -> None:
        with self._lock:
            if flow.finished:
                return
            flow.finished = True
        flow.key.destroy()
        if close_listener:
            threading.Thread(target=flow.listener.close, daemon=True).start()
        else:
            # Called from the listener's own thread: close it once this request is answered.
            threading.Timer(0.5, flow.listener.close).start()
        if outcome is not None:
            payload: dict[str, object] = {"result": outcome}
            if message:
                payload["message"] = message
            if outcome == "connected":
                payload["connection"] = self.info()
            self._emit("connect:done", payload)

    # --- icons ----------------------------------------------------------------------------

    def _icon(self, icon: str | None) -> WorkspaceIcon | None:
        """Notion gives an emoji or an image URL. Images are fetched once and kept as a data
        URI, so the UI's strict CSP doesn't need to allow remote images and they show offline."""
        if not icon:
            return None
        if not icon.startswith("https://"):
            return {"type": "emoji", "value": icon[:16]}
        try:
            response = self._http.get(icon)
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            if response.status_code != 200 or content_type not in ICON_TYPES:
                return None
            if len(response.content) > MAX_ICON_BYTES:
                return None
        except httpx.HTTPError:
            logger.info("Couldn't download the workspace icon; showing a letter instead")
            return None
        encoded = base64.b64encode(response.content).decode("ascii")
        return {"type": "image", "value": f"data:{content_type};base64,{encoded}"}

    # --- logout (12.7) --------------------------------------------------------------------

    def logout(self, clear_local_data: object) -> dict[str, object]:
        if not isinstance(clear_local_data, bool):
            raise AppError("Choose whether to keep or clear the local data.")
        self.cancel_sign_in()
        credential = self._tokens.credential()
        revoked: bool | None = None
        revoke_error: str | None = None
        if credential is not None and credential.kind == "oauth":
            try:
                self._service.revoke(credential.access_token)
                revoked = True
            except Exception as exc:  # noqa: BLE001 - revoke failures never block logout
                revoked = False
                revoke_error = getattr(exc, "user_message", "Revoking access failed.")
                logger.warning("Revoking the Notion connection failed: %s", type(exc).__name__)
        self._tokens.forget()
        keys = list(CONNECTION_KEYS)
        if clear_local_data:
            keys += list(SOURCE_DATA_KEYS)
            with lock_for(self._db), self._db:
                self._db.execute("DELETE FROM work_logs")
        self._settings.delete(keys)
        self._titles.clear()
        logger.info(
            "Disconnected from Notion (local data %s)", "cleared" if clear_local_data else "kept"
        )
        return {
            "kind": credential.kind if credential else None,
            "revoked": revoked,
            "revoke_error": revoke_error,
            "cleared_local_data": clear_local_data,
        }

    # --- database picker (12.6) -----------------------------------------------------------

    def list_data_sources(self, cursor: object = None) -> DataSourcePage:
        if self._tokens.credential() is None:
            raise NotConnectedError
        page = self._reader.search_data_sources(cursor if isinstance(cursor, str) else None)
        groups: dict[str, DatabaseGroup] = {}
        for item in page.get("results", []):
            if not isinstance(item, dict) or item.get("object") != "data_source":
                continue
            parent = item.get("parent") or {}
            database_id = parent.get("database_id") if isinstance(parent, dict) else None
            source_name = _plain_title(item.get("title")) or "Untitled data source"
            if not isinstance(database_id, str):
                continue
            title, emoji = self._database_title(database_id, fallback=source_name)
            group = groups.setdefault(
                database_id,
                {
                    "database_id": database_id,
                    "title": title,
                    "icon_emoji": emoji,
                    "data_sources": [],
                },
            )
            group["data_sources"].append({"id": str(item.get("id")), "name": source_name})
        next_cursor = page.get("next_cursor") if page.get("has_more") else None
        return {
            "groups": list(groups.values()),
            "next_cursor": next_cursor if isinstance(next_cursor, str) else None,
            "sharing_help_url": SHARING_HELP_URL,
        }

    def _database_title(self, database_id: str, *, fallback: str) -> tuple[str, str | None]:
        cached = self._titles.get(database_id)
        if cached:
            return cached
        try:
            database = self._reader.retrieve_database(database_id)
        except NotionRequestError:
            return fallback, None
        title = _plain_title(database.get("title")) or fallback
        icon = database.get("icon")
        emoji = (
            icon.get("emoji") if isinstance(icon, dict) and icon.get("type") == "emoji" else None
        )
        self._titles[database_id] = (title, emoji if isinstance(emoji, str) else None)
        return self._titles[database_id]

    def choose_data_source(
        self, database_id: object, data_source_id: object, confirm_replace: object = False
    ) -> ConnectionInfo:
        if not isinstance(database_id, str) or not isinstance(data_source_id, str):
            raise AppError("Choose a database first.")
        source = self._reader.retrieve_data_source(data_source_id)
        parent = source.get("parent") or {}
        if not isinstance(parent, dict) or parent.get("database_id") != database_id:
            raise AppError("That data source doesn't belong to the chosen database.")
        previous = self._settings.get_str("data_source_id")
        if previous and previous != data_source_id and confirm_replace is not True:
            with lock_for(self._db):
                count = self._db.execute("SELECT COUNT(*) FROM work_logs").fetchone()[0]
            if count:
                old = self._settings.get_str("database_title") or "the previous database"
                raise ConfirmationRequiredError(
                    f"Switching removes the {count} entries copied from {old}. They stay in "
                    "Notion, and the new database's entries are copied at the next sync."
                )
        title, _emoji = self._database_title(
            database_id, fallback=_plain_title(source.get("title")) or "Untitled"
        )
        values: dict[str, object] = {
            "database_id": database_id,
            "data_source_id": data_source_id,
            "database_title": title,
        }
        if previous and previous != data_source_id:
            with lock_for(self._db), self._db:
                self._db.execute("DELETE FROM work_logs")
            values.update(dict.fromkeys(k for k in SOURCE_DATA_KEYS if k not in SOURCE_KEYS))
        self._settings.set_many(values)
        logger.info("Chose the work log data source")
        return self.info()


class _MemoryStore:
    """A CredentialStore stand-in that never touches Credential Manager (for token checks)."""

    def __init__(self, credential: StoredCredential) -> None:
        self._credential: StoredCredential | None = credential

    def load(self) -> StoredCredential | None:
        return self._credential

    def save(self, credential: StoredCredential) -> None:
        self._credential = credential

    def delete(self) -> None:
        self._credential = None


def _plain_title(rich_text: object) -> str:
    if not isinstance(rich_text, list):
        return ""
    return "".join(
        str(part.get("plain_text", "")) for part in rich_text if isinstance(part, dict)
    ).strip()


def _identity(me: dict[str, Any]) -> dict[str, str | None]:
    """Workspace and account details from ``users/me``, for a bot or a person."""
    if me.get("type") == "bot":
        bot = me.get("bot") or {}
        name = bot.get("workspace_name") if isinstance(bot, dict) else None
        workspace_id = bot.get("workspace_id") if isinstance(bot, dict) else None
        return {
            "workspace_name": name if isinstance(name, str) else None,
            "workspace_id": workspace_id if isinstance(workspace_id, str) else None,
            "account_name": None,
        }
    person_name = me.get("name")
    return {
        "workspace_name": None,
        "workspace_id": None,
        "account_name": person_name if isinstance(person_name, str) else None,
    }


def _flag(value: object) -> dict[str, str] | None:
    if isinstance(value, dict) and all(isinstance(value.get(k), str) for k in ("since", "reason")):
        return {"since": value["since"], "reason": value["reason"]}
    return None


def _is_icon(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") in ("emoji", "image")
        and isinstance(value.get("value"), str)
    )


def _browser_page_for(outcome: SignInResult) -> BrowserPage:
    pages: dict[str, BrowserPage] = {
        "access_denied": BrowserPage(
            "Sign-in cancelled", "You didn't allow access in Notion, so nothing changed.", ok=False
        ),
        "expired": BrowserPage(
            "This sign-in expired",
            "It took too long to finish. Return to Habit Tracker and click Connect again.",
            ok=False,
        ),
        "service_unreachable": BrowserPage(
            "Notion couldn't be reached",
            "Habit Tracker's sign-in service couldn't reach Notion. Return to the app and "
            "try again.",
            ok=False,
        ),
        "notion_error": BrowserPage(
            "Notion couldn't complete the sign-in",
            "Return to Habit Tracker and try again.",
            ok=False,
        ),
    }
    return pages.get(
        outcome,
        BrowserPage("Something went wrong", "Return to Habit Tracker and try again.", ok=False),
    )
