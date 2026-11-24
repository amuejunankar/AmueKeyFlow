"""Dashboard overview page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.ui.base_page import ScrollPage
from app.ui.components.buttons import make_button
from app.ui.components.cards import SectionCard, StatCard
from app.ui.components.chips import Pill
from app.ui.components.empty_state import EmptyState
from app.ui.components.mapping_row import MappingRow
from app.ui.components.toggle import ToggleSwitch


class DashboardPage(ScrollPage):
    title = "Dashboard"
    subtitle = "Overview of your keyboard workspace"

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self._syncing = False
        self.layout_main.setSpacing(16)

        stats = QGridLayout()
        stats.setSpacing(16)
        self.total_card = StatCard("Mappings", "keyboard")
        self.profile_card = StatCard("Active profile", "profiles")
        self.status_card = StatCard("Status", "power")
        for index, card in enumerate((self.total_card, self.profile_card, self.status_card)):
            stats.addWidget(card, 0, index)
            stats.setColumnStretch(index, 1)
        self.layout_main.addLayout(stats)

        columns = QHBoxLayout()
        columns.setSpacing(18)

        self.recent_card = SectionCard("Recent mappings", "Last created or edited")
        self.create_button = make_button("New mapping", "primary", "plus")
        self.create_button.clicked.connect(self.controller.create_mapping)
        self.recent_card.add_trailing(self.create_button)
        self.recent_body = self.recent_card.body
        self.recent_empty = EmptyState(
            "keyboard",
            "No mappings yet",
            "Create your first mapping to get started.",
            "Create your first mapping",
        )
        self.recent_empty.action.clicked.connect(self.controller.create_mapping)
        self.recent_body.addWidget(self.recent_empty)
        self.recent_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        columns.addWidget(self.recent_card, 3)

        side = QVBoxLayout()
        side.setSpacing(16)
        engine_card = SectionCard("Engine", "Live status")
        self.engine_pill = Pill("STARTING", "muted", compact=True)
        engine_card.add_trailing(self.engine_pill)
        self.engine_text = QLabel("")
        self.engine_text.setProperty("muted", True)
        self.engine_text.setWordWrap(True)
        engine_card.body.addWidget(self.engine_text)
        hotkey = QLabel("CTRL+ALT+SHIFT+F12 stops interception instantly.")
        hotkey.setProperty("muted", True)
        hotkey.setWordWrap(True)
        engine_card.body.addWidget(hotkey)
        self.emergency_button = make_button("Emergency stop", "danger", "power")
        self.emergency_button.setToolTip("Disable interception immediately and restore the normal keyboard")
        self.emergency_button.clicked.connect(self.controller.emergency_stop)
        engine_card.body.addWidget(self.emergency_button)
        side.addWidget(engine_card, 0, Qt.AlignTop)

        caffeine_card = SectionCard("Caffeine", "Keep the screen awake")
        self.caffeine_pill = Pill("OFF", "muted", compact=True)
        caffeine_card.add_trailing(self.caffeine_pill)
        caffeine_row = QWidget()
        caffeine_layout = QHBoxLayout(caffeine_row)
        caffeine_layout.setContentsMargins(0, 0, 0, 0)
        caffeine_layout.setSpacing(12)
        self.caffeine_text = QLabel("")
        self.caffeine_text.setProperty("muted", True)
        self.caffeine_text.setWordWrap(True)
        caffeine_layout.addWidget(self.caffeine_text, 1)
        self.caffeine_toggle = ToggleSwitch(False)
        self.caffeine_toggle.toggled.connect(self._on_caffeine_toggled)
        caffeine_layout.addWidget(self.caffeine_toggle)
        caffeine_card.body.addWidget(caffeine_row)
        side.addWidget(caffeine_card, 0, Qt.AlignTop)
        side.addStretch(1)
        columns.addLayout(side, 1)

        self.layout_main.addLayout(columns, 1)

    def refresh(self) -> None:
        total, active = self.controller.db.count_mappings()
        self.total_card.set_value(str(total), f"{active} enabled")
        profile = self.controller.profiles.active
        self.profile_card.set_value(profile.name, f"{len(self.controller.profiles.active_mappings())} mapping(s)")

        status = self.controller.engine.status()
        if status["emergency"]:
            self.status_card.set_value("Stopped", "Emergency stop active")
            self.engine_pill.set_text("STOPPED")
            self.engine_pill.set_tone("danger")
            self.engine_text.setText("Interception is off and your keyboard is back to normal. Recover the engine from Settings.")
        elif status["running"] and status["enabled"] and not status["paused"]:
            self.status_card.set_value("Running", "Mappings are live")
            self.engine_pill.set_text("LIVE")
            self.engine_pill.set_tone("success")
            self.engine_text.setText(f"Hook active · {active} mapping(s) firing in {profile.name}.")
        elif status["running"] and status["paused"]:
            self.status_card.set_value("Paused", "Keys pass through")
            self.engine_pill.set_text("PAUSED")
            self.engine_pill.set_tone("warning")
            self.engine_text.setText("Mappings are paused until you resume them from the top bar.")
        elif status["running"]:
            self.status_card.set_value("Idle", "Mappings disabled")
            self.engine_pill.set_text("IDLE")
            self.engine_pill.set_tone("warning")
            self.engine_text.setText("The hook is running but all mappings are disabled.")
        else:
            self.status_card.set_value("Stopped", "Keyboard hook idle")
            self.engine_pill.set_text("OFFLINE")
            self.engine_pill.set_tone("muted")
            self.engine_text.setText(status["error"][:120] or "The keyboard hook is not running. Enable the engine in Settings.")

        self._sync_caffeine()
        self._refresh_recent()

    def _on_caffeine_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        self.controller.set_caffeine(bool(checked))

    def _sync_caffeine(self) -> None:
        power = self.controller.power
        enabled = power.is_enabled()
        self._syncing = True
        try:
            self.caffeine_toggle.setChecked(enabled, animate=False)
        finally:
            self._syncing = False
        self.caffeine_pill.set_text("ON" if enabled else "OFF")
        self.caffeine_pill.set_tone("success" if enabled else "muted")
        self.caffeine_text.setText(
            "The display and this computer stay awake until you switch it off."
            if enabled
            else "Stops Windows from turning off the display or sleeping while you work."
        )

    def _refresh_recent(self) -> None:
        while self.recent_body.count():
            item = self.recent_body.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.recent_empty:
                widget.deleteLater()
        recent = self.controller.db.recent_mappings(5)
        self.recent_empty.setVisible(not recent)
        if not recent:
            self.recent_body.addWidget(self.recent_empty)
            return
        for mapping in recent:
            row = MappingRow(self.controller, mapping, actions=("edit", "delete"))
            self.recent_body.addWidget(row)
