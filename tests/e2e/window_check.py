"""Drive the real window and record what the UI shows, for tests/e2e/test_window.py.

Run as a separate process, because pywebview's GUI loop can start only once per process and
must own the main thread::

    python tests/e2e/window_check.py <results.json> <scenario> [--dev]

It opens the app as ``habit-tracker --diagnostics`` does, in the data folder named by
``HABIT_TRACKER_HOME``, with an in-memory keyring so the real Credential Manager is never
touched, and inspects it with ``evaluate_js``. Scenarios:

* ``ui``: the diagnostics under Settings: bridge check and every error button;
* ``startup-error``: start with a damaged database file and read the error page;
* ``blank-ui``: load a page that never reports ready and read the error page that replaces it;
* ``connect-token``: paste a personal access token (fake Notion), choose the work log,
  disconnect, and reconnect;
* ``connect-oauth``: "Connect to Notion" through a local token service (``wrangler dev``) and
  a fake Notion, with a scripted browser following the real redirects; then disconnect;
* ``connect-oauth-deny``: the same, declining access in "Notion";
* ``mapping``: the column mapping screen: a database with no end-time column, then the Work
  Log's automatic mapping, saving, reopening and changing it (full sync required);
* ``sync-first``: connect, map and let the first sync copy every entry (good and broken), then
  save the fake Notion and keyring to the data folder;
* ``rawlog``: sync the broken entries, open the raw log from the dashboard's flagged count, and
  read every red cell and its explanation, selecting and opening a row, and a CSV export;
* ``parent-task``: the real Work Log with its Task Tracker unshared: the mapping explains how to
  share it; once shared, Check again maps Parent Task, and the raw log and the day detail open
  the linked tasks (issue #12);
* ``sync-relaunch``: a second launch on that folder: Notion edits and a deletion are made first;
  the launch's quick sync picks up the edits, and a full sync from Settings removes the deleted
  entry.
* ``policy-notice``: a copy connected through Notion sign-in that acknowledged policy version 1
  opens a build bundling version 2 (``packaging/test-policy.json``): the notice comes first,
  nothing reaches Notion until Continue, and the token service is never contacted;
* ``policy-relaunch``: the next launch of that build on the same folder shows no notice.
* ``policy-unrecorded``: as ``policy-notice``, but the copy connected before Phase 8, so it has
  no acknowledged version at all: it counts as version 1 and gets the notice (issue #13).
* ``policy-fresh``: that build on an empty data folder shows Connect and no notice.

Results are written as JSON; the process exits 0 even when a check fails, so the test can
report every finding.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from datetime import time as clock
from pathlib import Path
from typing import Any

import httpx
import keyring

from app.main import parse_args, run_window
from app.notion.client import NOTION_URL_ENV_VAR
from app.notion.service_client import SERVICE_URL_ENV_VAR
from app.paths import AppPaths
from tests.support.fake_notion import FakeDatabase, FakeDataSource
from tests.support.fake_notion_server import FakeNotionServer
from tests.support.memory_keyring import MemoryKeyring
from tests.support.notion_schemas import (
    SECOND_TASK,
    TASK_PAGE,
    add_source,
    add_task_tracker,
    broken_rows,
    page,
    real_work_log_schema,
    rich,
    when,
    without,
    work_log_rows,
    work_log_schema,
)

TIMEOUT_S = 30.0
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = REPO_ROOT / "service"
# Development-only values for the local Worker; never real secrets.
E2E_SIGNING_KEY = "A" * 43

Scenario = Callable[[Any, dict[str, Any]], None]

#: Set by --screenshots DIR: where to save PNGs of key screens for review.
SCREENSHOT_DIR: Path | None = None


def snap(name: str) -> None:
    if SCREENSHOT_DIR is None:
        return
    from tests.support.screenshot import capture_window

    time.sleep(0.6)  # let the last render and any transition settle
    capture_window("Habit Tracker", SCREENSHOT_DIR / f"{name}.png")


# --- helpers ----------------------------------------------------------------------------------


def wait_for(window: Any, script: str, timeout: float = TIMEOUT_S) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = window.evaluate_js(script)
        if last:
            return last
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for: {script} (last value {last!r})")


def click(window: Any, label: str, within: str = "document") -> None:
    found = window.evaluate_js(
        f"(() => {{ const b = [...{within}.querySelectorAll('button')]"
        f".find((el) => el.textContent.trim() === {json.dumps(label)});"
        " if (!b) return false; b.click(); return true; })()"
    )
    if not found:
        raise LookupError(f"No button labelled {label!r}")


def click_label(window: Any, text: str) -> None:
    found = window.evaluate_js(
        "(() => { const l = [...document.querySelectorAll('label')]"
        f".find((el) => el.textContent.includes({json.dumps(text)}));"
        " if (!l) return false; l.click(); return true; })()"
    )
    if not found:
        raise LookupError(f"No label containing {text!r}")


def type_into(window: Any, selector: str, value: str) -> None:
    """Set a React-controlled input's value the way typing does."""
    window.evaluate_js(
        f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
        " const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
        f" set.call(el, {json.dumps(value)});"
        " el.dispatchEvent(new Event('input', { bubbles: true })); })()"
    )


