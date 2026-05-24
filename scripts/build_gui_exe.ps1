# Backward-compatible entry point; runs the full repo build (GUI + deps + Go CLI).
# For GUI-only:  .\scripts\build_gui_exe.ps1 -SkipGo
# Prefer:         .\scripts\build.ps1
param(
    [switch]$ForceFfmpeg,
    [switch]$ForceCCExtractor,
    [switch]$SkipGo,
    [switch]$SkipGui,
    [switch]$SkipCCExtractor,
    [switch]$SkipTests
)

$BuildScript = Join-Path $PSScriptRoot "build.ps1"
if (-not (Test-Path $BuildScript)) { throw "Missing $BuildScript" }

& powershell -NoProfile -ExecutionPolicy Bypass -File $BuildScript `
    @PSBoundParameters
