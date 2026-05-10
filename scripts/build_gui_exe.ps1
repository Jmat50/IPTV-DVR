# Build standalone Windows GUI: gui\iptv-gui.exe (PyInstaller onefile + windowed).
# This script ensures required runtime dependencies are present:
# - gui\ffmpeg\ffmpeg.exe + gui\ffmpeg\ffprobe.exe
# - tools\mythtv\mythcommflag.exe
# It skips each install when already present unless force switches are passed.
# Prereqs: Python 3.10+ on PATH (py launcher or python), pip, Internet for pip/pyinstaller and FFmpeg download.
#
# Close any running copy of gui\iptv-gui.exe (or an older gui\iptv-recorder.exe) before rebuilding.
param(
    [switch]$ForceFfmpeg,
    [switch]$ForceMythCommflag,
    [string]$MythCommflagExePath = "",
    [string]$MythCommflagZipPath = "",
    [string]$MythCommflagDownloadUrl = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Py = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Py = "python" }
else { throw "Python not found. Install Python 3.10+ and ensure 'py' or 'python' is on PATH." }

Write-Host "Installing / upgrading PyInstaller..."
& $Py -m pip install -q --upgrade pip pyinstaller

$FfmpegDest = Join-Path $Root "gui\ffmpeg"
$FfmpegScript = Join-Path $Root "scripts\download_ffmpeg.ps1"
if (-not (Test-Path $FfmpegScript)) { throw "Missing $FfmpegScript" }
$BundledFfmpegExe = Join-Path $FfmpegDest "ffmpeg.exe"
$BundledFfprobeExe = Join-Path $FfmpegDest "ffprobe.exe"
if ($ForceFfmpeg -or -not (Test-Path $BundledFfmpegExe) -or -not (Test-Path $BundledFfprobeExe)) {
    Write-Host "Installing / refreshing bundled FFmpeg..."
    powershell -NoProfile -ExecutionPolicy Bypass -File $FfmpegScript -DestDir $FfmpegDest
}
else {
    Write-Host "Bundled FFmpeg + FFprobe already present; skipping download."
    Write-Host " - " $BundledFfmpegExe
    Write-Host " - " $BundledFfprobeExe
}

$MythCommflagExe = Join-Path $Root "tools\mythtv\mythcommflag.exe"
$MythCommflagScript = Join-Path $Root "scripts\setup_mythcommflag.ps1"
if (-not (Test-Path $MythCommflagScript)) { throw "Missing $MythCommflagScript" }
if ($ForceMythCommflag -or -not (Test-Path $MythCommflagExe)) {
    Write-Host "Installing / refreshing mythcommflag..."
    $MythArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $MythCommflagScript)
    if (-not [string]::IsNullOrWhiteSpace($MythCommflagExePath)) {
        $MythArgs += @("-ExePath", $MythCommflagExePath)
    }
    elseif (-not [string]::IsNullOrWhiteSpace($MythCommflagZipPath)) {
        $MythArgs += @("-ZipPath", $MythCommflagZipPath)
    }
    elseif (-not [string]::IsNullOrWhiteSpace($MythCommflagDownloadUrl)) {
        $MythArgs += @("-DownloadUrl", $MythCommflagDownloadUrl)
    }
    else {
        throw "mythcommflag is missing. Provide -MythCommflagExePath <exe>, -MythCommflagZipPath <zip>, or -MythCommflagDownloadUrl <url>."
    }
    powershell @MythArgs
}
else {
    Write-Host "mythcommflag already present; skipping install:" $MythCommflagExe
}

$Main = Join-Path $Root "gui\main.py"
if (-not (Test-Path $Main)) { throw "Missing $Main" }

$StageDist = Join-Path $Root "gui\_dist_stage"
$StageWork = Join-Path $Root "gui\build"
if (Test-Path $StageDist) { Remove-Item $StageDist -Recurse -Force }
New-Item -ItemType Directory -Force -Path $StageDist | Out-Null

Write-Host "Building (staging)..."
$Hidden = @(
    "paths",
    "config_store",
    "duration_parse",
    "m3u_load",
    "recorder",
    "scheduler_win",
    "job_runner",
    "postprocess"
)
$HiddenArgs = @()
foreach ($m in $Hidden) { $HiddenArgs += "--hidden-import"; $HiddenArgs += $m }

& $Py -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name iptv-gui `
    --distpath $StageDist `
    --workpath $StageWork `
    --specpath gui `
    --paths (Join-Path $Root "gui") `
    @HiddenArgs `
    $Main

$Built = Join-Path $StageDist "iptv-gui.exe"
if (-not (Test-Path $Built)) { throw "Build failed: $Built not found" }

$Final = Join-Path $Root "gui\iptv-gui.exe"
Copy-Item -Force $Built $Final
Remove-Item $StageDist -Recurse -Force

Write-Host "OK:" $Final
Write-Host "Bundled FFmpeg:" (Join-Path $FfmpegDest "ffmpeg.exe")
Write-Host "Bundled FFprobe:" (Join-Path $FfmpegDest "ffprobe.exe")