def text(window: Any, selector: str) -> str | None:
    result = window.evaluate_js(
        f"document.querySelector({json.dumps(selector)})?.innerText ?? null"
    )
    return str(result) if result is not None else None


def select_option(window: Any, selector: str, label: str) -> None:
    """Choose an option of a React-controlled <select> by its text, the way a user does."""
    found = window.evaluate_js(
        f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
        " if (!el) return false;"
        f" const option = [...el.options].find((o) => o.textContent === {json.dumps(label)});"
        " if (!option) return false;"
        " const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;"
        " set.call(el, option.value);"
        " el.dispatchEvent(new Event('change', { bubbles: true })); return true; })()"
    )
    if not found:
        raise LookupError(f"No option {label!r} in {selector}")


def selected(window: Any, selector: str) -> str | None:
    result = window.evaluate_js(
        f"document.querySelector({json.dumps(selector)})?.selectedOptions[0]?.textContent ?? null"
    )
    return str(result) if result is not None else None


MAPPING_LOADED = "document.querySelector('#field-start') !== null"
DATABASES_LOADED = "document.querySelector('[aria-label=\"Databases\"]') !== null"


def heading_is(title: str) -> str:
    return (
        "[...document.querySelectorAll('h1')]"
        f".some((h) => h.textContent.trim() === {json.dumps(title)})"
    )


def run_scenario(scenario: Scenario) -> Callable[[Any, dict[str, Any]], None]:
    def wrapped(window: Any, results: dict[str, Any]) -> None:
        try:
            scenario(window, results)
        except Exception:
            results["failure"] = traceback.format_exc()
        finally:
            results["finished"] = True
            window.destroy()

    return wrapped


# --- scenarios ---------------------------------------------------------------------------------


def diagnostics(window: Any, results: dict[str, Any]) -> None:
    wait_for(window, heading_is("See where your working hours go"))
    click(window, "Settings")
    wait_for(window, "document.querySelector('.card .status.ok') !== null")
    # Read only once the app's details have arrived: the flag depends on them.
    results["dev_flag"] = text(window, ".dev-flag")
    results["facts"] = text(window, ".card .facts")
    results["csp"] = window.evaluate_js(
        "document.querySelector('meta[http-equiv=\"Content-Security-Policy\"]')?.content ?? null"
    )

    click(window, "Run bridge check")
    wait_for(
        window, "document.querySelector('.event-log code')?.textContent === 'bridge-check:done'"
    )
    results["events"] = window.evaluate_js(
        "[...document.querySelectorAll('.event-log li')].map((li) => li.innerText)"
    )

    click(window, "Error in a Python call")
    wait_for(window, "document.querySelectorAll('.banner').length >= 1")
    click(window, "Error in a Python thread")
    wait_for(window, "document.querySelectorAll('.banner').length >= 2")
    click(window, "Rejected promise")
    wait_for(window, "document.querySelectorAll('.banner').length >= 3")
    click(window, "Error in UI code")
    wait_for(window, "document.querySelectorAll('.banner').length >= 4")
    results["banners"] = window.evaluate_js(
        "[...document.querySelectorAll('.banner')].map((el) => el.innerText)"
    )

    click(window, "Error while rendering")
    wait_for(window, "/Error ID/.test(document.querySelector('.fatal')?.innerText ?? '')")
    results["fatal"] = text(window, ".fatal")


def read_error_page(window: Any, results: dict[str, Any]) -> None:
    wait_for(window, "document.querySelector('main[role=alert] h1') !== null")
    results["title"] = window.evaluate_js("document.querySelector('h1').textContent")
    results["text"] = text(window, "main")
    results["detail"] = window.evaluate_js("document.querySelector('#detail')?.value ?? null")


def choose_work_log(window: Any, results: dict[str, Any], prefix: str) -> None:
    wait_for(window, heading_is("Choose your work log"))
    wait_for(window, "document.querySelector('[aria-label=\"Databases\"]') !== null")
    results[f"{prefix}_picker"] = text(window, "[aria-label='Databases']")
    results[f"{prefix}_topbar"] = text(window, ".topbar")
    click_label(window, "Reading")
    snap(f"{prefix}-picker")
    click_label(window, "Work Log (test)")
    click(window, "Use this database")
    # First time: the columns are mapped automatically and reviewed before the home screen.
    wait_for(window, heading_is("Map your columns"))
    wait_for(window, MAPPING_LOADED)
    results[f"{prefix}_mapping_end"] = selected(window, "#field-end")
    snap(f"{prefix}-mapping")
    click(window, "Save mapping")
    wait_for(window, heading_is("Work Log (test)"))
    results[f"{prefix}_home"] = text(window, "main")
    snap(f"{prefix}-home")


def disconnect(window: Any, results: dict[str, Any], prefix: str, *, clear: bool = False) -> None:
    click(window, "Settings")
    wait_for(window, heading_is("Settings"))
    results[f"{prefix}_settings"] = text(window, "[aria-labelledby='settings-connection']")
    click(window, "Disconnect")
    wait_for(window, "document.querySelector('[role=dialog]') !== null")
    snap(f"{prefix}-disconnect-dialog")
    if clear:
        click_label(window, "Delete them")
    click(window, "Disconnect", within="document.querySelector('[role=dialog]')")
    wait_for(window, "document.querySelector('.notice[role=status]') !== null")
    results[f"{prefix}_summary"] = text(window, ".notice[role=status]")
    snap(f"{prefix}-settings-after")
    results[f"{prefix}_keyring_after_logout"] = len(MemoryKeyring.store)


