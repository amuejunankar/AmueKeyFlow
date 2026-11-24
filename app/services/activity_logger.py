"""Mapping event logging that never stores typed text or unrelated keystrokes."""

from __future__ import annotations

import logging

from app.database.database import Database
from app.database.models import Mapping
from app.services.settings_manager import SettingsManager

log = logging.getLogger(__name__)


class ActivityLogger:
    """Record only what is needed to troubleshoot a mapping event.

    The configured *output text* of a Text mapping is deliberately not stored -
    only its length - so the activity history never becomes a log of what the
    mapping types into other applications.
    """

    def __init__(self, database: Database, settings: SettingsManager) -> None:
        self._db = database
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.get_bool("activity_logging", True)

    def set_enabled(self, enabled: bool) -> None:
        self._settings.set("activity_logging", bool(enabled))

    @staticmethod
    def safe_output_text(mapping: Mapping | None) -> str:
        if mapping is None:
            return ""
        if mapping.mapping_type == "text":
            text = str(mapping.output_config.get("text", ""))
            lines = text.count("\n") + 1
            return f"Text · {len(text)} characters" + (f", {lines} lines" if lines > 1 else "")
        if mapping.mapping_type == "macro":
            steps = mapping.output_config.get("steps", []) or []
            return f"Macro · {len(steps)} steps"
        return mapping.output_display

    def log(self, mapping: Mapping | None, status: str = "success", detail: str = "") -> None:
        if not self.enabled:
            return
        try:
            input_text = mapping.input_display if mapping else ""
            output_text = self.safe_output_text(mapping)
            self._db.add_activity(mapping, input_text, output_text, status=status, detail=detail)
            self._db.prune_activity(self._settings.get_int("activity_max_entries", 1000))
        except Exception:  # pragma: no cover - logging must never break the engine
            log.exception("Could not record activity")

    def entries(self, limit: int = 200, search: str = ""):
        return self._db.list_activity(limit=limit, search=search)

    def clear(self) -> None:
        self._db.clear_activity()
