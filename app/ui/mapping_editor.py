"""Create and edit mappings: trigger, output and options."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.constants import MAPPING_TYPES, TRIGGER_BEHAVIORS, WINDOWS_ACTIONS
from app.database.models import Mapping, new_id, utc_now
from app.engine.conflict_detector import has_conflict
from app.engine.keycodes import (
    KEY_LIST,
    chord_display,
    make_chord,
    normalize_mods,
    validate_chord,
)
from app.engine.output_spec import (
    describe_macro_step,
    describe_output,
    validate_macro_step,
    validate_output,
)
from app.ui.components.buttons import IconButton, make_button
from app.ui.components.cards import SectionCard
from app.ui.components.chips import ChordChips
from app.ui.components.dialogs import ConfirmDialog, FramelessSheet
from app.ui.components.toggle import ToggleSwitch
from app.ui.theme import key_popup_stylesheet, palette

MODIFIER_CHOICES = [("ctrl", "CTRL"), ("shift", "SHIFT"), ("alt", "ALT"), ("win", "WIN")]


class _RecorderBridge(QObject):
    captured = Signal(object)
    timed_out = Signal()
    progress = Signal(object)


class KeySelector(QComboBox):
    """Searchable key picker covering letters, F1-F24, navigation, media."""

    def __init__(self, placeholder: str = "Select a key…", parent: QWidget | None = None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(16)
        self.lineEdit().setPlaceholderText(placeholder)
        for info in KEY_LIST:
            self.addItem(info.label, info.name)
        labels = [info.label for info in KEY_LIST]
        completer = QCompleter(labels, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.activated.connect(self._on_completed)
        completer.setMaxVisibleItems(10)
        self.setCompleter(completer)
        # Both popups are top-level windows, so the global ``QComboBox
        # QAbstractItemView`` rules do not reach them and they would use the
        # system palette (black in the light theme on a dark desktop).
        for popup in (completer.popup(), self.view()):
            popup.setObjectName("KeyPopup")
            popup.setStyleSheet(key_popup_stylesheet())
            popup.setAttribute(Qt.WA_StyledBackground, True)
        self.setCurrentIndex(-1)
        self.setMinimumWidth(170)

    def _on_completed(self, text: str) -> None:
        for index in range(self.count()):
            if self.itemText(index) == text:
                self.setCurrentIndex(index)
                return

    def key(self) -> str:
        text = self.currentText().strip()
        if not text:
            return ""
        index = self.currentIndex()
        if index >= 0 and self.itemText(index).lower() == text.lower():
            return str(self.itemData(index))
        for index in range(self.count()):
            if self.itemText(index).lower() == text.lower():
                self.setCurrentIndex(index)
                return str(self.itemData(index))
        return ""

    def set_key(self, name: str) -> None:
        for index in range(self.count()):
            if self.itemData(index) == name:
                self.setCurrentIndex(index)
                return
        self.setCurrentIndex(-1)
        self.setEditText("")


def modifier_row(mods: list[str], parent: QWidget | None = None) -> tuple[QWidget, dict[str, QCheckBox]]:
    widget = QWidget(parent)
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    boxes: dict[str, QCheckBox] = {}
    for token, label in MODIFIER_CHOICES:
        box = QCheckBox(label)
        box.setChecked(token in mods)
        boxes[token] = box
        layout.addWidget(box)
    layout.addStretch(1)
    return widget, boxes


class _PulseDot(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._on = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pulse)
        self._timer.start(600)

    def _pulse(self) -> None:
        self._on = not self._on
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        tint = p["accent"]["secondary"]
        painter.setBrush(painter.brush().color().fromRgb(0, 0, 0, 0) if False else _qc(tint, 60 if self._on else 20))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 12, 12)
        painter.setBrush(_qc(tint, 255 if self._on else 120))
        painter.drawEllipse(3, 3, 6, 6)
        painter.end()


def _qc(hexa: str, alpha: int):
    from app.ui.theme import color

    return color(hexa, alpha)


class MacroStepDialog(FramelessSheet):
    def __init__(self, parent: QWidget | None, step: dict[str, Any] | None = None):
        step = step or {"type": "key", "key": "a"}
        kind = step.get("type", "key")
        super().__init__(parent, "Macro step", "Configure one keyboard operation", width=460)
        self.result_step: dict[str, Any] | None = None

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("Step type"))
        self.kind = QComboBox()
        for key, label in (("key", "Key press"), ("shortcut", "Shortcut"), ("text", "Type text"), ("wait", "Wait")):
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.kind.currentIndexChanged.connect(self._sync)
        kind_row.addWidget(self.kind, 1)
        self.body.addLayout(kind_row)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        key_page = QWidget()
        key_layout = QHBoxLayout(key_page)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(QLabel("Key"))
        self.key = KeySelector()
        self.key.set_key(str(step.get("key", "a")))
        key_layout.addWidget(self.key, 1)
        self.stack.addWidget(key_page)

        shortcut_page = QWidget()
        shortcut_layout = QVBoxLayout(shortcut_page)
        shortcut_layout.setContentsMargins(0, 0, 0, 0)
        shortcut_layout.setSpacing(10)
        mods_widget, self.mods = modifier_row([str(m) for m in step.get("mods", ["ctrl"])])
        shortcut_layout.addWidget(mods_widget)
        row = QHBoxLayout()
        row.addWidget(QLabel("Key"))
        self.shortcut_key = KeySelector()
        self.shortcut_key.set_key(str(step.get("key", "a")))
        row.addWidget(self.shortcut_key, 1)
        shortcut_layout.addLayout(row)
        self.stack.addWidget(shortcut_page)

        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        self.text = QPlainTextEdit(str(step.get("text", "")))
        self.text.setPlaceholderText("Text to type when this step runs")
        self.text.setFixedHeight(90)
        text_layout.addWidget(self.text)
        self.stack.addWidget(text_page)

        wait_page = QWidget()
        wait_layout = QHBoxLayout(wait_page)
        wait_layout.setContentsMargins(0, 0, 0, 0)
        wait_layout.addWidget(QLabel("Wait (ms)"))
        self.wait_ms = QSpinBox()
        self.wait_ms.setRange(0, 60_000)
        self.wait_ms.setSingleStep(50)
        self.wait_ms.setValue(int(step.get("ms", 300)))
        wait_layout.addWidget(self.wait_ms)
        wait_layout.addStretch(1)
        self.stack.addWidget(wait_page)

        self.body.addWidget(self.stack)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {palette()['danger']}; font-size: 11px;")
        self.error_label.setVisible(False)
        self.body.addWidget(self.error_label)

        self.footer.addStretch(1)
        cancel = self.add_footer_button("Cancel")
        cancel.clicked.connect(self.reject)
        save = self.add_footer_button("Apply step", "primary")
        save.clicked.connect(self._save)
        self._sync()

    def _sync(self) -> None:
        self.stack.setCurrentIndex(max(0, self.kind.currentIndex()))

    def _collect(self) -> dict[str, Any]:
        kind = self.kind.currentData()
        if kind == "key":
            return {"type": "key", "key": self.key.key()}
        if kind == "shortcut":
            mods = [token for token, box in self.mods.items() if box.isChecked()]
            return {"type": "shortcut", "mods": mods, "key": self.shortcut_key.key()}
        if kind == "text":
            return {"type": "text", "text": self.text.toPlainText()}
        return {"type": "wait", "ms": self.wait_ms.value()}

    def _save(self) -> None:
        step = self._collect()
        ok, message = validate_macro_step(step)
        if not ok:
            self.error_label.setText(message)
            self.error_label.setVisible(True)
            return
        self.result_step = step
        self.accept()


class _MacroRow(QWidget):
    def __init__(self, index: int, step: dict[str, Any], editor: "MacroEditor"):
        super().__init__()
        self.step = step
        self.editor = editor
        self._hover = False
        self.setFixedHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(10)
        badge = QLabel(str(index + 1))
        badge.setFixedWidth(18)
        badge.setProperty("muted", True)
        f = badge.font()
        f.setWeight(QFont.Bold)
        badge.setFont(f)
        layout.addWidget(badge)
        label = QLabel(describe_macro_step(step))
        layout.addWidget(label, 1)
        up = IconButton("chevron-up", tooltip="Move up", size=26, icon_size=14)
        up.clicked.connect(lambda: editor.move(index, -1))
        down = IconButton("chevron-down", tooltip="Move down", size=26, icon_size=14)
        down.clicked.connect(lambda: editor.move(index, 1))
        edit = IconButton("edit", tooltip="Edit step", size=26, icon_size=14)
        edit.clicked.connect(lambda: editor.edit(index))
        delete = IconButton("trash", tooltip="Remove step", size=26, icon_size=14, danger=True)
        delete.clicked.connect(lambda: editor.remove(index))
        for widget in (up, down, edit, delete):
            layout.addWidget(widget)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPen

        from app.ui.theme import color

        rect = QRectF(self.rect()).adjusted(0.5, 1, -0.5, -1)
        painter.setBrush(color(p["white"], 18 if p["is_dark"] else 8))
        painter.setPen(QPen(color(p["white"], p["border_alpha"]), 1))
        painter.drawRoundedRect(rect, 9, 9)
        painter.end()


class MacroEditor(QWidget):
    changed = Signal()

    def __init__(self, parent_dialog: QWidget, steps: list[dict[str, Any]] | None = None):
        super().__init__()
        self._parent_dialog = parent_dialog
        self.steps: list[dict[str, Any]] = copy.deepcopy(steps or [])
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._rows: list[QWidget] = []
        self._empty = QLabel("No steps yet. Add a key press, shortcut, text or a wait.")
        self._empty.setProperty("muted", True)
        self.add_button = make_button("Add step", "ghost", "plus")
        self.add_button.clicked.connect(self._menu)
        self._render()

    def _menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Key press", lambda: self._add({"type": "key", "key": "a"}))
        menu.addAction("Shortcut", lambda: self._add({"type": "shortcut", "mods": ["ctrl"], "key": "a"}))
        menu.addAction("Type text", lambda: self._add({"type": "text", "text": "Hello"}))
        menu.addAction("Wait", lambda: self._add({"type": "wait", "ms": 300}))
        menu.exec(self.add_button.mapToGlobal(self.add_button.rect().bottomLeft()))

    def _add(self, step: dict[str, Any]) -> None:
        dialog = MacroStepDialog(self._parent_dialog, step)
        dialog.center_on_parent()
        if dialog.exec() == dialog.Accepted and dialog.result_step is not None:
            self.steps.append(dialog.result_step)
            self._render()
            self.changed.emit()

    def edit(self, index: int) -> None:
        if not 0 <= index < len(self.steps):
            return
        dialog = MacroStepDialog(self._parent_dialog, self.steps[index])
        dialog.center_on_parent()
        if dialog.exec() == dialog.Accepted and dialog.result_step is not None:
            self.steps[index] = dialog.result_step
            self._render()
            self.changed.emit()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.steps):
            self.steps.pop(index)
            self._render()
            self.changed.emit()

    def move(self, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= index < len(self.steps) and 0 <= target < len(self.steps):
            self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
            self._render()
            self.changed.emit()

    def _render(self) -> None:
        for row in self._rows:
            self._layout.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        self._layout.removeWidget(self._empty)
        self._empty.hide()
        self._layout.removeWidget(self.add_button)
        if not self.steps:
            self._empty.show()
            self._layout.addWidget(self._empty)
        for index, step in enumerate(self.steps):
            row = _MacroRow(index, step, self)
            self._rows.append(row)
            self._layout.addWidget(row)
        self._layout.addWidget(self.add_button)


class MappingEditor(FramelessSheet):
    def __init__(self, controller, mapping: Mapping | None = None, parent: QWidget | None = None):
        is_new = mapping is None
        super().__init__(
            parent,
            "New mapping" if is_new else "Edit mapping",
            "Choose a trigger, describe the result and save.",
            width=880,
        )
        self.controller = controller
        self.mapping = mapping
        self._recording = False
        self._record_target = "input"
        self._bridge = _RecorderBridge()
        self._bridge.captured.connect(self._on_captured, Qt.QueuedConnection)
        self._bridge.timed_out.connect(self._on_recording_timeout, Qt.QueuedConnection)
        self._bridge.progress.connect(self._on_recording_progress, Qt.QueuedConnection)
        self._record_timer = QTimer(self)
        self._record_timer.setSingleShot(True)
        self._record_timer.timeout.connect(self._on_recording_timeout)

        screen = self.screen().availableGeometry() if self.screen() else None
        height = 760
        if screen is not None:
            height = min(760, screen.height() - 60)
        self.setFixedHeight(height + 52)

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QScrollArea.NoFrame)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setAttribute(Qt.WA_StyledBackground, False)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 8, 4)
        self.content_layout.setSpacing(16)
        body.setWidget(content)
        self.body.addWidget(body, 1)

        self._build_input_section()
        self._build_output_section()
        self._build_options_section()
        self.content_layout.addStretch(1)
        self._build_footer()

        self._load(mapping)

    # ------------------------------------------------------------------ A
    def _section(self, title: str) -> SectionCard:
        card = SectionCard("", padding=18)
        header = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        header.addWidget(label)
        card.body.addLayout(header)
        self.content_layout.addWidget(card)
        return card

    def _build_input_section(self) -> None:
        card = self._section("WHEN I PRESS")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.record_button = make_button("Record key", "primary", "record")
        self.record_button.clicked.connect(self._toggle_recording)
        row.addWidget(self.record_button)

        self.chord_preview = QWidget()
        preview_layout = QHBoxLayout(self.chord_preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)
        self.chips = ChordChips(None, placeholder="No trigger recorded yet")
        preview_layout.addWidget(self.chips)
        self.input_hint = QLabel("Record a key or pick it manually.")
        self.input_hint.setProperty("muted", True)
        preview_layout.addWidget(self.input_hint, 1)
        row.addWidget(self.chord_preview, 1)

        self.clear_button = make_button("Clear", "ghost")
        self.clear_button.clicked.connect(self._clear_chord)
        row.addWidget(self.clear_button)
        card.body.addLayout(row)

        self.record_panel = QFrame()
        self.record_panel.setObjectName("RecordingPanel")
        self.record_panel.setAttribute(Qt.WA_StyledBackground, True)
        panel_layout = QHBoxLayout(self.record_panel)
        panel_layout.setContentsMargins(16, 12, 12, 12)
        panel_layout.setSpacing(10)
        panel_layout.addWidget(_PulseDot())
        self.record_label = QLabel("Listening… press the key combination you want to use.")
        panel_layout.addWidget(self.record_label, 1)
        self.cancel_record = make_button("Cancel", "ghost")
        self.cancel_record.clicked.connect(self._cancel_recording)
        panel_layout.addWidget(self.cancel_record)
        self.record_panel.setVisible(False)
        card.body.addWidget(self.record_panel)

        manual_header = QHBoxLayout()
        manual_header.setSpacing(8)
        self.manual_toggle = make_button("Set manually", "link")
        self.manual_toggle.setToolTip("Choose modifiers and the trigger key without recording")
        self.manual_toggle.clicked.connect(self._toggle_manual)
        manual_header.addWidget(self.manual_toggle)
        manual_header.addStretch(1)
        card.body.addLayout(manual_header)

        self.manual_panel = QWidget()
        manual = QHBoxLayout(self.manual_panel)
        manual.setContentsMargins(0, 0, 0, 0)
        manual.setSpacing(12)
        self.mods_widget, self.mod_boxes = modifier_row([])
        manual.addWidget(self.mods_widget, 1)
        self.mod_side = QComboBox()
        self.mod_side.addItem("Any side", "any")
        self.mod_side.addItem("Left side", "left")
        self.mod_side.addItem("Right side", "right")
        self.mod_side.setFixedWidth(104)
        self.mod_side.setToolTip(
            "Pin modifiers to a physical side (LEFT CTRL vs RIGHT CTRL). "
            "“Any side” matches both, which is what recording captures."
        )
        self.mod_side.currentIndexChanged.connect(self._on_manual_change)
        manual.addWidget(self.mod_side)
        self.key_selector = KeySelector("Choose a trigger key…")
        self.key_selector.currentIndexChanged.connect(self._on_manual_change)
        self.key_selector.editTextChanged.connect(lambda _: self._on_manual_change())
        manual.addWidget(self.key_selector, 1)
        self.manual_panel.setVisible(False)
        card.body.addWidget(self.manual_panel)

    # ------------------------------------------------------------------ B
    def _build_output_section(self) -> None:
        card = self._section("THEN PERFORM")
        segment_row = QHBoxLayout()
        segment_row.setSpacing(4)
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.type_buttons: dict[str, QPushButton] = {}
        for key, label in MAPPING_TYPES.items():
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("variant", "segment")
            button.setCursor(Qt.PointingHandCursor)
            self.type_group.addButton(button)
            self.type_buttons[key] = button
            button.clicked.connect(lambda _=False, k=key: self._set_type(k))
            segment_row.addWidget(button)
        segment_row.addStretch(1)
        self.output_record = make_button("Record", "default", "record")
        self.output_record.setToolTip("Press the key or shortcut to send instead of picking it manually")
        self.output_record.clicked.connect(self._toggle_output_recording)
        segment_row.addWidget(self.output_record)
        card.body.addLayout(segment_row)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        card.body.addWidget(self.stack)

        # Key
        key_page = QWidget()
        key_layout = QVBoxLayout(key_page)
        key_layout.setContentsMargins(0, 4, 0, 0)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Key"))
        self.output_key = KeySelector("Search or pick a key…")
        key_row.addWidget(self.output_key, 1)
        key_layout.addLayout(key_row)
        self.stack.addWidget(key_page)

        # Shortcut
        shortcut_page = QWidget()
        shortcut_layout = QVBoxLayout(shortcut_page)
        shortcut_layout.setContentsMargins(0, 4, 0, 0)
        shortcut_layout.setSpacing(10)
        mods_widget, self.output_mods = modifier_row(["ctrl"])
        shortcut_layout.addWidget(mods_widget)
        shortcut_row = QHBoxLayout()
        shortcut_row.addWidget(QLabel("Key"))
        self.shortcut_key = KeySelector("Search or pick a key…")
        shortcut_row.addWidget(self.shortcut_key, 1)
        shortcut_layout.addLayout(shortcut_row)
        shortcut_hint = QLabel("Modifiers are optional — leave all unchecked to press the key alone.")
        shortcut_hint.setObjectName("Hint")
        shortcut_hint.setWordWrap(True)
        shortcut_layout.addWidget(shortcut_hint)
        self.stack.addWidget(shortcut_page)

        # Action
        action_page = QWidget()
        action_layout = QVBoxLayout(action_page)
        action_layout.setContentsMargins(0, 4, 0, 0)
        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("Windows action"))
        self.action_combo = QComboBox()
        for key, label in WINDOWS_ACTIONS.items():
            self.action_combo.addItem(label, key)
        action_row.addWidget(self.action_combo, 1)
        action_layout.addLayout(action_row)
        hint = QLabel("Protected combinations such as Ctrl+Alt+Del cannot be mapped.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        action_layout.addWidget(hint)
        self.stack.addWidget(action_page)

        # Text
        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(0, 4, 0, 0)
        self.text_output = QPlainTextEdit()
        self.text_output.setPlaceholderText("Text typed when the mapping fires (line breaks supported)")
        self.text_output.setFixedHeight(96)
        text_layout.addWidget(self.text_output)
        self.stack.addWidget(text_page)

        # Macro
        macro_page = QWidget()
        macro_layout = QVBoxLayout(macro_page)
        macro_layout.setContentsMargins(0, 4, 0, 0)
        self.macro_editor = MacroEditor(self)
        macro_layout.addWidget(self.macro_editor)
        self.stack.addWidget(macro_page)

        self.output_status = QLabel("")
        self.output_status.setObjectName("Hint")
        self.output_status.setWordWrap(True)
        self.output_status.setVisible(False)
        card.body.addWidget(self.output_status)

        self.current_type = "shortcut"
        self._set_type("shortcut")

    # ------------------------------------------------------------------ C
    def _build_options_section(self) -> None:
        card = self._section("OPTIONS")

        top = QHBoxLayout()
        top.setSpacing(18)
        name_box = QVBoxLayout()
        name_box.setSpacing(4)
        name_box.addWidget(self._field_label("MAPPING NAME"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Copy selection")
        name_box.addWidget(self.name_input)
        top.addLayout(name_box, 1)

        enabled_box = QVBoxLayout()
        enabled_box.setSpacing(8)
        enabled_box.addWidget(self._field_label("STATUS"))
        enabled_row = QHBoxLayout()
        enabled_row.setSpacing(10)
        self.enabled_toggle = ToggleSwitch(True)
        enabled_row.addWidget(self.enabled_toggle)
        self.enabled_label = QLabel("Mapping enabled")
        enabled_row.addWidget(self.enabled_label)
        enabled_row.addStretch(1)
        enabled_box.addLayout(enabled_row)
        top.addLayout(enabled_box, 0)
        card.body.addLayout(top)

        advanced_header = QHBoxLayout()
        advanced_header.setSpacing(8)
        self.advanced_toggle = make_button("Advanced options", "link")
        self.advanced_toggle.setToolTip("Description, trigger behaviour and execution delay")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        advanced_header.addWidget(self.advanced_toggle)
        advanced_header.addStretch(1)
        card.body.addLayout(advanced_header)

        self.advanced_panel = QWidget()
        advanced = QGridLayout(self.advanced_panel)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setHorizontalSpacing(16)
        advanced.setVerticalSpacing(12)

        advanced.addWidget(self._field_label("DESCRIPTION"), 0, 0, 1, 2)
        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Optional note")
        advanced.addWidget(self.description_input, 1, 0, 1, 2)

        advanced.addWidget(self._field_label("TRIGGER BEHAVIOR"), 2, 0)
        advanced.addWidget(self._field_label("EXECUTION DELAY"), 2, 1)
        self.trigger_combo = QComboBox()
        for key, label in TRIGGER_BEHAVIORS.items():
            self.trigger_combo.addItem(label, key)
        self.trigger_combo.setToolTip(
            "On key press: fires once per physical press\n"
            "On key release: fires when the trigger key is released\n"
            "While key is held: repeats until released\n"
            "Toggle: holds the output keys until the trigger is pressed again (Key and Shortcut outputs)"
        )
        self.trigger_combo.currentIndexChanged.connect(self._sync_trigger_hint)
        advanced.addWidget(self.trigger_combo, 3, 0)

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 60_000)
        self.delay_spin.setSingleStep(10)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setFixedWidth(130)
        self.delay_spin.setToolTip("0 uses the global delay from Settings")
        advanced.addWidget(self.delay_spin, 3, 1, Qt.AlignLeft)

        self.advanced_panel.setVisible(False)
        card.body.addWidget(self.advanced_panel)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("Hint")
        self.hint_label.setWordWrap(True)
        card.body.addWidget(self.hint_label)
        self.conflict_label = QLabel("")
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setVisible(False)
        card.body.addWidget(self.conflict_label)

    def _toggle_manual(self) -> None:
        visible = not self.manual_panel.isVisible()
        self.manual_panel.setVisible(visible)
        self.manual_toggle.setText("Hide manual selection" if visible else "Set manually")

    def _toggle_advanced(self) -> None:
        visible = not self.advanced_panel.isVisible()
        self.advanced_panel.setVisible(visible)
        self.advanced_toggle.setText("Hide advanced options" if visible else "Advanced options")

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _build_footer(self) -> None:
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {palette()['danger']}; font-size: 11.5px;")
        self.footer.addWidget(self.error_label, 1)
        cancel = self.add_footer_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.save_button = self.add_footer_button(
            "Create mapping" if self.mapping is None else "Save changes", "primary", "check"
        )
        self.save_button.clicked.connect(self._save)
        self.save_button.setDefault(True)

    # -- state -------------------------------------------------------------
    def _load(self, mapping: Mapping | None) -> None:
        if mapping is None:
            self.name_input.setText("")
            self.description_input.setText("")
            self.trigger_combo.setCurrentIndex(self.trigger_combo.findData("press"))
            self.delay_spin.setValue(0)
            self.enabled_toggle.setChecked(True, animate=False)
            self.type_buttons["shortcut"].setChecked(True)
            self._set_type("shortcut")
            self.shortcut_key.set_key("c")
            self.output_mods["ctrl"].setChecked(True)
            self.output_key.set_key("pageup")
            self.text_output.setPlainText("")
            return

        self.name_input.setText(mapping.name)
        self.description_input.setText(mapping.description)
        index = self.trigger_combo.findData(mapping.trigger_behavior)
        self.trigger_combo.setCurrentIndex(max(0, index))
        self.delay_spin.setValue(int(mapping.delay or 0))
        self.enabled_toggle.setChecked(mapping.is_enabled, animate=False)

        mods = [str(m) for m in mapping.input_config.get("mods", [])]
        side = "any"
        if mods and all(m.startswith("l") and m[1:] in self.mod_boxes for m in mods):
            side = "left"
        elif mods and all(m.startswith("r") and m[1:] in self.mod_boxes for m in mods):
            side = "right"
        if hasattr(self, "mod_side"):
            self.mod_side.setCurrentIndex(max(0, self.mod_side.findData(side)))
        for token, box in self.mod_boxes.items():
            box.setChecked(token in mods or ("l" + token) in mods or ("r" + token) in mods)
        self.key_selector.set_key(str(mapping.input_config.get("key", "")))
        self._update_chips()

        self.type_buttons[mapping.mapping_type].setChecked(True)
        self._set_type(mapping.mapping_type)
        output = mapping.output_config
        if mapping.mapping_type == "key":
            self.output_key.set_key(str(output.get("key", "")))
        elif mapping.mapping_type == "shortcut":
            out_mods = [str(m) for m in output.get("mods", [])]
            for token, box in self.output_mods.items():
                box.setChecked(token in out_mods)
            self.shortcut_key.set_key(str(output.get("key", "")))
        elif mapping.mapping_type == "action":
            self.action_combo.setCurrentIndex(max(0, self.action_combo.findData(output.get("action"))))
        elif mapping.mapping_type == "text":
            self.text_output.setPlainText(str(output.get("text", "")))
        elif mapping.mapping_type == "macro":
            self.macro_editor.steps = copy.deepcopy(output.get("steps", []))
            self.macro_editor._render()

    def _set_type(self, key: str) -> None:
        self.current_type = key
        order = list(MAPPING_TYPES.keys())
        if key in order:
            self.stack.setCurrentIndex(order.index(key))
            self.type_buttons[key].setChecked(True)
        if hasattr(self, "output_record"):
            self.output_record.setVisible(key in {"key", "shortcut"})
        if hasattr(self, "output_status"):
            self.output_status.setVisible(False)
        self._sync_trigger_hint()

    def _sync_trigger_hint(self) -> None:
        if not hasattr(self, "trigger_combo"):
            return
        trigger = self.trigger_combo.currentData()
        if trigger == "toggle" and self.current_type not in {"key", "shortcut"}:
            self.hint_label.setText(
                "Toggle mode holds the output keys down, so it is only available for Key and Shortcut outputs. "
                "Change the trigger behaviour or the output type."
            )
        elif trigger == "toggle":
            self.hint_label.setText(
                "Toggle: press once to hold the output keys, press again to release them. The mapping shows as latched until then."
            )
        elif trigger == "hold":
            self.hint_label.setText("While key is held: the output repeats until the trigger key is released.")
        else:
            self.hint_label.setText("")

    # -- chord helpers -----------------------------------------------------
    def _current_chord(self) -> dict[str, Any]:
        checked = [token for token, box in self.mod_boxes.items() if box.isChecked()]
        side = self.mod_side.currentData() if hasattr(self, "mod_side") else "any"
        if side == "left":
            mods = ["l" + token for token in checked]
        elif side == "right":
            mods = ["r" + token for token in checked]
        else:
            mods = checked
        key = self.key_selector.key()
        return {"mods": mods, "key": key}

    def _update_chips(self) -> None:
        chord = self._current_chord()
        self.chips.set_chord(chord if chord.get("key") else None)
        if chord.get("key"):
            self.input_hint.setText("Picked manually")
        else:
            self.input_hint.setText("Record a key or pick it manually.")
        self._check_conflict()

    def _on_manual_change(self, *args) -> None:
        self._update_chips()

    def _clear_chord(self) -> None:
        for box in self.mod_boxes.values():
            box.setChecked(False)
        self.key_selector.set_key("")
        if hasattr(self, "mod_side"):
            self.mod_side.setCurrentIndex(0)
        self._update_chips()

    # -- recording ---------------------------------------------------------
    def _toggle_recording(self) -> None:
        if self._recording:
            self._cancel_recording()
            return
        self._start_recording("input")

    def _toggle_output_recording(self) -> None:
        if self._recording:
            self._cancel_recording()
            return
        self._start_recording("output")

    def _start_recording(self, target: str) -> None:
        engine = self.controller.engine
        if not engine.hook.is_running:
            if not engine.start():
                self.error_label.setText(
                    "The keyboard hook is not running, so keys cannot be recorded. "
                    "Enable the keyboard engine in Settings and try again."
                )
                return
        self._recording = True
        self._record_target = target
        self.save_button.setEnabled(False)
        self.error_label.setText("")
        if target == "output":
            self.record_panel.setVisible(False)
            self.record_button.setEnabled(False)
            self.output_record.setText("Cancel recording")
            self.output_status.setText("Listening… press the keys to send.")
            self.output_status.setVisible(True)
            for button in self.type_buttons.values():
                button.setEnabled(False)
        else:
            self.record_panel.setVisible(True)
            self.record_button.setText("Recording…")
            self.record_button.setEnabled(False)
            self.output_record.setEnabled(False)
            self.record_label.setText("Listening… press the key combination you want to use.")
        started = engine.record_capture(
            on_captured=lambda chord: self._bridge.captured.emit(chord),
            on_timeout=lambda: self._bridge.timed_out.emit(),
            on_progress=lambda mods: self._bridge.progress.emit(mods),
        )
        if not started:
            self._finish_recording()
            self.error_label.setText("Recording could not start. Check that the keyboard engine is running.")
            return
        timeout_ms = max(3, self.controller.settings.get_int("recording_timeout_s", 8)) * 1000
        self._record_timer.start(timeout_ms + 500)

    def _finish_recording(self) -> None:
        self._recording = False
        self._record_timer.stop()
        self.record_panel.setVisible(False)
        self.record_button.setText("Record key")
        self.record_button.setEnabled(True)
        self.output_record.setText("Record output")
        self.output_record.setEnabled(True)
        for button in self.type_buttons.values():
            button.setEnabled(True)
        if self.output_status.text().startswith("Listening"):
            self.output_status.setVisible(False)
        self.save_button.setEnabled(True)
        try:
            self.controller.engine.cancel_recording()
        except Exception:
            pass

    def _cancel_recording(self) -> None:
        self._finish_recording()

    def _on_recording_progress(self, mods) -> None:
        if not self._recording:
            return
        labels = " + ".join(str(m).upper() for m in mods)
        if self._record_target == "output":
            self.output_status.setText(f"Listening… {labels}" if labels else "Listening… press the keys to send.")
            self.output_status.setVisible(True)
            return
        self.record_label.setText(f"Listening… {labels}" if labels else "Listening… press the key combination you want to use.")

    def _on_captured(self, chord) -> None:
        if not self._recording:
            return
        target = self._record_target
        self._finish_recording()
        if not isinstance(chord, dict):
            return
        try:
            mods = normalize_mods([str(m) for m in chord.get("mods", [])])
        except ValueError:
            mods = []
        if target == "output":
            self._apply_output_capture(mods, str(chord.get("key", "")))
            return
        for token, box in self.mod_boxes.items():
            box.setChecked(token in mods)
        if hasattr(self, "mod_side"):
            self.mod_side.setCurrentIndex(0)
        self.key_selector.set_key(str(chord.get("key", "")))
        self._update_chips()
        if not self.name_input.text().strip():
            self.input_hint.setText("Captured — add an output and a name.")

    def _apply_output_capture(self, mods: list[str], key: str) -> None:
        """Fill the output from a recording, switching type when modifiers are used."""
        if not key:
            return
        if mods or self.current_type == "shortcut":
            self._set_type("shortcut")
            for token, box in self.output_mods.items():
                box.setChecked(token in mods)
            self.shortcut_key.set_key(key)
        else:
            self._set_type("key")
            self.output_key.set_key(key)
        self.output_status.setText(f"Recorded output: {chord_display({'mods': mods, 'key': key})}")
        self.output_status.setVisible(True)

    def _on_recording_timeout(self) -> None:
        if not self._recording:
            return
        target = self._record_target
        self._finish_recording()
        if target == "output":
            self.output_status.setText("Recording timed out. Pick the key manually.")
            self.output_status.setVisible(True)
        else:
            self.input_hint.setText("Recording timed out. Try again or pick keys manually.")

    # -- conflicts ---------------------------------------------------------
    def _check_conflict(self) -> None:
        chord = self._current_chord()
        self.conflict_label.setVisible(False)
        if not chord.get("key") or not self.controller.settings.get_bool("conflict_warnings", True):
            return
        candidate = Mapping(
            id=self.mapping.id if self.mapping else "candidate",
            profile_id=self.controller.profiles.active_id,
            name="",
            input_config=chord,
            output_config={},
            mapping_type="key",
        )
        other = has_conflict(candidate, self.controller.profiles.active_mappings())
        if other is not None:
            self.conflict_label.setText(
                f"⚠  {chord_display(chord)} is already used by “{other.name or other.input_display}”. "
                "You can still save, but only one of them will fire."
            )
            self.conflict_label.setStyleSheet(f"color: {palette()['warning']}; font-size: 11.5px;")
            self.conflict_label.setVisible(True)

    # -- saving ------------------------------------------------------------
    def _build_output(self) -> tuple[dict[str, Any] | None, str]:
        if self.current_type == "key":
            key = self.output_key.key()
            if not key:
                return None, "Choose the key that should be pressed."
            return {"key": key}, ""
        if self.current_type == "shortcut":
            mods = [token for token, box in self.output_mods.items() if box.isChecked()]
            key = self.shortcut_key.key()
            if not key:
                return None, "Choose the shortcut's main key."
            # Modifiers are optional: an empty list sends the key by itself, so every
            # key (PAGE UP, F13, media keys, …) can be assigned through this tab too.
            return {"mods": mods, "key": key}, ""
        if self.current_type == "action":
            return {"action": self.action_combo.currentData()}, ""
        if self.current_type == "text":
            text = self.text_output.toPlainText()
            if not text:
                return None, "Enter the text that should be typed."
            return {"text": text}, ""
        if self.current_type == "macro":
            if not self.macro_editor.steps:
                return None, "Add at least one macro step."
            return {"steps": copy.deepcopy(self.macro_editor.steps)}, ""
        return None, "Choose an output type."

    def _save(self) -> None:
        self.error_label.setText("")
        chord = self._current_chord()
        ok, message = validate_chord(chord)
        if not ok:
            self.error_label.setText(message if chord.get("key") else "Record or choose the trigger key first.")
            return
        output, error = self._build_output()
        if output is None:
            self.error_label.setText(error)
            return
        ok, message = validate_output(self.current_type, output)
        if not ok:
            self.error_label.setText(message)
            return
        trigger = self.trigger_combo.currentData()
        if trigger == "toggle" and self.current_type not in {"key", "shortcut"}:
            self.error_label.setText("Toggle mode is only available for Key and Shortcut outputs.")
            return

        name = self.name_input.text().strip()
        if not name:
            name = f"{chord_display(chord)} → {describe_output(self.current_type, output)}"
        if len(name) > 80:
            name = name[:77] + "…"

        candidate = Mapping(
            id=self.mapping.id if self.mapping else new_id(),
            profile_id=self.mapping.profile_id if self.mapping else self.controller.profiles.active_id,
            name=name,
            description=self.description_input.text().strip(),
            input_config=make_chord([str(m) for m in chord.get("mods", [])], str(chord["key"])),
            output_config=output,
            mapping_type=self.current_type,
            trigger_behavior=str(trigger),
            delay=self.delay_spin.value(),
            is_enabled=self.enabled_toggle.isChecked(),
            created_at=self.mapping.created_at if self.mapping else utc_now(),
            updated_at=utc_now(),
        )

        if self.controller.settings.get_bool("conflict_warnings", True):
            other = has_conflict(candidate, self.controller.profiles.active_mappings())
            if other is not None:
                proceed = ConfirmDialog.ask(
                    self,
                    "Duplicate trigger",
                    f"{candidate.input_display} is already mapped to “{other.output_display}” by “{other.name}”.\n\n"
                    "Saving will keep both mappings, but only one of them can fire. Continue?",
                    "Save anyway",
                    danger=True,
                )
                if not proceed:
                    return

        if not self.controller.save_mapping(candidate):
            self.error_label.setText("The mapping could not be saved. Check the log for details.")
            return
        self.accept()

    # -- lifecycle ---------------------------------------------------------
    def reject(self) -> None:  # noqa: N802
        if self._recording:
            self._finish_recording()
        super().reject()

    def closeEvent(self, event):  # noqa: N802
        if self._recording:
            self._finish_recording()
        super().closeEvent(event)
