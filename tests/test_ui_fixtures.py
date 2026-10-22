"""The UI's mapping fixtures must match what the Python service produces today."""

from __future__ import annotations

from tests.support.ui_fixtures import FIXTURE_PATH, render


def test_ui_mapping_fixtures_are_up_to_date() -> None:
    expected = render()
    actual = FIXTURE_PATH.read_text(encoding="utf-8") if FIXTURE_PATH.is_file() else ""
    assert actual == expected, (
        "ui/src/test/mappingFixtures.json is out of date. "
        "Run: uv run python -m tests.support.ui_fixtures"
    )