def paste_token(window: Any, token: str) -> None:
    click(window, "Home")
    wait_for(window, heading_is("See where your working hours go"))
    click(window, "Use a token instead")
    click_label(window, "Personal access token")
    type_into(window, "input[type=password]", token)
    snap("02-token-form")
    click(window, "Check and connect")


def connect_token(fake: FakeNotionServer) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        # Connect, choose the work log, disconnect keeping local data.
        wait_for(window, heading_is("See where your working hours go"))
        snap("01-connect")
        paste_token(window, fake.notion.issue_token())
        choose_work_log(window, results, "first")
        results["first_keyring"] = len(MemoryKeyring.store)
        disconnect(window, results, "first")

        # Reconnect: the kept database choice means straight to the home screen.
        paste_token(window, fake.notion.issue_token())
        wait_for(window, heading_is("Work Log (test)"))
        results["again_home"] = text(window, "main")
        results["again_keyring"] = len(MemoryKeyring.store)

        # Disconnect clearing local data: next time, the work log is chosen afresh.
        disconnect(window, results, "cleared", clear=True)
        paste_token(window, fake.notion.issue_token())
        wait_for(window, heading_is("Choose your work log"))
        results["after_clear"] = "picker"

    return scenario


def mapping(fake: FakeNotionServer) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is("See where your working hours go"))
        paste_token(window, fake.notion.issue_token())

        # A database with no end-time column: the exact explanation, and no way to save.
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        click_label(window, "Work Log (no end)")
        click(window, "Use this database")
        wait_for(window, MAPPING_LOADED)
        results["no_end_row"] = window.evaluate_js(
            "document.querySelector('#field-end').closest('li').innerText"
        )
        results["no_end_blockers"] = text(window, "[aria-label='Before you can save']")
        results["no_end_save_disabled"] = window.evaluate_js(
            "[...document.querySelectorAll('button')]"
            ".find((b) => b.textContent.trim() === 'Save mapping').disabled"
        )
        snap("mapping-no-end")

        # The Work Log copy: every field matched, with its real sample values.
        click(window, "Choose a different database")
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        click_label(window, "Work Log (test)")
        click(window, "Use this database")
        wait_for(window, heading_is("Map your columns"))
        wait_for(window, MAPPING_LOADED)
        keys = ("start", "end", "task_name", "parent_task", "display_id", "logged_minutes")
        results["fields"] = {key: selected(window, f"#field-{key}") for key in keys}
        results["samples"] = {key: text(window, f"#field-{key}-samples") for key in keys}
        snap("mapping-work-log")
        click(window, "Save mapping")
        wait_for(window, heading_is("Work Log (test)"))
        results["saved_home"] = text(window, "main")

        # Reopen, change a field, save: a full sync is now required.
        click(window, "Review column mapping")
        wait_for(window, heading_is("Column mapping"))
        wait_for(window, MAPPING_LOADED)
        select_option(window, "#field-display_id", "Not used")
        click(window, "Save mapping")
        # Saving the change starts the full sync it needs; the flag clears when it finishes.
        wait_for(
            window,
            "(() => { const el = document.querySelector('.sync-done');"
            " return el !== null && el.innerText.includes('The column mapping changed.'); })()",
            timeout=60,
        )
        results["changed_home"] = text(window, "[aria-labelledby='sync-title']")
        snap("mapping-full-sync")
        click(window, "Settings")
        wait_for(window, heading_is("Settings"))
        results["settings"] = text(window, "[aria-labelledby='settings-connection']")

    return scenario


SYNC_DONE = "document.querySelector('.sync-done') !== null"
STATE_FILE = "e2e-state.json"


def wait_for_sync(window: Any, kind: str) -> None:
    wait_for(
        window,
        "(() => { const el = document.querySelector('.sync-done');"
        f" return el !== null && el.innerText.startsWith({json.dumps(kind)}); }})()",
        timeout=60,
    )


def panel_text(window: Any) -> dict[str, Any]:
    return {
        "panel": text(window, "[aria-labelledby='sync-title']"),
        "flagged": window.evaluate_js(
            "[...document.querySelectorAll('.flagged-entry')].map((li) => li.innerText)"
        ),
        "indicator": text(window, ".sync-indicator"),
    }


