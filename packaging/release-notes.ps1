<#
.SYNOPSIS
    Checks a release tag and writes its GitHub Release notes from CHANGELOG.md (PLAN.md 13).

.DESCRIPTION
    Refuses the release unless:
      - the tag is vX.Y.Z and X.Y.Z is the version in pyproject.toml;
      - the tagged commit is on main;
      - CHANGELOG.md has a non-empty "## [X.Y.Z] - YYYY-MM-DD" entry.
    The notes are that entry, followed by how to check the download.

.EXAMPLE
    .\packaging\release-notes.ps1 -Tag v0.1.0 -Out build\release-notes.md
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$Tag,
    [Parameter(Mandatory)] [string]$Out,
    [switch]$SkipMainCheck
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot

if ($Tag -notmatch '^v(\d+\.\d+\.\d+)$') { throw "The tag '$Tag' isn't vX.Y.Z." }
$Version = $Matches[1]
$ProjectVersion = (Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version = "([^"]+)"').Matches[0].Groups[1].Value
if ($ProjectVersion -ne $Version) {
    throw "The tag says $Version but pyproject.toml says $ProjectVersion. Update pyproject.toml (and uv.lock) on main first."
}

if (-not $SkipMainCheck) {
    git -C $Root fetch --quiet origin main
    git -C $Root merge-base --is-ancestor HEAD origin/main
    if ($LASTEXITCODE -ne 0) { throw "The tagged commit isn't on main. Releases are tagged on main only (PLAN.md 15.2)." }
}

$Lines = Get-Content (Join-Path $Root "CHANGELOG.md") -Encoding utf8
$Header = "^## \[$([regex]::Escape($Version))\] - \d{4}-\d{2}-\d{2}\s*$"
$Start = -1
for ($i = 0; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match $Header) { $Start = $i; break }
}
if ($Start -lt 0) { throw "CHANGELOG.md has no '## [$Version] - YYYY-MM-DD' entry." }
$End = $Lines.Count
for ($i = $Start + 1; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match '^## ') { $End = $i; break }
}
$Body = ($Lines[($Start + 1)..($End - 1)] -join "`n").Trim()
if (-not $Body) { throw "The CHANGELOG.md entry for $Version is empty." }

$Notes = @"
$Body

---

**Install:** download ``HabitTracker-Setup-$Version.exe`` below and run it. Windows may show a SmartScreen warning because the app isn't code-signed yet; the README explains what to do.

**Check the download (optional):** in PowerShell, ``(Get-FileHash .\HabitTracker-Setup-$Version.exe -Algorithm SHA256).Hash`` should match the hash in ``HabitTracker-Setup-$Version.exe.sha256``.
"@
New-Item -ItemType Directory -Force (Split-Path -Parent $Out) | Out-Null
[IO.File]::WriteAllText((Join-Path (Get-Location) $Out), $Notes + "`n", [Text.UTF8Encoding]::new($false))
Write-Host "Release notes for $Version written to $Out"
