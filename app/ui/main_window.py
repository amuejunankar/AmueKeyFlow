"""Application shell: frameless window, sidebar, top bar and page stack."""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QRadialGradient, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from app.ui.activity import ActivityPage
from app.ui.dashboard import DashboardPage
from app.ui.icons import app_icon
from app.ui.key_mapper import KeyMapperPage
from app.ui.key_tester import KeyTesterPage
from app.ui.profiles import ProfilesPage
from app.ui.settings import SettingsPage
from app.ui.sidebar import Sidebar
from app.ui.theme import color, palette
from app.ui.topbar import TopBar
from app.ui.voice_fx import VoiceFxPage

log = logging.getLogger(__name__)

PAGE_ORDER = ["dashboard", "mapper", "tester", "voice", "profiles", "activity", "settings"]


class MainWindow(QWidget):
    def __init__(self, controller):
        super().__init__(None)
        self.controller = controller
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle("Amue KeyFlow")
        self.setWindowIcon(app_icon(128))
        self.setMinimumSize(1120, 700)
        self.resize(1360, 860)
        self._allow_close = False
        self._tray_hint_shown = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.navigated.connect(self.navigate)
        root.addWidget(self.sidebar)

        content = QWidget()
        content.setAttribute(Qt.WA_StyledBackground, False)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.topbar = TopBar()
        self.topbar.search_requested.connect(self.controller.open_search)
        self.topbar.mappings_toggled.connect(self.controller.set_mappings_enabled)
        self.topbar.pause_clicked.connect(self.controller.toggle_pause)
        self.topbar.minimize_clicked.connect(self.showMinimized)
        self.topbar.maximize_clicked.connect(self.toggle_maximized)
        self.topbar.close_clicked.connect(self.controller.request_close)
        content_layout.addWidget(self.topbar)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(controller),
            "mapper": KeyMapperPage(controller),
            "tester": KeyTesterPage(controller),
            "voice": VoiceFxPage(controller),
            "profiles": ProfilesPage(controller),
            "activity": ActivityPage(controller),
            "settings": SettingsPage(controller),
        }
        for key in PAGE_ORDER:
            self.stack.addWidget(self.pages[key])
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        self.current_page_key = "dashboard"
        self.navigate("dashboard")

        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.controller.open_search)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.controller.create_mapping)
        QShortcut(QKeySequence("Ctrl+Shift+P"), self, activated=self.controller.toggle_pause)

    # -- navigation --------------------------------------------------------
    def navigate(self, key: str) -> None:
        if key not in self.pages:
            return
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.current_page_key = key
        self.sidebar.set_active(key)
        self.topbar.set_page(getattr(page, "title", ""), getattr(page, "subtitle", ""))
        try:
            page.on_shown()
        except Exception:  # pragma: no cover
            log.exception("Page refresh failed for %s", key)

    def refresh_current_page(self) -> None:
        page = self.pages.get(self.current_page_key)
        if page is not None:
            try:
                page.refresh()
            except Exception:  # pragma: no cover
                log.exception("Refreshing %s failed", self.current_page_key)
        status = self.controller.engine.status()
        self.sidebar.set_status(status["running"], status["enabled"], status["paused"], status["emergency"])
        self.topbar.set_mappings_enabled(status["enabled"])
        self.topbar.set_paused(status["paused"])
        self.topbar.set_maximized(bool(self.windowState() & Qt.WindowMaximized))

    def refresh_all_pages(self) -> None:
        for key, page in self.pages.items():
            if key == self.current_page_key:
                continue
            try:
                page.refresh()
            except Exception:  # pragma: no cover
                log.exception("Refreshing %s failed", key)
        self.refresh_current_page()

    # -- window ------------------------------------------------------------
    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.topbar.set_maximized(self.isMaximized())

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self.topbar.set_maximized(self.isMaximized())

    def closeEvent(self, event):  # noqa: N802
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.controller.request_close()

    def force_close(self) -> None:
        self._allow_close = True
        self.close()

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor(p["bg"]))
        gradient.setColorAt(0.55, QColor(p["bg2"]))
        gradient.setColorAt(1.0, QColor(p["bg3"]))
        painter.fillRect(rect, gradient)

        accent = QColor(p["accent"]["primary"])
        glow = QRadialGradient(QPointF(rect.width() * 0.18, -rect.height() * 0.1), rect.height() * 0.75)
        glow.setColorAt(0.0, color(accent.name(), 52 if p["is_dark"] else 24))
        glow.setColorAt(1.0, color(accent.name(), 0))
        painter.fillRect(rect, glow)

        cyan = QRadialGradient(QPointF(rect.width() * 0.98, rect.height() * 0.95), rect.height() * 0.7)
        cyan.setColorAt(0.0, color("#2DD4BF", 34 if p["is_dark"] else 16))
        cyan.setColorAt(1.0, color("#2DD4BF", 0))
        painter.fillRect(rect, cyan)
        painter.end()

    # -- frameless resizing ------------------------------------------------
    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform == "win32" and event_type == b"windows_generic_MSG" and not self.isMaximized():
            try:
                from ctypes import wintypes

                class _MSG(ctypes.Structure):
                    _fields_ = [
                        ("hWnd", wintypes.HWND),
                        ("message", wintypes.UINT),
                        ("wParam", ctypes.c_size_t),
                        ("lParam", ctypes.c_ssize_t),
                        ("time", wintypes.DWORD),
                        ("pt_x", wintypes.LONG),
                        ("pt_y", wintypes.LONG),
                    ]

                msg = _MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    geo = self.frameGeometry()
                    border = 7
                    left = abs(x - geo.left()) <= border
                    right = abs(x - geo.right()) <= border
                    top = abs(y - geo.top()) <= border
                    bottom = abs(y - geo.bottom()) <= border
                    if top and left:
                        return True, 13
                    if top and right:
                        return True, 14
                    if bottom and left:
                        return True, 16
                    if bottom and right:
                        return True, 17
                    if left:
                        return True, 10
                    if right:
                        return True, 11
                    if top:
                        return True, 12
                    if bottom:
                        return True, 15
            except Exception:  # pragma: no cover - never break window messages
                pass
        return super().nativeEvent(event_type, message)