def save_state(fake: FakeNotionServer, home: Path) -> None:
    """Keep the fake Notion and the in-memory keyring for the next launch (a new process)."""
    notion = fake.notion
    state = {
        "databases": [vars(db) for db in notion.databases.values()],
        "data_sources": [vars(ds) for ds in notion.data_sources.values()],
        "valid_tokens": sorted(notion.valid_tokens),
        "keyring": [[svc, user, value] for (svc, user), value in MemoryKeyring.store.items()],
    }
    (home / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")


def load_state(fake: FakeNotionServer, home: Path) -> None:
    state = json.loads((home / STATE_FILE).read_text(encoding="utf-8"))
    notion = fake.notion
    notion.workspace_name = "E2E Workspace"
    for db in state["databases"]:
        notion.databases[db["id"]] = FakeDatabase(**db)
    for ds in state["data_sources"]:
        notion.data_sources[ds["id"]] = FakeDataSource(**ds)
    notion.valid_tokens = set(state["valid_tokens"])
    for svc, user, value in state["keyring"]:
        MemoryKeyring.store[(svc, user)] = value


def sync_first(fake: FakeNotionServer, home: Path) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is("See where your working hours go"))
        paste_token(window, fake.notion.issue_token())
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        click_label(window, "Work Log (test)")
        click(window, "Use this database")
        wait_for(window, MAPPING_LOADED)
        click(window, "Save mapping")
        wait_for(window, heading_is("Work Log (test)"))
        wait_for_sync(window, "Full sync")
        wait_for(window, "document.querySelectorAll('.flagged-entry').length > 0")
        results["first"] = panel_text(window)
        snap("sync-first")
        save_state(fake, home)

    return scenario


def sync_relaunch(fake: FakeNotionServer, home: Path) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        # The launch's own sync: a quick sync (the full one ran minutes ago).
        wait_for(window, heading_is("Work Log (test)"))
        wait_for_sync(window, "Quick sync")
        wait_for(window, "document.querySelectorAll('.flagged-entry').length > 0")
        results["relaunch"] = panel_text(window)
        snap("sync-relaunch")
        # A full sync from Settings removes the entry deleted in Notion.
        click(window, "Settings")
        wait_for(window, heading_is("Settings"))
        click(window, "Run full sync")
        click(window, "Home")
        wait_for_sync(window, "Full sync")
        results["full"] = panel_text(window)
        snap("sync-full")

    return scenario


POLICY_TITLE = "The privacy policy has changed"
TEST_POLICY = REPO_ROOT / "packaging" / "test-policy.json"


