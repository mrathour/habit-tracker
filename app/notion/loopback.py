"""The one-request listener on 127.0.0.1 that receives the sign-in result (PLAN.md 12.3).

It binds a random free port, serves only ``GET /done``, and accepts exactly one request whose
``state`` matches. Other paths get 404 and a wrong state gets 400; neither ends the sign-in.
The browser is shown a small page saying what happened. The page holds no secrets.
"""

from __future__ import annotations

import html
import http.server
import logging
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

HOST: Final = "127.0.0.1"
PAGE_CSP: Final = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
)


@dataclass(frozen=True, slots=True)
class BrowserPage:
    title: str
    message: str
    ok: bool


#: Called with the hand-off payload; returns the page to show in the browser.
PayloadHandler = Callable[[str], BrowserPage]


def render_browser_page(page: BrowserPage) -> bytes:
    colour = "#2f6f5e" if page.ok else "#b3261e"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="color-scheme" content="light dark">
<title>{html.escape(page.title)} · Habit Tracker</title>
<style>
body {{ font: 16px/1.5 "Segoe UI", system-ui, sans-serif; display: grid; place-items: center;
       min-height: 90vh; margin: 0; padding: 16px; }}
main {{ max-width: 520px; text-align: center; }}
h1 {{ color: {colour}; font-size: 22px; }}
</style></head>
<body><main><h1>{html.escape(page.title)}</h1><p>{html.escape(page.message)}</p>
<p>You can close this tab.</p></main></body></html>""".encode()


class LoopbackListener:
    def __init__(self, state_getter: Callable[[], str | None], on_payload: PayloadHandler) -> None:
        self._state_getter = state_getter
        self._on_payload = on_payload
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._accepted = False
        listener = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                listener._handle(self)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                # The URL holds the encrypted payload; never log requests.
                return

        self._server = http.server.HTTPServer((HOST, 0), Handler)
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="oauth-listener", daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        logger.info("Waiting for the sign-in result on 127.0.0.1:%d", self.port)

    def wait(self, timeout: float) -> bool:
        """True once the hand-off arrived; False on timeout or close."""
        return self._done.wait(timeout) and self._accepted

    def close(self) -> None:
        self._done.set()
        self._server.shutdown()
        self._server.server_close()

    def _handle(self, request: http.server.BaseHTTPRequestHandler) -> None:
        url = urllib.parse.urlsplit(request.path)
        params = dict(urllib.parse.parse_qsl(url.query))
        if url.path != "/done":
            self._reply(request, 404, None)
            return
        expected = self._state_getter()
        with self._lock:
            if self._accepted or expected is None or params.get("state") != expected:
                self._reply(request, 400, None)
                return
            self._accepted = True
        try:
            page = self._on_payload(params.get("payload", ""))
        except Exception:
            logger.exception("Handling the sign-in result failed")
            page = BrowserPage(
                "Something went wrong",
                "Habit Tracker couldn't finish connecting. Return to the app and try again.",
                ok=False,
            )
        self._reply(request, 200, page)
        self._done.set()

    @staticmethod
    def _reply(
        request: http.server.BaseHTTPRequestHandler, status: int, page: BrowserPage | None
    ) -> None:
        body = render_browser_page(page) if page else b""
        request.send_response(status)
        request.send_header("Content-Type", "text/html; charset=utf-8")
        request.send_header("Content-Security-Policy", PAGE_CSP)
        request.send_header("Cache-Control", "no-store")
        request.send_header("Referrer-Policy", "no-referrer")
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        request.wfile.write(body)
