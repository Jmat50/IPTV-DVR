# Downloads latest Windows x64 FFmpeg (GPL) from BtbN FFmpeg-Builds into
# DestDir\ffmpeg.exe and DestDir\ffprobe.exe.
# License: FFmpeg is LGPL/GPL — see https://ffmpeg.org/legal.html and the build's README.
# Runtime: how IPTV-DVR invokes FFmpeg (Windows console protection) is documented in README.md
#   under "FFmpeg console and accidental close (Windows)".
param(
    # Default: <repo>\gui\ffmpeg
    [string]$DestDir = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DestDir)) {
    $DestDir = Join-Path $Root "gui\ffmpeg"
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
$FfmpegBin = Join-Path $Inner.FullName "bin\ffmpeg.exe"
$FfprobeBin = Join-Path $Inner.FullName "bin\ffprobe.exe"
if (-not (Test-Path $FfmpegBin)) { throw "ffmpeg.exe not found at $FfmpegBin" }
if (-not (Test-Path $FfprobeBin)) { throw "ffprobe.exe not found at $FfprobeBin" }
Copy-Item -Force $FfmpegBin (Join-Path $DestDir "ffmpeg.exe")
Copy-Item -Force $FfprobeBin (Join-Path $DestDir "ffprobe.exe")
Remove-Item $Work -Recurse -Force
Write-Host "Installed:" (Join-Path $DestDir "ffmpeg.exe")
Write-Host "Installed:" (Join-Path $DestDir "ffprobe.exe")