class RecordingService:
    """Stands in for the token service: records every request, so a test can prove none came."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        recorder = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _record(self) -> None:
                recorder.requests.append(f"{self.command} {self.path}")
                self.send_response(503)
                self.end_headers()

            do_GET = do_POST = _record  # noqa: N815 - http.server method names

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._httpd.shutdown()


def seed_policy_copy(fake: FakeNotionServer, paths: AppPaths, acknowledged: int | None = 1) -> None:
    """A copy that connected with Notion sign-in and acknowledged policy version 1, or, with
    ``acknowledged=None``, connected before the app recorded a version."""
    from app.db import open_database
    from app.db.settings import Settings
    from app.notion.credentials import CredentialStore, StoredCredential, utc_now
    from app.redaction import Secret

    seed_fake_notion(fake)
    CredentialStore.for_paths(paths).save(
        StoredCredential(
            kind="oauth",
            access_token=Secret(fake.notion.issue_token()),
            refresh_token=Secret("nrt_e2e_policy_refresh"),
            obtained_at=utc_now(),
        )
    )
    database = open_database(paths.database)
    Settings(database.connection).set_many(
        {
            "auth_kind": "oauth",
            "workspace_name": "E2E Workspace",
        }
        | ({"acknowledged_policy_version": acknowledged} if acknowledged is not None else {})
    )
    database.close()


def policy_notice(fake: FakeNotionServer, service: RecordingService) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is(POLICY_TITLE))
        results["notice_text"] = text(window, ".policy-notice")
        results["nav_shown"] = window.evaluate_js("document.querySelector('nav') !== null")
        snap("policy-notice")
        # Give anything that wrongly starts behind the notice time to reach Notion.
        time.sleep(3)
        results["notion_requests_before_continue"] = len(fake.notion.requests)
        click(window, "Continue")
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        results["after_continue"] = "picker"
        results["notion_requests_after_continue"] = len(fake.notion.requests)
        results["service_requests"] = list(service.requests)
        save_state(fake, paths_root(window))

    return scenario


def policy_relaunch(fake: FakeNotionServer, service: RecordingService) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        results["notice_shown"] = window.evaluate_js(heading_is(POLICY_TITLE))
        results["service_requests"] = list(service.requests)

    return scenario


def policy_fresh(fake: FakeNotionServer, service: RecordingService) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is("See where your working hours go"))
        time.sleep(2)  # time for a wrongly shown notice to appear
        results["notice_shown"] = window.evaluate_js(heading_is(POLICY_TITLE))
        results["connect_shown"] = window.evaluate_js(heading_is("See where your working hours go"))
        results["notion_requests"] = len(fake.notion.requests)
        results["service_requests"] = list(service.requests)

    return scenario


def paths_root(_window: Any) -> Path:
    return AppPaths.resolve().root


def local_iso(day: date, hour: int, minute: int = 0) -> str:
    """A wall-clock time on this computer, as Notion writes it (with the local offset)."""
    moment = datetime.combine(day, clock(hour, minute)).astimezone()
    return moment.isoformat(timespec="milliseconds")


def dashboard_rows() -> list[dict[str, Any]]:
    """Sessions in the last three days, in this computer's time zone. Worked out by hand:

    * 3 days ago: C 23:00 to 00:30 crosses midnight: 60 min here, 30 min the next day.
    * 2 days ago: A 09:00-10:30 (90) and B 10:00-11:00 (60) overlap by 30 min, counted
      once: 120; plus C's 30: 150 min (2 h 30 min) from 3 sessions.
    * Yesterday: D 14:00-14:45: 45 min.
    * Total 255 min (4 h 15 min); current streak 3 days, through yesterday.
    """
    today = datetime.now().astimezone().date()  # this computer's local date
    d1, d2, d3 = (today - timedelta(days=n) for n in (1, 2, 3))
    source = work_log_schema()

    def row(page_id: str, name: str, start: str, end: str) -> dict[str, Any]:
        return page(
            source,
            {"Name": rich(name), "Start Time": when(start), "End Time": when(end)},
            created="2026-01-01T00:00:00.000Z",
            page_id=page_id,
        )

    return [
        row("dash-a", "Write", local_iso(d2, 9), local_iso(d2, 10, 30)),
        row("dash-b", "Review", local_iso(d2, 10), local_iso(d2, 11)),
        row("dash-c", "Late night", local_iso(d3, 23), local_iso(d2, 0, 30)),
        row("dash-d", "Plan", local_iso(d1, 14), local_iso(d1, 14, 45)),
    ]


def click_in(window: Any, container: str, label: str) -> None:
    click(window, label, within=f"document.querySelector({json.dumps(container)})")


def dashboard(fake: FakeNotionServer) -> Scenario:
    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is("See where your working hours go"))
        paste_token(window, fake.notion.issue_token())
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        click_label(window, "Work Log (test)")
        click(window, "Use this database")
        wait_for(window, MAPPING_LOADED)
        click(window, "Save mapping")
        wait_for(window, heading_is("Work Log (test)"))
        wait_for_sync(window, "Full sync")
        wait_for(window, "document.querySelector('.stat-row .stat:not(.skeleton)') !== null")
        wait_for(window, "document.querySelectorAll('.echart canvas').length >= 3")
        results["canvases"] = window.evaluate_js(
            "document.querySelectorAll('.echart canvas').length"
        )
        results["banners"] = window.evaluate_js("document.querySelectorAll('.banner').length")
        results["stats"] = window.evaluate_js(
            "[...document.querySelectorAll('.stat')].map((el) => el.innerText)"
        )
        snap("dashboard")
        daily = "[aria-labelledby='daily-title']"
        click_in(window, daily, "Show as table")
        wait_for(window, f'document.querySelector("{daily} table") !== null')
        results["daily_rows"] = window.evaluate_js(
            f'[...document.querySelectorAll("{daily} tbody tr")]'
            ".map((tr) => tr.innerText).filter((t) => !t.includes('\\t0 min\\t'))"
        )
        # The day with the overlap and the midnight split.
        two_days_ago = datetime.now().astimezone().date() - timedelta(days=2)
        label = window.evaluate_js(
            f'[...document.querySelectorAll("{daily} tbody th button")]'
            f".map((b) => b.textContent)[2]"
        )
        results["detail_label"] = label
        window.evaluate_js(f'document.querySelectorAll("{daily} tbody th button")[2].click()')
        wait_for(window, "document.querySelector('.day-detail') !== null")
        results["detail"] = text(window, "[role=dialog]")
        results["detail_day"] = two_days_ago.isoformat()
        snap("dashboard-day")

    return scenario


def rawlog(fake: FakeNotionServer, home: Path, opened: list[str]) -> Scenario:
    """Connect, sync the broken entries, open the raw log from the dashboard's flagged count,
    and read every red cell, a hover explanation, selection, opening, and a CSV export."""

    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is("See where your working hours go"))
        paste_token(window, fake.notion.issue_token())
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        click_label(window, "Work Log (test)")
        click(window, "Use this database")
        wait_for(window, MAPPING_LOADED)
        click(window, "Save mapping")
        wait_for(window, heading_is("Work Log (test)"))
        wait_for_sync(window, "Full sync")
        wait_for(window, "document.querySelector('.stat-row .stat:not(.skeleton)') !== null")
        click(window, "See them in the raw log")
        wait_for(window, heading_is("Raw log"))
        wait_for(window, "document.querySelectorAll('tr[data-page-id]').length > 0")
        results["status"] = text(window, ".rawlog-head [role=status]")
        results["chips"] = text(window, "[aria-label='Active filters']")
        results["rows"] = window.evaluate_js(
            "[...document.querySelectorAll('tr[data-page-id]')].map((tr) => ({"
            " page_id: tr.dataset.pageId,"
            " red: [...tr.querySelectorAll('td.cell-issue')]"
            ".map((td) => [td.dataset.kind, td.dataset.tip]) }))"
        )

        # Hovering over a red cell explains it.
        mismatch = "tr[data-page-id='p-mismatch']"
        window.evaluate_js(
            f'document.querySelector("{mismatch} td.cell-issue")'
            ".dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))"
        )
        wait_for(window, "document.querySelector('.cell-tooltip') !== null")
        results["tooltip"] = text(window, ".cell-tooltip")
        snap("rawlog-issues")

        # A click only selects; a double-click opens the entry in Notion.
        window.evaluate_js(f'document.querySelector("{mismatch} td[data-kind=task_name]").click()')
        wait_for(window, f'document.querySelector("{mismatch}").ariaSelected === "true"')
        time.sleep(0.5)
        results["opened_after_click"] = list(opened)
        window.evaluate_js(
            f'document.querySelector("{mismatch} td[data-kind=task_name]")'
            ".dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))"
        )
        deadline = time.monotonic() + TIMEOUT_S
        while not opened and time.monotonic() < deadline:
            time.sleep(0.2)
        results["opened_after_double_click"] = list(opened)

        # Export what's on screen through the (stubbed) native Save dialog.
        target = home / "exports" / "raw log.csv"
        target.parent.mkdir(exist_ok=True)
        window.create_file_dialog = lambda *_args, **_kwargs: str(target)
        click(window, "Export CSV")
        wait_for(
            window,
            "document.querySelector('.export-notice') !== null",
        )
        results["export_notice"] = text(window, ".export-notice")
        raw = target.read_bytes() if target.exists() else b""
        results["csv_bom"] = raw.startswith(b"\xef\xbb\xbf")
        results["csv"] = raw[3:].decode("utf-8") if raw else ""
        snap("rawlog-export")

        # Clearing the filters shows every entry.
        click(window, "Clear all")
        wait_for(
            window,
            "(() => { const s = document.querySelector('.rawlog-head [role=status]');"
            " return s !== null && !s.innerText.startsWith('Showing'); })()",
        )
        results["all_status"] = text(window, ".rawlog-head [role=status]")

    return scenario


def parent_task_rows() -> list[dict[str, Any]]:
    """Yesterday, in this computer's time zone: one session linked to a task, one to two."""
    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    source = real_work_log_schema()

    def row(page_id: str, name: str, start: int, end: int, links: list[str]) -> dict[str, Any]:
        return page(
            source,
            {
                "Name": rich(name),
                "Start Time": when(local_iso(yesterday, start)),
                "End Time": when(local_iso(yesterday, end)),
                "Parent Task": [{"id": link} for link in links],
            },
            created="2026-01-01T00:00:00.000Z",
            page_id=page_id,
        )

    return [
        row("parent-a", "Map the columns", 9, 10, [TASK_PAGE]),
        row("parent-b", "Review", 11, 12, [TASK_PAGE, SECOND_TASK]),
    ]


