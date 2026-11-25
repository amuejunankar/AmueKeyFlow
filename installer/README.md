# Installer

`amue_keyflow.iss` builds a per-user Inno Setup installer for Amue KeyFlow.

1. Build the executable first:

   ```powershell
   powershell -ExecutionPolicy Bypass -File build\build.ps1
   ```

2. Install [Inno Setup 6](https://jrsoftware.org/isdl.php) if it is not already installed.
3. Compile the script:

   ```powershell
   & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\amue_keyflow.iss
   ```

Setup closes a running tray instance before copying files, so upgrading in place works
even while Amue KeyFlow is running.

The installer is written to `installer\output\AmueKeyFlow-1.6.1-Setup.exe`. The script
uses directives supported by Inno Setup 6.0.5 and newer (`ArchitecturesAllowed=x64`).

It installs under `%LOCALAPPDATA%\Programs\Amue KeyFlow` (or Program Files when
elevated), adds Start Menu and optional desktop shortcuts, offers an optional
current-user startup entry, and can launch the app after installation.
Uninstalling never deletes your profiles or mappings in `%APPDATA%\AmueKeyFlow`.

## Signing

The script itself contains no certificate. Signing directives are compiled in only when
ISCC is given `/DSIGN` plus a sign tool definition:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DSIGN "/Skfwsign=<signtool command>" installer\amue_keyflow.iss
```

That is what `build\build.ps1 -Installer` does when a certificate is configured, so
building through it is the supported path:

```powershell
$env:KEYFLOW_SIGN_PFX = "C:\keys\amue-keyflow.pfx"
$env:KEYFLOW_SIGN_PFX_PASSWORD = "<certificate password>"
powershell -ExecutionPolicy Bypass -File build\build.ps1 -Installer
```

`SignTool=kfwsign` makes Inno Setup sign the Setup file *and*, with the default
`SignedUninstaller=yes`, the uninstaller and the temporary self-copies Setup launches.
Signing the compiled Setup file afterwards with signtool leaves those copies unsigned,
which security software can block, so the signing happens inside the compile.

Without `/DSIGN` — a plain ISCC compile, or any build with no certificate — the output
is unsigned and behaves exactly as before. See `signing\README.md` for the certificate
variables, timestamping and verification.
