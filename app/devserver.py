"""The Vite dev server used by dev mode.

``habit-tracker --dev`` reuses a dev server that is already running (``npm run dev`` in
``ui/``), or starts one itself and stops it when the window closes. Vite provides hot reload.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO, Final
from urllib.parse import urlsplit

from app.errors import AppError

logger = logging.getLogger(__name__)
vite_logger = logging.getLogger("vite")

DEFAULT_DEV_URL: Final = "http://127.0.0.1:5173/"
STARTUP_TIMEOUT_S: Final = 60.0
STOP_TIMEOUT_S: Final = 5.0

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def validate_dev_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost"} or not parts.port:
        raise AppError(
            "The dev server address must be a local http address with a port.",
            detail=f"Got {url!r}; for example {DEFAULT_DEV_URL}",
        )
    return url


def is_serving(url: str, timeout: float = 1.0) -> bool:
    """True if something answers HTTP requests at ``url``."""
    try:
        # The URL is validated to be local http by validate_dev_url.
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError):
        return False


class ViteDevServer:
    """A Vite process this app started and is responsible for stopping."""

    def __init__(self, process: subprocess.Popen[str], url: str) -> None:
        self._process = process
        self.url = url
        self._reader = threading.Thread(
            target=self._forward_output, args=(process.stdout,), name="vite-output", daemon=True
        )
        self._reader.start()

    @classmethod
    def start(cls, ui_dir: Path, url: str) -> ViteDevServer:
        node = shutil.which("node")
        if node is None:
            raise AppError(
                "Node.js wasn't found, so the dev server can't start.",
                detail="Install Node.js LTS (see docs/setup.md) and open a new terminal.",
            )
        vite = ui_dir / "node_modules" / "vite" / "bin" / "vite.js"
        if not vite.is_file():
            raise AppError(
                "The UI's packages aren't installed, so the dev server can't start.",
                detail=f"Run: npm --prefix {ui_dir} ci",
            )
        port = urlsplit(url).port
        host = urlsplit(url).hostname
        command = [node, str(vite), "--host", str(host), "--port", str(port), "--strictPort"]
        logger.info("Starting the Vite dev server at %s", url)
        process = subprocess.Popen(  # noqa: S603 - fixed command, no shell
            command,
            cwd=ui_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"},
        )
        server = cls(process, url)
        server._wait_until_serving()
        return server

    def _wait_until_serving(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self.stop()
                raise AppError(
                    "The dev server stopped while starting.",
                    detail=f"Vite exited with code {self._process.returncode}; see the log.",
                )
            if is_serving(self.url, timeout=0.5):
                logger.info("Vite dev server is ready")
                return
            time.sleep(0.2)
        self.stop()
        raise AppError(
            "The dev server didn't start in time.",
            detail=f"Nothing answered at {self.url} within {STARTUP_TIMEOUT_S:.0f} seconds.",
        )

    @staticmethod
    def _forward_output(stream: IO[str] | None) -> None:
        if stream is None:
            return
        for line in stream:
            text = _ANSI.sub("", line).rstrip()
            if text:
                vite_logger.info("%s", text)

    def stop(self) -> None:
        """Stop the process (if still running) and release its output pipe. Idempotent."""
        if self._process.poll() is None:
            logger.info("Stopping the Vite dev server")
            self._process.terminate()
            try:
                self._process.wait(timeout=STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=STOP_TIMEOUT_S)
        self._reader.join(timeout=STOP_TIMEOUT_S)
        if self._process.stdout is not None and not self._process.stdout.closed:
            self._process.stdout.close()


def ensure_dev_server(ui_dir: Path, url: str) -> ViteDevServer | None:
    """Use a running dev server at ``url``, or start one. Returns the server if we started it."""
    validate_dev_url(url)
    if is_serving(url):
        logger.info("Using the dev server already running at %s", url)
        return None
    return ViteDevServer.start(ui_dir, url)
