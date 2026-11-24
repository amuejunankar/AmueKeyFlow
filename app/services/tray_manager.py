"""System tray icon, status colours and context menu."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.constants import APP_NAME
from app.ui.icons import app_icon

log = logging.getLogger(__name__)


def status_icon(base: QIcon, dot_color: str) -> QIcon:
    pixmap = base.pixmap(64, 64)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QColor(10, 12, 24, 200))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(38, 38, 24, 24)
    painter.setBrush(QColor(dot_color))
    painter.drawEllipse(42, 42, 16, 16)
    painter.end()
    return QIcon(pixmap)


class TrayManager(QObject):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.icon = app_icon(128)
        self.tray = QSystemTrayIcon(status_icon(self.icon, "#F5B544"), self)
        self.tray.setToolTip(f"{APP_NAME} — starting…")

        self.menu = QMenu()
        self.menu.setStyleSheet(self._menu_style())
        self.open_action = QAction(f"Open {APP_NAME}", self.menu)
        self.open_action.triggered.connect(self.controller.show_window)
        self.menu.addAction(self.open_action)
        self.menu.addSeparator()

        self.enable_action = QAction("Enable mappings", self.menu)
        self.enable_action.triggered.connect(lambda: self.controller.set_mappings_enabled(True))
        self.menu.addAction(self.enable_action)
        self.disable_action = QAction("Disable mappings", self.menu)
        self.disable_action.triggered.connect(lambda: self.controller.set_mappings_enabled(False))
        self.menu.addAction(self.disable_action)
        self.pause_action = QAction("Pause mappings", self.menu)
        self.pause_action.triggered.connect(lambda: self.controller.set_paused(True))
        self.menu.addAction(self.pause_action)
        self.resume_action = QAction("Resume mappings", self.menu)
        self.resume_action.triggered.connect(lambda: self.controller.set_paused(False))
        self.menu.addAction(self.resume_action)
        self.menu.addSeparator()

        self.profiles_menu = self.menu.addMenu("Current profile")
        self.profile_group = QActionGroup(self.profiles_menu)
        self.profile_group.setExclusive(True)
        self.menu.addSeparator()

        self.caffeine_action = QAction("Keep screen awake (Caffeine)", self.menu)
        self.caffeine_action.setCheckable(True)
        self.caffeine_action.setToolTip("Stop Windows from turning off the display or sleeping")
        self.caffeine_action.toggled.connect(self.controller.set_caffeine)
        self.menu.addAction(self.caffeine_action)
        self.menu.addSeparator()

        settings_action = QAction("Settings", self.menu)
        settings_action.triggered.connect(lambda: self.controller.navigate("settings"))
        self.menu.addAction(settings_action)
        self.exit_action = QAction("Exit", self.menu)
        self.exit_action.triggered.connect(self.controller.quit_application)
        self.menu.addAction(self.exit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

    def _menu_style(self) -> str:
        from app.ui.theme import palette

        p = palette()
        return (
            f"QMenu {{ background: {p['popup']}; color: {p['text']}; border: 1px solid "
            f"rgba(255,255,255,0.12); border-radius: 10px; padding: 6px; }}"
            "QMenu::item { padding: 7px 24px 7px 12px; border-radius: 6px; }"
            f"QMenu::item:selected {{ background: {p['accent']['primary']}55; }}"
            "QMenu::separator { height: 1px; background: rgba(255,255,255,0.10); margin: 5px 8px; }"
        )

    def show(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:  # pragma: no cover - unusual desktop session
            log.warning("System tray is not available")

    def hide(self) -> None:
        self.tray.hide()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.controller.show_window()

    def refresh_state(self) -> None:
        status = self.controller.engine.status()
        if status["emergency"]:
            tint, label = "#F87171", "emergency stop"
        elif status["running"] and status["enabled"] and not status["paused"]:
            tint, label = "#3DDC97", "mappings active"
        elif status["running"]:
            tint, label = "#F5B544", "paused / disabled"
        else:
            tint, label = "#5C6484", "engine stopped"
        self.tray.setIcon(status_icon(self.icon, tint))
        profile = self.controller.profiles.active
        voice = getattr(self.controller, "voice", None)
        voice_note = f" — voice: {voice.preset_label()}" if voice is not None and voice.is_running() else ""
        power = getattr(self.controller, "power", None)
        caffeine_note = " — screen awake" if power is not None and power.is_enabled() else ""
        self.tray.setToolTip(f"{APP_NAME} — {label} — profile: {profile.name}{voice_note}{caffeine_note}")

        if power is not None:
            self.caffeine_action.blockSignals(True)
            self.caffeine_action.setChecked(power.is_enabled())
            self.caffeine_action.blockSignals(False)

        self.enable_action.setEnabled(not status["enabled"] or status["paused"])
        self.disable_action.setEnabled(status["enabled"] and not status["paused"])
        self.pause_action.setEnabled(status["running"] and not status["paused"])
        self.resume_action.setEnabled(status["running"] and status["paused"])

        self.profiles_menu.clear()
        for action in list(self.profile_group.actions()):
            self.profile_group.removeAction(action)
        for profile in self.controller.profiles.profiles():
            action = QAction(profile.name, self.profiles_menu)
            action.setCheckable(True)
            action.setChecked(profile.id == self.controller.profiles.active_id)
            action.triggered.connect(lambda _=False, pid=profile.id: self.controller.switch_profile(pid))
            self.profile_group.addAction(action)
            self.profiles_menu.addAction(action)
        self.menu.setStyleSheet(self._menu_style())

    def notify(self, title: str, message: str, ms: int = 3000) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable() and self.tray.isVisible():
            self.tray.showMessage(title, message, app_icon(64), ms)
