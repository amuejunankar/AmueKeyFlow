"""Settings page — only the options a typical user actually changes."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.constants import ACCENTS, APP_NAME, APP_VERSION
from app.engine.keycodes import chord_display
from app.ui.base_page import ScrollPage
from app.ui.components.buttons import make_button
from app.ui.components.cards import SectionCard
from app.ui.components.dialogs import Toast
from app.ui.components.toggle import ToggleSwitch
from app.ui.theme import color, palette


class SettingRow(QWidget):
    def __init__(self, title: str, description: str, control: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(18)
        text_widget = QWidget()
        text_widget.setMaximumWidth(640)
        text_box = QVBoxLayout(text_widget)
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        label = QLabel(title)
        font = label.font()
        font.setPointSizeF(10.2)
        font.setWeight(QFont.DemiBold)
        label.setFont(font)
        text_box.addWidget(label)
        if description:
            hint = QLabel(description)
            hint.setProperty("muted", True)
            text_box.addWidget(hint)
        layout.addWidget(text_widget, 1, Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(control, 0, Qt.AlignVCenter)


class AccentSwatch(QWidget):
    clicked = Signal(str)

    def __init__(self, key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.selected = False
        self._hover = False
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(key.capitalize())

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802
        accent = ACCENTS[self.key]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        ring = QRectF(1, 1, 32, 32)
        if self.selected or self._hover:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(color(accent["primary"], 180 if self.selected else 90), 2))
            painter.drawEllipse(ring)
        inner = QRectF(6, 6, 22, 22)
        gradient = QLinearGradient(inner.topLeft(), inner.bottomRight())
        gradient.setColorAt(0.0, color(accent["primary"]))
        gradient.setColorAt(1.0, color(accent["secondary"]))
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(inner)
        if self.selected:
            painter.setBrush(color("#FFFFFF", 220))
            painter.drawEllipse(QRectF(14.5, 14.5, 5, 5))
        painter.end()


class SettingsPage(ScrollPage):
    title = "Settings"
    subtitle = "Startup, appearance and backup"

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self._building = True
        self._build_general()
        self._build_appearance()
        self._build_keyboard()
        self._build_backup()
        self.layout_main.addStretch(1)
        self._building = False

    # -- builders ----------------------------------------------------------
    def _section(self, title: str, subtitle: str) -> SectionCard:
        card = SectionCard(title, subtitle)
        self.layout_main.addWidget(card)
        return card

    def _toggle(self, key: str, on_change=None) -> ToggleSwitch:
        switch = ToggleSwitch(False)

        def handler(checked: bool) -> None:
            if self._building:
                return
            if on_change is not None:
                on_change(checked)
            else:
                self.controller.settings.set(key, checked)
                self.controller.refresh_state()

        switch.toggled.connect(handler)
        return switch

    def _combo(self, options: list[tuple[str, object]], key: str | None = None, on_change=None) -> QComboBox:
        combo = QComboBox()
        for label, value in options:
            combo.addItem(label, value)
        combo.setFixedWidth(210)
        if key or on_change:
            def handler(_index: int) -> None:
                if self._building:
                    return
                value = combo.currentData()
                if on_change is not None:
                    on_change(value)
                elif key:
                    self.controller.settings.set(key, value)
                    self.controller.refresh_state()

            combo.currentIndexChanged.connect(handler)
        return combo

    # -- general -----------------------------------------------------------
    def _build_general(self) -> None:
        card = self._section("General", "Startup and window")
        self.startup_toggle = self._toggle("start_with_windows", self._on_startup_toggle)
        card.body.addWidget(
            SettingRow("Start with Windows", "Launch in the background when you sign in.", self.startup_toggle)
        )
        self.start_min_toggle = self._toggle("launch_minimized", self._on_start_minimized)
        card.body.addWidget(
            SettingRow(
                "Start minimized to tray",
                "Open in the tray instead of showing the window.",
                self.start_min_toggle,
            )
        )
        self.minimize_toggle = self._toggle("minimize_to_tray")
        card.body.addWidget(
            SettingRow("Keep running in the tray", "Closing the window keeps mappings active.", self.minimize_toggle)
        )
        self.activity_toggle = self._toggle("activity_logging")
        card.body.addWidget(
            SettingRow("Log mapping activity", "Records events for the Activity page.", self.activity_toggle)
        )

    def _on_startup_toggle(self, enabled: bool) -> None:
        ok, message = self.controller.set_start_with_windows(enabled)
        Toast.show_message(self.window(), message, "success" if ok else "error")
        if not ok:
            self.refresh()

    def _on_start_minimized(self, enabled: bool) -> None:
        # One switch controls both manual launches and the autostart entry.
        self.controller.settings.set("launch_minimized", enabled)
        self.controller.settings.set("startup_behavior", "tray" if enabled else "window")
        self.controller.refresh_state()

    # -- appearance --------------------------------------------------------
    def _build_appearance(self) -> None:
        card = self._section("Appearance", "Theme and accent colour")
        self.theme_combo = self._combo(
            [("Dark", "dark"), ("Light", "light"), ("Follow system", "system")],
            on_change=self._on_theme_change,
        )
        card.body.addWidget(SettingRow("Theme", "Dark, light, or match Windows.", self.theme_combo))

        swatches_widget = QWidget()
        swatch_layout = QHBoxLayout(swatches_widget)
        swatch_layout.setContentsMargins(0, 0, 0, 0)
        swatch_layout.setSpacing(8)
        self.swatches: dict[str, AccentSwatch] = {}
        for key in ACCENTS:
            swatch = AccentSwatch(key)
            swatch.clicked.connect(self._on_accent_change)
            self.swatches[key] = swatch
            swatch_layout.addWidget(swatch)
        card.body.addWidget(SettingRow("Accent colour", "Highlights and active states.", swatches_widget))

    def _on_theme_change(self, value) -> None:
        self.controller.settings.set("theme", value)
        self.controller.apply_appearance()

    def _on_accent_change(self, key: str) -> None:
        self.controller.settings.set("accent", key)
        self.controller.apply_appearance()

    # -- keyboard ----------------------------------------------------------
    def _build_keyboard(self) -> None:
        card = self._section("Keyboard", "Engine and safety")
        self.engine_toggle = self._toggle("engine_enabled", self._on_engine_toggle)
        card.body.addWidget(
            SettingRow(
                "Keyboard engine",
                "Turn off to use your normal keyboard.",
                self.engine_toggle,
            )
        )
        hotkey = chord_display({"mods": ["ctrl", "alt", "shift"], "key": "f12"})
        self.emergency_toggle = self._toggle("emergency_hotkey_enabled")
        card.body.addWidget(
            SettingRow(
                "Emergency stop hotkey",
                f"{hotkey} stops interception instantly.",
                self.emergency_toggle,
            )
        )

    def _on_engine_toggle(self, enabled: bool) -> None:
        self.controller.set_engine_enabled(enabled)

    # -- backup ------------------------------------------------------------
    def _build_backup(self) -> None:
        card = self._section("Backup", "Keep your mappings safe")
        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
        export_button = make_button("Export", "default", "download")
        export_button.clicked.connect(self.controller.export_all)
        import_button = make_button("Import", "default", "upload")
        import_button.clicked.connect(self.controller.import_configuration)
        folder_button = make_button("Open data folder", "ghost", "external")
        folder_button.clicked.connect(self.controller.open_config_folder)
        for button in (export_button, import_button, folder_button):
            button_layout.addWidget(button)
        card.body.addWidget(
            SettingRow("Configuration", "Export or restore all profiles.", buttons)
        )

        about = QLabel(f"{APP_NAME} {APP_VERSION} · Offline by design.")
        about.setProperty("muted", True)
        card.body.addWidget(about)

    # -- refresh -----------------------------------------------------------
    def refresh(self) -> None:
        self._building = True
        s = self.controller.settings
        self.startup_toggle.setChecked(s.get_bool("start_with_windows"), animate=False)
        self.start_min_toggle.setChecked(s.get_bool("launch_minimized", False), animate=False)
        self.minimize_toggle.setChecked(s.get_bool("minimize_to_tray"), animate=False)
        self.activity_toggle.setChecked(s.get_bool("activity_logging", True), animate=False)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(s.get("theme"))))
        accent_key = str(s.get("accent"))
        for key, swatch in self.swatches.items():
            swatch.set_selected(key == accent_key)
        self.engine_toggle.setChecked(s.get_bool("engine_enabled"), animate=False)
        self.emergency_toggle.setChecked(s.get_bool("emergency_hotkey_enabled"), animate=False)
        self._building = False
