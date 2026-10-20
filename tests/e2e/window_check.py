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
* ``connect-oauth-deny``: the same, declining access in "Notion".

Results are written as JSON; the process exits 0 even when a check fails, so the test can
report every finding.
"""

from __future__ import annotations

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
from pathlib import Path
from typing import Any

import httpx
import keyring

from app.main import parse_args, run_window
from app.notion.client import NOTION_URL_ENV_VAR
from app.notion.service_client import SERVICE_URL_ENV_VAR
from app.paths import AppPaths
from tests.support.fake_notion_server import FakeNotionServer
from tests.support.memory_keyring import MemoryKeyring

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
    results["dev_flag"] = text(window, ".dev-flag")
    click(window, "Settings")
    wait_for(window, "document.querySelector('.card .status.ok') !== null")
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
    fake.notion.add_database("Work Log (test)")
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
