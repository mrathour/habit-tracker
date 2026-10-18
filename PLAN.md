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
| № ID | Unique ID | 6 |
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
| End time | date | **Required** | Must include a time. |
| Task name | title, rich_text | Optional | Shown as "Untitled" when blank. Never flagged. |
| Parent task link | relation | Optional, recommended | Stored as the related page ID; shown as a clickable Notion link. |
| Display ID | unique_id, number | Optional | A friendly label in the raw log. |
| Logged minutes | number, formula (number) | Optional | Used **only** for validation. Durations always come from End − Start. |
| Extra fields | any readable type | Optional, any number | Chosen by the user on the mapping screen. |

### 4.2 Mapping rules

- **Store mappings by property ID, not column name,** so renaming a column in Notion never breaks the mapping.
- **Auto-matching** pairs columns by type first, then by name similarity. Examples: the title property becomes Task name; a date property whose name contains "start" becomes Start time, and one containing "end", "stop" or "finish" becomes End time; a number whose name contains "min" becomes Logged minutes.
- **The review screen** shows each app field with the Notion column it's mapped to. The user can change any mapping, or set an optional field to "Not used". Only columns of compatible types are offered for each field.
- **Missing required fields:** if a required field has no compatible column, setup cannot finish. The screen explains exactly what is missing, for example: "Your database needs a second date column to use as the end time."
- **Extra fields:** an "Additional fields" section lists every unmapped column. Ticked columns are synced and shown in the raw log, with filters appropriate to their type.
- **Adding or changing mappings after setup** automatically triggers a full sync, so existing entries get the new data.

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

## 6. Sync engine

### 6.1 Quick sync (automatic, every launch)

1. Run the schema check (6.3).
2. Note the time the sync starts.
3. Query the Work Log for pages whose `last_edited_time` is on or after the last successful sync **minus 5 minutes**. Notion records `last_edited_time` only to the minute, so the overlap prevents missed edits.
4. Upsert each page into the local database and re-run validation for it.
5. When it finishes successfully, save the start time from step 2 as the new "last successful sync". Using the start time means edits made during the sync are caught next time.

Quick sync catches new entries and edits, including renamed tasks. It does **not** detect deleted entries; that is left to full sync.

### 6.2 Full sync (settings button; also first-time setup)

1. Run the schema check (6.3).
2. Fetch every page in the database.
3. Upsert all of them and re-run validation.
4. **Only if every page was fetched successfully,** delete local entries whose page ID was not seen. A failed or interrupted full sync never deletes anything.
5. Save both "last full sync" and "last successful sync".

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
- **Threading:** syncs run on a background thread. The UI receives progress events (pages fetched, entries added, updated or removed) and stays responsive.
- **States the UI shows:**
  - not yet synced;
  - quick sync in progress (subtle indicator);
  - full sync in progress (progress bar);
  - completed with a summary;
  - failed with a clear reason and a retry button;
  - offline, where the app shows local data and a note that sync was skipped;
  - "Reconnect to Notion" (the refresh was rejected);
  - "Paste a new token" (a pasted token expired or was revoked);
  - token service unreachable, which only matters when a refresh is needed (12.5).
- **Time zones:** all timestamps are stored in UTC and shown in the computer's local time zone. Notion date values are parsed like this:
  - **Offset** (`Z`, `+05:30`): convert directly to UTC.
  - **No offset, with `time_zone`:** localize with `zoneinfo.ZoneInfo(time_zone)`, then convert to UTC.
  - **Date only:** this is the Missing time issue (5).
  - **Range** (an `end` inside one mapped date property): ignored. Each app field reads only `start`.

## 7. Dashboard

Durations always come from End − Start. Entries excluded by validation do not count.

1. **Daily totals:** a bar chart of minutes or hours per day, with a selectable range (7 days, 30 days, 90 days, or custom).
2. **Weekly trends:** weekly totals with a 4-week rolling average line.
3. **Streaks:** current streak and longest streak. A day counts when its total meets a threshold set in settings. The default threshold is more than 0 minutes.
4. **Calendar heatmap:** a GitHub-style year view shaded by daily minutes. Hovering over a day shows its total and number of sessions.

**Rules**
- **Sessions crossing midnight** are split proportionally between the days they cover. This is the default; settings also offers "count the whole session on its start date".
- **The week starts on Monday** by default; this can be changed in settings.
- **Every chart has an empty state.** Before the first sync, or when a range has no data, the chart says so instead of appearing broken.

## 8. Raw log view

