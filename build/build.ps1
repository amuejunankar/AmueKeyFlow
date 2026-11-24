# Build Amue KeyFlow: icon, tests, PyInstaller bundle.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File build\build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Installing dependencies ==" -ForegroundColor Cyan
python -m pip install --upgrade -r requirements-dev.txt

Write-Host "== Generating application icon ==" -ForegroundColor Cyan
python tools/make_icon.py

Write-Host "== Running automated tests ==" -ForegroundColor Cyan
python -m pytest -q

Write-Host "== Building executable ==" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean build/amue_keyflow.spec

$exe = Join-Path $root "dist\AmueKeyFlow\AmueKeyFlow.exe"
if (-not (Test-Path $exe)) {
    throw "Build failed: $exe was not created."
}
Write-Host ""
Write-Host "Executable: $exe" -ForegroundColor Green
Write-Host "Next: open installer\amue_keyflow.iss in Inno Setup 6 and compile it." -ForegroundColor Green
