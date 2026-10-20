"""A fake Notion API for tests. Responses follow Notion API 2026-03-11.

:meth:`FakeNotion.handle` maps an ``httpx.Request`` to an ``httpx.Response``, so unit tests plug
it into ``httpx.MockTransport``; the end-to-end tests serve the same handler over HTTP.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx


def notion_error(status: int, code: str, message: str = "error") -> httpx.Response:
    return httpx.Response(
        status, json={"object": "error", "status": status, "code": code, "message": message}
    )


@dataclass
class FakeDatabase:
    id: str
    title: str
    data_source_ids: list[str]
    icon: dict[str, Any] | None = None


@dataclass
class FakeDataSource:
    id: str
    name: str
    database_id: str


@dataclass
class FakeNotion:
    """State of a pretend workspace. Tests change it, then make requests."""

    workspace_name: str = "Test Workspace"
    workspace_id: str = "ws-0001"
    bot_id: str = "bot-0001"
    #: Access tokens Notion currently accepts.
    valid_tokens: set[str] = field(default_factory=set)
    #: For the OAuth endpoints: refresh token -> True while valid.
    valid_refresh_tokens: set[str] = field(default_factory=set)
    databases: dict[str, FakeDatabase] = field(default_factory=dict)
    data_sources: dict[str, FakeDataSource] = field(default_factory=dict)
    #: Hidden from search (not shared with the integration).
    unshared: set[str] = field(default_factory=set)
    page_size: int = 100
    #: Queue of forced responses for the next requests, e.g. a 503 or a network error.
    next_failures: list[httpx.Response | Exception] = field(default_factory=list)
    #: Users/me shape: "bot" for OAuth and internal tokens, "person" for personal tokens.
    me_type: str = "bot"
    requests: list[httpx.Request] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    # --- setup helpers --------------------------------------------------------------------

    def issue_token(self, prefix: str = "ntn_") -> str:
        token = prefix + uuid.uuid4().hex + uuid.uuid4().hex[:8]
        self.valid_tokens.add(token)
        return token

    def add_database(self, title: str, sources: list[str] | None = None) -> FakeDatabase:
        db_id = str(uuid.uuid4())
        database = FakeDatabase(id=db_id, title=title, data_source_ids=[])
        for name in sources or [title]:
            ds = FakeDataSource(id=str(uuid.uuid4()), name=name, database_id=db_id)
            self.data_sources[ds.id] = ds
            database.data_source_ids.append(ds.id)
        self.databases[db_id] = database
        return database

    # --- the handler ----------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
            if self.next_failures:
                failure = self.next_failures.pop(0)
                if isinstance(failure, Exception):
                    raise failure
                return failure
        path = request.url.path
        if (
            request.headers.get("Notion-Version") != "2026-03-11"
            and path.startswith("/v1/")
            and not path.startswith("/v1/oauth")
        ):
            return notion_error(400, "missing_version", "Notion-Version must be 2026-03-11")
        if path.startswith("/v1/oauth/"):
            return self._oauth(request)
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ")
        if token not in self.valid_tokens:
            return notion_error(401, "unauthorized", "API token is invalid.")
        if request.method != "GET" and not (request.method == "POST" and path == "/v1/search"):
            return notion_error(403, "restricted_resource", "The fake Notion is read-only.")
        return self._api(request, path)

    def _api(self, request: httpx.Request, path: str) -> httpx.Response:
        if path == "/v1/users/me":
            if self.me_type == "person":
                return httpx.Response(
                    200,
                    json={
                        "object": "user",
                        "id": "user-1",
                        "type": "person",
                        "name": "Mayank",
                        "person": {"email": "someone@example.test"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "object": "user",
                    "id": self.bot_id,
                    "type": "bot",
                    "name": "Habit Tracker",
                    "bot": {
                        "owner": {"type": "workspace", "workspace": True},
                        "workspace_name": self.workspace_name,
                    },
                },
            )
        if path == "/v1/search":
            return self._search(json.loads(request.content or b"{}"))
        if match := re.fullmatch(r"/v1/databases/([^/]+)", path):
            database = self.databases.get(match[1])
            if database is None or database.id in self.unshared:
                return notion_error(404, "object_not_found")
            return httpx.Response(200, json=self.database_json(database))
        if match := re.fullmatch(r"/v1/data_sources/([^/]+)", path):
            source = self.data_sources.get(match[1])
            if source is None or source.database_id in self.unshared:
                return notion_error(404, "object_not_found")
            return httpx.Response(200, json=self.data_source_json(source))
        return notion_error(404, "invalid_request_url")

    def _search(self, body: dict[str, Any]) -> httpx.Response:
        if body.get("filter") != {"property": "object", "value": "data_source"}:
            return notion_error(400, "validation_error", "expected the data_source filter")
        visible = [s for s in self.data_sources.values() if s.database_id not in self.unshared]
        start = int(body.get("start_cursor") or 0)
        size = min(int(body.get("page_size", 100)), self.page_size)
        page = visible[start : start + size]
        more = start + size < len(visible)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "results": [self.data_source_json(s) for s in page],
                "has_more": more,
                "next_cursor": str(start + size) if more else None,
                "type": "page_or_data_source",
            },
        )

    def database_json(self, database: FakeDatabase) -> dict[str, Any]:
        return {
            "object": "database",
            "id": database.id,
            "title": [
                {"type": "text", "plain_text": database.title, "text": {"content": database.title}}
            ],
            "icon": database.icon,
            "data_sources": [
                {"id": ds_id, "name": self.data_sources[ds_id].name}
                for ds_id in database.data_source_ids
            ],
            "url": f"https://www.notion.so/{database.id.replace('-', '')}",
        }

    def data_source_json(self, source: FakeDataSource) -> dict[str, Any]:
        return {
            "object": "data_source",
            "id": source.id,
            "title": [
                {"type": "text", "plain_text": source.name, "text": {"content": source.name}}
            ],
            "parent": {"type": "database_id", "database_id": source.database_id},
            "properties": {},
        }

    # --- OAuth (used behind the token service in end-to-end tests) -------------------------

    def _oauth(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path == "/v1/oauth/token":
            if body.get("grant_type") == "refresh_token":
                old = body.get("refresh_token")
                if old not in self.valid_refresh_tokens:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.valid_refresh_tokens.discard(old)
            elif body.get("grant_type") != "authorization_code":
                return httpx.Response(400, json={"error": "unsupported_grant_type"})
            access = self.issue_token()
            refresh = "nrt_" + uuid.uuid4().hex
            self.valid_refresh_tokens.add(refresh)
            return httpx.Response(
                200,
                json={
                    "access_token": access,
                    "refresh_token": refresh,
                    "token_type": "bearer",
                    "bot_id": self.bot_id,
                    "workspace_id": self.workspace_id,
                    "workspace_name": self.workspace_name,
                    "workspace_icon": None,
                    "owner": {"type": "user"},
                    "duplicated_template_id": None,
                },
            )
        if request.url.path == "/v1/oauth/revoke":
            self.valid_tokens.discard(body.get("token"))
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": "not_found"})
