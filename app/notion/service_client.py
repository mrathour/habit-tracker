"""Client for the Habit Tracker token service (service/, docs/handoff-protocol.md).

Only connect (``/start``), renew (``/refresh``) and disconnect (``/revoke``) use the service.
Everything else goes straight from the app to Notion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

import httpx

from app import __version__
from app.notion.errors import (
    NotionAccessError,
    ReconnectRequiredError,
    TokenServiceUnreachableError,
)
from app.notion.handoff import TokenGrant
from app.redaction import Secret

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_URL: Final = "https://habit-tracker.mrathour.workers.dev"
#: Overrides the service address, for the end-to-end tests' local Worker.
SERVICE_URL_ENV_VAR: Final = "HABIT_TRACKER_SERVICE_URL"
TIMEOUT_S: Final = 15.0


class TokenServiceError(NotionAccessError):
    """The service answered, but with an error the app can't recover from by itself."""

    def __init__(self, error: str, status: int) -> None:
        super().__init__(
            "Habit Tracker's sign-in service couldn't complete the request. Try again later.",
            detail=f"{status} {error}",
        )
        self.error = error
        self.status = status


@dataclass(frozen=True, slots=True)
class StartResult:
    state: str
    authorize_url: str
    server_time: float


class TokenServiceClient:
    def __init__(
        self, base_url: str = DEFAULT_SERVICE_URL, http: httpx.Client | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(
            timeout=TIMEOUT_S,
            headers={"User-Agent": f"HabitTracker/{__version__}"},
            follow_redirects=False,
        )

    def _post(self, path: str, body: dict[str, Any], action: str) -> dict[str, Any]:
        try:
            response = self._http.post(f"{self.base_url}{path}", json=body)
        except httpx.HTTPError as exc:
            # Never include the request: it may hold a token.
            raise TokenServiceUnreachableError(action, detail=type(exc).__name__) from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise TokenServiceUnreachableError(action, detail=f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise TokenServiceError("bad_response", response.status_code)
        if response.status_code != 200:
            error = str(data.get("error", "unknown"))
            if error == "invalid_grant":
                raise ReconnectRequiredError(detail="The token service reported invalid_grant.")
            if error == "notion_unreachable":
                raise TokenServiceUnreachableError(action, detail="Notion was unreachable")
            raise TokenServiceError(error, response.status_code)
        return data

    def health(self) -> bool:
        try:
            response = self._http.get(f"{self.base_url}/health")
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def start(self, port: int, public_key: str) -> StartResult:
        data = self._post("/start", {"port": port, "public_key": public_key}, "start signing in")
        try:
            return StartResult(
                state=str(data["state"]),
                authorize_url=str(data["authorize_url"]),
                server_time=float(data["server_time"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TokenServiceError("bad_response", 200) from exc

    def refresh(self, refresh_token: Secret) -> TokenGrant:
        data = self._post(
            "/refresh", {"refresh_token": refresh_token.reveal()}, "renew Notion access"
        )
        access = data.get("access_token")
        new_refresh = data.get("refresh_token")
        if not isinstance(access, str) or not isinstance(new_refresh, str) or not access:
            raise TokenServiceError("bad_response", 200)
        name = data.get("workspace_name")
        icon = data.get("workspace_icon")
        return TokenGrant(
            access_token=Secret(access),
            refresh_token=Secret(new_refresh),
            bot_id=str(data.get("bot_id", "")),
            workspace_id=str(data.get("workspace_id", "")),
            workspace_name=name if isinstance(name, str) else None,
            workspace_icon=icon if isinstance(icon, str) else None,
        )

    def revoke(self, token: Secret) -> None:
        self._post("/revoke", {"token": token.reveal()}, "disconnect from Notion")

    def close(self) -> None:
        self._http.close()
