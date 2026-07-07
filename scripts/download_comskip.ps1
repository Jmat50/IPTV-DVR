# Downloads a Windows Comskip runtime bundle into gui\tools\comskip\
# (comskip.exe + comskip.ini + required sibling DLLs).
param(
    [string]$DestDir = "",
    [string]$ZipUrl = "https://kaashoek.com/files/comskip82_012.zip"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DestDir)) {
    $DestDir = Join-Path $Root "gui\tools\comskip"
}
elseif (-not [System.IO.Path]::IsPathRooted($DestDir)) {
    $DestDir = Join-Path $Root $DestDir
}
$DestDir = [System.IO.Path]::GetFullPath($DestDir)
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$Work = Join-Path $env:TEMP ("comskip_unpack_" + [Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Download = Join-Path $Work "comskip.zip"
Write-Host "Downloading Comskip from $ZipUrl ..."
Invoke-WebRequest -Uri $ZipUrl -OutFile $Download
Expand-Archive -Path $Download -DestinationPath $Work -Force

$Found = Get-ChildItem -Path $Work -Recurse -Filter "comskip.exe" | Select-Object -First 1
if (-not $Found) {
    throw "comskip.exe not found in downloaded archive"
}
$BinDir = $Found.Directory.FullName
$ExePath = Join-Path $DestDir "comskip.exe"
Copy-Item -Force $Found.FullName $ExePath

$Ini = Get-ChildItem -Path $BinDir -Filter "comskip.ini" -File | Select-Object -First 1
if ($Ini) {
    Copy-Item -Force $Ini.FullName (Join-Path $DestDir "comskip.ini")
}

Get-ChildItem -Path $BinDir -Filter "*.dll" -File |
    ForEach-Object {
        Copy-Item -Force $_.FullName (Join-Path $DestDir $_.Name)
    }

# Apply project-tuned ini when the repo ships a template.
$Template = Join-Path $Root "gui\tools\comskip\comskip.ini"
if (Test-Path $Template) {
    Copy-Item -Force $Template (Join-Path $DestDir "comskip.ini")
}

Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Installed:" $ExePath
if (Test-Path (Join-Path $DestDir "comskip.ini")) {
    Write-Host "Installed:" (Join-Path $DestDir "comskip.ini")
}
