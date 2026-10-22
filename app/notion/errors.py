"""Errors from talking to Notion and the token service, each mapped to a state the UI shows.

Every class carries a ``state`` the UI switches on (PLAN.md 6.4 "States the UI shows") and a
message written for the user. None of them ever includes a token.
"""

from __future__ import annotations

from typing import Literal

from app.errors import AppError

ConnectionState = Literal[
    "offline",
    "reconnect",
    "paste_new_token",
    "service_unreachable",
    "credential_store",
    "notion_error",
    "not_connected",
]


class NotionAccessError(AppError):
    """Base class: something stopped the app from reaching Notion's data."""

    state: ConnectionState = "notion_error"


class OfflineError(NotionAccessError):
    """No network connection to Notion or the token service."""

    state = "offline"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            "You're offline, or Notion can't be reached right now. Your local data is still "
            "available.",
            detail=detail,
        )


class ReconnectRequiredError(NotionAccessError):
    """An OAuth connection was revoked or can no longer be renewed (invalid_grant, 401)."""

    state = "reconnect"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            "Notion no longer accepts Habit Tracker's access. Reconnect to Notion to continue; "
            "your local data is kept.",
            detail=detail,
        )


class PasteNewTokenError(NotionAccessError):
    """A pasted token expired or was revoked. Pasted tokens can't be renewed by the app."""

    state = "paste_new_token"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            "Notion no longer accepts the token you pasted. It may have expired or been "
            "revoked. Paste a new token in Settings → Advanced; your local data is kept.",
            detail=detail,
        )


class TokenServiceUnreachableError(NotionAccessError):
    """The sign-in service couldn't be reached. Only connect, renew and revoke need it."""

    state = "service_unreachable"

    def __init__(self, action: str = "renew Notion access", detail: str | None = None) -> None:
        super().__init__(
            f"Couldn't {action}: Habit Tracker's sign-in service can't be reached. Try again "
            "in a moment. Your local data is still available.",
            detail=detail,
        )


class CredentialStoreError(NotionAccessError):
    """Windows Credential Manager refused to save, read or delete the token."""

    state = "credential_store"

    def __init__(self, action: str, detail: str | None = None) -> None:
        super().__init__(
            f"Windows Credential Manager couldn't {action} Habit Tracker's Notion access.",
            detail=detail,
        )


class NotConnectedError(NotionAccessError):
    """No Notion connection is stored."""

    state = "not_connected"

    def __init__(self) -> None:
        super().__init__("Habit Tracker isn't connected to Notion yet.")


class NotionRequestError(NotionAccessError):
    """Notion refused a request for a reason other than authentication."""

    state = "notion_error"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message, detail=f"Notion error {status}: {code}" if code else None)
        self.code = code
        self.status = status
