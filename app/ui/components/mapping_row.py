"""A single mapping displayed as a glass table row."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.database.models import Mapping
from app.ui.components.buttons import IconButton
from app.ui.components.chips import ChordChips, Pill
from app.ui.components.toggle import ToggleSwitch
from app.ui.icons import icon_pixmap
from app.ui.theme import color, palette


class MappingRow(QWidget):
    def __init__(
        self,
        controller,
        mapping: Mapping,
        actions: tuple[str, ...] = ("edit", "duplicate", "delete"),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.controller = controller
        self.mapping = mapping
        self._hover = False
        self._conflict = mapping.id in controller.conflict_ids()
        self.setFixedHeight(68)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(3)
        name = QLabel(mapping.name or mapping.input_display)
        font = name.font()
        font.setPointSizeF(10.2)
        font.setWeight(QFont.DemiBold)
        name.setFont(font)
        left.addWidget(name)
        self.chips = ChordChips(mapping.input_config, compact=True)
        left.addWidget(self.chips)
        layout.addLayout(left, 0)

        arrow = QLabel()
        arrow.setPixmap(icon_pixmap("arrow-right", palette()["faint"], 15, 1.6))
        layout.addWidget(arrow, 0)

        output_box = QVBoxLayout()
        output_box.setSpacing(3)
        output = QLabel(mapping.output_display)
        output.setToolTip(mapping.output_display)
        font2 = output.font()
        font2.setPointSizeF(9.8)
        output.setFont(font2)
        output_box.addWidget(output)
        type_label = QLabel(mapping.mapping_type.upper() if mapping.mapping_type != "action" else "ACTION")
        type_label.setProperty("muted", True)
        f3 = type_label.font()
        f3.setPointSizeF(8.0)
        f3.setLetterSpacing(QFont.PercentageSpacing, 112)
        type_label.setFont(f3)
        output_box.addWidget(type_label)
        layout.addLayout(output_box, 1)

        if self._conflict:
            warning = QLabel()
            warning.setPixmap(icon_pixmap("alert", palette()["warning"], 16, 1.9))
            warning.setToolTip("Another mapping uses the same input combination")
            layout.addWidget(warning)

        if "toggle" not in actions:
            layout.addWidget(
                Pill(
                    "ON" if mapping.is_enabled else "OFF",
                    "success" if mapping.is_enabled else "muted",
                    dot=False,
                    compact=True,
                )
            )

        if "toggle" in actions:
            switch = ToggleSwitch(mapping.is_enabled)
            switch.setToolTip("Enable or disable this mapping")
            switch.toggled.connect(lambda checked, m=mapping: controller.set_mapping_enabled(m, checked))
            layout.addWidget(switch)

        if "edit" in actions:
            edit = IconButton("edit", tooltip="Edit mapping", size=30)
            edit.clicked.connect(lambda _=False, m=mapping: controller.edit_mapping(m.id))
            layout.addWidget(edit)
        if "duplicate" in actions:
            duplicate = IconButton("copy", tooltip="Duplicate mapping", size=30)
            duplicate.clicked.connect(lambda _=False, m=mapping: controller.duplicate_mapping(m.id))
            layout.addWidget(duplicate)
        if "delete" in actions:
            delete = IconButton("trash", tooltip="Delete mapping", size=30, danger=True)
            delete.clicked.connect(lambda _=False, m=mapping: controller.delete_mapping(m.id))
            layout.addWidget(delete)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.controller.edit_mapping(self.mapping.id)
        super().mouseDoubleClickEvent(event)

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
        painter.setBrush(color(p["white"], 26 if self._hover else (12 if p["is_dark"] else 6)))
        painter.setPen(QPen(color(p["white"], p["border_alpha"] if self._hover else 14), 1))
        painter.drawRoundedRect(rect, 12, 12)
        if not self.mapping.is_enabled:
            painter.setPen(Qt.NoPen)
            painter.setBrush(color(p["white"], 4))
            painter.drawRoundedRect(rect, 12, 12)
        painter.end()
