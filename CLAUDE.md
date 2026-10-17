# CLAUDE.md

## Project

This is a Windows desktop habit tracker. It reads the user's Notion **Work Log** database (read-only), keeps a local SQLite copy, and shows charts of time spent working. The stack is Python + pywebview for the back end and React + TypeScript + ECharts for the front end.

## Top rule

**Never consider effort or complexity** when making, changing, scaling down or phasing any part of the plan. Choose the best solution for the user and the product, never the easiest one to build. Do not rule out options, shrink features, defer work or suggest simpler alternatives because of effort, complexity or time, and do not cite them as reasons in any recommendation. Build every state: empty, loading, error and edge cases. The only exception is a cost, deadline or resource limit the user states explicitly for a specific task.

## Source of truth

**Read `PLAN.md` at the start of every session.** It is the source of truth for scope, design and build phases.

## Current phase

**Phase 0: Project setup.** Follow `PLAN.md` section 15.1 completely.

1. Ask the user to settle the decisions listed at the top of 15.1: name, visibility, license, and project folder location.
2. Run every tool check command and report the results. Ask before installing anything missing; then open a new terminal and re-check.
3. Tell the user exactly which manual steps they need to do: `gh auth login` and creating the Notion test databases. Wait until they confirm.
4. Configure Git, create the repository files, make the first commit, and push to a new private GitHub repo.
5. Apply the GitHub settings: labels, milestones, merge options, and security options.
6. Write `docs/setup.md`, summarize the result, and wait for approval.

**Next: Phase 1: Explore the Chrome extension** at `C:\Users\LENOVO\Documents\JS\myNotionNotes`.

- Read the extension. **Do not modify it.**
- Write `docs/extension-notes.md`. It should cover:
  - the auth flow, including how tokens are obtained, stored and refreshed, and whether a client secret or backend is involved;
  - every Notion API call it makes;
  - its pagination, rate-limit and error handling;
  - which pieces are worth porting to Python.
- Propose an auth design for the desktop app that fits `PLAN.md` section 12.
- Stop and wait for the user's approval.

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

To be filled in during Phase 2, covering how to install dependencies, run in development mode, run the tests, and build the installer.