def parent_task(fake: FakeNotionServer, tracker: FakeDatabase, opened: list[str]) -> Scenario:
    """Issue #12: the Task Tracker starts unshared, so the mapping explains how to share it.
    Sharing it and clicking Check again maps Parent Task; the sync keeps its links, and the raw
    log and the day detail open the task in Notion."""

    def wait_opened(count: int) -> None:
        deadline = time.monotonic() + TIMEOUT_S
        while len(opened) < count and time.monotonic() < deadline:
            time.sleep(0.2)

    def scenario(window: Any, results: dict[str, Any]) -> None:
        wait_for(window, heading_is("See where your working hours go"))
        paste_token(window, fake.notion.issue_token())
        wait_for(window, heading_is("Choose your work log"))
        wait_for(window, DATABASES_LOADED)
        click_label(window, "Work Log")
        click(window, "Use this database")
        wait_for(window, MAPPING_LOADED)
        parent_row = "document.querySelector('#field-parent_task').closest('li')"
        results["share_help"] = window.evaluate_js(f"{parent_row}.innerText")
        results["parent_before"] = selected(window, "#field-parent_task")
        window.evaluate_js(f"{parent_row}.scrollIntoView({{ block: 'center' }})")
        snap("parent-share-help")

        with fake.notion.lock:
            fake.notion.unshared.discard(tracker.id)  # the user shares it in Notion
        click(window, "Check again", within=parent_row)
        wait_for(
            window,
            "document.querySelector('#field-parent_task')?.selectedOptions[0]?.textContent"
            " === 'Parent Task · Relation'",
        )
        results["parent_after"] = selected(window, "#field-parent_task")
        results["share_help_after"] = window.evaluate_js(
            f"{parent_row}.querySelector('.notice') !== null"
        )
        click(window, "Save mapping")
        wait_for(window, heading_is("Work Log"))
        wait_for_sync(window, "Full sync")

        # The raw log's Parent task cell opens the task.
        click(window, "Raw log", within="document.querySelector('nav')")
        wait_for(window, heading_is("Raw log"))
        wait_for(window, "document.querySelectorAll('tr[data-page-id]').length === 2")
        cell = "tr[data-page-id='parent-a'] td[data-kind=parent_task]"
        results["raw_cell"] = text(window, cell)
        window.evaluate_js(f'document.querySelector("{cell} button").click()')
        wait_opened(1)
        results["opened_from_raw_log"] = list(opened)

        # The day detail lists both links of the second session.
        click(window, "Home", within="document.querySelector('nav')")
        wait_for(window, "document.querySelector('.stat-row .stat:not(.skeleton)') !== null")
        daily = "[aria-labelledby='daily-title']"
        click_in(window, daily, "Show as table")
        wait_for(window, f'document.querySelector("{daily} table") !== null')
        window.evaluate_js(
            f'[...document.querySelectorAll("{daily} tbody tr")]'
            ".find((tr) => !tr.innerText.includes('\\t0 min')).querySelector('th button').click()"
        )
        wait_for(window, "document.querySelector('.day-detail') !== null")
        results["detail"] = text(window, "[role=dialog]")
        snap("parent-day-detail")
        for label in (
            "Open the parent task of Review in Notion",
            "Open linked page 2 of Review in Notion",
        ):
            window.evaluate_js(
                f"document.querySelector('[role=dialog] button[aria-label=\"{label}\"]').click()"
            )
        wait_opened(3)
        results["opened"] = list(opened)

    return scenario


