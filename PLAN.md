# Notion Work Log Habit Tracker — Project Plan

This file is the single source of truth for the project. Any change to scope or design is recorded in the **Decisions log** at the end.

## Guiding principle

**Never consider effort or complexity** when making, changing, scaling down or phasing any part of the plan. Choose the best solution for the user and the product, never the easiest one to build. Do not rule out options, shrink features, defer work or suggest simpler alternatives because of effort, complexity or time, and do not cite them as reasons in any recommendation. Build every state: empty, loading, error and edge cases. The only exception is a cost, deadline or resource limit the user states explicitly for a specific task.

---

## 1. Overview

A Windows desktop app that tracks a work habit: time spent working. The user logs work sessions in a Notion **Work Log** database. The app reads that database, keeps a local copy, and turns it into habit-tracking charts.

- **Notion is the source of truth.** The app is strictly read-only: it never writes to Notion.
- **The app works offline.** All charts and views read from the local copy; Notion is contacted only during sync.
- **Personal first, shareable later.** It is built for the author, but designed so other people can connect their own Notion workspace and database.

## 2. Scope

**In scope (v1)**
- Notion login (OAuth through the token service, or a pasted internal integration token or PAT) and Work Log database selection
- Automatic column mapping with user review, required-field checks, and user-chosen extra fields
- Full sync and quick sync into a local SQLite database
- Non-blocking validation of entries
- Dashboard: daily totals, weekly trends, streaks, calendar heatmap
- Raw log view with filters and highlighted issues
- Windows installer

**Out of scope (possible future upgrades)**
- Reading the Task Tracker database (for example, showing parent task names or per-task breakdowns)
- Writing anything back to Notion
- macOS and Linux builds
- The extra chart and gamification ideas in section 9

## 3. Source data: the author's Work Log

| Notion column | Notion type | Example |
|---|---|---|
| ID (Notion shows it as № ID) | Unique ID | 6 |
| Name | Title | "Work Log Table Created" (may be blank) |
| Start Time | Date with time | October 17, 2026 5:41 PM |
| End Time | Date with time | October 17, 2026 5:43 PM |
| MinuteSpent | Number | 2 |
| Parent Task | Relation → Task Tracker | Link to a task page |

Task names are often blank at first and renamed later. **Parent Task** keeps entries consistent for auditing. The app must not treat blank or changed names as problems.

## 4. App fields and column mapping

### 4.1 App fields

| App field | Compatible Notion types | Status | Notes |
|---|---|---|---|
| Notion page ID | built in | Automatic | The internal primary key. No mapping needed. |
| Start time | date | **Required** | Must include a time. |
| End time | date, or the end of a date range in the Start time column | **Required** | Must include a time. |
| Task name | title, rich_text | Optional | Shown as "Untitled" when blank. Never flagged. |
| Parent task link | relation | Optional, recommended | Stored as the related page ID; shown as a clickable Notion link. An entry linking several pages keeps them all (`parent_task_ids`); the first is the parent task. Several links are never an issue. |
| Display ID | unique_id, number | Optional | A friendly label in the raw log. |
| Logged minutes | number, formula (number) | Optional | Used **only** for validation. Durations always come from End − Start. |
| Extra fields | any readable type | Optional, any number | Chosen by the user on the mapping screen. |

### 4.2 Mapping rules

- **Store mappings by property ID, not column name,** so renaming a column in Notion never breaks the mapping.
- **Auto-matching** pairs columns by type first, then by name similarity. Examples: the title property becomes Task name; a date property whose name contains "start" becomes Start time, and one containing "end", "stop" or "finish" becomes End time; a number whose name contains "min" becomes Logged minutes.
- **The review screen** shows each app field with the Notion column it's mapped to. The user can change any mapping, or set an optional field to "Not used". Only columns of compatible types are offered for each field.
- **Missing required fields:** if a required field has no compatible column, setup cannot finish. The screen explains exactly what is missing, for example: "Your database needs a second date column to use as the end time."
- **Extra fields:** an "Additional fields" section lists every unmapped column. Ticked columns are synced and shown in the raw log, with filters appropriate to their type.
- **Adding or changing mappings after setup** automatically triggers a full sync, so existing entries get the new data. Saving a changed mapping sets the `full_sync_required` setting (11), which the app shows on Home and Settings; a full sync clears it. Saving an unchanged mapping, and the first save, don't set it.
- **Matching details** (Phase 4):
  - Names are split at spaces, symbols and camelCase (`MinuteSpent` → "minute spent") and compared by keyword in three tiers: a whole word or phrase, a word that begins with a keyword, then a near spelling.
  - Within a field, an earlier type wins: the title over a text column, a unique ID over a number, a number over a formula.
  - Each column feeds at most one field; the only exception is a date range (below).
  - Optional fields are filled only with evidence: a matching name, or a type that identifies the field on its own (the title, the only unique ID, the only relation). A number with no telling name is never guessed to be Logged minutes or Display ID.
  - **Ties are never guessed.** When the best candidates for a field are equally good, the field is marked **Please choose** with those candidates and nothing selected. Saving is blocked until each one is answered; for an optional field, "Not used" is an answer.
  - A formula's result type isn't in the schema, so it counts as a number for Logged minutes unless the sample rows show another type.
- **Date ranges.** One date column can hold each session as a range (Start → End). End time's choices always include "End of the date range in ‹Start column›". It is chosen automatically only when no date column has an end-like name, Start time matched a single column, and the sample rows show that column holding ranges. It is stored as the same property ID with `part: "end"`, and follows Start time if Start moves to another column.
- **Sample values.** The review screen reads the 25 most recently created rows (one read-only query) and shows up to three non-empty values per column, in local time. A database with no rows maps from the schema alone. Dates without a time are marked, because validation will flag them. Relations show a count of linked pages and people a count, since neither their titles nor names are read.
- **Columns that can't be used** (buttons, Notion's `unsupported` type, and any type newer than the app) are listed under Additional fields with the reason and a disabled checkbox.

## 5. Validation (never blocks sync)

Validation is informational only. Every entry is imported, and its issues are stored with it.

| Issue | Rule | Effect |
|---|---|---|
| Duration mismatch | Logged minutes differs from (End − Start) by more than 1 minute. Checked only when Logged minutes is mapped and has a value, and only when Start and End both have times and End is not before Start; otherwise the entry shows only its Missing time or Invalid range issue. | Shown as a red cell |
| Invalid range | End time is before Start time | Red cells; excluded from charts |
| Missing time | Start or End is empty, or has a date but no time | Red cells; excluded from charts |
| Unreadable extra field | An extra field's value cannot be read | Red cell for that field only |

In the raw log, each affected cell turns red, and hovering over it shows a plain explanation, for example: "Logged 148 min, but Start → End is 123 min." A "Has issues" filter shows only flagged entries. The dashboard shows a small count of flagged entries that links to that filtered view.

Blank task names are **not** an issue.

**Date ranges** (4.2): when End time is the end of the Start column's range, Start is the range's start and End its end, both converted with the property's `time_zone`. The rules above apply unchanged: an entry whose date has no end, or whose start or end has no time, is a Missing time issue; an end before the start is an Invalid range.

## 6. Sync engine

### 6.1 Quick sync (automatic, every launch)

