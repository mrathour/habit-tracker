"""Events pushed from Python to the UI.

Python calls :meth:`EventChannel.emit` from any thread. The UI listens for the DOM event
``habit-tracker:event`` on ``window``; its ``detail`` is ``{"name": ..., "payload": ...}``.

Events emitted while the page is loading are buffered and delivered once the UI reports that
its listener is attached (:meth:`EventChannel.mark_ready`), so nothing sent during startup or a
reload is lost.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import Final, Protocol

logger = logging.getLogger(__name__)

DOM_EVENT_NAME: Final = "habit-tracker:event"
MAX_BUFFERED_EVENTS: Final = 1000


class ScriptRunner(Protocol):
    """The part of ``webview.Window`` the channel needs."""

    def run_js(self, script: str) -> object: ...


def build_dispatch_script(name: str, payload: object) -> str:
    """JavaScript that dispatches one event. The detail is JSON, which is valid JS."""
    detail = json.dumps({"name": name, "payload": payload}, ensure_ascii=True, allow_nan=False)
    event_name = json.dumps(DOM_EVENT_NAME)
    return f"window.dispatchEvent(new CustomEvent({event_name}, {{detail: {detail}}}));"


class EventChannel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runner: ScriptRunner | None = None
        self._ready = False
        self._pending: deque[str] = deque(maxlen=MAX_BUFFERED_EVENTS)

    def attach(self, runner: ScriptRunner) -> None:
        with self._lock:
            self._runner = runner

    def mark_loading(self) -> None:
        """The page is (re)loading: buffer events until the new page is ready."""
        with self._lock:
            self._ready = False

    def mark_ready(self) -> None:
        """The UI's listener is attached: deliver buffered events, then send directly."""
        with self._lock:
            self._ready = True
            pending = list(self._pending)
            self._pending.clear()
            runner = self._runner
        for script in pending:
            self._run(runner, script)

    def emit(self, name: str, payload: object = None) -> None:
        script = build_dispatch_script(name, payload)
        with self._lock:
            if not self._ready or self._runner is None:
                if len(self._pending) == self._pending.maxlen:
                    logger.warning("Event buffer full; dropping the oldest event")
                self._pending.append(script)
                return
            runner = self._runner
        self._run(runner, script)

    @staticmethod
    def _run(runner: ScriptRunner | None, script: str) -> None:
        if runner is None:
            return
        try:
            runner.run_js(script)
        except Exception:
            logger.exception("Could not deliver an event to the window")
