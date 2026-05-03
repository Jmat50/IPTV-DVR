# Downloads latest Windows x64 FFmpeg (GPL) from BtbN FFmpeg-Builds into DestDir\ffmpeg.exe
# License: FFmpeg is LGPL/GPL — see https://ffmpeg.org/legal.html and the build's README.
param(
    # Default: <repo>\ffmpeg. For portable GUI exe use: -DestDir ".\gui\ffmpeg"
    [string]$DestDir = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DestDir)) {
    $DestDir = Join-Path $Root "ffmpeg"
}
else {
    if (-not [System.IO.Path]::IsPathRooted($DestDir)) {
        $DestDir = Join-Path $Root $DestDir
    }
    $DestDir = [System.IO.Path]::GetFullPath($DestDir)
}
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$ZipUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"
$Work = Join-Path $env:TEMP ("ffmpeg_unpack_" + [Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Zip = Join-Path $Work "ffmpeg.zip"

Write-Host "Downloading FFmpeg (may take a minute)..."
Invoke-WebRequest -Uri $ZipUrl -OutFile $Zip
Expand-Archive -Path $Zip -DestinationPath $Work -Force
$Inner = Get-ChildItem -Path $Work -Directory | Where-Object { $_.Name -like "ffmpeg-*" } | Select-Object -First 1
if (-not $Inner) { throw "Unexpected zip layout under $Work" }
$Bin = Join-Path $Inner.FullName "bin\ffmpeg.exe"
if (-not (Test-Path $Bin)) { throw "ffmpeg.exe not found at $Bin" }
Copy-Item -Force $Bin (Join-Path $DestDir "ffmpeg.exe")
Remove-Item $Work -Recurse -Force
Write-Host "Installed:" (Join-Path $DestDir "ffmpeg.exe")
