<#
.SYNOPSIS
    Builds Habit Tracker's Setup.exe (PLAN.md 13): the UI, the PyInstaller app, then the
    Inno Setup installer, with checks between steps.

.DESCRIPTION
    Run from anywhere; paths are relative to the repository. Output:
        build\installer\HabitTracker-Setup-<version>[-<suffix>].exe
        build\installer\HabitTracker-Setup-<version>[-<suffix>].exe.sha256

    The built HabitTracker.exe must pass --self-check (frozen, the right version and policy,
    Windows Credential Manager, the UI and the migrations) before the installer is made.

.PARAMETER PolicyFile
    Bundle this privacy-policy file instead of app\policy.json. Used for the "newer policy"
    test build: -PolicyFile packaging\test-policy.json -Suffix policytest

.PARAMETER Suffix
    Added to the installer's file name and the build folders, so a test build never replaces
    the real one.

.PARAMETER SkipUi
    Reuse the existing ui\dist instead of building it again.

.EXAMPLE
    .\packaging\build.ps1
#>
[CmdletBinding()]
param(
    [string]$PolicyFile = "",
    [ValidatePattern('^[a-z0-9-]*$')]
    [string]$Suffix = "",
    [switch]$SkipUi
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
    function Invoke-Checked([string]$What, [scriptblock]$Command) {
        & $Command
        if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
    }

    $Version = (Select-String -Path pyproject.toml -Pattern '^version = "([^"]+)"').Matches[0].Groups[1].Value
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "pyproject.toml version '$Version' isn't X.Y.Z." }
    $Name = if ($Suffix) { "HabitTracker-Setup-$Version-$Suffix" } else { "HabitTracker-Setup-$Version" }
    $BuildDir = Join-Path $Root "build"
    $PyiDir = Join-Path $BuildDir ($(if ($Suffix) { "pyinstaller-$Suffix" } else { "pyinstaller" }))
    $AppDir = Join-Path $PyiDir "dist\HabitTracker"
    $InstallerDir = Join-Path $BuildDir "installer"
    Write-Host "Habit Tracker $Version -> $Name.exe"

    $Policy = if ($PolicyFile) { (Resolve-Path $PolicyFile).Path } else { Join-Path $Root "app\policy.json" }
    $ExpectedPolicy = (Get-Content $Policy -Raw | ConvertFrom-Json).version

    if (-not $SkipUi) {
        Step "Building the UI"
        Invoke-Checked "The UI build" { npm --prefix ui run build }
    }

    Step "Building the app with PyInstaller"
    $env:HABIT_TRACKER_POLICY_FILE = $Policy
    try {
        Invoke-Checked "PyInstaller" {
            uv run --group build pyinstaller packaging\habit_tracker.spec --noconfirm --clean `
                --distpath (Join-Path $PyiDir "dist") --workpath (Join-Path $PyiDir "work")
        }
    }
    finally { Remove-Item Env:HABIT_TRACKER_POLICY_FILE -ErrorAction SilentlyContinue }

    Step "Checking the built app (--self-check)"
    $CheckHome = Join-Path $PyiDir "self-check-home"
    Remove-Item $CheckHome -Recurse -Force -ErrorAction SilentlyContinue
    $env:HABIT_TRACKER_HOME = $CheckHome
    try {
        # Piping makes PowerShell wait for the windowed exe and collect what it prints.
        $Output = & (Join-Path $AppDir "HabitTracker.exe") --self-check | Out-String
        $ExitCode = $LASTEXITCODE
    }
    finally { Remove-Item Env:HABIT_TRACKER_HOME -ErrorAction SilentlyContinue }
    Write-Host $Output
    if ($ExitCode -ne 0) { throw "The built app's self-check failed (exit code $ExitCode)." }
    $Report = $Output | ConvertFrom-Json
    $Problems = @()
    if (-not $Report.ok) { $Problems += "it reported a problem" }
    if (-not $Report.frozen) { $Problems += "it isn't the frozen build" }
    if ($Report.version -ne $Version) { $Problems += "version $($Report.version), expected $Version" }
    if ($Report.policy_version -ne $ExpectedPolicy) { $Problems += "policy $($Report.policy_version), expected $ExpectedPolicy" }
    if ($Report.credential_store -ne "keyring.backends.Windows.WinVaultKeyring") { $Problems += "credential store $($Report.credential_store)" }
    if ($Report.schema_version -lt 1) { $Problems += "no database migrations" }
    if (-not ($Report.ui_url -like "file:///*/_internal/ui/dist/index.html")) { $Problems += "UI at $($Report.ui_url)" }
    if ($Problems) { throw "The built app isn't right: $($Problems -join '; ')." }
    Remove-Item $CheckHome -Recurse -Force

    Step "Writing the license and third-party notices"
    $NoticesDir = Join-Path $PyiDir "notices"
    New-Item -ItemType Directory -Force $NoticesDir | Out-Null
    Copy-Item (Join-Path $Root "LICENSE") (Join-Path $NoticesDir "LICENSE.txt")
    Invoke-Checked "The third-party notices" {
        uv run --group build python packaging\third_party_notices.py (Join-Path $NoticesDir "THIRD_PARTY_NOTICES.txt")
    }

    Step "Getting Microsoft's WebView2 bootstrapper"
    $Bootstrapper = Join-Path $BuildDir "webview2\MicrosoftEdgeWebview2Setup.exe"
    if (-not (Test-Path $Bootstrapper)) {
        New-Item -ItemType Directory -Force (Split-Path $Bootstrapper) | Out-Null
        Invoke-WebRequest "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $Bootstrapper -UseBasicParsing
    }
    $Signature = Get-AuthenticodeSignature $Bootstrapper
    if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") {
        Remove-Item $Bootstrapper -Force
        throw "The WebView2 bootstrapper's signature isn't a valid Microsoft one ($($Signature.Status)); deleted it."
    }
    Write-Host "Signed by: $($Signature.SignerCertificate.Subject)"

    Step "Building the installer with Inno Setup"
    $Iscc = @(
        (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Join-Path $env:USERPROFILE "scoop\apps\inno-setup\current\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) wasn't found. Install it: scoop install extras/inno-setup" }
    New-Item -ItemType Directory -Force $InstallerDir | Out-Null
    Invoke-Checked "Inno Setup" {
        & $Iscc /Qp "/DAppVersion=$Version" "/DSourceDir=$AppDir" "/DWebView2Bootstrapper=$Bootstrapper" "/DNoticesDir=$NoticesDir" `
            "/DOutputDir=$InstallerDir" "/DOutputName=$Name" packaging\HabitTracker.iss
    }

    $Setup = Join-Path $InstallerDir "$Name.exe"
    $Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
    # One LF-terminated line, so `sha256sum -c` works as well as Get-FileHash.
    [System.IO.File]::WriteAllText("$Setup.sha256", "$Hash  $Name.exe`n", [System.Text.Encoding]::ASCII)
    Step "Done"
    Write-Host "$Setup"
    Write-Host ("{0:N1} MB, SHA-256 {1}" -f ((Get-Item $Setup).Length / 1MB), $Hash)
}
finally {
    Pop-Location
}
