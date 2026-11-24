"""Caffeine: keep the display and the system awake while it is switched on.

``SetThreadExecutionState`` applies to the calling thread, so the flag is set and
released on the thread that owns the manager: the Qt GUI thread, which lives as
long as the application does.  Nothing here touches Qt, so the service can be
tested on its own.
"""

from __future__ import annotations

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class PowerManager:
    """Own Windows' sleep and display-timeout override for this process."""

    def __init__(self) -> None:
        self._enabled = False

    @staticmethod
    def is_supported() -> bool:
        return sys.platform == "win32"

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> tuple[bool, str]:
        if not self.is_supported():
            return False, "Caffeine is only available on Windows."
        flags = int(ES_CONTINUOUS)
        if enabled:
            flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        try:
            result = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
        except Exception as exc:  # pragma: no cover - depends on the machine
            log.exception("SetThreadExecutionState failed")
            return False, f"Caffeine could not be applied: {exc}"
        if not result:
            return False, "Windows refused to keep this computer awake."
        self._enabled = bool(enabled)
        log.info("Caffeine %s", "on" if enabled else "off")
        return True, (
            "Caffeine on — the screen stays awake until you switch it off."
            if enabled
            else "Caffeine off — Windows manages sleep again."
        )

    def release(self) -> None:
        """Drop the override (called on exit so the setting never outlives us)."""
        if self._enabled:
            self.set_enabled(False)
