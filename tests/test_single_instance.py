from __future__ import annotations

import uuid

import pytest

from app import main
from app.paths import AppPaths
from app.single_instance import SingleInstance


def unique_name() -> str:
    return rf"Local\HabitTrackerTest-{uuid.uuid4().hex}"


def test_first_copy_holds_the_lock_and_second_sees_it() -> None:
    name = unique_name()
    with SingleInstance(name) as first:
        assert not first.already_running
        second = SingleInstance(name)
        assert not second.acquire()
        assert second.already_running
    # Released: a new copy can start.
    with SingleInstance(name) as third:
        assert not third.already_running


def test_different_names_are_independent() -> None:
    with SingleInstance(unique_name()) as a, SingleInstance(unique_name()) as b:
        assert not a.already_running
        assert not b.already_running


def test_release_is_idempotent() -> None:
    lock = SingleInstance(unique_name())
    lock.acquire()
    lock.release()
    lock.release()


def test_second_launch_focuses_the_first_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = AppPaths.resolve()
    focused: list[str] = []

    def focus(title: str) -> bool:
        focused.append(title)
        return True

    monkeypatch.setattr(main, "bring_existing_window_to_front", focus)
    monkeypatch.setattr(main, "run_window", lambda *_a, **_k: pytest.fail("must not open a window"))
    with SingleInstance(paths.instance_lock_name):
        assert main.main([]) == 0
    assert focused == ["Habit Tracker"]


def test_second_launch_explains_when_the_window_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AppPaths.resolve()
    shown: list[str] = []
    monkeypatch.setattr(main, "bring_existing_window_to_front", lambda _title: False)
    monkeypatch.setattr(main, "show_fatal_message", shown.append)
    with SingleInstance(paths.instance_lock_name):
        assert main.main([]) == 0
    assert shown == ["Habit Tracker is already running."]