1. Run the schema check (6.3).
2. Note the time the sync starts **on Notion's clock**: the `Date` header of Notion's first response in the sync (the schema check's `GET /v1/data_sources/{id}`). The PC's clock is never used, so a fast or slow PC clock can't skip edits. If that header is missing or unreadable, the newest `last_edited_time` received is used instead (never later than the true start, so always safe); if nothing was received either, the cursor isn't moved.
3. Query the Work Log for pages whose `last_edited_time` is on or after the last successful sync **minus 5 minutes**. Notion records `last_edited_time` only to the minute, so the overlap prevents missed edits.
4. Upsert each page into the local database and re-run validation for it.
5. When it finishes successfully, save the start time from step 2 as the new "last successful sync". Using the start time means edits made during the sync are caught next time.

Quick sync catches new entries and edits, including renamed tasks. It does **not** detect deleted entries; that is left to full sync. Nor does it see formula or rollup values that change without the page itself being edited, so **on launch a full sync runs instead when the last full sync is more than 24 hours old** (measured on Notion's clock), when nothing has been synced yet, or when `full_sync_required` is set. Saving a mapping also starts a sync, which is full on first setup and after a change.

### 6.2 Full sync (settings button; also first-time setup)

1. Run the schema check (6.3).
2. Fetch every page in the database.
3. Upsert all of them and re-run validation.
4. **Only if every page was fetched successfully,** delete local entries whose page ID was not seen. A failed or interrupted full sync never deletes anything.
   - **Mass-removal safeguard:** if that would remove more than 50% of the local entries, or all of them, nothing is deleted yet. The app shows how many would go and the likely causes (the database is no longer shared with Habit Tracker, a different workspace, filters on the data source, or real deletions), with **Remove them** and **Keep them**. The rest of the sync's changes still apply. The question waits in `pending_removal` (11) until answered; Remove deletes only entries not copied again since; Keep clears it, and the next full sync asks again if they are still missing.
5. Save both "last full sync" and "last successful sync" (Notion's time, as in 6.1), and clear `full_sync_required`.

### 6.3 Schema check (before every sync)

- If a **required** mapped property no longer exists or has changed to an incompatible type, the sync does not start. The app explains what changed and opens the mapping screen.
- If an **optional or extra** mapped property is missing, the sync continues without that field and shows a warning.
- Problems in individual entries **never** stop a sync (see section 5).

### 6.4 Mechanics

- **API version and endpoints:** every request sends `Notion-Version: 2026-03-11`.
  - Rows come from `POST /v1/data_sources/{data_source_id}/query`.
  - The schema check (6.3) reads `GET /v1/data_sources/{data_source_id}`.
  - Quick sync filters on the `last_edited_time` timestamp.
- **Pagination:** pages of 100 using Notion's `start_cursor`. Relation values with `has_more: true` (more than 25 references) are completed with `GET /v1/pages/{page_id}/properties/{property_id}`, paginated.
- **Rate limits:** stay under about 3 requests per second with our own request limiter. On HTTP 429, wait for the `Retry-After` time and retry. Retry temporary network and server errors with backoff. Both retry behaviours come from `notion-client`'s retry options. Every request has an explicit timeout.
- **Auth errors:** a 401 triggers one serialized token refresh, then a single retry (12.5). A pasted token that gets a 401 asks for a new token. Neither case ever deletes local data.
- **Threading:** syncs run on a background thread with their own SQLite connection, one at a time; a full sync asked for during a quick sync runs right after it. The app's shared connection carries a lock that every user holds. The UI receives `sync:status` events with the whole status (pages fetched, entries added, updated or removed) and stays responsive.
- **Unreadable pages:** a page Notion sends without valid timestamps is skipped and reported; its local copy is never removed by that sync.
- **States the UI shows:**
  - not yet synced;
  - quick sync in progress (subtle indicator);
  - full sync in progress (progress bar);
  - completed with a summary (kept in `last_sync_result`, so it is still shown after a relaunch);
  - failed with a clear reason and a retry button;
  - offline, where the app shows local data and a note that sync was skipped;
  - "Reconnect to Notion" (the refresh was rejected);
  - "Paste a new token" (a pasted token expired or was revoked);
  - token service unreachable, which only matters when a refresh is needed (12.5).
- **Time zones:** all timestamps are stored in UTC and shown in the computer's local time zone. Notion date values are parsed like this:
  - **Offset** (`Z`, `+05:30`): convert directly to UTC.
  - **No offset, with `time_zone`:** localize with `zoneinfo.ZoneInfo(time_zone)`, then convert to UTC.
  - **Date only:** this is the Missing time issue (5).
  - **Range** (an `end` inside one mapped date property): each app field reads the part its mapping names, `start` unless End time is mapped to the end of the Start column's range (4.2).

## 7. Dashboard

Durations always come from End − Start. Entries excluded by validation do not count.

1. **Daily totals:** a bar chart of minutes or hours per day, with a selectable range (7 days, 30 days, 90 days, or custom up to today, at most three years).
2. **Weekly trends:** weekly totals for the last 12, 26 or 52 weeks (default 26) with a 4-week rolling average line: the mean of each week and the three before it, over the weeks since the first logged week when fewer than four exist. The current week is included and marked "so far".
3. **Streaks:** current streak and longest streak. A day counts when its total is more than 0 minutes (threshold 0, the default) or at least the threshold set in settings. **Today's grace:** a day with no time logged *yet* doesn't break the current streak, which runs through yesterday until today ends. Future days never count. Among equally long streaks, the most recent is shown as the longest.
4. **Calendar heatmap:** a GitHub-style view of the last 12 months by default, with a year picker, shaded by daily minutes. Hovering over a day shows its total and number of sessions.

**Rules**
- **Days are the computer's local days.** The UI sends its IANA time zone with each request; `zoneinfo` handles daylight-saving days of 23 and 25 hours.
- **Rules applied in order** (`app/stats/allocation.py`):
  1. **Which sessions count:** entries with a valid range; Missing time and Invalid range entries are left out (5).
  2. **Overlapping sessions** (setting): "Count overlapping time once" (default) counts any moment covered by two or more sessions once, crediting it to the session that started first (then the one that ends first, then by page ID), so totals reflect actual time spent and, with the split rule, no day exceeds 24 hours. "Add every session's full time" counts each session in full. Overlaps are never a validation issue.
  3. **Sessions crossing midnight** (setting): split proportionally between the days they cover (default), or "count the whole session on its start date", which puts all the time credited to a session on its start date (so a session longer than a day can exceed 24 hours there).
  A day's session count is every session the midnight rule places on it, whether or not its time was counted under the overlap rule.
- **The week starts on Monday** by default; this can be changed in settings.
- **Day detail:** clicking a day in any chart (or its table row) lists its sessions: times, full length, minutes counted that day, whether it crosses midnight, and any overlap with the minutes overlapped and which sessions it overlaps, plus "Open in Notion". This is how totals are checked against Notion.
- **Accessibility:** every chart has an accessible label and a "Show as table" view.
- **Flagged entries:** the dashboard shows the count of entries with issues, linking to the raw log with its "Has issues" filter on (8).
- **Every chart has an empty state.** Before the first sync, when no entry can be charted, or when a range has no data, the chart says so instead of appearing broken. The figures refresh when a sync finishes.

## 8. Raw log view

A "Raw log" tab beside Home and Settings. Rows are filtered, sorted and paged in Python (`app/rawlog/`) and the table draws only the rows in view, so it stays fast with thousands of entries.

- **Columns:** Display ID, Task name, Start, End, Duration (computed from End − Start), Logged minutes, Parent task (link), the user's extra fields, Overlap, Issues, and an "Open in Notion" button. Columns for app fields mapped as "Not used" are left out. Times are shown in the computer's local time.
- **Filters:** date range (local start date), task name search, parent task, duration range, has issues, issue type (Missing time, Invalid range, Duration mismatch, Unreadable extra field; matches any chosen), overlaps another session, and a type-appropriate filter for each extra field:
  - text, URL, email, phone, ID, place: contains;
  - number: min/max;
  - checkbox: yes/no;
  - select, status, verification, multi-select: any of the chosen options;
  - date, created and edited times: a local date range;
  - formula: by its result type (number, text, checkbox or date);
  - rollup: number, date, or contains for a list.
  
  Every extra field can also be filtered on "is empty" or "has a value". People and relations are filtered only on empty or not, because their names and titles aren't read. Filters on Duration leave out entries that have no valid range.
- **Selecting and opening** (decided in Phase 7): a single click on a row only selects it, and the arrow keys move the selection. Each row ends with an "Open in Notion" icon button; double-clicking a row, or pressing Enter on the selected row, also opens it. Text in cells can be selected and copied. The parent task link and the "+N" list open their own pages.
- **Sorting:** every column sorts, ascending or descending. Empty values always sort last, and ties keep the newest start first. The default is Start, newest first.
- **Columns are remembered** (decided in Phase 7): the sort order, the column widths (dragged on the header's edge) and the columns hidden with the column picker are kept in the `raw_log_view` setting (11) across relaunches. At least one data column stays visible. Filters reset on each launch.
- **Several parent links** (decided in Phase 5): the Parent task cell shows the first link, followed by a "+N" chip when the entry links more pages. The chip opens a small list of every linked page ("Linked page 2", …, each opening in Notion; titles aren't read, as the Task Tracker is out of scope). The parent task filter matches an entry when any of its linked pages matches. This is never shown as an issue.
- **Issues:** red cells with hover explanations, as described in section 5. Invalid range colours both Start and End. Each red cell also carries its explanation for screen readers, and the row's Issues cell opens the full list from the keyboard.
- **Overlaps** (decided in Phase 7): a row whose session overlaps another counted session gets an informational marker (not red) with the overlapped minutes, listing the sessions it overlaps. It uses the dashboard's own overlap function (`app/stats/allocation.py`), on the same counted sessions, so the raw log and the day detail always agree; a test proves it. Overlaps are never an issue.
- **CSV export** (decided in Phase 7): "Export CSV" saves exactly the rows, visible columns, column order and sorting on screen through a native Windows Save dialog run from Python.
  - The file is UTF-8 with a BOM, so Excel opens it correctly.
  - Times are local, written as `YYYY-MM-DD HH:MM`, with the time zone in the column header, for example "Start (Asia/Kolkata)".
  - Durations, logged minutes and overlaps are plain numbers of minutes. Parent tasks are Notion links, and issues are their explanations; several of either are written one per line within the cell.
  - Text that a spreadsheet would run as a formula (starting with `=`, `+`, `-`, `@`, a tab or a carriage return) is prefixed with `'`.
  - The file is written to a temporary file next to the target and then moved into place, so a failed save never leaves a half-written file.
  - States: nothing to export (the button is disabled, with the reason); the dialog is cancelled (nothing happens); a write error, such as the file being open in Excel (explained, with Try again); and success, showing the path with "Show in folder".
- **States:** loading, empty (not yet synced, or a sync is copying entries now), no results (filters exclude everything, with Clear filters), an error with Try again, and refreshing after a sync finishes.

## 9. Future ideas (not in v1)

- Time-of-day profile: when in the day work happens
- Day-of-week pattern
- Session-length distribution
- Daily goal with a progress ring
- Breakdown charts by a select-type extra field, such as category or project
- Gamification: XP per minute, levels, and milestone badges such as "first 100 hours" or "30-day streak"
- Task Tracker integration: parent task names and per-task breakdowns
- macOS build

## 10. Tech stack

**Back end: Python 3.12**

| Purpose | Choice |
|---|---|
| Desktop window | `pywebview` (uses WebView2 on Windows) |
| Notion API | `notion-client` ≥ 3.1, with `notion_version="2026-03-11"` set explicitly. Rows come from the **data-source** endpoints: `POST /v1/data_sources/{id}/query`, plus search filtered to data sources. Its built-in retries on 429 and 5xx (with `Retry-After` and backoff) are used. Patterns from the Chrome extension are re-implemented, not copied (`docs/extension-notes.md`). |
| Local database | built-in `sqlite3` |
| Token storage | `keyring` (Windows Credential Manager) |
| Time zones | `zoneinfo` plus the `tzdata` package, because Windows has no system IANA database |
| OAuth hand-back crypto | `cryptography` (X25519, HKDF-SHA256, AES-256-GCM) |
| Single instance | A Windows named mutex, so only one copy of the app runs |
| Dependencies | `uv` |
| Tests and linting | `pytest` (with `pytest -m gui` end-to-end tests that drive the real window), `ruff`, `mypy --strict` |

**Front end:** React + TypeScript built with Vite, Apache ECharts for charts, and TanStack Table for the raw log.
- **TypeScript 6.0** in strict mode (plus `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`). TypeScript 7 waits until typescript-eslint supports it.
- **Tooling:** ESLint with type-checked rules, Prettier, and Vitest with Testing Library.
- **Build:** a single self-contained `ui/dist/index.html`, with every script and style inlined. The app loads it over `file://`, where module scripts can't load other files, so no local web server is needed. The build adds a Content-Security-Policy that allows only the hashes of its own inline scripts, so text from Notion can never run as script.

**Bridge:** pywebview's JS API. The UI calls Python methods directly, for example `window.pywebview.api.full_sync()`, and Python pushes sync progress to the UI. There is no local web server. The only listener is the one-request OAuth hand-back on `127.0.0.1` during Connect (12.3).
- **Calls never reject.** Every Python method returns `{ok: true, data}` or `{ok: false, error}`, where `error` is an already-logged, redacted report with a short error ID.
- **Events.** Python pushes events as a `habit-tracker:event` DOM event, `{name, payload}`. Events emitted while the page is loading are buffered until the UI reports it is listening, so none are lost at startup or on reload.
- **Types.** The TypeScript types in `ui/src/bridge/types.ts` mirror `app/api.py`.

**Run modes**
- **Normal:** `habit-tracker` loads the built UI.
- **Dev:** `habit-tracker --dev` loads the Vite dev server, which it starts (or reuses) and stops on exit. It gives hot reload, the web inspector, DEBUG logging to the console, and the diagnostics panel.
- **Diagnostics:** `--diagnostics` shows the diagnostics panel in normal mode.
- **Self-check:** `--self-check` starts up without a window and prints a JSON report, for CI.

**Errors and logs**
- **Logs:** rotating files in `%APPDATA%\HabitTracker\logs\` (2 MB × 5), with UTC timestamps. Every handler masks tokens and secrets: Notion token shapes, `Authorization` headers, secret-named keys, OAuth URL parameters, and any value registered at run time.
- **Unexpected errors** show a readable message with an error ID instead of a crash or a blank window, and are logged. This covers Python calls, background threads, UI code, promises and rendering.
- **Startup failures** (database, missing UI, dev server) show an error page in the window. In normal mode, a UI that loads but never reports ready is replaced by the error page after 15 seconds. Dev mode leaves the page alone, so Vite's error overlay and hot reload keep working.
- **If the window itself can't open** (for example WebView2 is missing), a Windows message box explains.

**Token service:** a Cloudflare Worker in TypeScript, under `service/`.
- **Tools:** Wrangler for deploys, Vitest with `@cloudflare/vitest-plugin` for tests (the renamed `@cloudflare/vitest-pool-workers`), running inside the Workers runtime.
- **Crypto:** WebCrypto for X25519, HKDF and AES-GCM. If the Workers runtime lacks X25519, use `@noble/curves`.
- **Details:** see 12.2.

**Legal and support pages:** static pages (home, privacy policy, terms of use, support) served by the token service itself (12.2), so no separate web host is needed.

## 11. Local data model (SQLite)

The database file lives at `%APPDATA%\HabitTracker\habit_tracker.db`, next to the `logs\` folder. Both are created on first run. The `HABIT_TRACKER_HOME` environment variable points the app at another folder, for tests or a throwaway copy.

**Migrations.** The schema is built by numbered SQL files in `app/db/migrations/` (`0001_initial.sql`, …), applied in order on every start.
- **Atomic:** each migration runs in its own transaction with its bookkeeping row.
- **Recorded:** `schema_migrations` (version, name, checksum, applied time) records what was applied, and `PRAGMA user_version` mirrors the latest version.
- **Safe to re-run:** only missing migrations are applied.
- **Refusals with a readable message:** a database whose applied migration files have since changed, and a database from a newer app version.
- **Rule:** never edit a migration once it is on `main`; add a new one.

**Integrity.** Tables are SQLite `STRICT` tables. `CHECK` constraints require every timestamp column to be ISO 8601 UTC ending in `Z`, and the JSON columns to hold valid JSON of the right shape (`extra_fields` an object, `issues` an array, `settings.value` any JSON value). Missing times and End-before-Start are allowed, because those entries are imported and flagged (5).

**`work_logs`**

| Column | Type | Notes |
|---|---|---|
| page_id | TEXT PRIMARY KEY | Notion page UUID |
| display_id | TEXT | Nullable |
| task_name | TEXT | Nullable |
| start_utc | TEXT | ISO 8601 UTC; nullable |
| end_utc | TEXT | ISO 8601 UTC; nullable |
| parent_task_id | TEXT | Nullable; the first linked page |
| parent_task_ids | TEXT | JSON list of every linked page, in Notion's order (migration 0002) |
| logged_minutes | REAL | Nullable |
| extra_fields | TEXT | JSON: `{property_id: {name, type, value}}`; values normalised by type (`app/sync/values.py`) |
| issues | TEXT | JSON list: `[{field, code, message}]` |
| created_time | TEXT | From Notion |
| last_edited_time | TEXT | From Notion |
| synced_at | TEXT | Time this row was last written |

Indexes on `start_utc` and `parent_task_id`.

**`settings`** is a key–value table (`key TEXT PRIMARY KEY, value TEXT` holding JSON). Its keys are:
- **Notion source:** `database_id`, `data_source_id`, `database_title`;
- **Connection metadata:** `auth_kind` (`oauth`, `internal` or `pat`), `workspace_id`, `workspace_name`, `workspace_icon` (`{type: "emoji" | "image", value}`; images are stored as a data URI), `account_name` (the person behind a personal access token);
- **Mapping:** `mapping`, version 1: `fields` (app field → `{property_id, part?}` or null for Not used; `part` is `start` or `end` for the date fields), `extra` (property IDs), `names_at_save` (property ID → column name, used only to word messages) and `saved_at`. Mappings are found by property ID only. `full_sync_required` (`{since, reason}`) is set when a saved mapping changes and cleared by a full sync;
- **Preferences:** `streak_threshold_minutes` (0 to 1440; 0 means any time), `week_start` (`monday` … `sunday`), `midnight_rule` (`split` or `start_date`), `overlap_rule` (`once` or `sum`); damaged values fall back to the defaults;
- **Raw log:** `raw_log_view` (`{sort: {column, direction}, widths: {column: px}, hidden: [column]}`), the raw log's remembered sort, column widths and hidden columns (8). It is kept when switching databases; columns that no longer exist are ignored;
- **Policy:** `acknowledged_policy_version` (13);
- **Sync bookkeeping:** `last_successful_sync` and `last_full_sync` (both on Notion's clock, 6.1), `last_sync_result` (`{kind, reason, finished_at, ok, added, updated, removed, flagged, skipped, warnings, pending_removal, error}`, shown after a relaunch) and `pending_removal` (`{count, total, found_at, page_ids}`, the mass-removal question, 6.2). All are cleared with the rest of the database's data when switching databases.

The local schema version is kept by the migration system (`schema_migrations` and `PRAGMA user_version`), not in `settings`.

Tokens are never stored here (12.5).

Notion page links are built when displayed: `https://www.notion.so/<page id without dashes>`.

## 12. Authentication

Decided in Phase 1 (see `docs/extension-notes.md` section 8). There are two ways to connect, and both end with a token in Windows Credential Manager.
- **Main path:** public OAuth through a small hosted **token service**.
- **Advanced path:** a pasted token, for workspaces where public integrations are blocked or for anyone who doesn't want a third-party service involved.

The rest of the app doesn't care which path produced the token.

### 12.1 Notion integration

- **A new public integration named "Habit Tracker"**, separate from the WebNotes extension's integration.
- **Capabilities:** read content only. No insert, update or comment capabilities, and no user information. Notion itself then refuses any write, which backs up the "never write to Notion" rule.
- **Installation scope: Any workspace.** Notion doesn't allow changing this after creation, and it is required for other users to connect.
- **Review:** Notion's authorization guide says the integration's Authorization URL appears only after the public connection is **submitted for review**. Its public docs don't list what the review requires, so we prepare these before creating the integration:
  - a home page;
  - a privacy policy;
  - a terms of use page;
  - a support page.

  The token service serves them (12.2). We fill in whatever the developer portal's form asks for when the integration is created. Listing on the Notion Marketplace is optional and has its own security review. It is not part of v1.
- **Redirect URI:** the token service's `https://…/callback`. Only that URI is registered.

### 12.2 Token service (`service/`)

- **What it is:** a stateless Cloudflare Worker written in TypeScript, in this repo under `service/`.
  - **Tests:** its own tests (Vitest with `@cloudflare/vitest-plugin`).
  - **Documentation:** `service/README.md` has the setup, configuration and deploy instructions (`wrangler deploy`).
  - **CI:** runs its tests.
- **Secrets:** the client secret and the state-signing key exist **only as Cloudflare secrets** (`wrangler secret put`), never in the repo, CI logs or any file. The client ID is a plain Worker variable.
- **Stores nothing:** no KV, D1 or other storage. Tokens exist only in memory for the length of one request.
- **Logs no tokens:** logs hold only the route, method, status code and duration, never request or response bodies, query strings or auth headers. Cloudflare's automatic invocation logs are turned off (`invocation_logs = false`), because they record the full request URL, which on `/callback` holds Notion's one-time code and the `state`.
- **Response headers:** `Cache-Control: no-store` and `Referrer-Policy: no-referrer` on every response.
- **Rate limit:** requests are rate-limited per IP address with Cloudflare's rate-limiting binding.
- **Routes:**

| Route | Purpose |
|---|---|
| `POST /start` | The app sends its loopback port and one-time public key. The service returns a signed `state`: an HMAC over a 32-byte random nonce, the port, the public key and an expiry 10 minutes ahead. |
| `GET /callback` | Notion's redirect URI. It verifies the `state` signature and expiry, then exchanges the code using the client secret. It encrypts the token response to the app's public key and redirects to `http://127.0.0.1:<port>/done`. |
| `POST /refresh` | Takes a refresh token and calls Notion's token endpoint with `grant_type: refresh_token`. Returns the new token pair. |
| `POST /revoke` | Takes a token and calls `POST /v1/oauth/revoke`. |
| `GET /health` | Liveness check, used by the app to explain service outages. |
| `GET /`, `/privacy`, `/terms`, `/support` | Static pages for the integration's listing in Notion's developer portal and for users. Bundled with the Worker from `service/pages/`. They have no forms and set no cookies. |

### 12.3 Connect flow (OAuth)

1. **Set up the hand-back.** The app generates a one-time **X25519 key pair**. It opens a listener on `127.0.0.1` at a random free port, which accepts **one** request and times out after 5 minutes.
2. **Get a signed state.** The app calls `/start` and gets back a signed `state`.
3. **Consent in the browser.** The app opens the system browser at Notion's Authorization URL (`owner=user`, the service's redirect URI, that `state`). The user picks their workspace and **shares the Work Log database**.
4. **Exchange on the service.** Notion redirects to `/callback`, which checks `state` and exchanges the code.
5. **Encrypt the result.** The service encrypts the token response to the app's public key: X25519, then HKDF-SHA256, then AES-256-GCM, with `state` as associated data. The response holds `access_token`, `refresh_token`, `bot_id`, `workspace_id`, `workspace_name` and an `exp` 120 seconds ahead.
6. **Redirect to the app.** The service redirects the browser to the app's listener. The plain token never appears in a URL, the browser history or any log.
7. **Accept the hand-back, once.** The app checks that `state` matches the one it sent and that `exp` hasn't passed, then decrypts. **The hand-back is one-time-use:**
   - the listener closes after the first request;
   - the private key is destroyed after the first decryption attempt, whether it succeeds or fails;
   - a replayed or late payload can't be decrypted.
8. **Store the token.** The app saves the token pair to Credential Manager. Then it shows the database picker (12.6).

**Edge cases:**
- **Busy port:** the app picks another random port.
- **Browser closed or timeout:** the app returns to the Connect screen with a message.
- **State mismatch, bad signature or expired payload:** the app rejects it and offers a retry.
- **Service unreachable:** the app shows a clear message and points to the advanced path.

### 12.4 Pasted tokens (Settings → Advanced)

The user chooses which kind they are pasting:

| Kind | How the user gets it | Access | Expiry | Notes the app shows |
|---|---|---|---|---|
| **Internal integration token** | Creates an internal connection in Notion's developer portal with **Read content** only, then shares the Work Log with it (Add connections) | Only pages shared with the connection | Doesn't expire unless regenerated | The recommended choice for this path, because it can be limited to reading |
| **Personal access token (PAT)** | Creates one in the developer portal under personal access tokens | Everything the user can access, without sharing | Chosen at creation: 7 days to 1 year (default 1 year) | None beyond the expiry; the app only makes read calls either way |

- **Validation:** the app checks the token with a read-only call (`GET /v1/users/me`), then shows the database picker. Nothing is stored until the check passes.
- **No refresh:** a 401 means the token expired or was revoked. The app shows "Paste a new token", and local data stays readable.
- **Logout:** deletes the stored token. Pasted tokens can't be revoked through the API by the app, so it explains how to revoke the token in Notion.

### 12.5 Token storage, refresh and offline behaviour

- **Storage**
  - The app keeps one Credential Manager entry via `keyring`: service `HabitTracker`, account `notion`.
  - The entry is a small JSON blob, `{kind, access_token, refresh_token?, bot_id?, obtained_at}`, kept well under the 2,560-byte credential limit.
  - Tokens never go into SQLite, plain files, logs, crash reports or the UI. `settings` holds only non-secret metadata (11).
- **Refresh tokens rotate, so writes come first:**
  1. When `/refresh` returns a new pair, the app **writes it to Credential Manager before using it**.
  2. If the write fails, the sync stops with a clear error. The pair is kept in memory, and the next attempt retries the write before any API call.
- **Refreshes are serialized:**
  - **One at a time:** a single lock lets only one refresh run.
  - **Shared result:** callers that hit a 401 while a refresh is running wait for its result instead of starting their own.
  - **Single instance:** the app runs as a single instance (a Windows named mutex), so the in-process lock covers every caller.
- **When refresh happens:** only on a 401 from Notion, once per request. If it fails with `invalid_grant`, the app shows "Reconnect to Notion" and keeps all local data available.
- **If the service is unreachable:**
  - Only connect, refresh and revoke depend on it.
  - The app keeps working offline, and **keeps syncing directly with Notion while the current access token is valid**.
  - If a refresh is needed during an outage, the sync shows "Couldn't renew Notion access: token service unreachable", with a retry button. Local data stays fully usable.

### 12.6 Database picker

- **Search:** the picker pages through `POST /v1/search` filtered to data sources (Notion API 2026-03-11).
- **Display:** data sources are grouped under their parent database, whose title (and emoji icon) is fetched once per database. A database with several data sources shows them as choices once it is selected. "Show more databases" loads the next page of search results.
- **Saved:** `database_id`, `data_source_id` and `database_title` (11), after checking with `GET /v1/data_sources/{id}` that the data source is readable and belongs to that database.
- **Switching:** choosing a different data source while entries from the previous one are stored asks first. Confirming removes those entries and the old database's mapping and sync times; they stay in Notion. Choosing the same one again keeps everything.
- **Empty:** if nothing is found, the picker explains how to share the database, with steps for the kind of connection: Add connections for Notion sign-in and internal tokens; for a personal access token, that the database must be visible to its owner. It offers "Refresh" and, for Notion sign-in, "Connect again and choose pages".
- **Problems:** a 401 shows "Reconnect to Notion" (OAuth) or "Paste a new token" (pasted tokens). Offline and other errors offer "Try again".

### 12.7 Logout

1. **Ask first:** the Disconnect dialog asks whether to keep or delete the entries copied to this computer.
2. **Revoke:** for OAuth, the app calls `/revoke`. A failure doesn't block logout; the app says Notion's access couldn't be cancelled and how to remove it in Notion. Pasted tokens can't be revoked by the app, so it explains where to revoke or delete them.
3. **Delete:** it deletes the Credential Manager entry and the connection metadata (11).
4. **Local data:**
   - **Keep:** keeps the entries and the database choice, so reconnecting picks up where it left off.
   - **Delete:** removes the entries, the database choice, the mapping and the sync times. Preferences stay.

**Replacing a connection:** pasting a token while connected through Notion sign-in revokes the old OAuth access first. A failure there doesn't block the new connection.

## 13. Windows packaging

- **Build:** PyInstaller in one-folder mode, which starts faster than one-file builds.
- **Installer:** Inno Setup creates `Setup.exe` with Start Menu and desktop shortcuts and an uninstaller. It checks for the WebView2 runtime and installs it if missing.
- **Data:** stays in `%APPDATA%\HabitTracker\` across reinstalls.
- **Code signing:** not used at first, so testers will see a SmartScreen warning. It can be added later as a separate build step.
- **Distribution:** a GitHub Actions workflow builds `Setup.exe` whenever a version tag (`vX.Y.Z`) is pushed and attaches it to a GitHub Release. Other users download the app from the Releases page.
- **Privacy policy change notices** (a promise in the privacy policy):
  - **When:** if a change affects how data is handled, it ships only in a new app version, and that version shows a notice the first time it opens, before it does anything differently.
  - **How the app knows:** each build bundles a policy version number and a plain-language summary of the change. The app compares that number with the `acknowledged_policy_version` setting (11) and shows the notice when the bundled one is newer. Acknowledging the notice saves the new number.
  - **Fresh installs:** they show no notice. The current version is saved when the user first connects, which is where the policy is linked.
  - **No website contact:** the app never checks the website for policy changes, because the policy says it uses the website only when connecting, renewing and disconnecting.

## 14. Project layout

```
habit-tracker/
├── PLAN.md
├── CLAUDE.md
├── README.md
├── .gitignore
├── .gitattributes
├── .editorconfig
├── pyproject.toml           # Python project, ruff, mypy and pytest settings
├── uv.lock
├── .python-version          # 3.12
├── .node-version            # Node.js major for CI
├── .pre-commit-config.yaml  # hygiene, gitleaks, ruff, mypy, Prettier, ESLint, tsc
├── .gitleaksignore          # fingerprints of known fake test values
├── .github/
│   ├── ISSUE_TEMPLATE/      # bug report, feature request
│   ├── pull_request_template.md
│   ├── dependabot.yml       # uv, npm, GitHub Actions
│   └── workflows/           # ci.yml (Phase 2), release (Phase 8)
├── docs/
│   ├── setup.md             # Phase 0 output: tools, versions, new-machine setup
│   ├── extension-notes.md   # Phase 1 output
│   ├── handoff-protocol.md  # Phase 3: signed state and encrypted hand-off, shared by app and service
│   ├── token-service.md     # Phase 3: service setup, secrets, deploy
│   └── notion-integration.md # Phase 3: the Notion public connection's settings
├── service/                 # Token service: Cloudflare Worker (TypeScript), Phase 3
│   ├── src/                 # /start, /callback, /refresh, /revoke, /health, page routes
│   ├── pages/               # home, privacy policy, terms, support (served by the Worker)
│   ├── test/                # Vitest + @cloudflare/vitest-plugin
│   ├── wrangler.toml        # no secrets; those are set with `wrangler secret put`
│   └── README.md            # setup, configuration and deploy instructions
├── app/                     # Python back end
│   ├── main.py              # entry point: run modes, pywebview window, startup error page
│   ├── api.py               # JS API methods the UI calls
│   ├── bridge.py            # ok/error response envelope
│   ├── events.py            # events pushed to the UI
│   ├── paths.py             # %APPDATA%\HabitTracker locations
│   ├── log.py, redaction.py # rotating logs; secret masking
│   ├── errors.py, error_page.py  # error reports with IDs; the in-window error page
│   ├── devserver.py         # Vite dev server for dev mode
│   ├── single_instance.py   # one running copy per data folder (named mutex)
│   ├── notion/              # handoff, loopback listener, credentials, tokens (renewal), service client, read-only client, connection (connect, picker, logout); later: pagination, property readers
│   ├── sync/                # schema check, engine (quick and full sync), page values, local store
│   ├── mapping/             # property types and samples, auto-matcher, saved mapping, review service
│   ├── validation/          # entry checks
│   ├── stats/               # allocation (overlap, then midnight rule), daily totals, weeks, streaks, preferences
│   ├── rawlog/              # the raw log: columns, filters, sorting, paging, remembered view, CSV export
│   └── db/                  # connections, migrator, migrations/*.sql, settings, queries
├── ui/                      # React + Vite front end
│   ├── src/                 # bridge/, errors/, components/, tests next to the code
│   └── plugins/             # Vite plugins (Content-Security-Policy)
├── tests/                   # pytest; tests/e2e drives the real window (pytest -m gui); tests/support has the fake Notion, in-memory keyring, hand-off vectors and screenshots
└── packaging/               # PyInstaller spec, Inno Setup script
```

## 15. Build phases

Each phase ends with something the user can run and check. Every phase after Phase 0 is built on its own branch and merged into `main` through a pull request once the user approves it (see 15.2).

| Phase | Work | Done when |
|---|---|---|
| 0. Project setup | Install and verify every tool, configure Git, create the GitHub repository, and add the housekeeping files. Full checklist in 15.1. | The private GitHub repo exists with the first commit pushed, every tool reports its version, and `docs/setup.md` records them. |
| 1. Explore the extension | Read the Chrome extension at `C:\Users\LENOVO\Documents\JS\myNotionNotes` without modifying it. Document its auth flow, Notion API calls, pagination and error handling in `docs/extension-notes.md`. Propose the auth design. | The user approves the notes and the auth design. |
| 2. Scaffold | Set up the Python package with `uv`, the React/Vite UI, the pywebview window and bridge, the SQLite schema with migrations, and the `%APPDATA%` paths. Add CI (GitHub Actions on `windows-latest`: ruff, pytest, TypeScript type check, UI build), pre-commit hooks for ruff and formatting, and Dependabot for Python, npm and Actions. | The app window opens on Windows, the UI calls a test Python method, and CI passes on the pull request. |
| 3. Connect | **Before the integration exists:** write the pages in `service/pages/` and deploy them with the service. Create the "Habit Tracker" public integration (12.1) and submit it for review. Claude Code gives the user exact steps for each manual part.<br>**Token service:** build `service/` with its tests and README, and add it to CI and Dependabot. Help the user create a Cloudflare account and set the secrets, then deploy.<br>**App:** build the OAuth connect flow with the encrypted one-time hand-back (12.3), the pasted-token path for internal integration tokens and PATs (12.4), Credential Manager storage with serialized refresh (12.5), the database picker (12.6), logout (12.7), the single-instance guard, and every connect, error and outage state. Write tests for the state signing, hand-back crypto, replay and expiry rejection, refresh serialization and token storage. | **(a)** With a personal access token, the user connects, sees their workspace, picks their Work Log, logs out and reconnects; all CI checks pass. **(b)** The token service is deployed and its tests pass. **(c)** OAuth sign-in from the app works end to end. **(d)** OAuth sign-in from the app also works for a second Notion workspace that doesn't own the integration; if Notion blocks it pending review, what the review requires is recorded here. |
| 4. Map | Build schema reading, auto-matching (including a single date-range column), the review screen with sample values, extra-field selection, missing-required-field errors, saving and reopening the mapping with the full-sync-required flag, and the reusable schema check (6.3). | The author's Work Log maps correctly with no manual changes and shows correct sample values; Work Log (test) maps correctly; a real Notion database with no end-time column shows the exact missing-field explanation; all CI checks pass. |
| 5. Sync | Implement full sync, quick sync (cursor on Notion's clock; a full sync on launch when the last is over 24 hours old), the mass-removal safeguard, validation, progress events, retries, every parent-task link, and Home's "Last sync" panel with the flagged entries. Write tests for sync and validation logic. | A fresh install syncs all entries; edits appear after relaunch; deletions disappear after full sync; every broken-entry fixture is flagged correctly, and every broken entry in Work Log (test) is flagged correctly. |
| 6. Dashboard | Build the four charts, streak logic, the midnight split, the overlap rule, the day detail panel, settings, and empty states. Write tests for the stats logic. | The charts match manually checked totals. |
| 7. Raw logs | Build the table with filters, red issue cells, hover explanations, and Notion links. | Every filter works, and flagged entries show the correct explanations. |
| 8. Package | Set up the PyInstaller build, the Inno Setup installer, the WebView2 check, the release workflow, a README for other users, and the privacy-policy change notice (13). | `Setup.exe` downloaded from a GitHub Release installs and runs on a clean Windows machine. A test build with a newer policy version shows the notice once on its first launch, and never contacts the website. |

### 15.1 Phase 0 checklist: project setup

**Decisions to settle first.** Claude Code asks the user about each:
- **Project and repository name.** Settled: `habit-tracker`.
- **Repository visibility.** Settled: private until the first public release.
- **License.** Needed before the repository or app is shared publicly. Still undecided, so it stays in Open items.
- **Project folder location** on this computer. Settled: `C:\Users\LENOVO\Documents\JS\habit-tracker`, with Claude Code run from PowerShell.

**Accounts and access.** These steps need the user:
- **GitHub CLI login.** Run `gh auth login` and complete the sign-in in the browser.
- **Notion data for testing.** Manual testing uses **Work Log (test)**, a copy of the Work Log with the same schema; the original **Work Log** is the real data. Every broken case (a missing end time, an end before its start, a minutes mismatch, a date without a time, a blank name) and a schema with no end-time column is always covered by pytest fixtures that mirror the Work Log's API responses, since the app never writes to Notion. Broken entries the user adds to Work Log (test) by hand are also checked manually.

**Tools on Windows.** Claude Code first runs each check command. It asks before installing anything missing, and installs with **Scoop** (not `winget`). Scoop itself must be installed first (see https://scoop.sh), with the `extras` bucket added (`scoop bucket add extras`); Python 3.12 also needs the `versions` bucket (`scoop bucket add versions`).

| Tool | Purpose | Check | Install |
|---|---|---|---|
| Scoop | Package manager for the tools below | `scoop --version` | See https://scoop.sh |
| Git for Windows | Version control | `git --version` | `scoop install git` |
| GitHub CLI | Repository, pull requests, releases | `gh --version` | `scoop install gh` |
| Python 3.12 | Back end | `py -3.12 --version` (or `python --version` without the `py` launcher) | `scoop install versions/python312` |
| uv | Python dependencies and virtual environments | `uv --version` | `scoop install uv` |
| Node.js LTS | Front-end build | `node --version`, `npm --version` | `scoop install nodejs-lts` |
| WebView2 Runtime | pywebview rendering | `(Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}').pv` | Usually preinstalled on Windows 10/11. Otherwise use Microsoft's Evergreen Bootstrapper; it is a system component and is not available from Scoop. |
| Inno Setup 6 | Windows installer | `scoop list inno-setup`, `iscc /?` | `scoop install extras/inno-setup` |
| VS Code (optional) | Editing and reviewing code | `code --version` | `scoop install extras/vscode` |

After installing, open a new terminal so the updated PATH is picked up, then re-run every check.

**Git configuration**
- `git config --global user.name` and `user.email`, matching the GitHub account. Use the GitHub no-reply email if you prefer not to publish a personal address.
- `git config --global init.defaultBranch main`
- `git config --global core.autocrlf false`, so line endings are controlled by `.gitattributes` instead.

**Repository files**
- **`.gitignore`:** Python caches, `.venv/`, `node_modules/`, `ui/dist/`, `build/`, `dist/`, PyInstaller output, `*.db`, `.env*`, logs, and editor and OS clutter.
- **`.gitattributes`:** `* text=auto eol=lf`; CRLF for `*.ps1`, `*.bat`, `*.cmd` and `*.iss`; binary for images and icons.
- **`.editorconfig`:** UTF-8 and LF; 4-space indentation for Python; 2 spaces for TypeScript, JSON, YAML and Markdown.
- **`README.md`:** app name, one-line description, the status "In development", and a link to `PLAN.md`.
- **`docs/setup.md`:** every tool with its installed version, plus step-by-step setup for a new development machine.
- **`.github/ISSUE_TEMPLATE/`:** a bug report (steps, expected vs. actual, app version, Windows version, screenshot) and a feature request.
- **`.github/pull_request_template.md`:** the phase, what changed, how to test it, and a checklist (tests pass; `PLAN.md` updated if a decision changed; no secrets committed).

**Create and push the repository**
1. In the project folder that already holds `PLAN.md` and `CLAUDE.md`, run `git init` and add the files above.
2. Commit to `main` with the message `Phase 0: project setup`.
3. Create the GitHub repo and push: `gh repo create <name> --private --source . --remote origin --push`.

**GitHub repository settings**
- **Labels:** `bug`, `enhancement`, `notion-api`, `sync`, `mapping`, `validation`, `ui`, `packaging`.
- **Milestones:** one per phase, 1 to 8.
- **Pull requests:** allow squash merge only, and delete branches automatically after merging.
- **Security:** enable Dependabot alerts, plus secret scanning and push protection where your GitHub plan offers them.
- **Branch protection:** not used (decided in Phase 2). GitHub offers it for this private repository only with GitHub Pro, which the user declined. Instead, a manual rule applies: a pull request is merged only after CI passes and the user gives explicit approval.

Phase 0 is the only phase committed directly to `main`.

### 15.2 Git workflow

- **`main` always holds approved, working code.** Never force-push it.
- **Each phase:**
  1. Create a branch `phase-N-short-name` from the latest `main`.
  2. Commit in small, logical steps with clear messages, and push regularly.
  3. Open a pull request with `gh pr create` using the template, linked to the phase milestone.
  4. The user tests the phase.
  5. After approval, squash-merge, delete the branch, and pull `main`.
- **Bugs and ideas found later** become GitHub issues, fixed on branches named `fix/short-name` or `feat/short-name`.
- **Releases:** from Phase 8 onward, tag `vX.Y.Z` on `main`. The tag triggers the release workflow.
- **Never commit** tokens, secrets, `.env` files, or local databases.

## 16. Open items

- License: undecided. It must be chosen before the repository or app is shared publicly.
- Cloudflare account: the user creates it when Phase 3 reaches the token service. Claude Code gives exact steps at that point.
- Notion review for other workspaces: sign-in without review is verified live only in the author's own workspace (2026-10-20). Phase 3 check (d) (a second Notion account) was accepted by the user's decision without being verified (2026-10-22). If another workspace's sign-in is ever blocked pending review, find out what Notion's review requires, record it here and in the Decisions log, and submit the connection.
- Chrome extension path: `C:\Users\LENOVO\Documents\JS\myNotionNotes`

## 17. Decisions log

| Date | Decision |
|---|---|
| 2026-10-17 | The app reads only the Work Log. Task Tracker integration is a future upgrade. |
| 2026-10-17 | Quick sync filters on `last_edited_time`; deletions are handled only by full sync. |
| 2026-10-17 | Sync is strictly one-way, from Notion to the app. |
| 2026-10-17 | Required fields: Start time and End time. Task name is optional; Parent task is optional but recommended. MinuteSpent is used only for ±1 minute validation. |
| 2026-10-17 | Flagged entries never block sync. Issues are shown as red cells in the raw log. |
| 2026-10-17 | Users can add extra Notion fields to the app through the mapping screen. |
| 2026-10-17 | Initial charts: daily totals, weekly trends, streaks, calendar heatmap, plus a raw log view with filters. |
| 2026-10-17 | Stack: Python + pywebview back end, React + ECharts front end, SQLite storage. |
| 2026-10-17 | Windows is the first target platform. |
| 2026-10-17 | Auth and Notion code will be adapted from the author's Chrome extension, as inspiration rather than a strict copy. |
| 2026-10-17 | Phase 0 is now project setup: tools, GitHub repository, and housekeeping files. The original phases moved to 1–8. |
| 2026-10-17 | Code lives in a private GitHub repo. Each phase gets its own branch and pull request, squash-merged after approval. |
| 2026-10-17 | CI runs on GitHub Actions (Windows). Installers are published through GitHub Releases on version tags. |
| 2026-10-17 | Effort and complexity are never reasons to change, scale down or phase any part of the plan (see Guiding principle). |
| 2026-10-17 | Project and repository name: `habit-tracker`. The GitHub repo is private until the first public release. The license is still undecided (see Open items). |
| 2026-10-17 | The project folder is `C:\Users\LENOVO\Documents\JS\habit-tracker`, and Claude Code is run from PowerShell. |
| 2026-10-17 | Development tools are installed with Scoop instead of `winget` (for example `scoop install gh extras/inno-setup`). The WebView2 Runtime is the exception, because Scoop doesn't provide it. The 15.1 tool table was updated to match. |
| 2026-10-17 | No Notion test databases. Development uses the original Work Log. Broken-entry and missing-column cases are tested with pytest fixtures; the Phase 4 and 5 "Done when" checks were updated to match. |
| 2026-10-17 | Supersedes the previous row: the user created **Work Log (test)** (same schema as the Work Log) for manual testing. Pytest fixtures still cover every broken case and the missing end-time column. There is no separate no-end-time database; the fixture covers that case. |
| 2026-10-17 | Duration mismatch is checked only when the range is valid (both times present, End not before Start). An entry with a missing time or an invalid range shows only that issue, never a mismatch as well. |
| 2026-10-18 | Auth design (Phase 1): public OAuth through a stateless hosted token service. The service returns tokens to the app encrypted (X25519 + AES-GCM) to a one-time key, through a one-request listener on `127.0.0.1`. The `state` is random and HMAC-signed and is checked on return. The hand-back is one-time-use and expires in 120 seconds. See 12. |
| 2026-10-18 | Token rules: refresh tokens rotate, so a new pair is written to Credential Manager before it is used. Refreshes are serialized (single-flight lock, single app instance). If the token service is unreachable, the app keeps working offline and keeps syncing while the access token is valid; only connect, refresh and revoke need the service. |
| 2026-10-18 | The token service stores and logs no tokens. The client secret and state-signing key are Cloudflare secrets only, never in the repo. The service code lives in `service/` with its own tests and deploy instructions, and runs on Cloudflare Workers. |
| 2026-10-18 | Settings → Advanced offers pasted tokens: internal integration tokens and personal access tokens. |
| 2026-10-18 | A new public Notion integration "Habit Tracker", separate from the extension's: read content only, installation scope Any workspace. Legal and support pages are served by the token service, ready before the integration is submitted for Notion's review. |
| 2026-10-18 | Notion API version `2026-03-11`, using data-source endpoints (`/v1/data_sources/{id}/query`). `notion-client` ≥ 3.1 with its built-in retries plus our own rate limiter. `settings` gains `data_source_id`, `auth_kind`, `workspace_id` and `workspace_name`. |
| 2026-10-18 | The home, privacy, terms and support pages are served by the Cloudflare Worker instead of GitHub Pages. That removes the need for a separate host and a GitHub plan for Pages on a private repo. |
| 2026-10-18 | Time zones: `zoneinfo` with the `tzdata` package (Windows has no IANA database). Date-time values without an offset are localized using the property's `time_zone`. |
| 2026-10-18 | Phase 2: the production UI is one self-contained `index.html` (vite-plugin-singlefile) loaded over `file://`, keeping "no local web server" (10). The build adds a Content-Security-Policy that allows only its own inline scripts by hash. pywebview's bridge works under it, which the end-to-end tests check. |
| 2026-10-18 | Phase 2: TypeScript is pinned to 6.0.x, because typescript-eslint (type-checked linting) supports only TypeScript below 6.1 and TypeScript 7 is current. Dependabot ignores TypeScript ≥ 6.1 until that changes. Also: ESLint, Prettier and Vitest for the UI, and `mypy --strict` for Python. |
| 2026-10-18 | Phase 2: schema migrations are numbered SQL files recorded in `schema_migrations` with checksums and mirrored in `PRAGMA user_version`. The `schema_version` key is removed from `settings` (11). Tables are `STRICT`, with `CHECK` constraints for UTC timestamps and JSON shapes. |
| 2026-10-18 | Phase 2: Python methods return an ok/error envelope with logged, redacted error reports and short error IDs. Python pushes events as DOM events, buffered until the UI is ready. Dev mode starts or reuses the Vite dev server. `HABIT_TRACKER_HOME` overrides the data folder. `--diagnostics` and `--self-check` are added (10). |
| 2026-10-18 | Phase 2: branch protection and rulesets for `main` are unavailable on this private repo on the current GitHub plan ("Upgrade to GitHub Pro or make this repository public"). |
| 2026-10-18 | Phase 2: GitHub secret scanning is unavailable on this private repo, so gitleaks scans staged changes in pre-commit and the full history in CI. CI actions are pinned to commit SHAs. End-to-end tests drive the real window in CI (`pytest -m gui`). |
| 2026-10-18 | Phase 2 review: approved removing the `schema_version` key from `settings`. The local schema version lives only in the migration system (11). |
| 2026-10-18 | Phase 2 review: approved pinning TypeScript to 6.0.x until typescript-eslint supports TypeScript 7 (10). |
| 2026-10-18 | Phase 2 review: Node.js moves to Scoop (`nodejs-lts`, 24.22.0), replacing the nodejs.org install in `C:\Program Files\nodejs`, so every tool now comes from Scoop. `.node-version` pins CI to the same exact version, and `ui/package.json` `engines` requires `>=24.22.0` (enforced by `engine-strict` in `ui/.npmrc`). jsdom is upgraded to 30, which needs Node 24.15 or later. |
| 2026-10-18 | Phase 2 review: no branch protection on `main`, and no GitHub Pro upgrade for it. The manual rule stays: never merge a pull request without the user's explicit approval, and only with CI passing. This supersedes the plan to apply branch protection later. |
| 2026-10-18 | Phase 3 plan: OAuth is tried with the public connection as soon as it exists. Notion's docs say review is needed only for a Marketplace listing (not part of v1), so a review is submitted only if Notion blocks unreviewed connections. The encrypted hand-off travels in the loopback redirect's query string; it can't be decrypted once the app's one-time key is gone. Workspace icons reach the UI as data URIs (a first letter for pasted tokens), keeping the UI's CSP strict. The full OAuth flow is tested offline against a fake Notion with `wrangler dev`. |
| 2026-10-18 | Phase 3: the Worker's tests use `@cloudflare/vitest-plugin`, the renamed and maintained successor of the deprecated `@cloudflare/vitest-pool-workers`, with Vitest 5 (as in `ui/`). |
| 2026-10-18 | Phase 3: Cloudflare's automatic invocation logs are off for the Worker, because they record full request URLs (Notion's code and the state on `/callback`). Only the Worker's own lines (route, method, status, duration) are kept (12.2). |
| 2026-10-18 | Phase 3: the public pages' wording follows what the app does for each way of connecting, including that a personal access token has the creator's full access, though the app sends only read requests. Terms are governed by the laws of India, with the courts at New Delhi having jurisdiction. The privacy policy keeps the "not aimed at children under 13" line and dates from the first deploy. |
| 2026-10-18 | Phase 3: the privacy policy promises notice of data-handling changes. Notices ship only inside app updates, shown on the first launch of the new version, and the app never contacts the website for them. Tracked as a Phase 8 requirement (13, 15), with a new `acknowledged_policy_version` setting (11). |
| 2026-10-18 | Phase 3 token service details (`docs/handoff-protocol.md`):
- **Errors are encrypted too.** The Worker returns every sign-in outcome, including cancel, access denied and Notion errors, in the encrypted envelope, so the app reacts at once instead of waiting for its 5-minute timeout.
- **Clock correction.** `/start` returns `server_time`, which corrects the app's expiry check for a wrong PC clock.
- **Origin requests refused.** `POST` routes refuse requests that carry an `Origin` header, so a web page can't drive them.
- **Bodies capped.** Request bodies are limited to 4 KB.
- **Redirect URI.** It is the Worker's own origin + `/callback`.
- **Rate limits per IP.** OAuth routes allow 20 requests a minute, and pages 120.
- **Deploy guard.** `npm run deploy` refuses while any page placeholder is unfilled, and runs the tests first. |
| 2026-10-20 | Phase 3: confirmed live that the unreviewed "Habit Tracker" public connection signs in through the deployed token service (`https://habit-tracker.mrathour.workers.dev`), and that the hand-off and revoke work. **This is verified only for the author's own workspace, where the author owns the connection.** Whether a workspace the author doesn't own can sign in without review is checked in Phase 3 verification (d). Until (d) passes, "no review needed" is not assumed for other users. |
| 2026-10-20 | Phase 3 app auth decisions:
- **Isolated copies.** A copy of the app pointed at another data folder (`HABIT_TRACKER_HOME`) uses its own Credential Manager account (`notion-<hash>`) and its own single-instance lock, so tests and throwaway copies never touch the real connection. A second launch focuses the running window and exits.
- **Retries.** The read-only Notion client also retries 5xx on read-only POSTs (search, query), which `notion-client` won't retry. A request is renewed at most once on 401; a second 401 means "Reconnect to Notion".
- **Pasted-token check.** A pasted token is checked with `GET /v1/users/me` from memory and stored only if Notion accepts it. A person returned by `users/me` (personal access tokens) is shown by name.
- **Error codes for the UI.** Error reports carry a `code` (the error's UI state) so screens can offer the right action.
- **No secrets in settings.** `settings` refuses keys that sound like secrets.
- **Opening links.** Only HTTPS links to Notion and the token service open in the browser. |
| 2026-10-20 | Phase 3 UI: the app's visual style is a time sheet: Bahnschrift for headings and figures, Segoe UI Variable for text, ledger green `#2f6f5e` on a cool grey. No web fonts, so the CSP stays strict and the UI works offline. The Connect screen's hero is a week of sessions on a 24-hour strip. |
| 2026-10-20 | Phase 3 testing: end-to-end window tests run against a fake Notion served over HTTP. For OAuth they also run the real token service locally with `wrangler dev`, with a scripted browser following the real redirects. Every test uses an in-memory keyring. The token service gets its own CI job and Dependabot entry, and pre-commit hooks for `service/`. |
| 2026-10-22 | Phase 3 approved. The user ran checks (a), (b) and (c). Check (d), signing in from a second Notion account, was **accepted by the user's decision without being verified**. "No review needed" is confirmed live only for the author's own workspace. If sign-in from another workspace is ever blocked, it is handled then (see Open items). |
| 2026-10-22 | Phase 4: a single date column holding a range (Start → End) can supply both Start time and End time. It is chosen automatically only when no date column has an end-like name, Start matched one column and the sample rows show ranges; otherwise "End of the date range in ‹Start column›" is offered by hand. It is stored as the same property ID with `part: "end"`. Validation (5) applies unchanged, and 6.4's range rule now reads the part each mapping names. |
| 2026-10-22 | Phase 4: when two or more columns fit a field equally well, the field is marked "Please choose" with nothing selected, and saving is blocked until it is answered ("Not used" counts for optional fields). Optional fields are filled automatically only with evidence (a telling name, or a type that identifies the field on its own). Each column feeds one field, except a date range. |
| 2026-10-22 | Phase 4: the review screen samples the 25 most recently created rows with one read-only query and shows up to three values per column in local time. A formula's result type is read from those samples. Buttons, `unsupported` and unknown property types are listed with the reason they can't be used. |
| 2026-10-22 | Phase 4: new setting `full_sync_required` (`{since, reason}`), set when a saved mapping changes (not on the first save or an unchanged save), shown on Home, Settings and the mapping screen, and cleared with the database's other data when switching databases. Phase 5's full sync clears it. The `mapping` setting's shape is recorded in 11. |
| 2026-10-22 | Phase 4 "Done when" updated: besides the tests, a real Notion database with no end-time column (created by the user) must show the exact missing-field explanation, and Work Log (test) must map correctly. This supersedes the 2026-10-17 row saying there is no separate no-end-time database; the pytest fixtures stay. |
| 2026-10-22 | Phase 4: `tzdata` added as a dependency (planned in 10). The author's Work Log schema was checked in Notion: its ID column is named "ID" (Notion shows unique IDs as "№ ID"); section 3 updated. The UI's mapping test fixtures are generated from the Python service, and a pytest check keeps them in step. |
| 2026-10-22 | Phase 5 plan approved, including a "Last sync" panel on Home (summary, counts, the flagged entries with their explanations and Open in Notion) so flagged entries can be checked before Phase 7's raw log, and a `last_sync_result` setting so the last outcome survives a relaunch (11). |
| 2026-10-22 | Phase 5: the quick-sync cursor is Notion's clock, never the PC's: the `Date` header of Notion's first response in the sync (the schema check), which is Notion's time when the sync started, to the second. Fallback: the newest `last_edited_time` received (never later than the true start, so safe but less current); with neither, the cursor stays. `last_full_sync` uses the same clock. Chosen over the newest `last_edited_time` because that stops advancing when nothing is edited and is rounded to the minute. The 5-minute overlap stays (6.1). |
| 2026-10-22 | Phase 5: on launch, a full sync runs instead of a quick sync when the last full sync is more than 24 hours old (on Notion's clock), because quick sync can't see formula and rollup values that change without editing the page. The mapping screen, Home and Settings say that formula and rollup values refresh with each full sync (6.1). |
| 2026-10-22 | Phase 5: mass-removal safeguard. A full sync that would remove more than 50% of the local entries, or all of them, pauses before deleting, shows the count and likely causes, and asks Remove them / Keep them. The sync's other changes still apply. Stored as `pending_removal` (6.2, 11). |
| 2026-10-22 | Phase 5: every page linked in the parent task relation is kept (`parent_task_ids`, migration 0002); the first stays `parent_task_id`. Never flagged. Phase 7 shows the first link and a "+N" list of the rest, and filters on any of them (8). Relations past 25 links are completed for the parent task and extra fields. |
| 2026-10-22 | Phase 5 implementation details: a launch starts one "auto" sync once the work log is mapped, and saving a mapping starts one too; a full sync asked for during a quick sync runs after it; syncs use their own SQLite connection, and the shared connection carries a lock every user holds; a page without valid timestamps is skipped, reported and never removed; extra field values are normalised by type (11); a formula Logged minutes that isn't a number counts as empty. |
| 2026-10-22 | Phase 5 review: the sync keeps its own SQLite connection, as planned. Its upserts, deletions and bookkeeping always went through it; the lock on the app's shared connection was added for a different race: the sync thread published its progress by reading the shared connection while bridge threads read it too. Now it reads its progress through its own connection as well, so a running sync never touches the shared connection (only once, after it ends), and the lock only serialises the UI side's short reads. Proven by a test: during a 5,000-entry full sync, the sync thread never takes that lock, and UI reads stay fast (147 reads, median 4.8 ms, max 40 ms; settings writes max 28 ms on the dev PC). The test fails if the old progress reads are restored. A second test upgrades a populated version-1 database (250 entries and settings) to version 2 with every row intact. |
| 2026-10-22 | Phase 6 plan approved: (a) a day detail panel (each session's times, full and counted minutes, midnight splits, overlaps, Open in Notion) for checking totals against Notion; (b) the dashboard's flagged count links to Home's flagged list until Phase 7; (c) streak rules: today's grace (no time yet today doesn't break the current streak) and future days never count; (d) weekly chart 12/26/52 weeks (default 26), calendar last 12 months by default with a year picker. Days follow the IANA time zone the UI sends, with `zoneinfo`; no new dependency. |
| 2026-10-22 | Phase 6: overlapping sessions. A new Dashboard setting `overlap_rule`: "Count overlapping time once" (default; overlapping time credited to the earliest-starting session, so totals are actual time and, with the split rule, no day exceeds 24 hours) or "Add every session's full time". Order: counted sessions, then the overlap rule, then the midnight rule, for both rules' options (7). The day detail marks overlapping sessions with the overlapped minutes and the sessions they overlap. Overlaps are not a validation issue. |
| 2026-10-22 | Phase 6: charts use modular ECharts imports (canvas renderer) under the existing strict CSP, follow the app's light and dark tokens, and each has a "Show as table" view. A day's session count includes sessions whose time was fully overlapped. With the start-date rule, one session longer than a day can exceed 24 hours on its start date, as Settings explains. |
| 2026-10-22 | Phase 7 plan approved, with three additions: (a) an issue-type filter (Missing time, Invalid range, Duration mismatch, Unreadable extra field; matches any chosen) beside "Has issues"; (b) the raw log remembers its sort order and column widths across relaunches; (c) a column picker to show or hide columns. (b) and (c) are kept in a new `raw_log_view` setting (11); filters reset on each launch. The dashboard's flagged count and Home's flagged list now open the raw log with "Has issues" on (7, 8). |
| 2026-10-22 | Phase 7: opening Notion is a deliberate action. A single click on a row only selects it. Each row has an "Open in Notion" icon button at its end, and double-clicking or pressing Enter on the selected row also opens it. The parent task link and the "+N" list still open their pages. Cell text can be selected and copied. This replaces "clicking a row opens the entry in Notion" (8). |
| 2026-10-22 | Phase 7: overlaps in the raw log. A row whose session overlaps another counted session gets an informational (not red) marker with the overlapped minutes, and there is an "Overlaps another session" filter. It reuses the dashboard's overlap function and its counted sessions (`app/stats/`), shared rather than reimplemented, and a test proves the raw log and the day detail agree (8). |
| 2026-10-22 | Phase 7: CSV export of exactly the rows, columns, order and sorting on screen, through a native Windows Save dialog run from Python. UTF-8 with a BOM; local times with the time zone in the header; every state handled (nothing to export, cancelled, write error such as the file being open in Excel, success with the path). Also decided: text starting with `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with `'` so a spreadsheet never runs it as a formula; the file is written to a temporary file and moved into place; "Show in folder" opens Explorer at the saved file (8). |
