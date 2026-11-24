"""Non-intercepting key observer that powers the Key Tester page.

The tester installs its own low-level keyboard hook whose handler always
returns ``False``, so every key still reaches the foreground application. That
also means the tester keeps working while the mapping engine is stopped,
paused or emergency-stopped, and it sees the trigger keys the engine swallows.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import sys
import threading
from typing import Callable

from app.engine.key_layout import key_id_for_event
from app.engine.keyboard_hook import LowLevelKeyboardHook
from app.engine.mapping_processor import HookEvent

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

MAPVK_VK_TO_VSC_EX = 4

TesterListener = Callable[[HookEvent, str | None], None]

if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT
    _user32.GetKeyNameTextW.argtypes = [wintypes.LONG, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetKeyNameTextW.restype = ctypes.c_int
else:  # pragma: no cover - the tester only runs on Windows
    _user32 = None


def windows_key_name(vk: int) -> str:
    """Ask Windows for the printable name of a virtual key, e.g. ``Volume Up``.

    The scan code is derived from the virtual key because ``GetKeyNameTextW``
    names a *position*: the physical scan code of a media or vendor key can sit
    on the same position as a letter (volume up reports scan 0x30), which would
    otherwise label it as that letter.
    """
    if not IS_WINDOWS or _user32 is None:
        return ""
    try:
        mapped = int(_user32.MapVirtualKeyW(int(vk), MAPVK_VK_TO_VSC_EX))
        scan = mapped & 0xFF
        is_extended = bool(mapped & 0xE000)
        if not scan:
            return ""
        l_param = (scan << 16) | (0x01000000 if is_extended else 0)
        buffer = ctypes.create_unicode_buffer(64)
        if _user32.GetKeyNameTextW(l_param, buffer, len(buffer)) > 0:
            return buffer.value.strip()
    except Exception:  # pragma: no cover - never break key handling for a label
        log.exception("Reading a key name failed")
    return ""


class KeyboardTester:
    """Observe physical keys without ever blocking them."""

    def __init__(self) -> None:
        self._hook = LowLevelKeyboardHook(lambda event: False)
        self._listeners: list[TesterListener] = []
        self._pressed: set[str] = set()
        self._lock = threading.Lock()

    # -- listeners ---------------------------------------------------------
    def add_listener(self, listener: TesterListener) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: TesterListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    # -- state -------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._hook.is_running

    @property
    def last_error(self) -> str:
        return self._hook.last_error

    @property
    def pressed(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._pressed)

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        if self._hook.is_running:
            return True
        if not self._hook.start():
            log.warning("Key tester hook failed: %s", self._hook.last_error)
            return False
        self._hook.add_listener(self._on_event)
        return True

    def stop(self) -> None:
        self._hook.remove_listener(self._on_event)
        self._hook.stop()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._pressed.clear()

    # -- internals ---------------------------------------------------------
    def _on_event(self, event: HookEvent) -> None:
        if event.injected:
            return
        key_id = key_id_for_event(event.vk, event.scan_code, event.extended)
        if key_id:
            with self._lock:
                if event.key_down:
                    self._pressed.add(key_id)
                else:
                    self._pressed.discard(key_id)
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(event, key_id)
            except Exception:  # pragma: no cover - a listener must not stop the hook
                log.exception("Key tester listener failed")
