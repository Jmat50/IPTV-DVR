# Downloads CommercialCleaner Windows release into tools\commercialcleaner\CommercialCleaner.exe
param(
    [string]$DestDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DestDir)) {
    $DestDir = Join-Path $Root "tools\commercialcleaner"
}
elseif (-not [System.IO.Path]::IsPathRooted($DestDir)) {
    $DestDir = Join-Path $Root $DestDir
}
$DestDir = [System.IO.Path]::GetFullPath($DestDir)
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$ZipUrl = "https://github.com/BillOatmanWork/CommercialCleaner-Release/releases/download/V1.0.0.0/CommercialCleaner-WIN.zip"
$Work = Join-Path $env:TEMP ("commercial_cleaner_unpack_" + [Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Zip = Join-Path $Work "commercial_cleaner.zip"

Write-Host "Downloading CommercialCleaner..."
Invoke-WebRequest -Uri $ZipUrl -OutFile $Zip
Expand-Archive -Path $Zip -DestinationPath $Work -Force

$Exe = Get-ChildItem -Path $Work -Recurse -Filter "CommercialCleaner*.exe" | Select-Object -First 1
if (-not $Exe) {
    throw "CommercialCleaner executable not found in downloaded archive."
}

$Target = Join-Path $DestDir "CommercialCleaner.exe"
Copy-Item -Force $Exe.FullName $Target
Remove-Item $Work -Recurse -Force
Write-Host "Installed:" $Target
