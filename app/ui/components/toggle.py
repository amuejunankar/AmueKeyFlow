"""Animated on/off switch."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Property, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui.theme import color, palette


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._offset = 1.0 if checked else 0.0
        self._enabled = True
        self.setFixedSize(42, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    # -- animated property -------------------------------------------------
    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    offset = Property(float, get_offset, set_offset)

    # -- api ---------------------------------------------------------------
    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True) -> None:  # noqa: N802
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        target = 1.0 if checked else 0.0
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._offset)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.set_offset(target)
        self.toggled.emit(checked)

    def toggle(self) -> None:
        self.setChecked(not self._checked)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(42, 24)

    # -- events ------------------------------------------------------------
    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.toggle()
        super().mouseReleaseEvent(event)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0, 1, self.width(), self.height() - 2)
        accent = p["accent"]
        enabled_alpha = 1.0 if self.isEnabled() else 0.45

        if self._checked:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            gradient.setColorAt(0.0, color(accent["primary"], 255 * enabled_alpha))
            gradient.setColorAt(1.0, color(accent["secondary"], 255 * enabled_alpha))
            painter.setBrush(gradient)
            painter.setPen(Qt.NoPen)
        else:
            painter.setBrush(color(p["white"], (26 if p["is_dark"] else 30) * enabled_alpha))
            painter.setPen(QPen(color(p["white"], p["border_alpha"] * enabled_alpha), 1))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        knob_x = 2 + self._offset * (rect.width() - 22)
        painter.setBrush(QColor(255, 255, 255, int(255 * enabled_alpha)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(knob_x, rect.top() + 2, 18, 18))
        painter.end()

    def enterEvent(self, event):  # noqa: N802
        self.update()
        super().enterEvent(event)
