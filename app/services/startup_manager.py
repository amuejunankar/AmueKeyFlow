"""Windows current-user startup integration (HKCU Run key)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.constants import APP_NAME

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AmueKeyFlow"


class StartupManager:
    """Manage an optional per-user startup entry.

    Uses ``HKCU\\...\\Run`` which never needs administrator rights.  Every call
    degrades gracefully on non-Windows platforms and when the registry is
    unavailable.
    """

    def __init__(self, executable: str | None = None, script: str | None = None) -> None:
        self._executable = executable
        self._script = script

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def is_supported() -> bool:
        return sys.platform == "win32"

    def build_command(self) -> str:
        # ``--autostart`` lets the app apply the configured startup behaviour
        # without rewriting the registry value when that setting changes.
        if getattr(sys, "frozen", False):
            exe = self._executable or sys.executable
            return f'"{exe}" --autostart'
        exe = self._executable or sys.executable
        script = self._script or str(Path(sys.argv[0]).resolve())
        # Prefer pythonw.exe so no console window flashes at logon.
        pythonw = Path(exe).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
        return f'"{exe}" "{script}" --autostart'

    def _open_key(self, access: int):
        import winreg

        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)

    # -- api ---------------------------------------------------------------
    def is_enabled(self) -> bool:
        if not self.is_supported():
            return False
        try:
            import winreg

            with self._open_key(winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
        except FileNotFoundError:
            return False
        except OSError:
            log.exception("Unable to read the startup registry value")
            return False

    def installed_command(self) -> str:
        if not self.is_supported():
            return ""
        try:
            import winreg

            with self._open_key(winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
        except OSError:
            return ""

    def enable(self) -> tuple[bool, str]:
        if not self.is_supported():
            return False, "Startup integration is only available on Windows."
        command = self.build_command()
        try:
            import winreg

            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
            if not self.is_enabled():
                return False, "The startup entry could not be verified after writing it."
            return True, "Amue KeyFlow will start with Windows."
        except OSError as exc:
            log.exception("Unable to enable startup")
            return False, f"Could not write the startup entry: {exc}"

    def disable(self) -> tuple[bool, str]:
        if not self.is_supported():
            return False, "Startup integration is only available on Windows."
        try:
            import winreg

            with self._open_key(winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
            return True, "Amue KeyFlow will no longer start with Windows."
        except FileNotFoundError:
            return True, "Startup entry was already disabled."
        except OSError as exc:
            log.exception("Unable to disable startup")
            return False, f"Could not remove the startup entry: {exc}"

    def sync(self, enabled: bool) -> tuple[bool, str]:
        """Ensure the registry matches ``enabled`` without duplicate entries."""
        current = self.is_enabled()
        if enabled and not current:
            return self.enable()
        if enabled and current:
            expected = self.build_command()
            if self.installed_command() != expected:
                return self.enable()
            return True, "Startup entry is up to date."
        if not enabled and current:
            return self.disable()
        return True, "Startup is disabled."
