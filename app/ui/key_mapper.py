"""Key Mapper page: the mapping list with search, filters and actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.engine.conflict_detector import conflicts_by_mapping
from app.ui.base_page import BasePage
from app.ui.components.buttons import IconButton, make_button
from app.ui.components.cards import Banner
from app.ui.components.empty_state import EmptyState
from app.ui.components.mapping_row import MappingRow
from app.ui.components.toggle import ToggleSwitch
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

        self._scope_override_id: str | None = None
        self._scope_guard = False
        self._toggle_guard = False

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.scope = QComboBox()
        self.scope.setFixedWidth(232)
        self.scope.setToolTip("Profile-wide mappings or one app's override")
        self.scope.currentIndexChanged.connect(self._on_scope_changed)
        toolbar.addWidget(self.scope)
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
        self.add_button.clicked.connect(lambda: self.controller.create_mapping(self._scope_override_id))
        toolbar.addWidget(self.add_button)
        layout.addLayout(toolbar)

        self.override_row = QWidget()
        override_layout = QHBoxLayout(self.override_row)
        override_layout.setContentsMargins(0, 0, 0, 0)
        override_layout.setSpacing(10)
        apply_label = QLabel("Apply this app's mappings")
        apply_label.setProperty("muted", True)
        override_layout.addWidget(apply_label)
        self.override_toggle = ToggleSwitch(True)
        self.override_toggle.setToolTip("Off keeps the app on your normal profile behaviour")
        self.override_toggle.toggled.connect(self._on_override_toggled)
        override_layout.addWidget(self.override_toggle)
        override_layout.addStretch(1)
        self.delete_override = IconButton(
            "trash", tooltip="Delete this app override", size=28, icon_size=14, danger=True
        )
        self.delete_override.clicked.connect(self._delete_override)
        override_layout.addWidget(self.delete_override)
        self.override_row.setVisible(False)
        layout.addWidget(self.override_row)

        self.scope_hint = QLabel("")
        self.scope_hint.setProperty("muted", True)
        self.scope_hint.setWordWrap(True)
        self.scope_hint.setVisible(False)
        layout.addWidget(self.scope_hint)

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
        self.empty.action.clicked.connect(lambda: self.controller.create_mapping(self._scope_override_id))
        layout.addWidget(self.empty, 1)
        self.empty.setVisible(False)

    # -- scope -------------------------------------------------------------
    def select_override(self, override_id: str | None) -> None:
        self._scope_override_id = override_id
        self._populate_scopes()
        self._render()

    def _populate_scopes(self) -> None:
        overrides = self.controller.db.list_app_overrides()
        if self._scope_override_id not in {o.id for o in overrides}:
            self._scope_override_id = None
        self._scope_guard = True
        try:
            self.scope.clear()
            self.scope.addItem(f"Profile \u00b7 {self.controller.profiles.active.name}", "")
            for override in overrides:
                suffix = "" if override.is_enabled else "  (off)"
                self.scope.addItem(f"{override.executable}{suffix}", override.id)
            self.scope.addItem("Add app override\u2026", "__add__")
            index = self.scope.findData(self._scope_override_id) if self._scope_override_id else 0
            self.scope.setCurrentIndex(max(0, index))
        finally:
            self._scope_guard = False

    def _on_scope_changed(self, _index: int) -> None:
        if self._scope_guard:
            return
        data = self.scope.currentData()
        if data == "__add__":
            self._scope_guard = True
            try:
                index = self.scope.findData(self._scope_override_id) if self._scope_override_id else 0
                self.scope.setCurrentIndex(max(0, index))
            finally:
                self._scope_guard = False
            QTimer.singleShot(0, self._prompt_new_override)
            return
        self._scope_override_id = data or None
        self._render()

    def _prompt_new_override(self) -> None:
        override_id = self.controller.add_app_override()
        self._populate_scopes()
        if override_id:
            self.select_override(override_id)
        else:
            self._render()

    def _on_override_toggled(self, checked: bool) -> None:
        if self._toggle_guard or not self._scope_override_id:
            return
        self.controller.set_app_override_enabled(self._scope_override_id, bool(checked))

    def _delete_override(self) -> None:
        override_id = self._scope_override_id
        if not override_id:
            return
        self.controller.delete_app_override(override_id)
        if self.controller.db.get_app_override(override_id) is None:
            self._scope_override_id = None
        self.refresh()

    def _sync_scope_controls(self) -> None:
        override = (
            self.controller.db.get_app_override(self._scope_override_id)
            if self._scope_override_id
            else None
        )
        self.override_row.setVisible(override is not None)
        self.scope_hint.setVisible(override is not None)
        if override is None:
            self._set_page_subtitle("Every mapping in the active profile")
            return
        self.scope_hint.setText(
            f"These mappings apply only while {override.executable} is in front. "
            "Where the profile maps the same key, this one wins."
        )
        self._set_page_subtitle(f"Mappings applied only in {override.executable}")
        self._toggle_guard = True
        try:
            self.override_toggle.setChecked(override.is_enabled, animate=False)
        finally:
            self._toggle_guard = False

    def _set_page_subtitle(self, subtitle: str) -> None:
        window = getattr(self.controller, "window", None)
        if window is None or window.current_page_key != "mapper":
            return
        window.topbar.set_page("Key Mapper", subtitle)

    def _show_conflicts(self) -> None:
        index = self.filter.findData("conflicts")
        if index >= 0:
            self.filter.setCurrentIndex(index)

    def refresh(self) -> None:
        self._populate_scopes()
        self._render()

    def _clear(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hide immediately: deferred deletion happens at the next event-loop
                # return, and until then a removed row would still paint over the new one.
                widget.hide()
                widget.deleteLater()

    def _render(self) -> None:
        query = self.search.text().strip().lower()
        mode = self.filter.currentData()
        mappings = self.controller.mappings_for_scope(self._scope_override_id)
        conflicts = conflicts_by_mapping(mappings)
        self._sync_scope_controls()
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
