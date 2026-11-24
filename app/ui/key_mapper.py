"""Key Mapper page: the mapping list with search, filters and actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.base_page import BasePage
from app.ui.components.buttons import make_button
from app.ui.components.cards import Banner
from app.ui.components.empty_state import EmptyState
from app.ui.components.mapping_row import MappingRow
from app.ui.icons import icon_pixmap
from app.ui.theme import palette


class KeyMapperPage(BasePage):
    title = "Key Mapper"
    subtitle = "Every mapping in the active profile"

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 8, 28, 24)
        layout.setSpacing(14)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mappings, keys or outputs…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(320)
        self.search.textChanged.connect(self._render)
        toolbar.addWidget(self.search)

        self.filter = QComboBox()
        self.filter.addItem("All mappings", "all")
        self.filter.addItem("Enabled", "enabled")
        self.filter.addItem("Disabled", "disabled")
        self.filter.addItem("Conflicts", "conflicts")
        self.filter.setFixedWidth(150)
        self.filter.currentIndexChanged.connect(self._render)
        toolbar.addWidget(self.filter)
        toolbar.addStretch(1)

        self.count_label = QLabel("0 mappings")
        self.count_label.setProperty("muted", True)
        toolbar.addWidget(self.count_label)

        self.add_button = make_button("Add New Mapping", "primary", "plus")
        self.add_button.clicked.connect(self.controller.create_mapping)
        toolbar.addWidget(self.add_button)
        layout.addLayout(toolbar)

        self.banner = Banner("Two mappings share the same input combination.", "warn")
        review = make_button("Show conflicts", "ghost")
        review.clicked.connect(self._show_conflicts)
        self.banner.add_action(review)
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

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
            "keyboard",
            "No mappings here",
            "Add a mapping to get started.",
            "Add New Mapping",
        )
        self.empty.action.clicked.connect(self.controller.create_mapping)
        layout.addWidget(self.empty, 1)
        self.empty.setVisible(False)

    def _show_conflicts(self) -> None:
        index = self.filter.findData("conflicts")
        if index >= 0:
            self.filter.setCurrentIndex(index)

    def refresh(self) -> None:
        self._render()

    def _clear(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self) -> None:
        query = self.search.text().strip().lower()
        mode = self.filter.currentData()
        mappings = self.controller.profiles.active_mappings()
        conflicts = self.controller.conflict_ids()
        visible = []
        for mapping in mappings:
            if mode == "enabled" and not mapping.is_enabled:
                continue
            if mode == "disabled" and mapping.is_enabled:
                continue
            if mode == "conflicts" and mapping.id not in conflicts:
                continue
            if query:
                haystack = " ".join(
                    [
                        mapping.name,
                        mapping.input_display,
                        mapping.output_display,
                        mapping.description,
                        mapping.mapping_type,
                    ]
                ).lower()
                if query not in haystack:
                    continue
            visible.append(mapping)

        self._clear()
        total = len(mappings)
        enabled = sum(1 for m in mappings if m.is_enabled)
        self.count_label.setText(f"{total} mapping{'s' if total != 1 else ''} · {enabled} enabled")
        self.banner.setVisible(bool(conflicts))

        if not visible:
            self.scroll.setVisible(False)
            self.empty.setVisible(True)
            if query or mode != "all":
                self.empty.set_text("No matches", "Try a different search or filter.")
            elif total == 0:
                self.empty.set_text("No mappings yet", "Add a mapping to get started.")
            else:
                self.empty.set_text("Nothing to show", "Adjust the filter to see your mappings.")
            return

        self.scroll.setVisible(True)
        self.empty.setVisible(False)
        for mapping in visible:
            self.rows.addWidget(MappingRow(self.controller, mapping, actions=("toggle", "edit", "duplicate", "delete")))
        self.rows.addStretch(1)
