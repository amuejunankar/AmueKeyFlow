"""Low level Windows keyboard hook (WH_KEYBOARD_LL) running on its own thread."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Callable, Iterable

from app.constants import INJECTION_TAG
from app.engine.keyboard_simulator import physical_modifier_tokens
from app.engine.mapping_processor import HookEvent

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10

EventHandler = Callable[[HookEvent], bool]
Listener = Callable[[HookEvent], None]


if IS_WINDOWS:
    import ctypes.wintypes as wintypes

    ULONG_PTR = ctypes.c_size_t

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallNextHookEx.restype = LRESULT
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT
    ]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
else:  # pragma: no cover
    HOOKPROC = None
    _user32 = None
    _kernel32 = None


class LowLevelKeyboardHook:
    """Install a global keyboard hook on a dedicated message-loop thread."""

    def __init__(self, handler: EventHandler) -> None:
        self._handler = handler
        self._listeners: list[Listener] = []
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hook_handle = None
        self._proc_ref = None
        self._running = threading.Event()
        self._ready = threading.Event()
        self._stopping = False
        self._error: str = ""
        self._install_time = 0.0

    # -- listeners ---------------------------------------------------------
    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    # -- state -------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running.is_set() and self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str:
        return self._error

    @property
    def uptime(self) -> float:
        return time.monotonic() - self._install_time if self._install_time else 0.0

    @staticmethod
    def is_supported() -> bool:
        return IS_WINDOWS

    # -- lifecycle ---------------------------------------------------------
    def start(self, timeout: float = 3.0) -> bool:
        if not IS_WINDOWS:
            self._error = "The keyboard hook requires Windows."
            return False
        if self.is_running:
            return True
        self._ready.clear()
        self._stopping = False
        self._error = ""
        self._thread = threading.Thread(target=self._run, name="KeyFlowHook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self._error = self._error or "The keyboard hook did not start in time."
            return False
        return self.is_running

    def stop(self, timeout: float = 3.0) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            self._clear_handle()
            self._running.clear()
            self._thread = None
            return
        self._stopping = True
        thread_id = self._thread_id
        if thread_id and _user32 is not None:
            for _ in range(20):
                if _user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0):
                    break
                time.sleep(0.01)
        thread.join(timeout)
        if thread.is_alive():
            log.warning("Keyboard hook thread did not stop in time")
        self._thread = None
        self._running.clear()
        self._install_time = 0.0

    def restart(self) -> bool:
        self.stop()
        time.sleep(0.05)
        return self.start()

    # -- internals ---------------------------------------------------------
    def _clear_handle(self) -> None:
        if self._hook_handle and _user32 is not None:
            try:
                _user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:  # pragma: no cover
                log.exception("Unhooking failed")
        self._hook_handle = None

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        try:
            module = _kernel32.GetModuleHandleW(None)
            self._proc_ref = HOOKPROC(self._proc)
            self._hook_handle = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc_ref, module, 0)
            if not self._hook_handle:
                self._error = f"SetWindowsHookEx failed (error {ctypes.get_last_error()})."
                self._ready.set()
                return
            self._install_time = time.monotonic()
            self._running.set()
            self._ready.set()

            msg = wintypes.MSG()
            # PeekMessage forces creation of this thread's message queue.
            _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            while True:
                result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:  # pragma: no cover
            self._error = str(exc)
            log.exception("Keyboard hook thread crashed")
            self._ready.set()
        finally:
            self._running.clear()
            self._clear_handle()

    def _proc(self, n_code: int, w_param: int, l_param: int):
        if n_code == HC_ACTION:
            try:
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                injected = bool(info.flags & LLKHF_INJECTED) or info.dwExtraInfo == INJECTION_TAG
                if not injected:
                    down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    event = HookEvent(
                        vk=int(info.vkCode),
                        key_down=down,
                        injected=False,
                        time=time.monotonic(),
                        extended=bool(info.flags & LLKHF_EXTENDED),
                        scan_code=int(info.scanCode),
                    )
                    for listener in tuple(self._listeners):
                        try:
                            listener(event)
                        except Exception:
                            log.exception("Keyboard listener failed")
                    if self._handler(event):
                        return 1
            except Exception:
                log.exception("Keyboard hook callback failed")
        return _user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

    # -- helpers -----------------------------------------------------------
    def seed_modifiers(self, processor) -> None:
        try:
            processor.sync_modifiers(physical_modifier_tokens())
        except Exception:  # pragma: no cover
            log.exception("Could not read the initial modifier state")


def current_modifier_tokens() -> Iterable[str]:
    return physical_modifier_tokens()
