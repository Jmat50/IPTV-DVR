# Downloads a Windows CCExtractor runtime bundle into tools\ccextractor\
# (ccextractor.exe + required sibling DLLs such as libgpac.dll).
param(
    [string]$DestDir = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DestDir)) {
    $DestDir = Join-Path $Root "gui\tools\ccextractor"
}
elseif (-not [System.IO.Path]::IsPathRooted($DestDir)) {
    $DestDir = Join-Path $Root $DestDir
}
$DestDir = [System.IO.Path]::GetFullPath($DestDir)
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$Release = Invoke-RestMethod -Uri "https://api.github.com/repos/CCExtractor/ccextractor/releases/latest"
$ZipAssets = $Release.assets | Where-Object { $_.name -match "win" -and $_.name -match "\.zip$" }
$ExeAssets = $Release.assets | Where-Object { $_.name -match "win" -and $_.name -match "\.exe$" }
$Asset = $ZipAssets | Select-Object -First 1
if (-not $Asset) {
    $Asset = $ExeAssets | Select-Object -First 1
}
if (-not $Asset) {
    throw "No Windows asset found on latest CCExtractor release"
}

$Work = Join-Path $env:TEMP ("ccextractor_unpack_" + [Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Download = Join-Path $Work $Asset.name
Write-Host "Downloading CCExtractor $($Release.tag_name)..."
Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $Download

$ExePath = Join-Path $DestDir "ccextractor.exe"
if ($Asset.name -match "\.exe$") {
    # Fallback path when only a raw executable asset is available.
    Copy-Item -Force $Download $ExePath
}
else {
    Expand-Archive -Path $Download -DestinationPath $Work -Force
    $Found = Get-ChildItem -Path $Work -Recurse -Filter "ccextractor.exe" | Select-Object -First 1
    if (-not $Found) {
        $Found = Get-ChildItem -Path $Work -Recurse -Filter "*.exe" |
            Where-Object { $_.Name -match "ccextractor" } |
            Select-Object -First 1
    }
    if (-not $Found) { throw "ccextractor.exe not found in $($Asset.name)" }
    $BinDir = $Found.Directory.FullName
    Copy-Item -Force $Found.FullName $ExePath
    # Copy all sibling DLLs needed by this CCExtractor build.
    Get-ChildItem -Path $BinDir -Filter "*.dll" -File |
        ForEach-Object {
            Copy-Item -Force $_.FullName (Join-Path $DestDir $_.Name)
        }
}

Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Installed:" $ExePath
if (Test-Path (Join-Path $DestDir "libgpac.dll")) {
    Write-Host "Installed:" (Join-Path $DestDir "libgpac.dll")
}
