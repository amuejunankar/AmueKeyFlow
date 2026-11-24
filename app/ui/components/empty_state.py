"""Empty state placeholder with an optional call to action."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.components.buttons import make_button
from app.ui.icons import icon_pixmap
from app.ui.theme import color, palette


class _IconHalo(QWidget):
    def __init__(self, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._icon = icon_name
        self.setFixedSize(64, 64)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0, 0, 64, 64)
        painter.setBrush(color(p["accent"]["primary"], 26))
        painter.setPen(color(p["accent"]["primary"], 70))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)
        painter.drawPixmap(22, 22, icon_pixmap(self._icon, p["accent"]["primary"] if not p["is_dark"] else p["accent"]["secondary"], 20, 1.6))
        painter.end()


class EmptyState(QWidget):
    def __init__(
        self,
        icon_name: str,
        title: str,
        description: str,
        action_text: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 28, 20, 28)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(_IconHalo(icon_name), 0, Qt.AlignHCenter)
        self.title = QLabel(title)
        self.title.setObjectName("EmptyTitle")
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)
        self.description = QLabel(description)
        self.description.setProperty("muted", True)
        self.description.setAlignment(Qt.AlignCenter)
        self.description.setWordWrap(True)
        self.description.setMinimumWidth(420)
        self.description.setMaximumWidth(470)
        policy = self.description.sizePolicy()
        policy.setHeightForWidth(True)
        self.description.setSizePolicy(policy)
        layout.addWidget(self.description, 0, Qt.AlignHCenter)
        self.action: QPushButton | None = None
        if action_text:
            self.action = make_button(action_text, "primary", "plus")
            layout.addSpacing(6)
            layout.addWidget(self.action, 0, Qt.AlignHCenter)
        layout.addStretch(1)

    def set_text(self, title: str, description: str) -> None:
        self.title.setText(title)
        self.description.setText(description)
