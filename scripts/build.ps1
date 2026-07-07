# One-command build for IPTV-DVR (Windows).
# - Bundled FFmpeg + FFprobe (skip if already under gui\ffmpeg)
# - Bundled CCExtractor for live captions (skip if already under gui\tools\ccextractor)
# - Bundled Comskip for commercial detection (skip if already under gui\tools\comskip)
# - Go CLI: iptvrecord.exe
# - GUI: gui\iptv-gui.exe (PyInstaller onefile)
#
# Prereqs: Go toolchain, Python 3.10+ (py or python on PATH), pip, Internet for optional downloads.
# Close any running gui\iptv-gui.exe before rebuilding.
param(
    [switch]$ForceFfmpeg,
    [switch]$ForceCCExtractor,
    [switch]$ForceComskip,
    [switch]$SkipGo,
    [switch]$SkipGui,
    [switch]$SkipCCExtractor,
    [switch]$SkipComskip,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

function Ensure-Ffmpeg {
    param([switch]$Force)
    $Dest = Join-Path $Root "gui\ffmpeg"
    $Script = Join-Path $Root "scripts\download_ffmpeg.ps1"
    $Ffmpeg = Join-Path $Dest "ffmpeg.exe"
    $Ffprobe = Join-Path $Dest "ffprobe.exe"
    if (-not (Test-Path $Script)) { throw "Missing $Script" }
    if ($Force -or -not (Test-Path $Ffmpeg) -or -not (Test-Path $Ffprobe)) {
        Write-Step "Installing bundled FFmpeg..."
        & powershell -NoProfile -ExecutionPolicy Bypass -File $Script -DestDir $Dest
    }
    else {
        Write-Host "Bundled FFmpeg + FFprobe already present; skipping download."
        Write-Host "  $Ffmpeg"
        Write-Host "  $Ffprobe"
    }
}

function Test-CcextractorPresent {
    $CandidateDirs = @(
        (Join-Path $Root "gui\tools\ccextractor"),
        (Join-Path $Root "tools\ccextractor")
    )
    foreach ($dir in $CandidateDirs) {
        $exe = Join-Path $dir "ccextractor.exe"
        $gpac = Join-Path $dir "libgpac.dll"
        if ((Test-Path $exe) -and (Test-Path $gpac)) {
            return $exe
        }
    }
    return $null
}

function Ensure-Ccextractor {
    param([switch]$Force)
    $Existing = Test-CcextractorPresent
    if (-not $Force -and $null -ne $Existing) {
        Write-Host "Bundled CCExtractor already present; skipping download."
        Write-Host "  $Existing"
        return
    }
    $Script = Join-Path $Root "scripts\download_ccextractor.ps1"
    if (-not (Test-Path $Script)) { throw "Missing $Script" }
    Write-Step "Installing bundled CCExtractor..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $Script
}

function Test-ComskipPresent {
    $CandidateDirs = @(
        (Join-Path $Root "gui\tools\comskip"),
        (Join-Path $Root "tools\comskip")
    )
    foreach ($dir in $CandidateDirs) {
        $exe = Join-Path $dir "comskip.exe"
        $ini = Join-Path $dir "comskip.ini"
        if ((Test-Path $exe) -and (Test-Path $ini)) {
            return $exe
        }
    }
    return $null
}

function Ensure-Comskip {
    param([switch]$Force)
    $Existing = Test-ComskipPresent
    if (-not $Force -and $null -ne $Existing) {
        Write-Host "Bundled Comskip already present; skipping download."
        Write-Host "  $Existing"
        return
    }
    $Script = Join-Path $Root "scripts\download_comskip.ps1"
    if (-not (Test-Path $Script)) { throw "Missing $Script" }
    Write-Step "Installing bundled Comskip..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $Script
}

function Build-GoCli {
    if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
        throw "Go not found on PATH. Install Go or pass -SkipGo."
    }
    if (-not $SkipTests) {
        Write-Step "Running Go tests..."
        & go test ./...
        if ($LASTEXITCODE -ne 0) { throw "go test failed with exit code $LASTEXITCODE" }
    }
    Write-Step "Building iptvrecord.exe..."
    & go build -o (Join-Path $Root "iptvrecord.exe") ./cmd/iptvrecord
    if ($LASTEXITCODE -ne 0) { throw "go build failed with exit code $LASTEXITCODE" }
    Write-Host "OK:" (Join-Path $Root "iptvrecord.exe")
}

