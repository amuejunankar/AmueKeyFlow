# Build Amue KeyFlow: icon, tests, PyInstaller bundle, optional installer.
# Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File build\build.ps1              (executable)
#   powershell -ExecutionPolicy Bypass -File build\build.ps1 -Installer    (executable + Setup)
#
# Both outputs are Authenticode-signed when a certificate is configured through
# the KEYFLOW_SIGN_* environment variables (see signing\README.md). Without one
# the build is unsigned, exactly as before.

param(
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

. (Join-Path $root "signing\signing.ps1")

function Find-ISCC {
    $candidates = @()
    if ($env:KEYFLOW_ISCC) { $candidates += $env:KEYFLOW_ISCC }
    $candidates += @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "ISCC.exe (Inno Setup 6) was not found. Install it, or set KEYFLOW_ISCC to its full path."
}

# Resolved before the build so a broken certificate setup fails in seconds
# instead of after PyInstaller.
$signing = Get-KeyFlowSigningConfig
if ($signing) {
    Write-Host "== Code signing enabled (thumbprint $($signing.Thumbprint)) ==" -ForegroundColor Cyan
} else {
    Write-Host "== Code signing disabled: no certificate configured ==" -ForegroundColor Yellow
    Write-Host "   Set KEYFLOW_SIGN_PFX (+ KEYFLOW_SIGN_PFX_PASSWORD) or KEYFLOW_SIGN_THUMBPRINT" -ForegroundColor Yellow
    Write-Host "   to sign the executable and the installer. See signing\README.md." -ForegroundColor Yellow
}

try {
    Write-Host "== Installing dependencies ==" -ForegroundColor Cyan
    python -m pip install --upgrade -r requirements-dev.txt

    Write-Host "== Generating application icon ==" -ForegroundColor Cyan
    python tools/make_icon.py

    Write-Host "== Running automated tests ==" -ForegroundColor Cyan
    # Only this tree's tests: the published copy in release\ duplicates module names.
    python -m pytest -q tests

    Write-Host "== Building executable ==" -ForegroundColor Cyan
    python -m PyInstaller --noconfirm --clean build/amue_keyflow.spec

    $exe = Join-Path $root "dist\AmueKeyFlow\AmueKeyFlow.exe"
    if (-not (Test-Path $exe)) {
        throw "Build failed: $exe was not created."
    }

    if ($signing) {
        Write-Host "== Signing executable ==" -ForegroundColor Cyan
        Invoke-KeyFlowSign -Config $signing -Files @($exe)
    }

    Write-Host ""
    Write-Host "Executable: $exe" -ForegroundColor Green

    if ($Installer) {
        Write-Host "== Building installer ==" -ForegroundColor Cyan
        $iscc = Find-ISCC
        $isccArguments = @()
        if ($signing) {
            $isccArguments += "/DSIGN"
            $isccArguments += (Get-KeyFlowInnoSignToolArgument -Config $signing)
        }
        $isccArguments += (Join-Path $root "installer\amue_keyflow.iss")

        & $iscc @isccArguments
        if ($LASTEXITCODE -ne 0) {
            throw "ISCC failed with exit code $LASTEXITCODE."
        }

        $setup = (Get-ChildItem (Join-Path $root "installer\output") -Filter "AmueKeyFlow-*-Setup.exe" |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1)
        if (-not $setup) {
            throw "ISCC reported success but no Setup file was written to installer\output."
        }
        Write-Host ""
        Write-Host "Installer: $($setup.FullName)" -ForegroundColor Green
        if ($signing) {
            Write-Host "Both files are Authenticode-signed." -ForegroundColor Green
        } else {
            Write-Host "Unsigned build: SmartScreen will show an unknown publisher." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Next: powershell -ExecutionPolicy Bypass -File build\build.ps1 -Installer" -ForegroundColor Green
        Write-Host "      (or compile installer\amue_keyflow.iss in Inno Setup 6)" -ForegroundColor Green
    }
}
finally {
    # Removes a .pfx certificate imported for this build; an already installed
    # certificate is left alone.
    Complete-KeyFlowSigning -Config $signing
}
