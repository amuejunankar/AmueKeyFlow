"""Windows SendInput based output synthesis.

Every injected event carries :data:`app.constants.INJECTION_TAG` in its
``dwExtraInfo`` field.  The low level hook ignores exactly those events, which
is what prevents a mapping's output from re-triggering mappings.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Iterable

from app.constants import INJECTION_TAG
from app.engine.keycodes import (
    EXTENDED_VK,
    MODIFIER_SPECIFIC_VK,
    MODIFIER_VK,
    vk_for_key,
)

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

# --- Win32 structures -------------------------------------------------------
if IS_WINDOWS:
    import ctypes.wintypes as wintypes

    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.LockWorkStation.restype = wintypes.BOOL
else:  # pragma: no cover - development on non-Windows
    INPUT = None
    _user32 = None
    wintypes = None

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001

#: Virtual keys used for the media/Windows actions.
ACTION_VK = {
    "volumeup": 0xAF,
    "volumedown": 0xAE,
    "mute": 0xAD,
    "playpause": 0xB3,
    "nexttrack": 0xB0,
    "prevtrack": 0xB1,
}

VK_LWIN = 0x5B
VK_TAB = 0x09


def is_extended(vk: int) -> bool:
    return vk in EXTENDED_VK or vk in {0xA3, 0xA5, 0x5B, 0x5C}


def generic_modifier_vk(token: str) -> tuple[int, bool]:
    token = token.lower()
    if token in MODIFIER_SPECIFIC_VK:
        vk = MODIFIER_SPECIFIC_VK[token]
        return vk, token in {"rctrl", "ralt", "rwin"}
    vk = MODIFIER_VK.get(token, 0)
    return vk, token == "win"


class SendInputError(RuntimeError):
    """Raised when Windows refuses injected input (usually UIPI / elevation)."""


class KeyboardSimulator:
    """Synthesise keyboard input and Windows media actions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._held_keys: set[int] = set()

    # -- low level ---------------------------------------------------------
    def _send(self, events: list) -> None:
        if not IS_WINDOWS or _user32 is None:  # pragma: no cover
            raise SendInputError("Input simulation requires Windows.")
        if not events:
            return
        array = (INPUT * len(events))(*events)
        sent = _user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
        if sent != len(events):
            error = ctypes.get_last_error()
            raise SendInputError(
                f"SendInput was blocked by Windows (error {error}). "
                "If the target window runs elevated, run Amue KeyFlow as administrator."
            )

    def _key_event(self, vk: int, key_up: bool, extended: bool | None = None) -> "INPUT":
        flags = 0
        if key_up:
            flags |= KEYEVENTF_KEYUP
        if extended is None:
            extended = is_extended(vk)
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        event = INPUT()
        event.type = INPUT_KEYBOARD
        event.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=INJECTION_TAG)
        return event

    def _unicode_event(self, code: int, key_up: bool) -> "INPUT":
        flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
        event = INPUT()
        event.type = INPUT_KEYBOARD
        event.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags, time=0, dwExtraInfo=INJECTION_TAG)
        return event

    # -- primitives --------------------------------------------------------
    def key_down(self, vk: int, extended: bool | None = None) -> None:
        with self._lock:
            self._send([self._key_event(vk, False, extended)])
            self._held_keys.add(vk)

    def key_up(self, vk: int, extended: bool | None = None) -> None:
        with self._lock:
            self._send([self._key_event(vk, True, extended)])
            self._held_keys.discard(vk)

    def tap(self, vk: int, extended: bool | None = None) -> None:
        with self._lock:
            self._send([self._key_event(vk, False, extended), self._key_event(vk, True, extended)])

    def tap_key(self, name: str) -> None:
        vk = vk_for_key(name)
        if not vk:
            raise SendInputError(f"Unknown output key: {name!r}")
        self.tap(vk)

    def press_modifiers(self, tokens: Iterable[str]) -> list[tuple[int, bool]]:
        pressed: list[tuple[int, bool]] = []
        for token in tokens:
            vk, extended = generic_modifier_vk(token)
            if not vk:
                continue
            self._send([self._key_event(vk, False, extended)])
            pressed.append((vk, extended))
        return pressed

    def release_modifiers(self, pressed: Iterable[tuple[int, bool]]) -> None:
        events = [self._key_event(vk, True, ext) for vk, ext in reversed(list(pressed))]
        if events:
            self._send(events)

    # -- composite ---------------------------------------------------------
    def send_chord(self, modifiers: Iterable[str], key: str, held_modifiers: Iterable[str] = ()) -> None:
        """Type ``modifiers + key``, temporarily parking physically held modifiers."""
        key_vk = vk_for_key(key)
        if not key_vk:
            raise SendInputError(f"Unknown output key: {key!r}")
        output_mods = [str(m).lower() for m in modifiers]
        physical = [str(m).lower() for m in held_modifiers if str(m).lower() in MODIFIER_SPECIFIC_VK]

        with self._lock:
            # Park the physical modifiers so the injected chord is exactly what
            # the user configured instead of being merged with ALT/SHIFT/CTRL.
            physical_release = []
            for token in physical:
                vk, extended = generic_modifier_vk(token)
                if vk and vk != key_vk and vk not in physical_release:
                    physical_release.append((vk, extended))
            events = [self._key_event(vk, True, ext) for vk, ext in physical_release]

            mod_events: list[tuple[int, bool]] = []
            for token in output_mods:
                vk, extended = generic_modifier_vk(token)
                if not vk:
                    continue
                mod_events.append((vk, extended))
                events.append(self._key_event(vk, False, extended))

            events.append(self._key_event(key_vk, False))
            events.append(self._key_event(key_vk, True))
            for vk, extended in reversed(mod_events):
                events.append(self._key_event(vk, True, extended))
            # Restore physically held modifiers so the user's keyboard state is intact.
            for vk, extended in physical_release:
                events.append(self._key_event(vk, False, extended))
            self._send(events)

    def send_text(self, text: str) -> None:
        events: list = []
        for char in text:
            if char == "\n":
                events.append(self._key_event(0x0D, False))
                events.append(self._key_event(0x0D, True))
            elif char == "\t":
                events.append(self._key_event(VK_TAB, False))
                events.append(self._key_event(VK_TAB, True))
            elif char == "\r":
                continue
            else:
                # Encode to UTF-16 code units so characters outside the BMP are
                # typed as their surrogate pair.
                encoded = char.encode("utf-16-le")
                for index in range(0, len(encoded), 2):
                    unit = int.from_bytes(encoded[index : index + 2], "little")
                    events.append(self._unicode_event(unit, False))
                    events.append(self._unicode_event(unit, True))
            if len(events) >= 80:
                self._send(events)
                events = []
        if events:
            self._send(events)

    # -- actions -----------------------------------------------------------
    def perform_action(self, action: str) -> None:
        if action in ACTION_VK:
            self.tap(ACTION_VK[action])
            return
        if action == "lock":
            if not IS_WINDOWS or _user32 is None:  # pragma: no cover
                raise SendInputError("Locking requires Windows.")
            if not _user32.LockWorkStation():
                raise SendInputError("Windows refused the lock request.")
            return
        if action == "taskview":
            # Win+Tab: win is pressed first and released last.
            with self._lock:
                win_event = self._key_event(VK_LWIN, False, True)
                tab_down = self._key_event(VK_TAB, False)
                tab_up = self._key_event(VK_TAB, True)
                win_up = self._key_event(VK_LWIN, True, True)
                # Win+Tab must also suppress the plain Tab that follows, so the
                # sequence is built as one atomic SendInput batch.
                self._send([win_event, tab_down])
                time.sleep(0.05)
                self._send([tab_up, win_up])
            return
        if action == "showdesktop":
            with self._lock:
                self._send(
                    [
                        self._key_event(VK_LWIN, False, True),
                        self._key_event(0x44, False),
                        self._key_event(0x44, True),
                        self._key_event(VK_LWIN, True, True),
                    ]
                )
            return
        raise SendInputError(f"Unsupported Windows action: {action!r}")

    # -- held keys (toggle / hold modes) ----------------------------------
    def hold_chord(self, modifiers: Iterable[str], key: str) -> None:
        with self._lock:
            pressed: list[tuple[int, bool]] = []
            for token in modifiers:
                vk, extended = generic_modifier_vk(token)
                if vk:
                    pressed.append((vk, extended))
            events = [self._key_event(vk, False, ext) for vk, ext in pressed]
            key_vk = vk_for_key(key)
            if key_vk:
                events.append(self._key_event(key_vk, False))
                self._held_keys.add(key_vk)
            self._send(events)
            for vk, _ in pressed:
                self._held_keys.add(vk)

    def release_keys(self, vks: Iterable[int]) -> None:
        with self._lock:
            events = []
            for vk in vks:
                events.append(self._key_event(vk, True))
                self._held_keys.discard(vk)
            if events:
                try:
                    self._send(events)
                except SendInputError:
                    log.exception("Could not release injected keys")

    def release_all(self) -> None:
        """Cleanup used by emergency stop and application shutdown."""
        with self._lock:
            held = sorted(self._held_keys, key=lambda v: v != 0x10)
            self._held_keys.clear()
        if held:
            self.release_keys(held)
        for token in ("lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt", "lwin", "rwin"):
            vk = MODIFIER_SPECIFIC_VK[token]
            try:
                self._send([self._key_event(vk, True)])
            except SendInputError:
                pass


def physical_modifier_tokens() -> list[str]:
    """Read the real modifier state from Windows (used when hooking starts)."""
    if not IS_WINDOWS or _user32 is None:  # pragma: no cover
        return []
    tokens: list[str] = []
    probe = {
        "lctrl": 0xA2,
        "rctrl": 0xA3,
        "lshift": 0xA0,
        "rshift": 0xA1,
        "lalt": 0xA4,
        "ralt": 0xA5,
        "lwin": 0x5B,
        "rwin": 0x5C,
    }
    for token, vk in probe.items():
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            tokens.append(token)
    return tokens


def vk_is_down(vk: int) -> bool:
    if not IS_WINDOWS or _user32 is None:  # pragma: no cover
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)