- **Columns:** Display ID, Task name, Start, End, Duration (computed), Logged minutes, Parent task (link), the user's extra fields, and an issues indicator.
- **Filters:** date range, task name search, parent task, duration range, has issues, and a type-appropriate filter for each extra field.
- **Behaviour:** columns are sortable; clicking a row opens the entry in Notion in the default browser; the parent task link opens the parent page.
- **Issues:** red cells with hover explanations, as described in section 5.
- **States:** empty (not yet synced), no results (filters exclude everything), and loading.

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
- **Tools:** Wrangler for deploys, Vitest with `@cloudflare/vitest-pool-workers` for tests.
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
| parent_task_id | TEXT | Nullable |
| logged_minutes | REAL | Nullable |
| extra_fields | TEXT | JSON: `{property_id: {name, type, value}}` |
| issues | TEXT | JSON list: `[{field, code, message}]` |
| created_time | TEXT | From Notion |
| last_edited_time | TEXT | From Notion |
| synced_at | TEXT | Time this row was last written |

Indexes on `start_utc` and `parent_task_id`.

**`settings`** is a key–value table (`key TEXT PRIMARY KEY, value TEXT` holding JSON). Its keys are:
- **Notion source:** `database_id`, `data_source_id`, `database_title`;
- **Connection metadata:** `auth_kind` (`oauth`, `internal` or `pat`), `workspace_id`, `workspace_name`;
- **Mapping:** `mapping` (app field → property ID, plus the list of extra fields);
- **Preferences:** `streak_threshold_minutes`, `week_start`, `midnight_rule`;
- **Sync bookkeeping:** `last_successful_sync`, `last_full_sync`.

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
  - **Tests:** its own tests (Vitest with `@cloudflare/vitest-pool-workers`).
  - **Documentation:** `service/README.md` has the setup, configuration and deploy instructions (`wrangler deploy`).
  - **CI:** runs its tests.
- **Secrets:** the client secret and the state-signing key exist **only as Cloudflare secrets** (`wrangler secret put`), never in the repo, CI logs or any file. The client ID is a plain Worker variable.
- **Stores nothing:** no KV, D1 or other storage. Tokens exist only in memory for the length of one request.
- **Logs no tokens:** logs hold only the route, status code and duration, never request or response bodies, query strings or auth headers.
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
- **Display:** it shows each data source with its parent database's title.
- **Saved:** `database_id` and `data_source_id` (11).
- **Empty:** if nothing is found, the picker explains how to share the database with the connection and offers "Connect again".

### 12.7 Logout

1. **Revoke:** for OAuth, the app calls `/revoke`. A failure doesn't block logout.
2. **Delete:** it deletes the Credential Manager entry.
3. **Ask:** it asks whether to keep or clear the local data, as before.

## 13. Windows packaging

- **Build:** PyInstaller in one-folder mode, which starts faster than one-file builds.
- **Installer:** Inno Setup creates `Setup.exe` with Start Menu and desktop shortcuts and an uninstaller. It checks for the WebView2 runtime and installs it if missing.
- **Data:** stays in `%APPDATA%\HabitTracker\` across reinstalls.
- **Code signing:** not used at first, so testers will see a SmartScreen warning. It can be added later as a separate build step.
- **Distribution:** a GitHub Actions workflow builds `Setup.exe` whenever a version tag (`vX.Y.Z`) is pushed and attaches it to a GitHub Release. Other users download the app from the Releases page.

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
│   └── extension-notes.md   # Phase 1 output
├── service/                 # Token service: Cloudflare Worker (TypeScript), Phase 3
│   ├── src/                 # /start, /callback, /refresh, /revoke, /health, page routes
│   ├── pages/               # home, privacy policy, terms, support (served by the Worker)
│   ├── test/                # Vitest + @cloudflare/vitest-pool-workers
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
│   ├── notion/              # auth (OAuth, pasted tokens, refresh), client, pagination, property readers
│   ├── sync/                # quick sync, full sync, schema check
│   ├── mapping/             # auto-matcher, extra fields
│   ├── validation/          # entry checks
│   ├── stats/               # daily totals, weeks, streaks, midnight split
│   └── db/                  # connections, migrator, migrations/*.sql, queries
├── ui/                      # React + Vite front end
│   ├── src/                 # bridge/, errors/, components/, tests next to the code
│   └── plugins/             # Vite plugins (Content-Security-Policy)
├── tests/                   # pytest; tests/e2e drives the real window (pytest -m gui)
└── packaging/               # PyInstaller spec, Inno Setup script
```

## 15. Build phases

Each phase ends with something the user can run and check. Every phase after Phase 0 is built on its own branch and merged into `main` through a pull request once the user approves it (see 15.2).

