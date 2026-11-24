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

The installer is written to `installer\output\AmueKeyFlow-1.1.0-Setup.exe`. The script
uses directives supported by Inno Setup 6.0.5 and newer (`ArchitecturesAllowed=x64`).

It installs under `%LOCALAPPDATA%\Programs\Amue KeyFlow` (or Program Files when
elevated), adds Start Menu and optional desktop shortcuts, offers an optional
current-user startup entry, and can launch the app after installation.
Uninstalling never deletes your profiles or mappings in `%APPDATA%\AmueKeyFlow`.
