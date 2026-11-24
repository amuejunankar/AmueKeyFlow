"""Glass panels, statistic cards and banners."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.icons import icon_pixmap
from app.ui.theme import color, palette, rgba


class GlassCard(QFrame):
    """Translucent rounded panel with a hairline border."""

    def __init__(self, parent: QWidget | None = None, radius: int = 18, hoverable: bool = False, padding: int = 0):
        super().__init__(parent)
        self._radius = radius
        self._hoverable = hoverable
        self._hover = False
        self.setAttribute(Qt.WA_StyledBackground, False)
        # Maximum keeps cards at their content height inside stretched layouts.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        if padding:
            self.setContentsMargins(padding, padding, padding, padding)

    def enterEvent(self, event):  # noqa: N802
        if self._hoverable:
            self._hover = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if self._hoverable:
            self._hover = False
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        card_alpha = p["card_hover_alpha"] if self._hover and self._hoverable else p["card_alpha"]
        if p["is_dark"]:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, color(p["white"], card_alpha + 8))
            gradient.setColorAt(1.0, color(p["white"], max(4, card_alpha - 6)))
            painter.setBrush(gradient)
        else:
            painter.setBrush(QColor(p["panel"]))
        pen = QPen(color(p["white"], p["border_alpha"]))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, self._radius, self._radius)

        # Top highlight for the glass effect.
        if p["is_dark"]:
            highlight = QPainterPath()
            highlight.addRoundedRect(rect, self._radius, self._radius)
            painter.setClipPath(highlight)
            painter.setPen(QPen(color("#FFFFFF", 16), 1))
            painter.drawLine(rect.left() + self._radius, rect.top() + 1, rect.right() - self._radius, rect.top() + 1)

        if self._hoverable:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            gradient.setColorAt(0.0, Qt.transparent)
            gradient.setColorAt(0.5, color(p["accent"]["primary"], 90 if self._hover else 0))
            gradient.setColorAt(1.0, Qt.transparent)
            painter.setPen(QPen(gradient, 1))
            painter.drawLine(rect.left() + 12, rect.top(), rect.right() - 12, rect.top())
        painter.end()


class IconBadge(QWidget):
    """Small gradient tile holding a line icon."""

    def __init__(self, icon_name: str, size: int = 38, parent: QWidget | None = None, tone: str | None = None):
        super().__init__(parent)
        self._icon = icon_name
        self._size = size
        self._tone = tone
        self.setFixedSize(size, size)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0, 0, self._size, self._size)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        primary = self._tone or p["accent"]["primary"]
        secondary = self._tone or p["accent"]["secondary"]
        gradient.setColorAt(0.0, color(primary, 70))
        gradient.setColorAt(1.0, color(secondary, 26))
        painter.setBrush(gradient)
        painter.setPen(QPen(color(p["white"], 32), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._size * 0.3, self._size * 0.3)
        painter.drawPixmap(
            int((self._size - self._size * 0.5) / 2),
            int((self._size - self._size * 0.5) / 2),
            icon_pixmap(self._icon, primary if not p["is_dark"] else "#FFFFFF", int(self._size * 0.5), 1.7),
        )
        painter.end()


class StatCard(GlassCard):
    def __init__(self, title: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent, radius=18, hoverable=True)
        self.setMinimumHeight(128)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        self._title = QLabel(title.upper())
        self._title.setObjectName("SectionTitle")
        self._title.setWordWrap(True)
        top.addWidget(self._title)
        top.addStretch(1)
        top.addWidget(IconBadge(icon_name, 34))
        layout.addLayout(top)

        self.value_label = QLabel("0")
        self.value_label.setObjectName("StatValue")
        self.value_label.setWordWrap(True)
        layout.addWidget(self.value_label)

        self.hint_label = QLabel("")
        self.hint_label.setProperty("muted", True)
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)

    def set_value(self, value: str, hint: str = "") -> None:
        self.value_label.setText(value)
        self.hint_label.setText(hint)


class SectionCard(GlassCard):
    """Card with a title row and a content layout."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None, padding: int = 20):
        super().__init__(parent, radius=18)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(14)

        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.header.addWidget(self.title_label)
        self.header.addStretch(1)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setProperty("muted", True)
        self.header.addWidget(self._subtitle)
        if title:
            self._layout.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self._layout.addLayout(self.body)
        # Keep content anchored to the top instead of spreading it out.
        self._layout.addStretch(1)

    def add_trailing(self, widget: QWidget) -> None:
        self.header.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)


class Banner(QFrame):
    """Inline informational banner with an icon and message."""

    TONES = {
        "info": ("InfoBanner", "info", "#60A5FA"),
        "warn": ("WarnBanner", "alert", "#F5B544"),
        "error": ("ErrorBanner", "alert", "#F87171"),
    }

    def __init__(self, text: str = "", tone: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        obj, icon_name, tint = self.TONES.get(tone, self.TONES["info"])
        self.setObjectName(obj)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._tone = tone
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(10)
        self._icon = QLabel()
        self._icon.setPixmap(icon_pixmap(icon_name, tint, 16, 1.8))
        layout.addWidget(self._icon, 0, Qt.AlignTop)
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label, 1)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        layout.addLayout(self._actions)

    def add_action(self, widget: QWidget) -> None:
        self._actions.addWidget(widget)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def set_tone(self, tone: str) -> None:
        if tone == self._tone:
            return
        obj, icon_name, tint = self.TONES.get(tone, self.TONES["info"])
        self._tone = tone
        self.setObjectName(obj)
        self._icon.setPixmap(icon_pixmap(icon_name, tint, 16, 1.8))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class Divider(QFrame):
    def __init__(self, vertical: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("VSeparator" if vertical else "Separator")
        self.setAttribute(Qt.WA_StyledBackground, True)
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)


class KeyValueRow(QWidget):
    """Small label/value pair used inside cards."""

    def __init__(self, label: str, value: str = "—", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._label = QLabel(label)
        self._label.setProperty("muted", True)
        layout.addWidget(self._label)
        layout.addStretch(1)
        self._value = QLabel(value)
        font = self._value.font()
        font.setWeight(QFont.DemiBold)
        self._value.setFont(font)
        layout.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


def add_soft_shadow(widget: QWidget, blur: int = 40, alpha: int = 120, dy: int = 10) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