| Phase | Work | Done when |
|---|---|---|
| 0. Project setup | Install and verify every tool, configure Git, create the GitHub repository, and add the housekeeping files. Full checklist in 15.1. | The private GitHub repo exists with the first commit pushed, every tool reports its version, and `docs/setup.md` records them. |
| 1. Explore the extension | Read the Chrome extension at `C:\Users\LENOVO\Documents\JS\myNotionNotes` without modifying it. Document its auth flow, Notion API calls, pagination and error handling in `docs/extension-notes.md`. Propose the auth design. | The user approves the notes and the auth design. |
| 2. Scaffold | Set up the Python package with `uv`, the React/Vite UI, the pywebview window and bridge, the SQLite schema with migrations, and the `%APPDATA%` paths. Add CI (GitHub Actions on `windows-latest`: ruff, pytest, TypeScript type check, UI build), pre-commit hooks for ruff and formatting, and Dependabot for Python, npm and Actions. | The app window opens on Windows, the UI calls a test Python method, and CI passes on the pull request. |
| 3. Connect | **Before the integration exists:** write the pages in `service/pages/` and deploy them with the service. Create the "Habit Tracker" public integration (12.1) and submit it for review. Claude Code gives the user exact steps for each manual part.<br>**Token service:** build `service/` with its tests and README, and add it to CI and Dependabot. Help the user create a Cloudflare account and set the secrets, then deploy.<br>**App:** build the OAuth connect flow with the encrypted one-time hand-back (12.3), the pasted-token path for internal integration tokens and PATs (12.4), Credential Manager storage with serialized refresh (12.5), the database picker (12.6), logout (12.7), the single-instance guard, and every connect, error and outage state. Write tests for the state signing, hand-back crypto, replay and expiry rejection, refresh serialization and token storage. | The user connects through OAuth and sees their Work Log in the picker. Connecting with an internal integration token and with a PAT also works. Logout revokes and removes the token. Service and app tests pass in CI. |
| 4. Map | Build auto-matching, the review screen, extra-field selection, and missing-required-field errors. | The author's Work Log maps correctly, and a fixture schema missing an end-time column shows a clear error (covered by tests and viewable in the UI with that fixture). |
| 5. Sync | Implement full sync, quick sync, the schema check, validation, progress events, and retries. Write tests for sync and validation logic. | A fresh install syncs all entries; edits appear after relaunch; deletions disappear after full sync; every broken-entry fixture is flagged correctly, and every broken entry in Work Log (test) is flagged correctly. |
| 6. Dashboard | Build the four charts, streak logic, the midnight split, settings, and empty states. Write tests for the stats logic. | The charts match manually checked totals. |
| 7. Raw logs | Build the table with filters, red issue cells, hover explanations, and Notion links. | Every filter works, and flagged entries show the correct explanations. |
| 8. Package | Set up the PyInstaller build, the Inno Setup installer, the WebView2 check, the release workflow, and a README for other users. | `Setup.exe` downloaded from a GitHub Release installs and runs on a clean Windows machine. |

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
- **Branch protection:** where your plan supports it, protect `main` so CI must pass before merging. Phase 2 checked this: GitHub refuses both branch protection and rulesets on this private repository on the Free plan. Until the repository is public or the plan is upgraded, the rule "merge only after CI passes and the user approves" is followed by hand (see Open items, and `docs/setup.md` for the settings to apply).

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
- Notion review for the public integration: Notion's public docs say only that the Authorization URL appears after the connection is "submitted for review". The exact fields and timeline will be seen in the developer portal in Phase 3. Until the review completes, Phase 3 testing can use the pasted-token path.
- Cloudflare account: the user creates it when Phase 3 reaches the token service. Claude Code gives exact steps at that point.
- Chrome extension path: `C:\Users\LENOVO\Documents\JS\myNotionNotes`
- Branch protection on `main`: unavailable for this private repository on the current GitHub plan (checked in Phase 2). Apply the settings in `docs/setup.md` when the repository becomes public (free there) or the plan is upgraded. Until then, pull requests are merged only after CI passes and the user approves.

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
| 2026-10-18 | Phase 2: branch protection and rulesets for `main` are unavailable on this private repo on the current GitHub plan ("Upgrade to GitHub Pro or make this repository public"). The intended settings are recorded in `docs/setup.md`, to apply later. Meanwhile, merging only after green CI and the user's approval is a manual rule. |
| 2026-10-18 | Phase 2: GitHub secret scanning is unavailable on this private repo, so gitleaks scans staged changes in pre-commit and the full history in CI. CI actions are pinned to commit SHAs. End-to-end tests drive the real window in CI (`pytest -m gui`). |
