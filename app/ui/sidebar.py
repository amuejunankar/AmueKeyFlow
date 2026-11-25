"""Left navigation rail with brand mark, page links and engine status."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.constants import APP_VERSION
from app.ui.components.chips import Pill
from app.ui.icons import icon_pixmap
from app.ui.theme import color, palette

NAV_ITEMS = [
    ("dashboard", "Dashboard", "dashboard"),
    ("mapper", "Key Mapper", "keyboard"),
    ("tester", "Key Tester", "tester"),
    ("voice", "Voice FX", "wave"),
    ("profiles", "Profiles", "profiles"),
    ("activity", "Activity", "activity"),
    ("settings", "Settings", "settings"),
]


class LogoMark(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0, 0, 40, 40)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, color(p["accent"]["primary"]))
        gradient.setColorAt(1.0, color("#3BC8E0"))
        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 12, 12)
        painter.setBrush(color("#FFFFFF", 235))
        painter.drawRoundedRect(QRectF(8.5, 8.5, 23, 23), 7, 7)
        font = QFont(self.font())
        font.setPointSizeF(14)
        font.setWeight(QFont.Black)
        painter.setFont(font)
        painter.setPen(color("#0B0D1B"))
        painter.drawText(QRectF(8.5, 8.5, 23, 23), Qt.AlignCenter, "A")
        painter.end()


class NavButton(QWidget):
    clicked = Signal(str)

    def __init__(self, key: str, label: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.label = label
        self.icon_name = icon_name
        self.active = False
        self._hover = False
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(label)

    def set_active(self, active: bool) -> None:
        self.active = active
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
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 44)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(8, 3, -8, -3)

        if self.active:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            gradient.setColorAt(0.0, color(p["accent"]["primary"], 110))
            gradient.setColorAt(1.0, color(p["accent"]["secondary"], 22))
            painter.setBrush(gradient)
            painter.setPen(QPen(color(p["accent"]["primary"], 120), 1))
            painter.drawRoundedRect(rect, 11, 11)
            painter.setBrush(color(p["accent"]["secondary"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(rect.left() - 8, rect.top() + 11, 3, rect.height() - 22), 1.5, 1.5)
        elif self._hover:
            painter.setBrush(color(p["white"], 22))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 11, 11)

        tint = "#FFFFFF" if self.active else (p["text"] if self._hover else p["muted"])
        pixmap = icon_pixmap(self.icon_name, tint, 18, 1.65)
        painter.drawPixmap(int(rect.left() + 13), int(rect.center().y() - 9), pixmap)

        font = QFont(self.font())
        font.setPointSizeF(10)
        font.setWeight(QFont.DemiBold if self.active else QFont.Medium)
        painter.setFont(font)
        painter.setPen(color("#FFFFFF") if self.active and p["is_dark"] else color(p["text"]))
        painter.drawText(
            QRectF(rect.left() + 44, rect.top(), rect.width() - 52, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.label,
        )
        painter.end()


class Sidebar(QFrame):
    navigated = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(248)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.nav_buttons: dict[str, NavButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(11)
        brand.setContentsMargins(6, 0, 0, 0)
        brand.addWidget(LogoMark())
        brand_box = QVBoxLayout()
        brand_box.setSpacing(1)
        name = QLabel("AMUE KEYFLOW")
        name.setObjectName("BrandName")
        sub = QLabel("KEYBOARD AUTOMATION")
        sub.setObjectName("BrandSub")
        brand_box.addWidget(name)
        brand_box.addWidget(sub)
        brand.addLayout(brand_box)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(20)

        for key, text, icon_name in NAV_ITEMS:
            button = NavButton(key, text, icon_name)
            button.clicked.connect(self.navigated.emit)
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self.override_host = QWidget()
        override_layout = QHBoxLayout(self.override_host)
        override_layout.setContentsMargins(10, 0, 10, 6)
        override_layout.setSpacing(6)
        self.override_pill = Pill("", "info", compact=True, dot=False)
        self.override_pill.setToolTip("An app override is layered on top of the active profile")
        override_layout.addWidget(self.override_pill)
        override_layout.addStretch(1)
        self.override_host.setVisible(False)
        layout.addWidget(self.override_host)

        self.status_card = _StatusCard()
        layout.addWidget(self.status_card)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 8, 8, 0)
        version = QLabel(f"v{APP_VERSION}")
        version.setProperty("muted", True)
        font = version.font()
        font.setPointSizeF(8.6)
        version.setFont(font)
        bottom.addWidget(version)
        layout.addLayout(bottom)

    def set_active(self, key: str) -> None:
        for nav_key, button in self.nav_buttons.items():
            button.set_active(nav_key == key)

    def set_status(self, running: bool, enabled: bool, paused: bool, emergency: bool) -> None:
        self.status_card.set_state(running, enabled, paused, emergency)

    def set_override(self, override) -> None:
        """Show the app override that is currently layered on the profile."""
        if override is None:
            self.override_host.setVisible(False)
            return
        count = getattr(override, "mapping_count", 0)
        label = override.executable if not count else f"{override.executable} \u00b7 {count}"
        self.override_pill.set_text(label)
        self.override_host.setVisible(True)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.setBrush(color(p["white"], p["sidebar_alpha"]))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect.adjusted(0, 0, 0, 0), 0, 0)
        painter.setPen(QPen(color(p["white"], p["border_alpha"]), 1))
        painter.drawLine(int(rect.right()) - 1, int(rect.top() + 12), int(rect.right()) - 1, int(rect.bottom() - 12))
        painter.end()


class _StatusCard(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("StatusCard")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFixedHeight(66)
        self._running = False
        self._enabled = True
        self._paused = False
        self._emergency = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(10)
        self._dot = _StatusDot()
        layout.addWidget(self._dot)
        box = QVBoxLayout()
        box.setSpacing(1)
        self._title = QLabel("Engine stopped")
        font = self._title.font()
        font.setPointSizeF(9.6)
        font.setWeight(QFont.DemiBold)
        self._title.setFont(font)
        self._subtitle = QLabel("Keyboard hook idle")
        self._subtitle.setProperty("muted", True)
        font2 = self._subtitle.font()
        font2.setPointSizeF(8.2)
        self._subtitle.setFont(font2)
        box.addWidget(self._title)
        box.addWidget(self._subtitle)
        layout.addLayout(box)
        layout.addStretch(1)

    def set_state(self, running: bool, enabled: bool, paused: bool, emergency: bool) -> None:
        self._running, self._enabled, self._paused, self._emergency = running, enabled, paused, emergency
        if emergency:
            self._title.setText("Emergency stop")
            self._subtitle.setText("Keyboard restored")
        elif not running:
            self._title.setText("Engine stopped")
            self._subtitle.setText("Keys pass through")
        elif paused:
            self._title.setText("Paused")
            self._subtitle.setText("Keys pass through")
        elif enabled:
            self._title.setText("Engine running")
            self._subtitle.setText("Mappings active")
        else:
            self._title.setText("Mappings off")
            self._subtitle.setText("Keys pass through")
        self._dot.set_state(self._dot_color())
        self.update()

    def _dot_color(self) -> str:
        p = palette()
        if self._emergency:
            return p["danger"]
        if not self._running:
            return p["faint"]
        if self._paused or not self._enabled:
            return p["warning"]
        return p["success"]

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(color(p["white"], 18 if p["is_dark"] else 26))
        painter.setPen(QPen(color(p["white"], p["border_alpha"]), 1))
        painter.drawRoundedRect(rect, 13, 13)
        painter.end()


class _StatusDot(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._color = palette()["success"]

    def set_state(self, tint: str) -> None:
        self._color = tint
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(color(self._color, 60))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(0, 0, 10, 10))
        painter.setBrush(color(self._color, 240))
        painter.drawEllipse(QRectF(2.5, 2.5, 5, 5))
        painter.end()
