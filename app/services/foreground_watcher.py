"""Foreground application tracking used by per-app profile rules.

The watcher polls the foreground window on a timer (cheap Win32 calls) and emits
the executable name whenever the user switches to a different application.  It
ignores Amue KeyFlow itself, so a rule can be added for the app the user was
just using while the settings window has focus.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_EXCLUDED = {"amuekeyflow.exe"}

if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def supported() -> bool:
    return _IS_WINDOWS


def process_executable(pid: int) -> str:
    """Return the lowercase executable name for a process id, or ``""``."""
    if not _IS_WINDOWS or pid <= 0:
        return ""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value).lower()
    finally:
        _kernel32.CloseHandle(handle)
    return ""


def _window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def foreground_executable(exclude_pid: int = 0) -> str:
    """Executable of the foreground window, excluding our own process."""
    if not _IS_WINDOWS:
        return ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = _window_pid(hwnd)
    if not pid or pid == exclude_pid:
        return ""
    executable = process_executable(pid)
    if executable in _EXCLUDED:
        return ""
    return executable


def visible_apps(exclude_pid: int = 0) -> list[str]:
    """Executable names of apps that currently own a visible titled window."""
    if not _IS_WINDOWS:
        return []
    names: set[str] = set()

    def callback(hwnd, _lparam):  # pragma: no cover - exercised by the OS
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        pid = _window_pid(hwnd)
        if pid and pid != exclude_pid:
            executable = process_executable(pid)
            if executable and executable not in _EXCLUDED:
                names.add(executable)
        return True

    callback_ref = _WNDENUMPROC(callback)
    if not _user32.EnumWindows(callback_ref, 0):
        log.debug("EnumWindows returned no results (error %s)", ctypes.get_last_error())
    return sorted(names)


class ForegroundWatcher(QObject):
    """Poll the foreground app and report changes on the UI thread."""

    changed = Signal(str)

    def __init__(self, interval_ms: int = 900, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._last_external = ""
        self._timer = QTimer(self)
        self._timer.setInterval(max(250, int(interval_ms)))
        self._timer.timeout.connect(self.poll)

    @property
    def last_external(self) -> str:
        """The last non-KeyFlow app that had focus (used by “Add current app”)."""
        return self._last_external

    def start(self) -> None:
        if supported():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> None:
        executable = foreground_executable(os.getpid())
        if not executable or executable == self._last_external:
            return
        self._last_external = executable
        self.changed.emit(executable)

    def running_apps(self) -> list[str]:
        return visible_apps(os.getpid())
