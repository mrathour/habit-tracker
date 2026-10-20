"""The stored Notion connection, in Windows Credential Manager via ``keyring`` (PLAN.md 12.5).

One entry: service ``HabitTracker``, account ``notion``. A copy of the app pointed at another
data folder (``HABIT_TRACKER_HOME``) uses its own account, so tests and throwaway copies never
touch the real connection.

The entry is a small JSON blob, ``{v, kind, access_token, refresh_token?, bot_id?,
obtained_at}``, kept well under Credential Manager's 2,560-byte limit. Tokens never go anywhere
else: not SQLite, not files, not logs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol

import keyring
import keyring.errors

from app.notion.errors import CredentialStoreError
from app.redaction import Secret, forget_secret

logger = logging.getLogger(__name__)

SERVICE_NAME: Final = "HabitTracker"
DEFAULT_ACCOUNT: Final = "notion"
FORMAT_VERSION: Final = 1
#: Windows stores the secret as UTF-16 in at most 2,560 bytes, so 1,280 characters.
MAX_BLOB_CHARS: Final = 1280

AuthKind = Literal["oauth", "internal", "pat"]
AUTH_KINDS: Final[frozenset[str]] = frozenset({"oauth", "internal", "pat"})


@dataclass(frozen=True, slots=True)
class StoredCredential:
    kind: AuthKind
    access_token: Secret
    refresh_token: Secret | None = None
    bot_id: str | None = None
    obtained_at: str = ""

    @property
    def can_refresh(self) -> bool:
        return self.kind == "oauth" and self.refresh_token is not None

    def to_json(self) -> str:
        data: dict[str, object] = {
            "v": FORMAT_VERSION,
            "kind": self.kind,
            "access_token": self.access_token.reveal(),
            "obtained_at": self.obtained_at or utc_now(),
        }
        if self.refresh_token is not None:
            data["refresh_token"] = self.refresh_token.reveal()
        if self.bot_id is not None:
            data["bot_id"] = self.bot_id
        return json.dumps(data, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> StoredCredential:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("v") != FORMAT_VERSION:
            raise ValueError("unsupported credential format")
        kind = data.get("kind")
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        bot_id = data.get("bot_id")
        if kind not in AUTH_KINDS or not isinstance(access, str) or not access:
            raise ValueError("malformed credential")
        if refresh is not None and not isinstance(refresh, str):
            raise ValueError("malformed credential")
        return cls(
            kind=kind,
            access_token=Secret(access),
            refresh_token=Secret(refresh) if refresh else None,
            bot_id=bot_id if isinstance(bot_id, str) else None,
            obtained_at=str(data.get("obtained_at", "")),
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class CredentialBackend(Protocol):
    """What the token manager needs from a store: Credential Manager, or memory for checks."""

    def load(self) -> StoredCredential | None: ...
    def save(self, credential: StoredCredential) -> None: ...
    def delete(self) -> None: ...


class CredentialStore:
    def __init__(self, account: str = DEFAULT_ACCOUNT) -> None:
        self.account = account

    def load(self) -> StoredCredential | None:
        try:
            text = keyring.get_password(SERVICE_NAME, self.account)
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreError("read", detail=type(exc).__name__) from exc
        if text is None:
            return None
        try:
            return StoredCredential.from_json(text)
        except (ValueError, json.JSONDecodeError):
            # Never log the blob: it holds the token. A damaged entry is treated as absent.
            logger.warning("The stored Notion connection is damaged; treating it as missing")
            return None

    def save(self, credential: StoredCredential) -> None:
        blob = credential.to_json()
        if len(blob) > MAX_BLOB_CHARS:
            raise CredentialStoreError(
                "save", detail=f"The connection is {len(blob)} characters; the limit is 1280."
            )
        try:
            keyring.set_password(SERVICE_NAME, self.account, blob)
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreError("save", detail=type(exc).__name__) from exc
        logger.info("Saved the Notion connection (%s) to Credential Manager", credential.kind)

    def delete(self) -> None:
        existing = self.load()
        try:
            keyring.delete_password(SERVICE_NAME, self.account)
        except keyring.errors.PasswordDeleteError:
            pass  # nothing stored
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreError("delete", detail=type(exc).__name__) from exc
        if existing is not None:
            forget_secret(existing.access_token.reveal())
            if existing.refresh_token is not None:
                forget_secret(existing.refresh_token.reveal())
        logger.info("Deleted the Notion connection from Credential Manager")
