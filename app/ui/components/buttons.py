"""Buttons with painted icons and accent treatments."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from app.ui.icons import icon_pixmap
from app.ui.theme import color, palette


class FlowButton(QPushButton):
    """Text button that paints its own gradient/glass background and icon.

    Painting everything removes the platform style's icon/label spacing quirks,
    which otherwise overlap at this typography scale.
    """

    HEIGHT = 38

    def __init__(
        self,
        text: str,
        variant: str = "default",
        icon_name: str | None = None,
        parent: QWidget | None = None,
        tint: str | None = None,
    ):
        super().__init__(text, parent)
        self._variant = variant
        self._icon_name = icon_name
        self._tint = tint
        self._hover = False
        self._pressed = False
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; }")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(self.HEIGHT if variant != "link" else 26)

    # -- geometry ----------------------------------------------------------
    def _paddings(self) -> tuple[int, int]:
        if self._variant == "link":
            return 6, 6
        if self._variant in {"primary", "danger"}:
            return 18, 20
        return 16, 18

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(self.font())
        left, right = self._paddings()
        width = metrics.horizontalAdvance(self.text()) + left + right
        if self._icon_name:
            width += 16 + 8
        height = 26 if self._variant == "link" else self.HEIGHT
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    # -- interaction -------------------------------------------------------
    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        self.update()

    # -- painting ----------------------------------------------------------
    def _colors(self) -> tuple[QColor, QColor | None, QColor]:
        p = palette()
        accent = p["accent"]
        text = QColor(p["text"])
        border = None
        if self._variant == "primary":
            background = QColor(accent["primary"])
            text = QColor(p["accent_text"])
        elif self._variant == "danger":
            background = color(p["danger"], 34)
            border = color(p["danger"], 96)
            text = QColor(p["danger"])
        elif self._variant == "ghost":
            background = color(p["white"], 0)
            border = color(p["white"], p["border_alpha"])
            text = QColor(p["muted"])
        elif self._variant == "link":
            background = color(p["white"], 0)
            text = QColor(accent["primary"] if not p["is_dark"] else accent["secondary"])
        else:
            background = color(p["white"], 22 if p["is_dark"] else 18)
            border = color(p["white"], p["border_alpha"])
        if not self.isEnabled():
            background = color(p["white"], 8)
            border = color(p["white"], 18)
            text = QColor(p["faint"])
        elif self._hover and self._variant not in {"primary", "link"}:
            background = color(p["white"], 30 if p["is_dark"] else 26)
            if self._variant == "danger":
                background = color(p["danger"], 52)
            if border is not None:
                border = color(p["white"], p["border_strong_alpha"])
        return background, border, text

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        accent = p["accent"]
        background, border, text_color = self._colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 10 if self._variant != "link" else 8

        if self._variant == "primary" and self.isEnabled():
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            if self._pressed:
                gradient.setColorAt(0.0, color(accent["primary"]))
                gradient.setColorAt(1.0, color(accent["primary"]))
            elif self._hover:
                gradient.setColorAt(0.0, color(accent["secondary"]))
                gradient.setColorAt(1.0, color(accent["primary"]))
            else:
                gradient.setColorAt(0.0, color(accent["primary"]))
                gradient.setColorAt(1.0, color(accent["secondary"]))
            painter.setBrush(gradient)
            painter.setPen(Qt.NoPen)
        else:
            painter.setBrush(background)
            painter.setPen(QPen(border, 1) if border is not None else Qt.NoPen)
        if background.alpha() > 0 or self._variant == "primary":
            painter.drawRoundedRect(rect, radius, radius)

        font = self.font()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        left, _ = self._paddings()
        icon_size = 16 if self._icon_name else 0
        gap = 8 if self._icon_name else 0
        text_width = metrics.horizontalAdvance(self.text())
        total = icon_size + gap + text_width
        start = max(left, (rect.width() - total) / 2)
        if icon_size:
            tint = text_color.name()
            pixmap = icon_pixmap(self._icon_name, tint, icon_size, 1.75)
            painter.drawPixmap(int(start), int(rect.center().y() - icon_size / 2 + 0.5), pixmap)
            start += icon_size + gap
        painter.setPen(text_color)
        painter.drawText(
            QRectF(start, rect.top(), max(10.0, rect.width() - start - 4), rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.text(),
        )
        painter.end()


def make_button(
    text: str,
    variant: str = "default",
    icon_name: str | None = None,
    parent: QWidget | None = None,
    tint: str | None = None,
) -> FlowButton:
    return FlowButton(text, variant, icon_name, parent, tint)


class IconButton(QPushButton):
    """Square, borderless icon button with a soft hover state."""

    def __init__(
        self,
        icon_name: str,
        parent: QWidget | None = None,
        size: int = 30,
        icon_size: int = 16,
        tooltip: str = "",
        tone: str | None = None,
        danger: bool = False,
    ):
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        self._tone = tone
        self._danger = danger
        self._hovered = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; }")
        if tooltip:
            self.setToolTip(tooltip)

    def enterEvent(self, event):  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        if self._hovered and self.isEnabled():
            background = color(p["danger"], 40) if self._danger else color(p["white"], 30)
            painter.setBrush(background)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
        if self._danger:
            tint = p["danger"]
        elif self._tone:
            tint = p[self._tone] if self._tone in p else p["text"]
        else:
            tint = p["text"]
        if not self.isEnabled():
            tint = p["faint"]
        pixmap = icon_pixmap(self._icon_name, tint, self._icon_size, 1.7)
        x = (self.width() - self._icon_size) / 2
        y = (self.height() - self._icon_size) / 2
        painter.drawPixmap(int(x), int(y), pixmap)
        painter.end()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.update()


class WindowButton(QPushButton):
    def __init__(self, icon_name: str, parent: QWidget | None = None, close: bool = False):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setFixedSize(34, 30)
        self.setCursor(Qt.ArrowCursor)
        self.setProperty("variant", "close" if close else "window")
        self._close = close

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self.underMouse():
            painter.setBrush(color(p["danger"] if self._close else p["white"], 200 if self._close else 34))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 8, 8)
        tint = "#FFFFFF" if (self._close and self.underMouse()) else p["muted"]
        pixmap = icon_pixmap(self._icon_name, tint, 14, 1.5)
        painter.drawPixmap(int((self.width() - 14) / 2), int((self.height() - 14) / 2), pixmap)
        painter.end()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(34, 30)
