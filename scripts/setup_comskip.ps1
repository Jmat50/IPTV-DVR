# Sets up tools\comskip with comskip.exe and comskip.ini.
# Usage examples:
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_comskip.ps1 -ZipPath "C:\Downloads\comskip.zip"
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_comskip.ps1 -DownloadUrl "https://example.com/comskip.zip"
param(
    [string]$ZipPath = "",
    [string]$DownloadUrl = "",
    [string]$DestDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DestDir)) {
    $DestDir = Join-Path $Root "tools\comskip"
}
elseif (-not [System.IO.Path]::IsPathRooted($DestDir)) {
    $DestDir = Join-Path $Root $DestDir
}
$DestDir = [System.IO.Path]::GetFullPath($DestDir)
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$Work = Join-Path $env:TEMP ("comskip_unpack_" + [Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Work | Out-Null

if ([string]::IsNullOrWhiteSpace($ZipPath)) {
    if ([string]::IsNullOrWhiteSpace($DownloadUrl)) {
        throw "Provide -ZipPath or -DownloadUrl to a Comskip ZIP file."
    }
    $ZipPath = Join-Path $Work "comskip.zip"
    Write-Host "Downloading Comskip zip..."
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath
}

if (-not (Test-Path $ZipPath)) {
    throw "ZIP file not found: $ZipPath"
}

Expand-Archive -Path $ZipPath -DestinationPath $Work -Force

$ComskipExe = Get-ChildItem -Path $Work -Recurse -Filter "comskip*.exe" | Select-Object -First 1
if (-not $ComskipExe) {
    throw "Could not locate comskip executable in ZIP."
}

$ComskipIni = Get-ChildItem -Path $Work -Recurse -Filter "comskip.ini" | Select-Object -First 1

Copy-Item -Force $ComskipExe.FullName (Join-Path $DestDir "comskip.exe")
if ($ComskipIni) {
    Copy-Item -Force $ComskipIni.FullName (Join-Path $DestDir "comskip.ini")
}

Remove-Item $Work -Recurse -Force
Write-Host "Installed comskip.exe to" (Join-Path $DestDir "comskip.exe")
if ($ComskipIni) {
    Write-Host "Installed comskip.ini to" (Join-Path $DestDir "comskip.ini")
}
else {
    Write-Host "No comskip.ini found in archive. Add one manually if needed."
}
