<#
.SYNOPSIS
    CI only: installs Inno Setup at the version used for development (docs/setup.md), checking
    the download's SHA-256, and puts ISCC.exe on the PATH for later steps.
#>
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Keep in step with the version installed by Scoop on the development PC (docs/setup.md).
$Version = "6.7.3"
$Sha256 = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"
$Tag = "is-" + $Version.Replace(".", "_")
$Url = "https://github.com/jrsoftware/issrc/releases/download/$Tag/innosetup-$Version.exe"

$Temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$Installer = Join-Path $Temp "innosetup-$Version.exe"
$Target = Join-Path $Temp "InnoSetup"

Invoke-WebRequest $Url -OutFile $Installer -UseBasicParsing
$Actual = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLower()
if ($Actual -ne $Sha256) { throw "Inno Setup download hash $Actual doesn't match $Sha256." }

$p = Start-Process $Installer -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CURRENTUSER", "/DIR=`"$Target`"" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "The Inno Setup installer failed (exit code $($p.ExitCode))." }
if (-not (Test-Path (Join-Path $Target "ISCC.exe"))) { throw "ISCC.exe wasn't installed in $Target." }

if ($env:GITHUB_PATH) { Add-Content $env:GITHUB_PATH $Target }
Write-Host "Inno Setup $Version installed in $Target"
