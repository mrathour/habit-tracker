# Habit Tracker

<img src="packaging/icon/app-icon.png" alt="" width="96" align="right">

A Windows app that reads the work sessions you log in a Notion database and turns them into daily totals, weekly trends, streaks and a calendar heatmap. It only ever **reads** from Notion, and your entries stay on your computer.

**Status:** test releases (0.x) for Windows 10 and 11. See [CHANGELOG.md](CHANGELOG.md) for what's in each version.

## What you need

- Windows 10 (version 1809 or later) or Windows 11, 64-bit.
- A Notion database where you log work sessions, with a start time and an end time for each entry. Other columns, such as a task name or the minutes spent, are optional.
- Microsoft Edge WebView2 Runtime. It's already on most PCs, and the installer adds it if it's missing.

## Install

1. Open the [Releases page](../../releases) and download `HabitTracker-Setup-<version>.exe` from the newest release.
2. Run it. Habit Tracker installs for your Windows account only, so it doesn't need administrator rights. It goes into `%LOCALAPPDATA%\Programs\Habit Tracker`, with shortcuts in the Start menu and, if you leave the option ticked, on the desktop.
3. Open **Habit Tracker** from the Start menu.

### "Windows protected your PC"

Habit Tracker isn't code-signed yet, so Microsoft Defender SmartScreen may stop the installer the first time with **Windows protected your PC**. To continue, choose **More info**, check that the app is `HabitTracker-Setup-<version>.exe`, then choose **Run anyway**. Only do this for a file you downloaded from this project's Releases page.

### Check the download (optional)

Each release lists a `.sha256` file next to the installer. In PowerShell, in your Downloads folder:

```powershell
(Get-FileHash .\HabitTracker-Setup-0.1.0.exe -Algorithm SHA256).Hash
```

The result should match the hash in `HabitTracker-Setup-0.1.0.exe.sha256` (letter case doesn't matter).

### If your antivirus flags Habit Tracker

Some antivirus programs flag apps they haven't seen before, especially unsigned apps built with PyInstaller, as Habit Tracker is. This is a known false positive. If it happens:

1. Make sure the installer came from this project's Releases page, and check its hash as above.
2. Look at what the antivirus reports. A **generic or heuristic** detection on a new file (names containing words like *Wacatac*, *Trojan:Win32/…!ml*, *Heur* or *Gen*) is the usual false positive.
3. With Microsoft Defender, you can [submit the file to Microsoft](https://www.microsoft.com/wdsi/filesubmission) as incorrectly detected. Microsoft reviews it and removes the detection if it's wrong. Other antivirus vendors have similar forms.
4. Until then, you can restore the file from quarantine and allow it, if you trust where it came from. If you aren't sure, don't run it, and [open an issue](../../issues) with the antivirus name and the detection name.

Code-signing the app would make these warnings less likely. It's planned before the first public release.

## Connect to Notion

When Habit Tracker opens, choose one way to connect:

- **Connect to Notion** (recommended): Notion opens in your browser. Choose your workspace, share the database you log work in, and allow access. Notion gives Habit Tracker read-only access to what you shared.
- **Use a token instead**: paste an internal integration token or a personal access token from Notion's developer portal. Use this if your workspace blocks public connections, or if you'd rather no sign-in service is involved.

Then choose your work log and check how its columns map to the app's fields. Habit Tracker copies your entries and shows the dashboard. Each time you open the app, it fetches what changed.

## Where your data is kept

- **Your entries, settings and logs** are in `%APPDATA%\HabitTracker` on your computer.
- **Your Notion sign-in** is in Windows Credential Manager, under **Windows Credentials** → **HabitTracker**.
- Nothing is sent anywhere else. The sign-in service is used only when you connect, when access is renewed, and when you disconnect. See the [privacy policy](https://habit-tracker.mrathour.workers.dev/privacy).

Reinstalling or upgrading keeps both, so you carry on where you left off.

## Updates

Habit Tracker doesn't check for new versions by itself. To update, download the newest installer from the [Releases page](../../releases) and run it. It upgrades the app in place and keeps your data. If a new version changes how your data is handled, it tells you the first time it opens, before it does anything differently.

## Uninstall

Open **Settings → Apps → Installed apps**, find **Habit Tracker**, and choose **Uninstall**. Close Habit Tracker first; the uninstaller asks you to if it's still running.

The uninstaller asks one question:

- **Leave "Also delete my Habit Tracker data and Notion sign-in" unticked** (the default) to keep your data and sign-in for a later reinstall.
- **Tick it** to remove everything: it deletes `%APPDATA%\HabitTracker` and the sign-in in Credential Manager. If you connected with Notion sign-in, it also cancels Habit Tracker's access with Notion. A pasted token can't be cancelled by the app: delete the internal connection, or revoke the personal access token, in Notion's developer portal. Nothing in Notion itself is changed.

If you uninstalled without the option and want to remove everything later, delete the `%APPDATA%\HabitTracker` folder, remove **HabitTracker** under **Windows Credentials** in Credential Manager, and remove Habit Tracker in Notion under **Settings → Connections**.

## Help

- [Support page](https://habit-tracker.mrathour.workers.dev/support): connecting, tokens, and where your data is.
- Found a bug or have an idea? [Open an issue](../../issues/new/choose). Include the app version (Settings → About this copy) and your Windows version.
- **Privacy:** [privacy policy](https://habit-tracker.mrathour.workers.dev/privacy) · **Terms:** [terms of use](https://habit-tracker.mrathour.workers.dev/terms)

## Development

Habit Tracker is Python (pywebview) with a React and TypeScript interface. Set up a development machine with [docs/setup.md](docs/setup.md). The commands to install, run, test and build are in [CLAUDE.md](CLAUDE.md#commands), and the scope and design are in [PLAN.md](PLAN.md).

To build the installer: `.\packaging\build.ps1` (details in [docs/setup.md](docs/setup.md#building-the-installer)).
