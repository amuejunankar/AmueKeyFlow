"""Capture a physical key combination for the mapping editor."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from app.engine.keyboard_hook import LowLevelKeyboardHook
from app.engine.keycodes import (
    MODIFIER_FAMILIES,
    VK_TO_KEY,
    VK_TO_MODIFIER,
    make_chord,
    normalize_mods,
)
from app.engine.mapping_processor import HookEvent

log = logging.getLogger(__name__)


class KeyRecorder:
    """Listen to the global hook and report the first non-modifier chord.

    Recording never intercepts input: the hook listener only observes events,
    so the user's typing continues to reach the foreground application while a
    combination is captured.
    """

    def __init__(self, hook: LowLevelKeyboardHook) -> None:
        self._hook = hook
        self._lock = threading.Lock()
        self._active = False
        self._mods: list[str] = []
        self._timer: threading.Timer | None = None
        self._on_captured: Callable[[dict], None] | None = None
        self._on_timeout: Callable[[], None] | None = None
        self._on_progress: Callable[[list[str]], None] | None = None
        self._last_key: tuple[int, float] | None = None
        self._timeout_s = 8.0

    # -- lifecycle ---------------------------------------------------------
    def start(
        self,
        timeout_s: float = 8.0,
        on_captured: Callable[[dict], None] | None = None,
        on_timeout: Callable[[], None] | None = None,
        on_progress: Callable[[list[str]], None] | None = None,
    ) -> bool:
        with self._lock:
            if self._active:
                return False
            if not self._hook.is_running:
                return False
            self._active = True
            self._mods = []
            self._timeout_s = max(2.0, float(timeout_s))
            self._on_captured = on_captured
            self._on_timeout = on_timeout
            self._on_progress = on_progress
            self._hook.add_listener(self._on_event)
            self._timer = threading.Timer(self._timeout_s, self._timeout)
            self._timer.daemon = True
            self._timer.start()
        return True

    def stop(self) -> None:
        with self._lock:
            self._active = False
            self._hook.remove_listener(self._on_event)
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._on_captured = None
            self._on_timeout = None
            self._on_progress = None

    @property
    def active(self) -> bool:
        return self._active

    # -- internals ---------------------------------------------------------
    def _timeout(self) -> None:
        with self._lock:
            if not self._active:
                return
            callback = self._on_timeout
        self.stop()
        if callback:
            callback()

    def _on_event(self, event: HookEvent) -> None:
        if not self._active or event.injected:
            return
        mod = VK_TO_MODIFIER.get(event.vk)
        if mod:
            token = mod[1]
            if event.key_down:
                if token not in self._mods:
                    self._mods.append(token)
            else:
                if token in self._mods:
                    self._mods.remove(token)
            progress = self._on_progress
            if progress and event.key_down:
                try:
                    progress(self._current_mods())
                except Exception:
                    pass
            return
        if not event.key_down:
            return
        key_name = VK_TO_KEY.get(event.vk)
        if key_name is None:
            return
        # Basic de-duplication: the same key repeated faster than 40 ms is noise.
        now = time.monotonic()
        if self._last_key and self._last_key[0] == event.vk and now - self._last_key[1] < 0.04:
            return
        self._last_key = (event.vk, now)
        mods = self._current_mods()
        try:
            chord = make_chord(mods, key_name)
        except ValueError:
            return
        with self._lock:
            if not self._active:
                return
            callback = self._on_captured
        self.stop()
        if callback:
            callback(chord)

    def _current_mods(self) -> list[str]:
        try:
            return normalize_mods(self._mods)
        except ValueError:
            return list(self._mods)
