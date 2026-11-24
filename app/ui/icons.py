"""Minimal line icons painted with QPainter (no external image assets)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from app.ui.theme import color

_CACHE: dict[tuple[str, str, int, float], QPixmap] = {}


def _path(name: str, rect: QRectF) -> tuple[QPainterPath, list[QRectF]]:
    """Return the main path plus optional filled shapes for an icon."""
    p = QPainterPath()
    extra: list[QRectF] = []
    w, h = rect.width(), rect.height()
    x, y = rect.x(), rect.y()

    if name == "dashboard":
        gap = w * 0.16
        cell = (w - gap) / 2
        for cx, cy in ((x, y), (x + cell + gap, y), (x, y + cell + gap), (x + cell + gap, y + cell + gap)):
            p.addRoundedRect(QRectF(cx, cy, cell, cell), cell * 0.28, cell * 0.28)
    elif name == "keyboard":
        p.addRoundedRect(QRectF(x, y + h * 0.12, w, h * 0.76), h * 0.2, h * 0.2)
        p.addRect(QRectF(x + w * 0.16, y + h * 0.28, w * 0.68, h * 0.02))
        for i in range(3):
            p.addRect(QRectF(x + w * (0.2 + i * 0.22), y + h * 0.52, w * 0.12, h * 0.02))
        p.addRect(QRectF(x + w * 0.3, y + h * 0.7, w * 0.4, h * 0.02))
    elif name == "tester":
        p.addEllipse(QRectF(x + w * 0.24, y + h * 0.24, w * 0.52, h * 0.52))
        p.moveTo(x + w * 0.5, y)
        p.lineTo(x + w * 0.5, y + h * 0.16)
        p.moveTo(x + w * 0.5, y + h * 0.84)
        p.lineTo(x + w * 0.5, y + h)
        p.moveTo(x, y + h * 0.5)
        p.lineTo(x + w * 0.16, y + h * 0.5)
        p.moveTo(x + w * 0.84, y + h * 0.5)
        p.lineTo(x + w, y + h * 0.5)
        extra.append(QRectF(x + w * 0.43, y + h * 0.43, w * 0.14, h * 0.14))
    elif name == "profiles":
        p.addRoundedRect(QRectF(x + w * 0.1, y, w * 0.8, h * 0.62), h * 0.14, h * 0.14)
        p.addRoundedRect(QRectF(x, y + h * 0.28, w * 0.8, h * 0.62), h * 0.14, h * 0.14)
    elif name == "activity":
        p.moveTo(x, y + h * 0.55)
        p.lineTo(x + w * 0.2, y + h * 0.55)
        p.lineTo(x + w * 0.32, y + h * 0.22)
        p.lineTo(x + w * 0.46, y + h * 0.82)
        p.lineTo(x + w * 0.6, y + h * 0.42)
        p.lineTo(x + w * 0.7, y + h * 0.55)
        p.lineTo(x + w, y + h * 0.55)
    elif name == "wave":
        for offset, height in ((0.12, 0.24), (0.32, 0.6), (0.5, 0.92), (0.68, 0.52), (0.88, 0.3)):
            cx = x + w * offset
            p.moveTo(cx, y + h * (0.5 - height / 2))
            p.lineTo(cx, y + h * (0.5 + height / 2))
    elif name == "settings":
        p.addEllipse(QRectF(x + w * 0.3, y + h * 0.3, w * 0.4, h * 0.4))
        for angle in range(0, 360, 45):
            import math

            rad = math.radians(angle)
            cx, cy = x + w / 2, y + h / 2
            p.moveTo(cx + math.cos(rad) * w * 0.3, cy + math.sin(rad) * h * 0.3)
            p.lineTo(cx + math.cos(rad) * w * 0.46, cy + math.sin(rad) * h * 0.46)
    elif name == "search":
        p.addEllipse(QRectF(x, y, w * 0.68, h * 0.68))
        p.moveTo(x + w * 0.62, y + h * 0.62)
        p.lineTo(x + w, y + h)
    elif name == "plus":
        p.moveTo(x + w / 2, y + h * 0.14)
        p.lineTo(x + w / 2, y + h * 0.86)
        p.moveTo(x + w * 0.14, y + h / 2)
        p.lineTo(x + w * 0.86, y + h / 2)
    elif name == "close":
        p.moveTo(x + w * 0.18, y + h * 0.18)
        p.lineTo(x + w * 0.82, y + h * 0.82)
        p.moveTo(x + w * 0.82, y + h * 0.18)
        p.lineTo(x + w * 0.18, y + h * 0.82)
    elif name == "minimize":
        p.moveTo(x + w * 0.14, y + h * 0.6)
        p.lineTo(x + w * 0.86, y + h * 0.6)
    elif name == "maximize":
        p.addRoundedRect(QRectF(x + w * 0.16, y + h * 0.16, w * 0.68, h * 0.68), 2.5, 2.5)
    elif name == "restore":
        p.addRoundedRect(QRectF(x + w * 0.12, y + h * 0.3, w * 0.58, h * 0.58), 2.5, 2.5)
        p.moveTo(x + w * 0.3, y + h * 0.22)
        p.lineTo(x + w * 0.86, y + h * 0.22)
        p.lineTo(x + w * 0.86, y + h * 0.72)
    elif name == "edit":
        p.moveTo(x + w * 0.14, y + h * 0.86)
        p.lineTo(x + w * 0.2, y + h * 0.58)
        p.lineTo(x + w * 0.7, y + h * 0.08)
        p.lineTo(x + w * 0.92, y + h * 0.3)
        p.lineTo(x + w * 0.42, y + h * 0.8)
        p.closeSubpath()
    elif name == "trash":
        p.moveTo(x + w * 0.14, y + h * 0.22)
        p.lineTo(x + w * 0.86, y + h * 0.22)
        p.moveTo(x + w * 0.36, y + h * 0.22)
        p.lineTo(x + w * 0.36, y + h * 0.1)
        p.lineTo(x + w * 0.64, y + h * 0.1)
        p.lineTo(x + w * 0.64, y + h * 0.22)
        p.moveTo(x + w * 0.22, y + h * 0.22)
        p.lineTo(x + w * 0.28, y + h * 0.92)
        p.lineTo(x + w * 0.72, y + h * 0.92)
        p.lineTo(x + w * 0.78, y + h * 0.22)
        p.moveTo(x + w * 0.44, y + h * 0.4)
        p.lineTo(x + w * 0.44, y + h * 0.76)
        p.moveTo(x + w * 0.58, y + h * 0.4)
        p.lineTo(x + w * 0.58, y + h * 0.76)
    elif name == "copy":
        p.addRoundedRect(QRectF(x + w * 0.06, y + h * 0.06, w * 0.6, h * 0.6), 3, 3)
        p.addRoundedRect(QRectF(x + w * 0.34, y + h * 0.34, w * 0.6, h * 0.6), 3, 3)
    elif name == "play":
        p.moveTo(x + w * 0.28, y + h * 0.14)
        p.lineTo(x + w * 0.86, y + h * 0.5)
        p.lineTo(x + w * 0.28, y + h * 0.86)
        p.closeSubpath()
    elif name == "pause":
        p.addRoundedRect(QRectF(x + w * 0.2, y + h * 0.14, w * 0.2, h * 0.72), 2, 2)
        p.addRoundedRect(QRectF(x + w * 0.6, y + h * 0.14, w * 0.2, h * 0.72), 2, 2)
    elif name == "check":
        p.moveTo(x + w * 0.12, y + h * 0.54)
        p.lineTo(x + w * 0.4, y + h * 0.82)
        p.lineTo(x + w * 0.88, y + h * 0.2)
    elif name == "alert":
        p.moveTo(x + w * 0.5, y + h * 0.08)
        p.lineTo(x + w * 0.94, y + h * 0.88)
        p.lineTo(x + w * 0.06, y + h * 0.88)
        p.closeSubpath()
        p.moveTo(x + w * 0.5, y + h * 0.38)
        p.lineTo(x + w * 0.5, y + h * 0.62)
        extra.append(QRectF(x + w * 0.46, y + h * 0.7, w * 0.08, h * 0.08))
    elif name == "power":
        p.moveTo(x + w * 0.5, y + h * 0.08)
        p.lineTo(x + w * 0.5, y + h * 0.42)
        arc = QRectF(x + w * 0.12, y + h * 0.16, w * 0.76, h * 0.76)
        p.arcMoveTo(arc, 130)
        p.arcTo(arc, 130, -260)
    elif name == "chevron-down":
        p.moveTo(x + w * 0.2, y + h * 0.36)
        p.lineTo(x + w * 0.5, y + h * 0.66)
        p.lineTo(x + w * 0.8, y + h * 0.36)
    elif name == "chevron-up":
        p.moveTo(x + w * 0.2, y + h * 0.64)
        p.lineTo(x + w * 0.5, y + h * 0.34)
        p.lineTo(x + w * 0.8, y + h * 0.64)
    elif name == "arrow-right":
        p.moveTo(x + w * 0.12, y + h * 0.5)
        p.lineTo(x + w * 0.86, y + h * 0.5)
        p.moveTo(x + w * 0.6, y + h * 0.24)
        p.lineTo(x + w * 0.86, y + h * 0.5)
        p.lineTo(x + w * 0.6, y + h * 0.76)
    elif name == "download":
        p.moveTo(x + w * 0.5, y + h * 0.08)
        p.lineTo(x + w * 0.5, y + h * 0.62)
        p.moveTo(x + w * 0.22, y + h * 0.38)
        p.lineTo(x + w * 0.5, y + h * 0.66)
        p.lineTo(x + w * 0.78, y + h * 0.38)
        p.moveTo(x + w * 0.14, y + h * 0.86)
        p.lineTo(x + w * 0.86, y + h * 0.86)
    elif name == "upload":
        p.moveTo(x + w * 0.5, y + h * 0.66)
        p.lineTo(x + w * 0.5, y + h * 0.12)
        p.moveTo(x + w * 0.22, y + h * 0.4)
        p.lineTo(x + w * 0.5, y + h * 0.12)
        p.lineTo(x + w * 0.78, y + h * 0.4)
        p.moveTo(x + w * 0.14, y + h * 0.86)
        p.lineTo(x + w * 0.86, y + h * 0.86)
    elif name == "record":
        extra.append(QRectF(x + w * 0.24, y + h * 0.24, w * 0.52, h * 0.52))
    elif name == "external":
        p.moveTo(x + w * 0.4, y + h * 0.18)
        p.lineTo(x + w * 0.84, y + h * 0.18)
        p.lineTo(x + w * 0.84, y + h * 0.62)
        p.moveTo(x + w * 0.84, y + h * 0.18)
        p.lineTo(x + w * 0.42, y + h * 0.6)
        p.moveTo(x + w * 0.22, y + h * 0.4)
        p.lineTo(x + w * 0.14, y + h * 0.4)
        p.lineTo(x + w * 0.14, y + h * 0.88)
        p.lineTo(x + w * 0.62, y + h * 0.88)
        p.lineTo(x + w * 0.62, y + h * 0.8)
    elif name == "pause-circle":
        p.addEllipse(QRectF(x, y, w, h))
        p.moveTo(x + w * 0.4, y + h * 0.32)
        p.lineTo(x + w * 0.4, y + h * 0.68)
        p.moveTo(x + w * 0.6, y + h * 0.32)
        p.lineTo(x + w * 0.6, y + h * 0.68)
    elif name == "app":
        p.addRoundedRect(QRectF(x + w * 0.08, y + h * 0.12, w * 0.84, h * 0.76), 3, 3)
        p.moveTo(x + w * 0.08, y + h * 0.34)
        p.lineTo(x + w * 0.92, y + h * 0.34)
        p.moveTo(x + w * 0.26, y + h * 0.6)
        p.lineTo(x + w * 0.74, y + h * 0.6)
        p.moveTo(x + w * 0.26, y + h * 0.74)
        p.lineTo(x + w * 0.56, y + h * 0.74)
    elif name == "logo":
        p.moveTo(x + w * 0.24, y + h * 0.78)
        p.lineTo(x + w * 0.5, y + h * 0.2)
        p.lineTo(x + w * 0.76, y + h * 0.78)
        p.moveTo(x + w * 0.34, y + h * 0.58)
        p.lineTo(x + w * 0.66, y + h * 0.58)
    return p, extra


def icon_pixmap(name: str, tint: str = "#EDEFF9", size: int = 20, width: float = 1.7) -> QPixmap:
    key = (name, tint, size, width)
    if key in _CACHE:
        return _CACHE[key]
    from app.ui.theme import palette

    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # The pixmap carries a device pixel ratio, so painting happens in logical
    # coordinates (0..size) and Qt scales it for the screen automatically.
    pad = size * 0.12
    rect = QRectF(pad, pad, size - pad * 2, size - pad * 2)
    path, extra = _path(name, rect)
    pen = QPen(color(tint))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if name in {"play", "pause"}:
        painter.setBrush(color(tint))
    painter.drawPath(path)
    if extra:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color(tint))
        for shape in extra:
            painter.drawEllipse(shape)
    painter.end()
    _CACHE[key] = pixmap
    return pixmap


def icon(name: str, tint: str = "#EDEFF9", size: int = 20, width: float = 1.7) -> QIcon:
    return QIcon(icon_pixmap(name, tint, size, width))


def app_icon(size: int = 256) -> QIcon:
    """The Amue KeyFlow application icon, drawn at any resolution."""
    from PySide6.QtGui import QLinearGradient

    from app.constants import ACCENTS

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor(ACCENTS["violet"]["primary"]))
    gradient.setColorAt(0.55, QColor("#6F5BF6"))
    gradient.setColorAt(1.0, QColor("#3BC8E0"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    painter.setBrush(QColor(255, 255, 255, 235))
    key_rect = QRectF(size * 0.22, size * 0.22, size * 0.56, size * 0.56)
    painter.drawRoundedRect(key_rect, size * 0.14, size * 0.14)
    painter.setBrush(QColor(12, 14, 28))
    letter_rect = QRectF(size * 0.28, size * 0.2, size * 0.44, size * 0.6)
    font = painter.font()
    font.setPixelSize(int(size * 0.4))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#0B0D1B"))
    painter.drawText(letter_rect, Qt.AlignCenter, "A")
    painter.end()
    return QIcon(pixmap)


def clear_cache() -> None:
    _CACHE.clear()
