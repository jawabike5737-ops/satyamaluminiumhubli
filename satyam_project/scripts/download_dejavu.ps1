# Download DejaVuSans.ttf into the repository fonts/ folder
# Usage: run from the project root in PowerShell (Admin not required)

$fontsDir = Join-Path -Path $PSScriptRoot -ChildPath "..\fonts"
$fontsDir = (Resolve-Path $fontsDir).Path
if (-not (Test-Path $fontsDir)) { New-Item -ItemType Directory -Path $fontsDir | Out-Null }

$url = 'https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf'
$out = Join-Path $fontsDir 'DejaVuSans.ttf'

Write-Output "Downloading DejaVuSans.ttf to: $out"
try {
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -ErrorAction Stop
    Write-Output "Download complete."
} catch {
    Write-Error "Download failed: $_. Exception.Message"
    Write-Output "If download fails, manually download from: https://github.com/dejavu-fonts/dejavu-fonts/tree/master/ttf and place DejaVuSans.ttf into the fonts folder."
}