def edit_in_notion(fake: FakeNotionServer) -> None:
    """What the user does in Notion between the two launches."""
    notion = fake.notion
    notion.edit_page(
        "p-mismatch",
        Name=[
            {
                "type": "text",
                "plain_text": "Mismatch, renamed",
                "text": {"content": "Mismatch, renamed"},
            }
        ],
    )
    notion.edit_page("p-no-end", **{"End Time": when("2026-10-21T09:30:00.000+05:30")})
    notion.delete_page("p-ok")  # fmt: skip


def scripted_browser(results: dict[str, Any]) -> Callable[[str], bool]:
    """Stands in for the system browser: follows the real redirect chain."""

    def open_url(url: str) -> bool:
        def follow() -> None:
            response = httpx.get(url, follow_redirects=True, timeout=30)
            results.setdefault("browser_pages", []).append(
                {
                    "url": str(response.url).split("?")[0],
                    "status": response.status_code,
                    "text": response.text,
                }
            )

        threading.Thread(target=follow, daemon=True).start()
        return True

    return open_url


def connect_oauth(window: Any, results: dict[str, Any]) -> None:
    wait_for(window, heading_is("See where your working hours go"))
    click(window, "Connect to Notion")
    choose_work_log(window, results, "oauth")
    results["oauth_keyring"] = len(MemoryKeyring.store)
    disconnect(window, results, "oauth")


def connect_oauth_deny(window: Any, results: dict[str, Any]) -> None:
    wait_for(window, heading_is("See where your working hours go"))
    click(window, "Connect to Notion")
    wait_for(window, "document.querySelector('.notice[role=alert]') !== null")
    snap("oauth-denied")
    results["notice"] = text(window, ".notice[role=alert]")
    results["keyring"] = len(MemoryKeyring.store)


# --- local services ---------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def local_worker(notion_url: str) -> Iterator[str]:
    """Run the token service with `wrangler dev`, pointed at the fake Notion."""
    node = shutil.which("node")
    wrangler = SERVICE_DIR / "node_modules" / "wrangler" / "bin" / "wrangler.js"
    if node is None or not wrangler.is_file():
        raise RuntimeError("Node.js and service/node_modules are needed (npm --prefix service ci)")
    port = free_port()
    command = [
        node, str(wrangler), "dev", "--ip", "127.0.0.1", "--port", str(port),
        "--var", f"NOTION_API_BASE:{notion_url}",
        "--var", "NOTION_CLIENT_ID:e2e-client-id",
        "--var", "NOTION_CLIENT_SECRET:e2e-only-not-a-secret",
        "--var", f"STATE_SIGNING_KEY:{E2E_SIGNING_KEY}",
    ]  # fmt: skip
    env = {**os.environ, "WRANGLER_SEND_METRICS": "false", "CI": "1", "NO_COLOR": "1"}
    log = (Path(os.environ["HABIT_TRACKER_HOME"]) / "wrangler.log").open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603 - fixed command
        command, cwd=SERVICE_DIR, env=env, stdout=log, stderr=subprocess.STDOUT
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"wrangler dev exited with {process.returncode}")
            try:
                if httpx.get(f"{url}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise RuntimeError("wrangler dev didn't start in 90 seconds")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()


def use_blank_ui(paths: AppPaths) -> None:
    """Serve a page that loads but never starts the app, and shorten the watchdog."""
    import app.main

    dist = paths.root / "blank-dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><html><body></body></html>", encoding="utf-8")
    app.main.ui_dist_dir = lambda: dist  # type: ignore[attr-defined]
    app.main.UI_READY_TIMEOUT_S = 2.0  # type: ignore[misc]


def seed_fake_notion(fake: FakeNotionServer) -> None:
    fake.notion.workspace_name = "E2E Workspace"
    add_source(fake.notion, "Work Log (test)", work_log_schema(), work_log_rows())
    no_end = without(work_log_schema(), "End Time")
    add_source(fake.notion, "Work Log (no end)", no_end, work_log_rows(no_end))
    fake.notion.add_database("Reading", ["Books", "Articles"])


# --- main -------------------------------------------------------------------------------------


