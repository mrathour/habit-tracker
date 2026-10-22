"""Serve :class:`FakeNotion` over HTTP for the end-to-end tests.

Besides the API it serves Notion's consent page, ``GET /v1/oauth/authorize``, as an immediate
redirect back to ``redirect_uri``: with a one-time ``code`` when ``authorize`` is "allow", or
``error=access_denied`` when it is "deny". The token endpoint then only accepts issued codes.
"""

from __future__ import annotations

import http.server
import json
import threading
import urllib.parse
import uuid
from typing import Literal

import httpx

from tests.support.fake_notion import FakeNotion


class FakeNotionServer:
    def __init__(self, notion: FakeNotion | None = None) -> None:
        self.notion = notion or FakeNotion()
        self.authorize: Literal["allow", "deny"] = "allow"
        self.issued_codes: set[str] = set()
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server._serve(self)

            def do_POST(self) -> None:
                server._serve(self)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> FakeNotionServer:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def _serve(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        url = urllib.parse.urlsplit(handler.path)
        if url.path == "/v1/oauth/authorize":
            self._authorize(handler, dict(urllib.parse.parse_qsl(url.query)))
            return
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length) if length else b""
        if url.path == "/v1/oauth/token":
            payload = json.loads(body or b"{}")
            if payload.get("grant_type") == "authorization_code":
                if payload.get("code") not in self.issued_codes:
                    self._send(handler, httpx.Response(400, json={"error": "invalid_grant"}))
                    return
                self.issued_codes.discard(payload["code"])
        request = httpx.Request(
            handler.command,
            f"{self.url}{handler.path}",
            headers=dict(handler.headers.items()),
            content=body,
        )
        self._send(handler, self.notion.handle(request))

    def _authorize(
        self, handler: http.server.BaseHTTPRequestHandler, query: dict[str, str]
    ) -> None:
        params = {"state": query.get("state", "")}
        if self.authorize == "allow":
            code = "code-" + uuid.uuid4().hex
            self.issued_codes.add(code)
            params["code"] = code
        else:
            params["error"] = "access_denied"
        target = f"{query.get('redirect_uri', '')}?{urllib.parse.urlencode(params)}"
        handler.send_response(302)
        handler.send_header("Location", target)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    @staticmethod
    def _send(handler: http.server.BaseHTTPRequestHandler, response: httpx.Response) -> None:
        content = response.content
        handler.send_response(response.status_code)
        handler.send_header(
            "Content-Type", response.headers.get("Content-Type", "application/json")
        )
        handler.send_header("Content-Length", str(len(content)))
        handler.end_headers()
        handler.wfile.write(content)
