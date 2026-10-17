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
- Notion login and Work Log database selection
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
| Duration mismatch | Logged minutes differs from (End − Start) by more than 1 minute. Checked only when Logged minutes is mapped and has a value. | Shown as a red cell |
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

- **Pagination:** pages of 100 using Notion's `start_cursor`.
- **Rate limits:** stay under about 3 requests per second. On HTTP 429, wait for the `Retry-After` time and retry. Retry temporary network and server errors with backoff.
- **Threading:** syncs run on a background thread. The UI receives progress events (pages fetched, entries added, updated or removed) and stays responsive.
- **States the UI shows:** not yet synced; quick sync in progress (subtle indicator); full sync in progress (progress bar); completed with a summary; failed with a clear reason and a retry button; offline, where the app shows local data and a note that sync was skipped.
- **Time zones:** all timestamps are stored in UTC and shown in the computer's local time zone.

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
| Notion API | `notion-client`; auth and helpers ported from the author's Chrome extension |
| Local database | built-in `sqlite3` |
| Token storage | `keyring` (Windows Credential Manager) |
| Dependencies | `uv` |
| Tests and linting | `pytest`, `ruff` |

**Front end:** React + TypeScript built with Vite, Apache ECharts for charts, and TanStack Table for the raw log. The built front end is bundled as static files.

**Bridge:** pywebview's JS API. The UI calls Python methods directly, for example `window.pywebview.api.full_sync()`, and Python pushes sync progress to the UI. There is no local web server.

## 11. Local data model (SQLite)

The database file lives at `%APPDATA%\HabitTracker\habit_tracker.db`.

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

**`settings`** is a key–value table (`key TEXT PRIMARY KEY, value TEXT` holding JSON). Its keys are: `database_id`, `database_title`, `mapping` (app field → property ID, plus the list of extra fields), `streak_threshold_minutes`, `week_start`, `midnight_rule`, `last_successful_sync`, `last_full_sync`, and `schema_version`.

Notion page links are built when displayed: `https://www.notion.so/<page id without dashes>`.

## 12. Authentication

The final design will be decided in **Phase 1**, after studying how the author's Chrome extension authenticates with Notion.

- **Goal:** support other users connecting their own workspaces, which means a public Notion integration with OAuth.
- **Constraint:** the OAuth client secret must not be embedded in the distributed app. The options are a small token-exchange service, or another approach the extension already uses.
- **Permissions:** read content only.
- **Token storage:** always in Windows Credential Manager via `keyring`; never in plain files or logs.
- **Logout** removes the token. The user chooses whether to keep or clear the local data.

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
├── .github/
│   ├── ISSUE_TEMPLATE/      # bug report, feature request
│   ├── pull_request_template.md
│   ├── dependabot.yml       # Phase 2
│   └── workflows/           # CI (Phase 2), release (Phase 8)
├── docs/
│   ├── setup.md             # Phase 0 output: tools, versions, new-machine setup
│   └── extension-notes.md   # Phase 1 output
├── app/                     # Python back end
│   ├── main.py              # pywebview window + JS bridge
│   ├── notion/              # auth, client, pagination
│   ├── sync/                # quick sync, full sync, schema check
│   ├── mapping/             # auto-matcher, extra fields
│   ├── validation/          # entry checks
│   ├── stats/               # daily totals, weeks, streaks, midnight split
│   └── db/                  # schema, migrations, queries
├── ui/                      # React + Vite front end
│   └── src/
├── tests/
└── packaging/               # PyInstaller spec, Inno Setup script
```

## 15. Build phases

Each phase ends with something the user can run and check. Every phase after Phase 0 is built on its own branch and merged into `main` through a pull request once the user approves it (see 15.2).

| Phase | Work | Done when |
|---|---|---|
| 0. Project setup | Install and verify every tool, configure Git, create the GitHub repository, and add the housekeeping files. Full checklist in 15.1. | The private GitHub repo exists with the first commit pushed, every tool reports its version, and `docs/setup.md` records them. |
| 1. Explore the extension | Read the Chrome extension at `C:\Users\LENOVO\Documents\JS\myNotionNotes` without modifying it. Document its auth flow, Notion API calls, pagination and error handling in `docs/extension-notes.md`. Propose the auth design. | The user approves the notes and the auth design. |
| 2. Scaffold | Set up the Python package with `uv`, the React/Vite UI, the pywebview window and bridge, the SQLite schema with migrations, and the `%APPDATA%` paths. Add CI (GitHub Actions on `windows-latest`: ruff, pytest, TypeScript type check, UI build), pre-commit hooks for ruff and formatting, and Dependabot for Python, npm and Actions. | The app window opens on Windows, the UI calls a test Python method, and CI passes on the pull request. |
| 3. Connect | Build Notion login, token storage, logout, and the database picker. | The user logs in and sees their Work Log in the picker. |
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
- **Branch protection:** where your plan supports it, protect `main` so CI must pass before merging (enabled once CI exists in Phase 2).

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

- Auth design: decided in Phase 1.
- License: undecided. It must be chosen before the repository or app is shared publicly.
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