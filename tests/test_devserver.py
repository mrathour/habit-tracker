from __future__ import annotations

import http.server
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import devserver
from app.errors import AppError


class _Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(404 if self.path == "/missing" else 200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def local_server() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


def free_port_url() -> str:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Quiet)
    port = server.server_address[1]
    server.server_close()
    return f"http://127.0.0.1:{port}/"


@pytest.mark.parametrize(
    "url",
    ["https://127.0.0.1:5173/", "http://example.com:5173/", "http://127.0.0.1/", "file:///x"],
)
def test_only_local_http_urls_are_accepted(url: str) -> None:
    with pytest.raises(AppError):
        devserver.validate_dev_url(url)


def test_local_urls_are_accepted() -> None:
    assert devserver.validate_dev_url("http://localhost:5173/") == "http://localhost:5173/"


def test_is_serving(local_server: str) -> None:
    assert devserver.is_serving(local_server)
    assert devserver.is_serving(local_server + "missing")  # any HTTP answer counts
    assert not devserver.is_serving(free_port_url(), timeout=0.2)


def test_running_server_is_reused(local_server: str, tmp_path: Path) -> None:
    assert devserver.ensure_dev_server(tmp_path, local_server) is None


def test_missing_node(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(AppError, match=r"Node\.js"):
        devserver.ensure_dev_server(tmp_path, free_port_url())


def test_missing_ui_packages(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="packages aren't installed") as caught:
        devserver.ensure_dev_server(tmp_path, free_port_url())
    assert "npm --prefix" in (caught.value.detail or "")


def test_server_that_exits_during_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vite = tmp_path / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    vite.write_text("console.log('starting'); process.exit(3);", encoding="utf-8")
    with pytest.raises(AppError, match="stopped while starting") as caught:
        devserver.ensure_dev_server(tmp_path, free_port_url())
    assert "code 3" in (caught.value.detail or "")


def test_server_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A stand-in for Vite: a tiny Node HTTP server on the requested port.
    vite = tmp_path / "node_modules" / "vite" / "bin" / "vite.js"
    vite.parent.mkdir(parents=True)
    vite.write_text(
        "const port = Number(process.argv[process.argv.indexOf('--port') + 1]);"
        "require('http').createServer((q, s) => s.end('ok')).listen(port, '127.0.0.1',"
        " () => console.log('ready on ' + port));",
        encoding="utf-8",
    )
    url = free_port_url()
    server = devserver.ensure_dev_server(tmp_path, url)
    assert server is not None
    try:
        assert devserver.is_serving(url)
    finally:
        server.stop()
    assert not devserver.is_serving(url, timeout=0.2)
    server.stop()  # stopping twice is harmless
