"""Keycap chips and status pills."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.engine.keycodes import MODIFIER_LABELS, key_label
from app.ui.theme import color, palette


class ChordChips(QWidget):
    """Render a chord as keycaps with separators, e.g. ``CTRL + SHIFT + B``."""

    def __init__(
        self,
        chord: dict | None = None,
        parent: QWidget | None = None,
        compact: bool = False,
        placeholder: str = "Not set",
    ):
        super().__init__(parent)
        self._chord = chord or {}
        self._compact = compact
        self._placeholder = placeholder
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_chord(self, chord: dict | None) -> None:
        self._chord = chord or {}
        self.updateGeometry()
        self.update()

    def _parts(self) -> list[str]:
        mods = [str(m).lower() for m in (self._chord.get("mods") or [])]
        key = str(self._chord.get("key", ""))
        parts = [MODIFIER_LABELS.get(m, m.upper()) for m in mods]
        if key:
            parts.append(key_label(key))
        return parts

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(8.6 if self._compact else 9.4)
        font.setWeight(QFont.DemiBold)
        font.setLetterSpacing(QFont.PercentageSpacing, 103)
        return font

    def _metrics(self) -> tuple[list[QFontMetrics], float, float]:
        font = self._font()
        metrics = [QFontMetrics(font) for _ in self._parts()]
        padding_h = 8 if self._compact else 10
        cap_height = 20 if self._compact else 25
        widths = [m.horizontalAdvance(part) + padding_h * 2 for m, part in zip(metrics, self._parts())]
        plus_width = 12 if self._compact else 15
        total = sum(widths) + plus_width * max(0, len(widths) - 1)
        return metrics, total, cap_height

    def sizeHint(self) -> QSize:  # noqa: N802
        _, width, height = self._metrics()
        if not self._parts():
            font = QFont(self.font())
            font.setPointSizeF(9)
            metrics = QFontMetrics(font)
            return QSize(metrics.horizontalAdvance(self._placeholder) + 8, 22)
        return QSize(int(width), int(height))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        parts = self._parts()
        if not parts:
            painter.setPen(color(p["faint"]))
            font = QFont(self.font())
            font.setPointSizeF(9)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft, self._placeholder)
            painter.end()
            return

        font = self._font()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        padding_h = 8 if self._compact else 10
        height = 20 if self._compact else 25
        plus_width = 12 if self._compact else 15
        x = 0.0
        y = (self.height() - height) / 2

        for index, part in enumerate(parts):
            width = metrics.horizontalAdvance(part) + padding_h * 2
            rect = QRectF(x, y, width, height)
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, color(p["white"], 34 if p["is_dark"] else 26))
            gradient.setColorAt(1.0, color(p["white"], 14 if p["is_dark"] else 12))
            painter.setBrush(gradient)
            painter.setPen(QPen(color(p["white"], p["border_strong_alpha"]), 1))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
            painter.setPen(color(p["text"]))
            painter.drawText(rect, Qt.AlignCenter, part)
            x += width
            if index < len(parts) - 1:
                painter.setPen(color(p["faint"]))
                painter.drawText(QRectF(x, y, plus_width, height), Qt.AlignCenter, "+")
                x += plus_width
        painter.end()


class Pill(QWidget):
    """Colour-coded status badge."""

    TONES = {
        "success": "success",
        "warning": "warning",
        "danger": "danger",
        "accent": None,
        "muted": "faint",
        "info": "info",
    }

    def __init__(
        self,
        text: str = "",
        tone: str = "muted",
        parent: QWidget | None = None,
        dot: bool = True,
        compact: bool = False,
    ):
        super().__init__(parent)
        self._text = text
        self._tone = tone
        self._dot = dot
        self._compact = compact
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_text(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    def _colors(self) -> tuple[QColor, QColor]:
        p = palette()
        key = self.TONES.get(self._tone, "faint")
        if key is None:
            main = QColor(p["accent"]["primary"])
            return main, color(p["accent"]["primary"], 30)
        main = QColor(p.get(key, p["muted"]))
        return main, color(main.name(), 28)

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(8.4 if self._compact else 9.0)
        font.setWeight(QFont.DemiBold)
        font.setLetterSpacing(QFont.PercentageSpacing, 104)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(self._font())
        width = metrics.horizontalAdvance(self._text) + (34 if self._dot else 20)
        return QSize(width, 20 if self._compact else 23)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event):  # noqa: N802
        if not self._text:
            return
        main, background = self._colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(background)
        painter.setPen(QPen(color(main.name(), 80), 1))
        radius = rect.height() / 2
        painter.drawRoundedRect(rect, radius, radius)
        painter.setFont(self._font())
        text_x = 10.0
        if self._dot:
            painter.setBrush(main)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(9, rect.center().y() - 2.5, 5, 5))
            text_x = 20.0
        painter.setPen(main)
        painter.drawText(
            QRectF(text_x, 0, rect.width() - text_x - 8, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._text,
        )
        painter.end()
