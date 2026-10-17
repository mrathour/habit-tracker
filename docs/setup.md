# Development setup

How this project's development machine is set up, and how to set up a new one. Commands are PowerShell. Tools are installed with [Scoop](https://scoop.sh) (see the Decisions log in `PLAN.md`).

## Installed tool versions

Checked on 2026-10-17 on Windows 10 Pro (build 21996).

| Tool | Version | Check command |
|---|---|---|
| Scoop | v0.6.0 | `scoop --version` |
| Git for Windows | 2.50.0.windows.2 | `git --version` |
| GitHub CLI | 2.102.0 | `gh --version` |
| Python | 3.12.10 | `py -3.12 --version` |
| uv | 0.11.12 | `uv --version` |
| Node.js | v24.7.0 (LTS) | `node --version` |
| npm | 11.5.1 | `npm --version` |
| WebView2 Runtime | 155.0.4283.60 | see below |
| Inno Setup | 6.7.3 (via Scoop, `iscc` on PATH) | `scoop list inno-setup`, `iscc /?` |
| VS Code (optional) | 1.142.0 | `code --version` |

WebView2 check:

```powershell
(Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}').pv
```

## Setting up a new development machine

1. **Install Scoop** by following https://scoop.sh, then add the buckets:

   ```powershell
   scoop bucket add extras
   scoop bucket add versions
   ```

2. **Install the tools:**

   ```powershell
   scoop install git gh versions/python312 uv nodejs-lts extras/inno-setup
   scoop install extras/vscode   # optional
   ```

   If the Python launcher `py` isn't available, use `python --version` to check the Python install.

3. **WebView2 Runtime.** It's preinstalled on current Windows 10 and 11. If the check above fails, install it with Microsoft's Evergreen Bootstrapper. Scoop doesn't provide it.

4. **Open a new terminal** so the PATH changes take effect, then run every check command in the table above.

5. **Configure Git** (use your GitHub no-reply email if you'd rather not publish your personal address; this machine uses a personal address by choice):

   ```powershell
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   git config --global init.defaultBranch main
   git config --global core.autocrlf false
   ```

   Line endings are controlled by `.gitattributes`, not `core.autocrlf`.

6. **Sign in to GitHub** and complete the browser sign-in:

   ```powershell
   gh auth login
   ```

   This machine uses the SSH protocol for Git operations, so an SSH key must be registered with GitHub (`ssh -T git@github.com` should greet you by username).

7. **Clone the repository:**

   ```powershell
   gh repo clone mrathour/habit-tracker
   ```

Project install, run, test and build commands are added in Phase 2 (see `CLAUDE.md` → Commands).

## Notion data for testing

Both databases have the columns ID, Name, Start Time, End Time, MinuteSpent and Parent Task.

| Database | Use | Link |
|---|---|---|
| Work Log | Real data | https://app.notion.com/p/3fc15553ce3d8099b48ecfe39046d671 |
| Work Log (test) | Manual testing | https://app.notion.com/p/3fc15553ce3d802081ecd3251a0468cd |

Broken cases in Work Log (test), checked 2026-10-17:

| Case | Present |
|---|---|
| Minutes mismatch | Yes: ID 7 (logged 148 min, Start → End is 123 min) |
| Missing end time | Not yet |
| End before start | Not yet |
| Date without a time | Not yet |
| Blank name | Not yet |

pytest fixtures cover every case, plus a schema with no end-time column, whatever the test database contains (see the Decisions log in `PLAN.md`).

## GitHub repository settings

Repository: https://github.com/mrathour/habit-tracker (private).

| Setting | State |
|---|---|
| Labels | `bug`, `enhancement`, `notion-api`, `sync`, `mapping`, `validation`, `ui`, `packaging` (GitHub's default labels are also kept) |
| Milestones | 1 to 8, one per phase (`Phase 1: Explore the extension` … `Phase 8: Package`) |
| Merge options | Squash merge only; head branches deleted automatically after merging |
| Dependabot alerts | Enabled |
| Secret scanning and push protection | Not available: GitHub rejects them for this private repository on the current plan (requires GitHub Secret Protection). Re-check when the repo becomes public, where they are free. |
| Branch protection on `main` | To be set up in Phase 2, once CI exists. Private-repo branch protection and rulesets also depend on the GitHub plan. |
