<#
.SYNOPSIS
    Installs, upgrades and uninstalls a built Setup.exe and checks every step (PLAN.md 13, 15).

.DESCRIPTION
    Runs in CI on a fresh Windows runner. It uses the REAL %APPDATA%\HabitTracker folder and the
    real Credential Manager entry, and its last step deletes both, so it refuses to run on a PC
    that already has Habit Tracker data unless -Force is given (never do that on your own PC).

    Checks:
      1. A silent install puts the app in %LOCALAPPDATA%\Programs\Habit Tracker with Start Menu
         and desktop shortcuts and an uninstall entry, and the installed app passes
         --self-check and opens its window, and Windows Defender finds no threats in it.
      2. Installing again over it (an upgrade) works and replaces the program's files.
      3. The default uninstall removes the program and shortcuts but keeps the data folder and
         the Notion sign-in.
      4. Uninstalling with /DELETEDATA=1 (the uninstaller's opt-in option) deletes both, and
         reports that a pasted token can't be cancelled by the app.

.PARAMETER Setup
    The Setup.exe to test.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Setup,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
$Setup = (Resolve-Path $Setup).Path
$AppDir = Join-Path $env:LOCALAPPDATA "Programs\Habit Tracker"
$Exe = Join-Path $AppDir "HabitTracker.exe"
$DataDir = Join-Path $env:APPDATA "HabitTracker"
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Habit Tracker.lnk"
$Desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Habit Tracker.lnk"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6994A669-BBC0-4C31-915E-B0EDA46AEDCC}_is1"
$Logs = Join-Path $Root "build\installer-test"
New-Item -ItemType Directory -Force $Logs | Out-Null

if ((Test-Path $DataDir) -and -not $Force -and $env:CI -ne "true") {
    throw "$DataDir exists. This test deletes it and the saved Notion sign-in; run it only in CI or a throwaway machine."
}

function Check([bool]$Condition, [string]$What) {
    if (-not $Condition) { throw "FAILED: $What" }
    Write-Host "  ok  $What" -ForegroundColor Green
}

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

function Install([string]$Log) {
    $p = Start-Process $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$Log`"" -Wait -PassThru
    Check ($p.ExitCode -eq 0) "Setup exited with 0 (got $($p.ExitCode)); log $Log"
}

function Uninstall([string]$Log, [string[]]$Extra = @()) {
    $command = (Get-ItemProperty $UninstallKey).UninstallString.Trim('"')
    $arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$Log`"") + $Extra
    Start-Process $command -ArgumentList $arguments -Wait | Out-Null
    # The uninstaller hands over to a copy of itself in %TEMP%, so wait for its work to finish.
    $deadline = (Get-Date).AddMinutes(3)
    while (((Test-Path $UninstallKey) -or (Test-Path $Exe)) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    Start-Sleep -Seconds 2
    Check (-not (Test-Path $UninstallKey)) "the uninstall entry is gone"
}

function SignInStored() {
    Push-Location $Root
    try { return ((uv run python packaging\credential_probe.py exists) -eq "yes") }
    finally { Pop-Location }
}

Step "1. Fresh install"
Install (Join-Path $Logs "install.log")
Check (Test-Path $Exe) "the app is in $AppDir"
Check (Test-Path (Join-Path $AppDir "unins000.exe")) "the uninstaller is there"
Check (Test-Path $StartMenu) "the Start Menu shortcut exists"
Check (Test-Path $Desktop) "the desktop shortcut exists"
$Entry = Get-ItemProperty $UninstallKey
Check ($Entry.DisplayName -eq "Habit Tracker") "Installed apps lists Habit Tracker"
$Report = (& $Exe --self-check | Out-String) | ConvertFrom-Json
Check ($Report.ok -and $Report.frozen) "the installed app passes --self-check"
Check ($Entry.DisplayVersion -eq $Report.version) "the listed version ($($Entry.DisplayVersion)) is the app's"
Check ($Report.data_dir -eq $DataDir) "it uses $DataDir"

$AppLog = Join-Path $DataDir "logs\habit-tracker.log"
$Process = Start-Process $Exe -PassThru
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Milliseconds 500
    $Ready = Select-String -Path $AppLog -Pattern "The UI reported ready" -Quiet -ErrorAction SilentlyContinue
} until ($Ready -or (Get-Date) -gt $deadline)
Check ([bool]$Ready) "the installed app opens its window and the UI reports ready"
Stop-Process -Id $Process.Id -Force
Wait-Process -Id $Process.Id -ErrorAction SilentlyContinue

Step "1b. Windows Defender scan of the installed app"
$MpCmdRun = Join-Path $env:ProgramFiles "Windows Defender\MpCmdRun.exe"
if (Test-Path $MpCmdRun) {
    $Scan = & $MpCmdRun -Scan -ScanType 3 -File $AppDir -DisableRemediation | Out-String
    Write-Host $Scan.Trim()
    if ($Scan -match "found no threats") {
        Check $true "Windows Defender found no threats"
    }
    elseif ($Scan -match "found \d+ threats?") {
        throw "FAILED: Windows Defender flagged the installed app. See the scan output above."
    }
    else {
        Write-Warning "Windows Defender couldn't scan here (exit code $LASTEXITCODE); not counted as a failure."
    }
}
else {
    Write-Warning "Windows Defender isn't available on this machine; scan skipped."
}

Step "2. Upgrade in place"
$Stale = Join-Path $AppDir "_internal\stale-file-from-old-version.txt"
"old" | Set-Content $Stale
Install (Join-Path $Logs "upgrade.log")
Check (-not (Test-Path $Stale)) "files from the previous version are removed"
Check ((& $Exe --self-check | Out-String | ConvertFrom-Json).ok) "the upgraded app passes --self-check"
Check (Test-Path (Join-Path $DataDir "habit_tracker.db")) "the data folder is untouched"

Step "3. Default uninstall keeps the data and the sign-in"
Push-Location $Root
try { uv run python packaging\credential_probe.py store-internal }
finally { Pop-Location }
Check (SignInStored) "a (fake) pasted token is stored"
Uninstall (Join-Path $Logs "uninstall-keep.log")
Check (-not (Test-Path $Exe)) "the program is removed"
Check (-not (Test-Path $StartMenu)) "the Start Menu shortcut is removed"
Check (-not (Test-Path $Desktop)) "the desktop shortcut is removed"
Check (Test-Path (Join-Path $DataDir "habit_tracker.db")) "the data folder is kept"
Check (SignInStored) "the Notion sign-in is kept"

Step "4. Uninstall with the delete option removes both"
Install (Join-Path $Logs "reinstall.log")
Check (Test-Path (Join-Path $DataDir "habit_tracker.db")) "a reinstall finds the kept data"
$UninstallLog = Join-Path $Logs "uninstall-delete.log"
Uninstall $UninstallLog @("/DELETEDATA=1")
Check (-not (Test-Path $Exe)) "the program is removed"
Check (-not (Test-Path $DataDir)) "the data folder is deleted"
Check (-not (SignInStored)) "the Notion sign-in is deleted"
$LogText = Get-Content $UninstallLog -Raw
Check ($LogText -match "Cleanup finished with code 4\b") "the cleanup reported a pasted internal token (code 4)"
Check ($LogText -match "still works until you delete the internal connection") "the uninstaller explains how to cancel the token"

Write-Host "`nAll installer checks passed." -ForegroundColor Green
