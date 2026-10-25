# Changelog

All notable changes to Habit Tracker. Each version's entry becomes its GitHub Release notes.
Versions follow `MAJOR.MINOR.PATCH`; 0.x versions are test releases.

## [0.1.0] - 2026-10-25

The first test release for Windows 10 and 11.

### Added

- **Connect to Notion** with Notion sign-in, or by pasting an internal integration token or a personal access token. The app only ever reads from Notion.
- **Choose your work log** and map its columns, with sample values and automatic matching. A parent task relation maps automatically; if its linked database isn't shared with Habit Tracker, the mapping screen explains how to share it, and a column that appears later is offered on Home and in Settings.
- **Sync** your entries to this computer: a quick sync on every launch, a full sync when needed, and checks that flag entries with missing times, an end before the start, or minutes that don't match.
- **Dashboard:** daily totals, weekly trends with a 4-week average, streaks, a calendar heatmap, and a day detail view that opens each session and its parent task in Notion, with settings for the week start, streak threshold, midnight rule and overlapping sessions.
- **Raw log:** every entry in a table with filters, sorting, issue explanations, overlap markers, links to Notion, and CSV export.
- **Installer:** `Setup.exe` installs Habit Tracker for the current user without administrator rights, adds Start Menu and desktop shortcuts, and installs Microsoft Edge WebView2 Runtime if it's missing.
- **Uninstaller:** keeps your data and Notion sign-in by default; an option deletes both.
- **Privacy notices:** if a future version changes how your data is handled, it tells you before doing anything differently.
- **License:** Habit Tracker is MIT-licensed. `LICENSE.txt` and `THIRD_PARTY_NOTICES.txt` (the licenses of the bundled Python runtime, Python packages and UI packages) are installed next to the app.
