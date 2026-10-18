from __future__ import annotations

import json
import re

import pytest

from app.events import DOM_EVENT_NAME, MAX_BUFFERED_EVENTS, EventChannel, build_dispatch_script


class FakeWindow:
    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.fail = False

    def run_js(self, script: str) -> None:
        if self.fail:
            raise RuntimeError("window closed")
        self.scripts.append(script)


def detail_of(script: str) -> object:
    match = re.search(r"\{detail: (.*)\}\)\);$", script)
    assert match, script
    return json.loads(match.group(1))


def test_dispatch_script_shape() -> None:
    script = build_dispatch_script("sync:progress", {"pages": 3})
    assert script.startswith(f'window.dispatchEvent(new CustomEvent("{DOM_EVENT_NAME}"')
    assert detail_of(script) == {"name": "sync:progress", "payload": {"pages": 3}}


@pytest.mark.parametrize(
    "payload",
    [
        "</script><script>alert(1)</script>",
        "line\u2028separator",
        'quote " and \\ backslash',
        "émoji 🎯",
    ],
)
def test_payloads_are_safely_encoded(payload: str) -> None:
    script = build_dispatch_script("x", {"text": payload})
    assert script.isascii()
    assert "</script>" not in script or "\\u003c" in script or '"</script>' in script
    assert detail_of(script) == {"name": "x", "payload": {"text": payload}}


def test_non_finite_numbers_are_rejected() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        build_dispatch_script("x", float("nan"))


def test_events_wait_until_the_ui_is_ready() -> None:
    window = FakeWindow()
    channel = EventChannel()
    channel.attach(window)
    channel.emit("a", 1)
    channel.emit("b", 2)
    assert window.scripts == []

    channel.mark_ready()
    assert [detail_of(s) for s in window.scripts] == [
        {"name": "a", "payload": 1},
        {"name": "b", "payload": 2},
    ]

    channel.emit("c", 3)
    assert detail_of(window.scripts[-1]) == {"name": "c", "payload": 3}


def test_reload_buffers_again() -> None:
    window = FakeWindow()
    channel = EventChannel()
    channel.attach(window)
    channel.mark_ready()
    channel.mark_loading()
    channel.emit("during-reload")
    assert window.scripts == []
    channel.mark_ready()
    assert len(window.scripts) == 1


def test_events_before_a_window_exists_are_kept() -> None:
    channel = EventChannel()
    channel.mark_ready()
    channel.emit("early")
    window = FakeWindow()
    channel.attach(window)
    channel.mark_ready()
    assert len(window.scripts) == 1


def test_buffer_is_bounded(caplog: pytest.LogCaptureFixture) -> None:
    window = FakeWindow()
    channel = EventChannel()
    channel.attach(window)
    for i in range(MAX_BUFFERED_EVENTS + 5):
        channel.emit("n", i)
    channel.mark_ready()
    assert len(window.scripts) == MAX_BUFFERED_EVENTS
    assert detail_of(window.scripts[0]) == {"name": "n", "payload": 5}
    assert "dropping the oldest" in caplog.text


def test_delivery_failures_are_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    window = FakeWindow()
    window.fail = True
    channel = EventChannel()
    channel.attach(window)
    channel.mark_ready()
    channel.emit("x")
    assert "Could not deliver an event" in caplog.text
