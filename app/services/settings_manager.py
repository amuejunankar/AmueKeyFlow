"""Persistent application settings with change notification."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.constants import DEFAULT_SETTINGS
from app.database.database import Database

log = logging.getLogger(__name__)

Listener = Callable[[str, Any], None]


class SettingsManager:
    def __init__(self, database: Database) -> None:
        self._db = database
        self._values: dict[str, Any] = database.all_settings()
        self._listeners: list[Listener] = []

    # -- reads -------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        if key in self._values:
            return self._values[key]
        return DEFAULT_SETTINGS.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def all(self) -> dict[str, Any]:
        return dict(self._values)

    # -- writes ------------------------------------------------------------
    def set(self, key: str, value: Any, persist: bool = True) -> None:
        if self._values.get(key) == value:
            return
        self._values[key] = value
        if persist:
            try:
                self._db.set_setting(key, value)
            except Exception:
                log.exception("Failed to persist setting %s", key)
        self._notify(key, value)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value)

    def reset(self) -> None:
        self._db.reset_settings()
        self._values = self._db.all_settings()
        for key in list(self._values):
            self._notify(key, self._values[key])

    # -- notification ------------------------------------------------------
    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self, key: str, value: Any) -> None:
        for listener in list(self._listeners):
            try:
                listener(key, value)
            except Exception:  # pragma: no cover - a listener must not break settings
                log.exception("Settings listener failed for %s", key)
