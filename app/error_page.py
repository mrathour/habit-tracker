"""A self-contained page shown in the window when the app can't show its normal UI.

It is used when startup fails (for example the database can't be opened or the UI isn't built)
and when the UI doesn't finish loading. Everything in it is escaped and inline, so it works
even when the UI bundle is missing or broken.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from app import APP_NAME
from app.errors import ErrorReport

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{app_name}: {title}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f6f6f4; --surface: #ffffff; --text: #1d1d1f; --muted: #5c5c63;
    --border: #dcdcd8; --accent: #b3261e; --button: #ececea;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #161618; --surface: #202023; --text: #ececee; --muted: #a2a2aa;
      --border: #34343a; --accent: #f2b8b5; --button: #2c2c31;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px;
    background: var(--bg); color: var(--text);
    font: 15px/1.5 "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
  }}
  main {{
    width: min(640px, 100%); background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 28px 32px;
  }}
  h1 {{ margin: 0 0 8px; font-size: 20px; font-weight: 600; color: var(--accent); }}
  p {{ margin: 0 0 12px; }}
  .muted {{ color: var(--muted); font-size: 13px; }}
  code {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 13px; }}
  textarea {{
    width: 100%; min-height: 72px; margin: 4px 0 16px; padding: 8px 10px; resize: vertical;
    border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--text);
    font: 13px/1.45 "Cascadia Mono", Consolas, monospace; user-select: text;
  }}
  .actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  button {{
    font: inherit; padding: 7px 14px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--button); color: var(--text); cursor: pointer;
  }}
  button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
</style>
</head>
<body>
<main role="alert">
  <h1>{title}</h1>
  <p>{message}</p>
  {detail_block}
  <p class="muted">Error ID <code>{error_id}</code>. The full details are in the log file in
  <code>{log_dir}</code>.</p>
  <div class="actions">
    <button type="button" data-action="open_log_folder">Open log folder</button>
    <button type="button" data-action="quit">Close Habit Tracker</button>
  </div>
</main>
<script>
  document.querySelectorAll("button[data-action]").forEach(function (button) {{
    button.addEventListener("click", function () {{
      var api = window.pywebview && window.pywebview.api;
      var action = button.getAttribute("data-action");
      if (api && typeof api[action] === "function") {{ api[action](); }}
    }});
  }});
</script>
</body>
</html>
"""


def render_error_page(report: ErrorReport, *, title: str, log_dir: Path) -> str:
    detail_block = ""
    if report.detail:
        detail_block = (
            '<label class="muted" for="detail">Details</label>'
            f'<textarea id="detail" readonly>{escape(report.detail)}</textarea>'
        )
    return _TEMPLATE.format(
        app_name=escape(APP_NAME),
        title=escape(title),
        message=escape(report.message),
        detail_block=detail_block,
        error_id=escape(report.id),
        log_dir=escape(str(log_dir)),
    )
