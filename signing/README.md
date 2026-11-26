# Code signing

Amue KeyFlow signs two files with an Authenticode certificate:

- `dist\AmueKeyFlow\AmueKeyFlow.exe` — the application the installer copies
- `installer\output\AmueKeyFlow-<version>-Setup.exe` — the download

Inno Setup also signs the uninstaller and every temporary self-copy Setup
launches, because the signing happens inside the compile (see
`SignTool` in `installer\amue_keyflow.iss`). Signing the Setup file afterwards
by hand would leave those copies unsigned, and Windows security software can
then block Setup from starting.

Nothing about the certificate lives in this repository. It is read from
environment variables at build time.

## Supply the certificate

Either a `.pfx` file:

```powershell
$env:KEYFLOW_SIGN_PFX = "C:\keys\amue-keyflow.pfx"
$env:KEYFLOW_SIGN_PFX_PASSWORD = Read-Host -AsSecureString | ConvertFrom-SecureString -AsPlainText
```

`Get-KeyFlowSigningConfig` imports that file into
`Cert:\CurrentUser\My` for the duration of the build, signs with its
thumbprint (so the password never appears on a command line or in a log), and
removes the imported certificate again when the build ends.

Or a certificate that is already installed for the current user:

```powershell
$env:KEYFLOW_SIGN_THUMBPRINT = "0123456789ABCDEF0123456789ABCDEF01234567"
```

`certmgr.msc` → *Personal* → *Certificates* → certificate → *Details* →
*Thumbprint* shows that value.

Optional:

| Variable | Purpose |
|---|---|
| `KEYFLOW_SIGN_TIMESTAMP_URL` | RFC 3161 timestamp server, default `http://timestamp.digicert.com`. Timestamping keeps signatures valid after the certificate expires. |
| `KEYFLOW_SIGNTOOL` | Full path to `signtool.exe`. Otherwise `PATH` and the Windows SDK folders are searched. |

`signtool.exe` comes with the Windows SDK; installing the *Windows SDK
Signing Tools* component is enough.

## Build signed

```powershell
powershell -ExecutionPolicy Bypass -File build\build.ps1 -Installer
```

Nothing else changes: the script signs the executable in place, then passes
`/DSIGN` and the sign tool definition to ISCC so the installer and its
uninstaller are signed too. Every signature is verified with
`signtool verify /pa` before the build is reported as successful, so a build
can never claim to be signed when it is not.

## Build without a certificate

Leave every `KEYFLOW_SIGN_*` variable unset. The build then prints

```
== Code signing disabled: no certificate configured ==
```

and produces exactly the unsigned output it always did. Compiling the
installer by hand also stays unsigned, because the signing directives are
inside `#ifdef SIGN`:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\amue_keyflow.iss
```

Do not set only some of the variables: a `.pfx` path that does not exist, a
thumbprint that is not installed, or a certificate without a private key stops
the build with an explanation instead of silently producing an unsigned file.

## Check a build

```powershell
Get-AuthenticodeSignature dist\AmueKeyFlow\AmueKeyFlow.exe | Format-List Status, StatusMessage, SignerCertificate
Get-AuthenticodeSignature installer\output\AmueKeyFlow-1.6.2-Setup.exe | Format-List Status, StatusMessage, SignerCertificate
```

`Status` must be `Valid` and `SignerCertificate.Subject` must name the
certificate's publisher.

## What signing does and does not change

- Downloads stop showing "Windows protected your PC" / unknown publisher once
  the certificate is trusted and enough downloads have built reputation.
  SmartScreen reputation is earned per certificate; a brand-new certificate
  starts with no reputation.
- An **OV** certificate builds reputation over downloads. An **EV**
  certificate is trusted immediately.
- Signing does not change the installer's behaviour: it stays per-user
  (`PrivilegesRequired=lowest`), and `%APPDATA%\AmueKeyFlow` is still never
  touched by install or uninstall.
- Keep the private key out of the repository. `*.pfx` and `*.p12` are
  git-ignored; never commit a certificate, its password, or a log that
  contains either.
