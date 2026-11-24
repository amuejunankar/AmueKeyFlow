"""Top navigation bar with page title, search, global toggle and window controls."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.components.buttons import IconButton, WindowButton, make_button
from app.ui.components.toggle import ToggleSwitch
from app.ui.icons import icon_pixmap
from app.ui.theme import color, palette


class _PauseButton(QPushButton):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._paused = False
        self.setFixedSize(34, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: 1px solid rgba(255,255,255,0.10);"
                           " border-radius: 9px; padding: 0px; }")
        self.setToolTip("Pause mappings")

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.setToolTip("Resume mappings" if paused else "Pause mappings")
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self.underMouse():
            painter.setBrush(color(p["white"], 26))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9, 9)
        tint = p["warning"] if self._paused else p["muted"]
        glyph = "play" if self._paused else "pause"
        painter.drawPixmap(9, 8, icon_pixmap(glyph, tint, 16, 1.8))
        painter.end()


class TopBar(QWidget):
    search_requested = Signal()
    mappings_toggled = Signal(bool)
    pause_clicked = Signal()
    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(88)
        self._drag_active = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 18, 16, 12)
        layout.setSpacing(14)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel("Dashboard")
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel("Overview of your keyboard workspace")
        self.subtitle_label.setObjectName("PageSubtitle")
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        layout.addLayout(titles)
        layout.addStretch(1)

        self.search_button = make_button("Search", "ghost", "search")
        self.search_button.setToolTip("Search mappings (Ctrl+K)")
        self.search_button.clicked.connect(self.search_requested.emit)
        layout.addWidget(self.search_button)

        self.toggle = ToggleSwitch(True)
        self.toggle.setToolTip("Enable or disable all mappings globally")
        self.toggle.toggled.connect(self.mappings_toggled.emit)
        layout.addWidget(self.toggle)

        self.pause_button = _PauseButton()
        self.pause_button.clicked.connect(self.pause_clicked.emit)
        layout.addWidget(self.pause_button)

        divider = QFrame()
        divider.setObjectName("VSeparator")
        divider.setAttribute(Qt.WA_StyledBackground, True)
        divider.setFixedSize(1, 26)
        layout.addWidget(divider)

        controls = QHBoxLayout()
        controls.setSpacing(2)
        self.min_button = WindowButton("minimize")
        self.max_button = WindowButton("maximize")
        self.close_button = WindowButton("close", close=True)
        self.min_button.clicked.connect(self.minimize_clicked.emit)
        self.max_button.clicked.connect(self.maximize_clicked.emit)
        self.close_button.clicked.connect(self.close_clicked.emit)
        for button in (self.min_button, self.max_button, self.close_button):
            controls.addWidget(button)
        layout.addLayout(controls)

    # -- state -------------------------------------------------------------
    def set_page(self, title: str, subtitle: str) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)

    def set_mappings_enabled(self, enabled: bool) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled, animate=False)
        self.toggle.blockSignals(False)

    def set_paused(self, paused: bool) -> None:
        self.pause_button.set_paused(paused)

    def set_maximized(self, maximized: bool) -> None:
        self.max_button.set_icon_name("restore" if maximized else "maximize")
        self.max_button.update()

    # -- dragging ----------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                if handle.windowState() & Qt.WindowMaximized:
                    handle.showNormal()
                else:
                    handle.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(color(p["white"], p["border_alpha"]), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        gradient = QColor(p["accent"]["primary"])
        gradient.setAlpha(0)
        painter.end()