function Build-GuiExe {
    $Py = $null
    if (Get-Command py -ErrorAction SilentlyContinue) { $Py = "py" }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $Py = "python" }
    else { throw "Python not found. Install Python 3.10+ and ensure 'py' or 'python' is on PATH." }

    Write-Step "Installing / upgrading PyInstaller..."
    & $Py -m pip install -q --upgrade pip pyinstaller

    Write-Step "Compiling Python GUI modules..."
    & $Py -m compileall (Join-Path $Root "gui")
    if ($LASTEXITCODE -ne 0) { throw "compileall failed with exit code $LASTEXITCODE" }

    $Main = Join-Path $Root "gui\main.py"
    if (-not (Test-Path $Main)) { throw "Missing $Main" }

    $StageDist = Join-Path $Root "gui\_dist_stage"
    $StageWork = Join-Path $Root "gui\build"
    if (Test-Path $StageDist) { Remove-Item $StageDist -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $StageDist | Out-Null

    Write-Step "Building gui\iptv-gui.exe (PyInstaller)..."
    $Hidden = @(
        "paths",
        "config_store",
        "duration_parse",
        "m3u_load",
        "recorder",
        "scheduler_win",
        "job_runner",
        "caption_mode",
        "caption_worker",
        "caption_finalize",
        "comskip_mode",
        "comskip_worker",
        "comskip_merge",
        "episode_boundaries",
        "comskip_chapters",
        "comskip_finalize"
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

    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $Built = Join-Path $StageDist "iptv-gui.exe"
    if (-not (Test-Path $Built)) { throw "Build failed: $Built not found" }

    $Final = Join-Path $Root "gui\iptv-gui.exe"
    Copy-Item -Force $Built $Final
    Remove-Item $StageDist -Recurse -Force

    Write-Host "OK:" $Final
}

Write-Host "IPTV-DVR build (root: $Root)"

Ensure-Ffmpeg -Force:$ForceFfmpeg

if (-not $SkipCCExtractor) {
    Ensure-Ccextractor -Force:$ForceCCExtractor
}
else {
    Write-Host "Skipping CCExtractor download (-SkipCCExtractor)."
}

if (-not $SkipComskip) {
    Ensure-Comskip -Force:$ForceComskip
}
else {
    Write-Host "Skipping Comskip download (-SkipComskip)."
}

if (-not $SkipGo) {
    Build-GoCli
}
else {
    Write-Host "Skipping Go CLI (-SkipGo)."
}

if (-not $SkipGui) {
    Build-GuiExe
}
else {
    Write-Host "Skipping GUI (-SkipGui)."
}

Write-Step "Build complete."
$FfmpegDest = Join-Path $Root "gui\ffmpeg"
Write-Host "  FFmpeg:   $(Join-Path $FfmpegDest 'ffmpeg.exe')"
$Ccx = Test-CcextractorPresent
if ($Ccx) { Write-Host "  CCExtractor: $Ccx" }
$Csk = Test-ComskipPresent
if ($Csk) { Write-Host "  Comskip:     $Csk" }
if (-not $SkipGo) { Write-Host "  CLI:      $(Join-Path $Root 'iptvrecord.exe')" }
if (-not $SkipGui) { Write-Host "  GUI:      $(Join-Path $Root 'gui\iptv-gui.exe')" }