def main() -> int:
    global SCREENSHOT_DIR
    out = Path(sys.argv[1])
    name = sys.argv[2]
    flags = sys.argv[3:]
    dev = "--dev" in flags
    if "--screenshots" in flags:
        SCREENSHOT_DIR = Path(flags[flags.index("--screenshots") + 1])
    keyring.set_keyring(MemoryKeyring())  # type: ignore[no-untyped-call]
    args = parse_args(["--diagnostics", *(["--dev"] if dev else [])])
    paths = AppPaths.resolve()
    paths.ensure()

    from app.log import configure_logging

    configure_logging(paths.logs_dir, debug=dev)
    results: dict[str, Any] = {}

    def open_window(scenario: Scenario) -> int:
        return run_window(
            args, paths, automation=lambda window: run_scenario(scenario)(window, results)
        )

    if name == "ui":
        exit_code = open_window(diagnostics)
    elif name == "startup-error":
        paths.database.write_bytes(b"this is not a SQLite database" * 100)
        exit_code = open_window(read_error_page)
    elif name == "blank-ui":
        use_blank_ui(paths)
        exit_code = open_window(read_error_page)
    elif name == "connect-token":
        with FakeNotionServer() as fake:
            seed_fake_notion(fake)
            fake.notion.me_type = "person"
            os.environ[NOTION_URL_ENV_VAR] = fake.url
            exit_code = open_window(connect_token(fake))
    elif name in ("sync-first", "sync-relaunch"):
        home = paths.root
        with FakeNotionServer() as fake:
            if name == "sync-first":
                fake.notion.workspace_name = "E2E Workspace"
                add_source(
                    fake.notion,
                    "Work Log (test)",
                    work_log_schema(),
                    work_log_rows() + broken_rows(),
                )
                scenario = sync_first(fake, home)
            else:
                load_state(fake, home)
                edit_in_notion(fake)
                scenario = sync_relaunch(fake, home)
            os.environ[NOTION_URL_ENV_VAR] = fake.url
            exit_code = open_window(scenario)
    elif name == "dashboard":
        with FakeNotionServer() as fake:
            fake.notion.workspace_name = "E2E Workspace"
            add_source(fake.notion, "Work Log (test)", work_log_schema(), dashboard_rows())
            os.environ[NOTION_URL_ENV_VAR] = fake.url
            exit_code = open_window(dashboard(fake))
    elif name == "rawlog":
        with FakeNotionServer() as fake:
            fake.notion.workspace_name = "E2E Workspace"
            add_source(
                fake.notion, "Work Log (test)", work_log_schema(), work_log_rows() + broken_rows()
            )
            os.environ[NOTION_URL_ENV_VAR] = fake.url
            opened: list[str] = []

            def record(url: str, *_args: Any, **_kwargs: Any) -> bool:
                opened.append(url)
                return True

            webbrowser.open = record
            exit_code = open_window(rawlog(fake, paths.root, opened))
    elif name == "parent-task":
        with FakeNotionServer() as fake:
            fake.notion.workspace_name = "E2E Workspace"
            tracker = add_task_tracker(fake.notion, shared=False)
            add_source(fake.notion, "Work Log", real_work_log_schema(), parent_task_rows())
            os.environ[NOTION_URL_ENV_VAR] = fake.url
            opened_pages: list[str] = []

            def record_page(url: str, *_args: Any, **_kwargs: Any) -> bool:
                opened_pages.append(url)
                return True

            webbrowser.open = record_page
            exit_code = open_window(parent_task(fake, tracker, opened_pages))
    elif name == "mapping":
        with FakeNotionServer() as fake:
            seed_fake_notion(fake)
            os.environ[NOTION_URL_ENV_VAR] = fake.url
            exit_code = open_window(mapping(fake))
    elif name in ("policy-notice", "policy-relaunch", "policy-unrecorded", "policy-fresh"):
        import app.policy

        # This run is the "newer" build: it bundles policy version 2.
        app.policy.POLICY_FILE = TEST_POLICY  # type: ignore[misc]
        service = RecordingService()
        os.environ[SERVICE_URL_ENV_VAR] = service.url
        with FakeNotionServer() as fake:
            if name == "policy-notice":
                seed_policy_copy(fake, paths)
                scenario = policy_notice(fake, service)
            elif name == "policy-unrecorded":
                seed_policy_copy(fake, paths, acknowledged=None)
                scenario = policy_notice(fake, service)
            elif name == "policy-fresh":
                seed_fake_notion(fake)
                scenario = policy_fresh(fake, service)
            else:
                load_state(fake, paths.root)
                scenario = policy_relaunch(fake, service)
            os.environ[NOTION_URL_ENV_VAR] = fake.url
            exit_code = open_window(scenario)
        service.close()
        from app.db import open_database
        from app.db.settings import Settings

        database = open_database(paths.database)
        results["acknowledged"] = Settings(database.connection).get("acknowledged_policy_version")
        database.close()
    elif name in ("connect-oauth", "connect-oauth-deny"):
        with FakeNotionServer() as fake:
            seed_fake_notion(fake)
            fake.authorize = "allow" if name == "connect-oauth" else "deny"
            with local_worker(fake.url) as service_url:
                os.environ[NOTION_URL_ENV_VAR] = fake.url
                os.environ[SERVICE_URL_ENV_VAR] = service_url
                webbrowser.open = scripted_browser(results)  # type: ignore[assignment]
                scenario = connect_oauth if name == "connect-oauth" else connect_oauth_deny
                exit_code = open_window(scenario)
            results["valid_tokens_remaining"] = len(fake.notion.valid_tokens)
    else:
        raise SystemExit(f"Unknown scenario {name!r}")

    results["exit_code"] = exit_code
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
