"""Drive the real window and record what the UI shows, for tests/e2e/test_window.py.

Run as a separate process, because pywebview's GUI loop can start only once per process and
must own the main thread::

    python tests/e2e/window_check.py <results.json> <scenario> [--dev]

It opens the app exactly as ``habit-tracker --diagnostics`` does (in the data folder named by
``HABIT_TRACKER_HOME``), then inspects it with ``evaluate_js``. Scenarios:

* ``ui``: click through the bridge check and every diagnostics error button;
* ``startup-error``: start with a damaged database file and read the error page.

Results are written as JSON; the process exits 0 even when a check fails, so the test can
report every finding.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from app.main import parse_args, run_window
from app.paths import AppPaths

TIMEOUT_S = 30.0


def wait_for(window: Any, script: str, timeout: float = TIMEOUT_S) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = window.evaluate_js(script)
        if last:
            return last
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for: {script} (last value {last!r})")


def click_button(window: Any, label: str) -> None:
    found = window.evaluate_js(
        "(() => { const b = [...document.querySelectorAll('button')]"
        f".find((el) => el.textContent.trim() === {json.dumps(label)});"
        " if (!b) return false; b.click(); return true; })()"
    )
    if not found:
        raise LookupError(f"No button labelled {label!r}")


def drive(window: Any, results: dict[str, Any]) -> None:
    try:
        wait_for(window, "document.querySelector('.status.ok') !== null")
        results["facts"] = window.evaluate_js("document.querySelector('.facts').innerText")
        results["badge"] = window.evaluate_js("document.querySelector('.badge').textContent")
        results["csp"] = window.evaluate_js(
            "document.querySelector('meta[http-equiv=\"Content-Security-Policy\"]')"
            "?.content ?? null"
        )

        click_button(window, "Run bridge check")
        wait_for(
            window, "document.querySelector('.event-log code')?.textContent === 'bridge-check:done'"
        )
        results["events"] = window.evaluate_js(
            "[...document.querySelectorAll('.event-log li')].map((li) => li.innerText)"
        )

        click_button(window, "Error in a Python call")
        wait_for(window, "document.querySelectorAll('.banner').length >= 1")
        click_button(window, "Error in a Python thread")
        wait_for(window, "document.querySelectorAll('.banner').length >= 2")
        click_button(window, "Rejected promise")
        wait_for(window, "document.querySelectorAll('.banner').length >= 3")
        click_button(window, "Error in UI code")
        wait_for(window, "document.querySelectorAll('.banner').length >= 4")
        results["banners"] = window.evaluate_js(
            "[...document.querySelectorAll('.banner')].map((el) => el.innerText)"
        )

        click_button(window, "Error while rendering")
        wait_for(window, "/Error ID/.test(document.querySelector('.fatal')?.innerText ?? '')")
        results["fatal"] = window.evaluate_js("document.querySelector('.fatal').innerText")
    except Exception:
        results["failure"] = traceback.format_exc()
    finally:
        results["finished"] = True
        window.destroy()


def read_error_page(window: Any, results: dict[str, Any]) -> None:
    try:
        wait_for(window, "document.querySelector('main[role=alert] h1') !== null")
        results["title"] = window.evaluate_js("document.querySelector('h1').textContent")
        results["text"] = window.evaluate_js("document.querySelector('main').innerText")
        results["detail"] = window.evaluate_js("document.querySelector('#detail')?.value ?? null")
    except Exception:
        results["failure"] = traceback.format_exc()
    finally:
        results["finished"] = True
        window.destroy()


SCENARIOS = {"ui": drive, "startup-error": read_error_page}


def main() -> int:
    out = Path(sys.argv[1])
    scenario = SCENARIOS[sys.argv[2]]
    dev = "--dev" in sys.argv[3:]
    args = parse_args(["--diagnostics", *(["--dev"] if dev else [])])
    paths = AppPaths.resolve()
    paths.ensure()
    if scenario is read_error_page:
        paths.database.write_bytes(b"this is not a SQLite database" * 100)

    from app.log import configure_logging

    configure_logging(paths.logs_dir, debug=dev)
    results: dict[str, Any] = {}
    exit_code = run_window(args, paths, automation=lambda window: scenario(window, results))
    results["exit_code"] = exit_code
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
