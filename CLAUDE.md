# CLAUDE.md

## Project

This is a Windows desktop habit tracker. It reads the user's Notion **Work Log** database (read-only), keeps a local SQLite copy, and shows charts of time spent working. The stack is Python + pywebview for the back end and React + TypeScript + ECharts for the front end.

## Top rule

**Never consider effort or complexity** when making, changing, scaling down or phasing any part of the plan. Choose the best solution for the user and the product, never the easiest one to build. Do not rule out options, shrink features, defer work or suggest simpler alternatives because of effort, complexity or time, and do not cite them as reasons in any recommendation. Build every state: empty, loading, error and edge cases. The only exception is a cost, deadline or resource limit the user states explicitly for a specific task.

## Source of truth

**Read `PLAN.md` at the start of every session.** It is the source of truth for scope, design and build phases.

## Current phase

**Phase 0: Project setup** is complete and approved (2026-10-17).

**Phase 1: Explore the Chrome extension** is complete and approved (2026-10-18, PR #1). Its output is `docs/extension-notes.md` and the auth design in `PLAN.md` section 12.

**Phase 2: Scaffold** is complete and approved (2026-10-18, PR #2). It delivered the uv Python project, the React + TypeScript + Vite UI, the pywebview window and JS bridge (dev and normal modes), `%APPDATA%\HabitTracker\` paths, the SQLite schema with versioned migrations, redacting rotating logs, in-window error handling, and CI, pre-commit and Dependabot. There is no branch protection (decided in the Phase 2 review): never merge without the user's explicit approval.

**Current: Phase 3: Connect**, on the branch `phase-3-connect`. Scope and "Done when" are in `PLAN.md` section 15, with the auth design in section 12. Work has not started yet: wait for the user's Phase 3 instructions, then restate what you'll build and how it will be checked.

**Next: Phase 4: Map** (see `PLAN.md` section 15).

Update this section whenever a new phase begins.

## How we work

1. **Work one phase at a time,** following `PLAN.md` section 15.
2. **At the start of a phase,** create the branch `phase-N-short-name` from the latest `main` (Phase 0 commits straight to `main`). Briefly restate what you'll build and how it will be checked.
3. **During a phase,** commit in small, logical steps with clear messages, and push regularly.
4. **At the end of a phase,** open a pull request with `gh pr create` using the template. Summarize what was built, give the user exact steps to test it, then wait for approval.
5. **After approval,** squash-merge the pull request, delete the branch, pull `main`, and update the "Current phase" section of this file.
6. **Ask before departing from `PLAN.md`.** When the user approves a change, add a row to the Decisions log in `PLAN.md` and update any affected sections in the same pull request.

## Hard rules

- **Never write to Notion.** Use read-only API calls only, such as search, retrieve and query.
- **Never put the Notion token or OAuth client secret** in source code, plain-text files, logs or git. Tokens go in Windows Credential Manager via `keyring`.
- Keep `.env` files, local databases and build output in `.gitignore`.
- Never force-push `main`, and never merge a pull request without the user's approval.
- Ask before installing software or changing system or global settings.
- **Validation must never stop a sync.** Only a missing or incompatible required property may stop one (`PLAN.md` section 6.3).
- **A full sync deletes local entries only if it fetched every page successfully.**
- **Store all timestamps in UTC;** convert to local time only for display.
- **Compute durations from End − Start,** never from the logged-minutes field.

## Conventions

- **Python:** version 3.12, managed with `uv`. Use type hints throughout, `ruff` for linting and formatting, and `pytest` for tests. Use `pathlib` for paths.
- **Front end:** TypeScript in strict mode, React function components and hooks, built with Vite.
- **Platform:** development is on Windows, so give shell commands in PowerShell syntax.
- **Tests:** write tests alongside the sync, validation, mapping and stats logic as you build them.

## Commands

PowerShell, from the repository root. The installer build arrives in Phase 8.

**Install** (once per clone, and after dependency changes):

```powershell
uv sync                       # Python 3.12 venv in .venv, from uv.lock
npm --prefix ui ci            # UI packages, from ui/package-lock.json
npm --prefix service ci       # token service packages (also needed for the OAuth window tests)
uv run pre-commit install     # git hook: lint, format, type check, secret scan on commit
```

**Run:**

```powershell
uv run habit-tracker --dev            # dev mode: starts (or reuses) the Vite dev server, hot reload, inspector, diagnostics
npm --prefix ui run build             # build ui/dist, needed before normal mode
uv run habit-tracker                  # normal mode: loads ui/dist over file://
uv run habit-tracker --diagnostics    # normal mode with the diagnostics panel
uv run habit-tracker --self-check     # start up without a window, print a JSON report
```

- `npm --prefix ui run dev` starts Vite on its own; `--dev` then reuses it.
- `$env:HABIT_TRACKER_HOME = "C:\some\folder"` points the app at a different data folder than `%APPDATA%\HabitTracker` (for example a throwaway copy); `Remove-Item Env:HABIT_TRACKER_HOME` to undo.

**Test:**

```powershell
uv run pytest                 # back-end tests (excludes the window tests)
uv run pytest -m gui          # end-to-end tests that open the real window; build the UI first
uv run pytest --cov           # with coverage
npm --prefix ui test          # UI tests (Vitest)
npm --prefix service test     # token service tests (Vitest in the Workers runtime)
```

**Lint, format and type check:**

```powershell
uv run ruff check             # add --fix to apply fixes
uv run ruff format            # add --check to only report
uv run mypy
npm --prefix ui run lint
npm --prefix ui run format    # format:check to only report
npm --prefix ui run typecheck
npm --prefix service run lint
npm --prefix service run typecheck
npm --prefix service run types   # wrangler.toml and worker-configuration.d.ts agree
uv run pre-commit run --all-files   # every hook, as CI runs them
```

**Token service (`service/`, details in `docs/token-service.md`):**

```powershell
npm --prefix service run dev      # local Worker on http://127.0.0.1:8787 (copy service/.dev.vars.example to .dev.vars first)
npm --prefix service run deploy   # checks page values and tests, then deploys to https://habit-tracker.mrathour.workers.dev
```

Secrets are set only by the user, in their own terminal, with `npx wrangler secret put`. Never ask for or handle their values.

**Test overrides:** `HABIT_TRACKER_SERVICE_URL` and `HABIT_TRACKER_NOTION_URL` point the app at a local token service and a fake Notion (the end-to-end tests use them). `PYTHON_KEYRING_BACKEND` is never needed: tests force an in-memory keyring.

**Build the UI:** `npm --prefix ui run build` type-checks, then writes the single-file bundle to `ui/dist/index.html`.

**Database migrations:** add `app/db/migrations/NNNN_short_name.sql` with the next number. Never edit a migration that is on `main`.
