# Authenticode signing helpers for Amue KeyFlow.
#
# Dot-source this file from a build script:
#   . (Join-Path $root "signing\signing.ps1")
#
# The certificate is supplied only through environment variables, so no secret
# and no key material ever lives in the repository:
#
#   KEYFLOW_SIGN_PFX            path to a .pfx code-signing certificate (recommended)
#   KEYFLOW_SIGN_PFX_PASSWORD   its password; omit when the .pfx has none
#   KEYFLOW_SIGN_THUMBPRINT     SHA-1 thumbprint of a certificate already installed
#                               in Cert:\CurrentUser\My (alternative to the .pfx)
#   KEYFLOW_SIGN_TIMESTAMP_URL  RFC 3161 timestamp server
#                               (default: http://timestamp.digicert.com)
#   KEYFLOW_SIGNTOOL            full path to signtool.exe (auto-detected otherwise)
#
# With neither a .pfx nor a thumbprint set, Get-KeyFlowSigningConfig returns
# $null and every caller builds unsigned, which is what a local build with no
# certificate needs.

$script:KeyFlowSignDescription = "Amue KeyFlow"

function Resolve-KeyFlowSignTool {
    if ($env:KEYFLOW_SIGNTOOL) {
        if (-not (Test-Path $env:KEYFLOW_SIGNTOOL)) {
            throw "KEYFLOW_SIGNTOOL points to '$env:KEYFLOW_SIGNTOOL', which does not exist."
        }
        return (Resolve-Path $env:KEYFLOW_SIGNTOOL).Path
    }

    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    # signtool ships with the Windows SDK; pick the newest x64 copy.
    $roots = @(
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"),
        (Join-Path $env:ProgramFiles "Windows Kits\10\bin"),
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\8.1\bin")
    )
    foreach ($base in $roots) {
        if (-not $base -or -not (Test-Path $base)) { continue }
        $found = Get-ChildItem -Path $base -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }

    throw "signtool.exe was not found. Install the Windows SDK signing tools, or set KEYFLOW_SIGNTOOL to its full path."
}

function Get-KeyFlowSigningConfig {
    $pfx = $env:KEYFLOW_SIGN_PFX
    $thumbprint = $env:KEYFLOW_SIGN_THUMBPRINT
    if (-not $pfx -and -not $thumbprint) { return $null }

    $timestamp = $env:KEYFLOW_SIGN_TIMESTAMP_URL
    if (-not $timestamp) { $timestamp = "http://timestamp.digicert.com" }

    $config = [pscustomobject]@{
        SignTool     = Resolve-KeyFlowSignTool
        TimestampUrl = $timestamp
        Thumbprint   = $null
        ImportedCert = $false
    }

    if ($thumbprint) {
        $normalized = ($thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
        $certificate = Get-ChildItem Cert:\CurrentUser\My |
            Where-Object { $_.Thumbprint -eq $normalized } |
            Select-Object -First 1
        if (-not $certificate) {
            throw "No certificate with thumbprint $normalized is installed in Cert:\CurrentUser\My."
        }
        if (-not $certificate.HasPrivateKey) {
            throw "The certificate $normalized has no private key in Cert:\CurrentUser\My, so it cannot sign."
        }
        $config.Thumbprint = $normalized
        return $config
    }

    if (-not (Test-Path $pfx)) {
        throw "KEYFLOW_SIGN_PFX points to '$pfx', which does not exist."
    }
    $pfxPath = (Resolve-Path $pfx).Path
    $password = $env:KEYFLOW_SIGN_PFX_PASSWORD
    if ($password) {
        $secure = ConvertTo-SecureString -String $password -AsPlainText -Force
        $imported = @(Import-PfxCertificate -FilePath $pfxPath -CertStoreLocation Cert:\CurrentUser\My -Password $secure)
    } else {
        $imported = @(Import-PfxCertificate -FilePath $pfxPath -CertStoreLocation Cert:\CurrentUser\My)
    }

    # A .pfx usually carries its issuer chain; the signing certificate is the
    # one with a private key.
    $signingCert = $imported | Where-Object { $_.HasPrivateKey } | Select-Object -First 1
    if (-not $signingCert) { $signingCert = $imported | Select-Object -First 1 }
    if (-not $signingCert) {
        throw "Importing '$pfxPath' returned no certificate."
    }

    $config.Thumbprint = $signingCert.Thumbprint
    $config.ImportedCert = $true
    return $config
}

function Invoke-KeyFlowSign {
    param(
        [Parameter(Mandatory)][pscustomobject]$Config,
        [Parameter(Mandatory)][string[]]$Files
    )

    foreach ($file in $Files) {
        if (-not (Test-Path $file)) {
            throw "Cannot sign '$file': the file does not exist."
        }
        $arguments = @(
            "sign",
            "/fd", "sha256",
            "/tr", $Config.TimestampUrl, "/td", "sha256",
            "/sha1", $Config.Thumbprint,
            "/d", $script:KeyFlowSignDescription,
            $file
        )
        & $Config.SignTool @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "signtool could not sign '$file' (exit code $LASTEXITCODE)."
        }

        & $Config.SignTool verify /pa /q $file
        if ($LASTEXITCODE -ne 0) {
            throw "The signature on '$file' did not verify (exit code $LASTEXITCODE)."
        }
        Write-Host "Signed and verified: $file" -ForegroundColor Green
    }
}

function Complete-KeyFlowSigning {
    param([pscustomobject]$Config)

    # Remove only a certificate this build imported, so an already installed
    # signing certificate is never touched.
    if ($Config -and $Config.ImportedCert -and $Config.Thumbprint) {
        $path = "Cert:\CurrentUser\My\$($Config.Thumbprint)"
        if (Test-Path $path) { Remove-Item $path -Force }
        $Config.ImportedCert = $false
    }
}

function Get-KeyFlowInnoSignToolArgument {
    <#
      Builds the ISCC `/Skfwsign=<command>` argument for the installer script.
      `/S<name>=<command>` names the sign tool, which has to match the
      `SignTool=kfwsign` directive in installer\amue_keyflow.iss. Inno Setup
      replaces $f with the quoted file to sign and $q with a quote, so the
      command is assembled with single-quoted PowerShell strings: no
      interpolation may touch those placeholders.
    #>
    param([Parameter(Mandatory)][pscustomobject]$Config)

    $tool = $Config.SignTool
    if ($tool -match '\s') { $tool = '$q' + $tool + '$q' }

    return '/Skfwsign=' + $tool +
        ' sign /fd sha256 /tr ' + $Config.TimestampUrl +
        ' /td sha256 /sha1 ' + $Config.Thumbprint +
        ' /d $qAmue KeyFlow$q $f'
}
