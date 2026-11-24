"""Activity page: recent mapping triggers."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.database.models import ActivityEntry
from app.ui.base_page import BasePage
from app.ui.components.buttons import make_button
from app.ui.components.chips import Pill
from app.ui.components.dialogs import ConfirmDialog
from app.ui.components.empty_state import EmptyState
from app.ui.theme import color, palette


class ActivityRow(QWidget):
    def __init__(self, entry: ActivityEntry, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(62)
        self._hover = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        time_box = QVBoxLayout()
        time_box.setSpacing(1)
        try:
            stamp = datetime.fromisoformat(entry.timestamp).astimezone().strftime("%d %b · %H:%M:%S")
        except ValueError:
            stamp = entry.timestamp
        time_label = QLabel(stamp)
        font = time_label.font()
        font.setPointSizeF(9.2)
        font.setWeight(QFont.DemiBold)
        time_label.setFont(font)
        time_box.addWidget(time_label)
        status = QLabel(entry.status.upper())
        status.setProperty("muted", True)
        font2 = status.font()
        font2.setPointSizeF(8.0)
        font2.setLetterSpacing(QFont.PercentageSpacing, 110)
        status.setFont(font2)
        time_box.addWidget(status)
        layout.addLayout(time_box)

        name_box = QVBoxLayout()
        name_box.setSpacing(1)
        name = QLabel(entry.mapping_name or "Unnamed mapping")
        name_font = name.font()
        name_font.setWeight(QFont.DemiBold)
        name.setFont(name_font)
        name_box.addWidget(name)
        detail = QLabel(entry.detail or f"{entry.input_text} → {entry.output_text}")
        detail.setProperty("muted", True)
        detail_font = detail.font()
        detail_font.setPointSizeF(8.8)
        detail.setFont(detail_font)
        name_box.addWidget(detail)
        layout.addLayout(name_box, 1)

        pill = Pill("SUCCESS" if entry.status == "success" else "FAILED", "success" if entry.status == "success" else "danger")
        layout.addWidget(pill)

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 2, -0.5, -2)
        painter.setBrush(color(p["white"], 24 if self._hover else (12 if p["is_dark"] else 6)))
        painter.setPen(QPen(color(p["white"], 20 if self._hover else 12), 1))
        painter.drawRoundedRect(rect, 12, 12)
        painter.end()


class ActivityPage(BasePage):
    title = "Activity"
    subtitle = "Recent mapping events for troubleshooting"

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 8, 28, 24)
        layout.setSpacing(14)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search activity…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(lambda _: self.refresh())
        toolbar.addWidget(self.search)
        toolbar.addStretch(1)

        clear = make_button("Clear history", "ghost", "trash")
        clear.clicked.connect(self._clear)
        toolbar.addWidget(clear)
        layout.addLayout(toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.container.setAttribute(Qt.WA_StyledBackground, False)
        self.rows = QVBoxLayout(self.container)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.rows.setSpacing(6)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

        self.empty = EmptyState(
            "activity",
            "Nothing logged yet",
            "Trigger a mapping to see it here.",
        )
        layout.addWidget(self.empty, 1)
        self.empty.setVisible(False)

    def _clear(self) -> None:
        if ConfirmDialog.ask(
            self,
            "Clear activity history?",
            "This removes every logged mapping event. Your mappings are not affected.",
            "Clear history",
            danger=True,
        ):
            self.controller.activity.clear()
            self.refresh()

    def refresh(self) -> None:
        logging_enabled = self.controller.settings.get_bool("activity_logging", True)

        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        entries = self.controller.activity.entries(limit=200, search=self.search.text().strip())
        self.empty.setVisible(not entries)
        self.scroll.setVisible(bool(entries))
        if not entries:
            if not logging_enabled:
                self.empty.set_text(
                    "Activity logging is off",
                    "Turn logging on to record mapping events for troubleshooting.",
                )
            elif self.search.text().strip():
                self.empty.set_text("No matches", "Try a different search.")
            else:
                self.empty.set_text("Nothing logged yet", "Trigger a mapping to see it here.")
            return
        for entry in entries:
            self.rows.addWidget(ActivityRow(entry))
        self.rows.addStretch(1)
