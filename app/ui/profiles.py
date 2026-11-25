"""Profile management page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from app.ui.base_page import ScrollPage
from app.ui.components.buttons import IconButton, make_button
from app.ui.components.cards import GlassCard, IconBadge
from app.ui.components.chips import Pill
from app.ui.components.dialogs import ConfirmDialog, FramelessSheet, Toast
from app.ui.components.toggle import ToggleSwitch
from app.ui.theme import palette


class ProfileDialog(FramelessSheet):
    def __init__(self, parent: QWidget | None, title: str, name: str = "", description: str = ""):
        super().__init__(parent, title, "Profiles keep their own mappings and settings.", width=460)
        self.result: tuple[str, str] | None = None
        name_label = QLabel("PROFILE NAME")
        name_label.setObjectName("FieldLabel")
        self.body.addWidget(name_label)
        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText("e.g. Gaming")
        self.body.addWidget(self.name_input)
        desc_label = QLabel("DESCRIPTION")
        desc_label.setObjectName("FieldLabel")
        self.body.addWidget(desc_label)
        self.description_input = QLineEdit(description)
        self.description_input.setPlaceholderText("Optional")
        self.body.addWidget(self.description_input)
        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {palette()['danger']}; font-size: 11.5px;")
        self.error.setVisible(False)
        self.body.addWidget(self.error)
        self.footer.addStretch(1)
        cancel = self.add_footer_button("Cancel")
        cancel.clicked.connect(self.reject)
        save = self.add_footer_button("Save", "primary")
        save.clicked.connect(self._save)
        save.setDefault(True)
        self.name_input.setFocus()

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.error.setText("Enter a profile name.")
            self.error.setVisible(True)
            return
        self.result = (name, self.description_input.text().strip())
        self.accept()

    @staticmethod
    def ask(parent, title: str, name: str = "", description: str = ""):
        dialog = ProfileDialog(parent, title, name, description)
        dialog.center_on_parent()
        if dialog.exec() == dialog.Accepted:
            return dialog.result
        return None


class AppOverrideDialog(FramelessSheet):
    """Pick the application that gets its own extra mappings."""

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(
            parent,
            "New app override",
            "Extra mappings that apply only while this app is in front.",
            width=520,
        )
        self.controller = controller
        self.result: tuple[str, str] | None = None
        self._last_app = (
            getattr(controller.foreground, "last_external", "") if hasattr(controller, "foreground") else ""
        )

        self.app_combo = QComboBox()
        self.app_combo.setEditable(True)
        self.app_combo.setInsertPolicy(QComboBox.NoInsert)
        apps: list[str] = []
        if hasattr(controller, "foreground"):
            apps = controller.foreground.running_apps()
        if self._last_app and self._last_app not in apps:
            apps.insert(0, self._last_app)
        apps = sorted(set(apps))
        self.app_combo.addItems(apps)
        if self._last_app in apps:
            self.app_combo.setCurrentIndex(apps.index(self._last_app))
        self.body.addWidget(self.app_combo)

        if self._last_app:
            hint_text = f"Your last active app is {self._last_app} — it is preselected."
        else:
            hint_text = "Pick a running app or type its .exe name."
        hint = QLabel(hint_text)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.body.addWidget(hint)

        name_label = QLabel("NAME (OPTIONAL)")
        name_label.setObjectName("FieldLabel")
        self.body.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Figma shortcuts")
        self.body.addWidget(self.name_input)

        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {palette()['danger']}; font-size: 11.5px;")
        self.error.setVisible(False)
        self.body.addWidget(self.error)

        self.footer.addStretch(1)
        cancel = self.add_footer_button("Cancel")
        cancel.clicked.connect(self.reject)
        create = self.add_footer_button("Create override", "primary")
        create.clicked.connect(self._create)
        create.setDefault(True)

    def _create(self) -> None:
        text = self.app_combo.currentText().strip()
        if not text:
            self.error.setText("Choose or type an application name first.")
            self.error.setVisible(True)
            return
        self.result = (text, self.name_input.text().strip())
        self.accept()


class AppRulesDialog(FramelessSheet):
    """Manage the applications that auto-activate a profile."""

    def __init__(self, controller, profile, parent: QWidget | None = None):
        super().__init__(
            parent,
            f"App rules — {profile.name}",
            "Switch to this profile automatically when one of these apps is in front.",
            width=540,
        )
        self.controller = controller
        self.profile = profile
        self._last_app = getattr(controller.foreground, "last_external", "") if hasattr(controller, "foreground") else ""

        picker = QHBoxLayout()
        picker.setSpacing(8)
        self.app_combo = QComboBox()
        self.app_combo.setEditable(True)
        self.app_combo.setInsertPolicy(QComboBox.NoInsert)
        apps: list[str] = []
        if hasattr(controller, "foreground"):
            apps = controller.foreground.running_apps()
        if self._last_app and self._last_app not in apps:
            apps.insert(0, self._last_app)
        apps = sorted(set(apps))
        self.app_combo.addItems(apps)
        if self._last_app in apps:
            self.app_combo.setCurrentIndex(apps.index(self._last_app))
        picker.addWidget(self.app_combo, 1)
        add_button = make_button("Add app", "primary", "plus")
        add_button.clicked.connect(self._add)
        picker.addWidget(add_button)
        self.body.addLayout(picker)

        if self._last_app:
            hint = f"Your last active app is {self._last_app} — it is preselected."
        else:
            hint = "Switch to the app you want, then reopen this window to preselect it, or type its .exe name."
        hint_label = QLabel(hint)
        hint_label.setObjectName("Hint")
        hint_label.setWordWrap(True)
        self.body.addWidget(hint_label)

        override_note = QLabel(
            "App overrides on the Key Mapper page are different: they keep this profile "
            "and only change the keys they list, and they win for those keys."
        )
        override_note.setObjectName("Hint")
        override_note.setWordWrap(True)
        self.body.addWidget(override_note)

        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {palette()['danger']}; font-size: 11.5px;")
        self.error.setVisible(False)
        self.body.addWidget(self.error)

        self.rules_host = QWidget()
        self.rules_layout = QVBoxLayout(self.rules_host)
        self.rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_layout.setSpacing(6)
        self.body.addWidget(self.rules_host)

        self.footer.addStretch(1)
        done = self.add_footer_button("Done", "primary")
        done.clicked.connect(self.accept)
        self._reload()

    def _reload(self) -> None:
        while self.rules_layout.count():
            item = self.rules_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        rules = self.controller.profiles.app_rules(self.profile.id)
        if not rules:
            empty = QLabel("No app rules yet. Add the app that should activate this profile.")
            empty.setProperty("muted", True)
            empty.setWordWrap(True)
            self.rules_layout.addWidget(empty)
            return
        for rule in rules:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            layout.addWidget(IconBadge("app", 28))
            label = QLabel(rule.executable)
            label.setToolTip("Auto-switches to this profile when this app is in the foreground")
            layout.addWidget(label, 1)
            remove = IconButton("trash", tooltip="Remove rule", size=26, icon_size=14, danger=True)
            remove.clicked.connect(lambda _=False, rule_id=rule.id: self._remove(rule_id))
            layout.addWidget(remove)
            self.rules_layout.addWidget(row)

    def _add(self) -> None:
        text = self.app_combo.currentText().strip()
        if not text:
            self._show_error("Choose or type an application name first.")
            return
        try:
            self.controller.profiles.add_app_rule(self.profile.id, text)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self.error.setVisible(False)
        self._reload()

    def _remove(self, rule_id: str) -> None:
        self.controller.profiles.remove_app_rule(rule_id)
        self.error.setVisible(False)
        self._reload()

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)


class ProfileCard(GlassCard):
    def __init__(
        self,
        controller,
        profile,
        mapping_count: int,
        is_active: bool,
        rules_count: int = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent, radius=16, hoverable=True)
        self.controller = controller
        self.profile = profile
        self.setFixedHeight(84)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 16, 14)
        layout.setSpacing(14)

        layout.addWidget(IconBadge("profiles", 40))

        titles = QVBoxLayout()
        titles.setSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel(profile.name)
        from PySide6.QtGui import QFont

        font = name.font()
        font.setPointSizeF(11.0)
        font.setWeight(QFont.DemiBold)
        name.setFont(font)
        name_row.addWidget(name)
        if is_active:
            name_row.addWidget(Pill("ACTIVE", "success", compact=True), 0, Qt.AlignVCenter)
        name_row.addStretch(1)
        titles.addLayout(name_row)
        description = QLabel(profile.description or "No description")
        description.setProperty("muted", True)
        titles.addWidget(description)
        layout.addLayout(titles, 1)

        rules_text = (
            f"{rules_count} app rule{'s' if rules_count != 1 else ''}"
            if rules_count
            else "No app rules"
        )
        stats = QLabel(f"{mapping_count} mapping{'s' if mapping_count != 1 else ''} · {rules_text}")
        stats.setProperty("muted", True)
        stats.setToolTip("Mappings in this profile and apps that auto-activate it")
        layout.addWidget(stats)

        if is_active:
            active_button = make_button("Active", "ghost", "check")
            active_button.setEnabled(False)
            active_button.setToolTip("Mappings in this profile are live")
            layout.addWidget(active_button)
        else:
            activate = make_button("Activate", "primary")
            activate.clicked.connect(lambda: controller.switch_profile(profile.id))
            layout.addWidget(activate)

        app_rules = IconButton("app", tooltip="App rules — auto-switch to this profile", size=30)
        app_rules.clicked.connect(lambda: controller.open_app_rules(profile.id))
        layout.addWidget(app_rules)

        more = make_button("···", "ghost")
        more.setToolTip("Rename, duplicate, export or delete")
        more.setFixedWidth(44)
        menu = QMenu(more)
        menu.addAction("Rename", lambda: controller.rename_profile(profile.id))
        menu.addAction("Duplicate", lambda: controller.duplicate_profile(profile.id))
        menu.addAction("Export", lambda: controller.export_profile(profile.id))
        menu.addSeparator()
        menu.addAction("Delete", lambda: controller.delete_profile(profile.id))
        more.clicked.connect(lambda: menu.exec(more.mapToGlobal(more.rect().bottomLeft())))
        layout.addWidget(more)


class ProfilesPage(ScrollPage):
    title = "Profiles"
    subtitle = "Separate mapping sets for different workflows"

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)

        header = QHBoxLayout()
        header.addStretch(1)
        self.auto_toggle = ToggleSwitch(controller.settings.get_bool("auto_switch_profiles", True))
        self.auto_toggle.setToolTip("Switch profiles automatically when a matched app is in front")
        self.auto_toggle.toggled.connect(self._on_auto_switch)
        auto_label = QLabel("Auto-switch by app")
        auto_label.setProperty("muted", True)
        header.addWidget(auto_label)
        header.addWidget(self.auto_toggle)
        header.addSpacing(12)
        new_button = make_button("New Profile", "primary", "plus")
        new_button.clicked.connect(self.controller.create_profile)
        header.addWidget(new_button)
        self.layout_main.addLayout(header)

        self.grid_host = QWidget()
        self.grid_host.setAttribute(Qt.WA_StyledBackground, False)
        self.grid = QVBoxLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.layout_main.addWidget(self.grid_host)

        self.layout_main.addStretch(1)

    def _on_auto_switch(self, enabled: bool) -> None:
        self.controller.settings.set("auto_switch_profiles", bool(enabled))
        self.controller.notify(
            "App-based profile switching enabled." if enabled else "App-based profile switching disabled.",
            "info",
        )

    def _clear(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def refresh(self) -> None:
        self._clear()
        profiles = self.controller.profiles.profiles()
        counts = self.controller.profiles.mapping_counts()
        rule_counts = self.controller.profiles.rule_counts()
        active_id = self.controller.profiles.active_id
        for profile in profiles:
            card = ProfileCard(
                self.controller,
                profile,
                counts.get(profile.id, 0),
                profile.id == active_id,
                rule_counts.get(profile.id, 0),
            )
            self.grid.addWidget(card)
