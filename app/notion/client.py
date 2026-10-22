"""Read-only access to the Notion API (PLAN.md 6.4, 10).

:class:`NotionReader` exposes only read calls. There is no method that writes, so the app can't
write to Notion even by mistake; with an OAuth or internal connection, Notion also refuses writes.

Every request:

* sends ``Notion-Version: 2026-03-11`` and has an explicit timeout;
* waits for the shared rate limiter (about 3 requests a second);
* is retried by ``notion-client`` on 429 (honouring ``Retry-After``) and on 5xx for GETs, and by
  this class on 5xx for read-only POSTs (search, query), which ``notion-client`` won't retry;
* on a 401, renews the access once through :class:`~app.notion.tokens.TokenManager` and retries.

Every response's ``Date`` header is remembered per thread (:meth:`NotionReader.server_time`), so
a sync can keep its bookkeeping on Notion's clock instead of the PC's (PLAN.md 6.1).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final, TypeVar

import httpx
from notion_client import APIErrorCode, APIResponseError, Client
from notion_client.errors import HTTPResponseError, RequestTimeoutError

from app import __version__
from app.notion.errors import NotionRequestError, OfflineError, ReconnectRequiredError
from app.notion.tokens import TokenManager
from app.redaction import Secret

logger = logging.getLogger(__name__)

NOTION_VERSION: Final = "2026-03-11"
DEFAULT_NOTION_URL: Final = "https://api.notion.com"
#: Overrides the Notion API address, for the end-to-end tests' fake Notion.
NOTION_URL_ENV_VAR: Final = "HABIT_TRACKER_NOTION_URL"
REQUEST_TIMEOUT_MS: Final = 30_000
REQUESTS_PER_SECOND: Final = 3.0
#: Extra attempts for 5xx on read-only POSTs (notion-client already retries GETs).
POST_5XX_RETRIES: Final = 2
POST_5XX_BACKOFF_S: Final = 1.0

T = TypeVar("T")


class RateLimiter:
    """Spaces requests at least ``1 / rate`` seconds apart, across threads."""

    def __init__(
        self,
        rate: float = REQUESTS_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = 1.0 / rate
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._next)
            self._next = start + self._interval
        delay = start - now
        if delay > 0:
            self._sleep(delay)


class NotionReader:
    def __init__(
        self,
        tokens: TokenManager,
        *,
        http: httpx.Client | None = None,
        base_url: str = DEFAULT_NOTION_URL,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._tokens = tokens
        self._limiter = limiter or RateLimiter()
        self._sleep = sleep
        self._local = threading.local()
        transport = http or httpx.Client(
            timeout=REQUEST_TIMEOUT_MS / 1000,
            headers={"User-Agent": f"HabitTracker/{__version__}"},
        )
        hooks = transport.event_hooks
        hooks["response"] = [*hooks.get("response", []), self._remember_server_time]
        transport.event_hooks = hooks
        self._client = Client(
            client=transport,
            base_url=base_url,
            notion_version=NOTION_VERSION,
            timeout_ms=REQUEST_TIMEOUT_MS,
            logger=logging.getLogger("notion_client"),
            log_level=logging.WARNING,
        )

    # --- the read-only surface ----------------------------------------------------------

    def users_me(self) -> dict[str, Any]:
        return self._call(lambda auth: self._client.users.me(auth=auth))

    def search_data_sources(self, start_cursor: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "filter": {"property": "object", "value": "data_source"},
            "page_size": 100,
        }
        if start_cursor:
            body["start_cursor"] = start_cursor
        return self._call(lambda auth: self._client.search(auth=auth, **body), post=True)

    def retrieve_database(self, database_id: str) -> dict[str, Any]:
        return self._call(lambda auth: self._client.databases.retrieve(database_id, auth=auth))

    def retrieve_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self._call(
            lambda auth: self._client.data_sources.retrieve(data_source_id, auth=auth)
        )

    def query_data_source(
        self,
        data_source_id: str,
        *,
        page_size: int = 100,
        start_cursor: str | None = None,
        sorts: list[dict[str, str]] | None = None,
        filter: dict[str, Any] | None = None,  # noqa: A002 - Notion's parameter name
    ) -> dict[str, Any]:
        """One page of rows: ``POST /v1/data_sources/{id}/query`` (a read, despite the POST)."""
        body: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            body["start_cursor"] = start_cursor
        if sorts:
            body["sorts"] = sorts
        if filter:
            body["filter"] = filter
        return self._call(
            lambda auth: self._client.data_sources.query(data_source_id, auth=auth, **body),
            post=True,
        )

    def retrieve_property_item(
        self, page_id: str, property_id: str, start_cursor: str | None = None
    ) -> dict[str, Any]:
        """One page of a property's values: ``GET /v1/pages/{id}/properties/{property_id}``.

        Used to complete relations with more than 25 links (``has_more``), 100 at a time.
        """
        extra: dict[str, Any] = {"page_size": 100}
        if start_cursor:
            extra["start_cursor"] = start_cursor
        return self._call(
            lambda auth: self._client.pages.properties.retrieve(
                page_id=page_id, property_id=property_id, auth=auth, **extra
            )
        )

    # --- Notion's clock -----------------------------------------------------------------

    def server_time(self) -> datetime | None:
        """Notion's time from the ``Date`` header of this thread's latest response, in UTC."""
        value = getattr(self._local, "server_time", None)
        return value if isinstance(value, datetime) else None

    def forget_server_time(self) -> None:
        """Start afresh, so :meth:`server_time` only reports responses that come later."""
        self._local.server_time = None

    def _remember_server_time(self, response: httpx.Response) -> None:
        header = response.headers.get("Date")
        if not header:
            return
        try:
            moment = parsedate_to_datetime(header)
        except (TypeError, ValueError, IndexError):
            logger.debug("Ignored an unreadable Date header")
            return
        if moment.tzinfo is None:
            return  # RFC 9110 dates are always GMT; anything else isn't trusted
        self._local.server_time = moment.astimezone(UTC)

    # --- plumbing -------------------------------------------------------------------------

    def _call(self, request: Callable[[str], Any], *, post: bool = False) -> dict[str, Any]:
        token = self._tokens.access_token()
        try:
            return self._attempt(request, token, post=post)
        except APIResponseError as exc:
            if exc.code != APIErrorCode.Unauthorized:
                raise _request_error(exc) from exc
        # 401: renew once (or learn that the user must reconnect / paste a new token), retry.
        renewed = self._tokens.renew_after_unauthorized(token)
        try:
            return self._attempt(request, renewed, post=post)
        except APIResponseError as exc:
            if exc.code == APIErrorCode.Unauthorized:
                # Renewed and still refused: the connection itself is gone. Only one renewal
                # per request (PLAN.md 6.4), so the user has to reconnect.
                raise ReconnectRequiredError(
                    detail="Notion refused the renewed access token."
                ) from exc
            raise _request_error(exc) from exc

    def _attempt(
        self, request: Callable[[str], Any], token: Secret, *, post: bool
    ) -> dict[str, Any]:
        attempts = 1 + (POST_5XX_RETRIES if post else 0)
        for attempt in range(attempts):
            self._limiter.wait()
            try:
                result = request(token.reveal())
            except (httpx.TransportError, RequestTimeoutError) as exc:
                raise OfflineError(detail=type(exc).__name__) from exc
            except HTTPResponseError as exc:
                retryable = post and exc.status in (500, 502, 503, 504)
                if retryable and attempt + 1 < attempts:
                    self._sleep(POST_5XX_BACKOFF_S * (2**attempt))
                    continue
                if isinstance(exc, APIResponseError):
                    raise
                raise NotionRequestError(
                    "Notion had a problem answering. Try again in a moment.", status=exc.status
                ) from exc
            if not isinstance(result, dict):
                raise NotionRequestError("Notion sent an unexpected response.")
            return result
        raise AssertionError("unreachable")  # pragma: no cover

    def close(self) -> None:
        self._client.close()


def _request_error(exc: APIResponseError) -> NotionRequestError:
    code = str(exc.code.value if hasattr(exc.code, "value") else exc.code)
    if exc.code == APIErrorCode.ObjectNotFound:
        message = (
            "Notion couldn't find that page or database, or it isn't shared with Habit Tracker."
        )
    elif exc.code == APIErrorCode.RestrictedResource:
        message = "Habit Tracker doesn't have access to that in Notion."
    elif exc.code == APIErrorCode.RateLimited:
        message = "Notion is limiting requests right now. Try again in a minute."
    else:
        message = "Notion refused the request."
    return NotionRequestError(message, code=code, status=exc.status)
