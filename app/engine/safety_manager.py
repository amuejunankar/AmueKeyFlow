"""Emergency stop, recovery and shutdown safety net."""

from __future__ import annotations

import logging
from typing import Callable

from app.engine.engine import MappingEngine
from app.services.settings_manager import SettingsManager

log = logging.getLogger(__name__)


class SafetyManager:
    """Single place that decides how the engine is shut down or revived."""

    def __init__(
        self,
        engine: MappingEngine,
        settings: SettingsManager,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._notify = notify
        self.last_reason = ""

    def emergency_stop(self, reason: str = "Emergency disable") -> None:
        self.last_reason = reason
        self._engine.emergency_stop(reason)
        if self._notify:
            self._notify(reason)

    def recover(self) -> bool:
        """Re-enable interception after an emergency stop."""
        self._settings.set("mappings_enabled", True)
        self._engine.processor.set_enabled(True)
        if self._engine.running:
            self._engine.processor.set_paused(False)
            self._engine._emergency = False
            return True
        ok = self._engine.start()
        if ok:
            self.last_reason = ""
        return ok

    def restore_normal_keyboard(self) -> None:
        """Stop interception entirely; physical keys pass through again."""
        self._engine.stop(release=True)
        self._engine.processor.set_enabled(False)
        if self._notify:
            self._notify("Keyboard interception stopped.")

    def pause_all(self) -> None:
        self._engine.processor.set_paused(True)
        self._settings.set("mappings_enabled", True)

    def shutdown(self) -> None:
        log.info("Safety shutdown: stopping engine and releasing all keys")
        self._engine.shutdown()
