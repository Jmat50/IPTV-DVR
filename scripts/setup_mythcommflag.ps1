# Installs mythcommflag into tools\mythtv\mythcommflag.exe.
# Usage examples:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_mythcommflag.ps1 -ExePath "C:\path\mythcommflag.exe"
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_mythcommflag.ps1 -ZipPath "C:\Downloads\mythtv-tools.zip"
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_mythcommflag.ps1 -DownloadUrl "https://example.com/mythcommflag.zip"
param(
    [string]$ExePath = "",
    [string]$ZipPath = "",
    [string]$DownloadUrl = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DestDir = Join-Path $Root "tools\mythtv"
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

if ([string]::IsNullOrWhiteSpace($ExePath) -and [string]::IsNullOrWhiteSpace($ZipPath) -and [string]::IsNullOrWhiteSpace($DownloadUrl)) {
    throw "Provide one of -ExePath, -ZipPath, or -DownloadUrl."
}

$Work = Join-Path $env:TEMP ("mythcommflag_setup_" + [Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Work | Out-Null

try {
    if (-not [string]::IsNullOrWhiteSpace($DownloadUrl)) {
        $downloadPath = Join-Path $Work "mythcommflag_download"
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $downloadPath
        if ($downloadPath.ToLower().EndsWith(".zip")) {
            $ZipPath = $downloadPath
        } else {
            $ExePath = $downloadPath
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($ZipPath)) {
        if (-not (Test-Path $ZipPath)) { throw "Zip file not found: $ZipPath" }
        Expand-Archive -Path $ZipPath -DestinationPath $Work -Force
        $foundExe = Get-ChildItem -Path $Work -Recurse -Filter "mythcommflag*.exe" | Select-Object -First 1
        if (-not $foundExe) {
            throw "Could not locate mythcommflag executable in ZIP."
        }
        $ExePath = $foundExe.FullName
    }

    if ([string]::IsNullOrWhiteSpace($ExePath)) {
        throw "No executable path resolved."
    }
    if (-not (Test-Path $ExePath)) {
        throw "Executable not found: $ExePath"
    }

    $Target = Join-Path $DestDir "mythcommflag.exe"
    Copy-Item -Force $ExePath $Target
    Write-Host "Installed mythcommflag to" $Target
}
finally {
    if (Test-Path $Work) {
        Remove-Item -Recurse -Force $Work
    }
}
