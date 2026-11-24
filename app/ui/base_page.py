"""Common page behaviour."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget


class BasePage(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("Page")
        self.setAttribute(Qt.WA_StyledBackground, False)

    def refresh(self) -> None:  # pragma: no cover - overridden
        pass

    def on_shown(self) -> None:
        self.refresh()


class ScrollPage(BasePage):
    """Page whose content lives inside a scroll area."""

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setAttribute(Qt.WA_StyledBackground, False)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)
        self.layout_main = QVBoxLayout(self.content)
        self.layout_main.setContentsMargins(28, 8, 28, 26)
        self.layout_main.setSpacing(18)
