"""Key Tester page: a live keyboard diagram plus keys outside the layout."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.database.models import Mapping
from app.engine.key_layout import BLOCKS, TOTAL_UNITS, KeyCap, describe_key, key_id_for_event
from app.engine.keyboard_tester import KeyboardTester, windows_key_name
from app.engine.keycodes import VK_TO_KEY, VK_TO_MODIFIER, chord_display
from app.engine.mapping_processor import build_mapping_index, mapping_for_chord
from app.ui.base_page import BasePage
from app.ui.components.buttons import make_button
from app.ui.components.cards import GlassCard, KeyValueRow
from app.ui.components.chips import Pill
from app.ui.theme import color, palette

PAD = 12.0
ROW_GAP = 5.0
FUNCTION_GAP = 10.0
CAP_INSET = 2.5


class KeyboardMap(QWidget):
    """Painted 104-key diagram; lit caps are the keys currently held down."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pressed: set[str] = set()
        self.setMinimumHeight(310)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_pressed(self, key_ids) -> None:
        pressed = {key_id for key_id in key_ids if key_id}
        if pressed != self._pressed:
            self._pressed = pressed
            self.update()

    # -- geometry ----------------------------------------------------------
    def _metrics(self) -> tuple[float, float, list[float]]:
        width = max(320.0, float(self.width()) - PAD * 2)
        height = max(240.0, float(self.height()) - PAD * 2)
        unit = width / TOTAL_UNITS
        gaps = ROW_GAP * 4 + FUNCTION_GAP
        row_h = max(22.0, (height - gaps) / 6)
        tops: list[float] = []
        y = PAD
        for row in range(6):
            tops.append(y)
            y += row_h
            y += FUNCTION_GAP if row == 0 else ROW_GAP
        return unit, row_h, tops

    def _cap_rect(self, cap: KeyCap, x: float, row: int, unit: float, row_h: float, tops: list[float]) -> QRectF:
        start = row
        top = tops[start]
        if cap.height > 1:
            end = start + int(cap.height) - 1
            height = tops[min(end, 5)] + row_h - top
        else:
            height = row_h
        return QRectF(x + CAP_INSET, top + CAP_INSET, cap.width * unit - CAP_INSET * 2, height - CAP_INSET * 2)

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = palette()
        accent = p["accent"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        unit, row_h, tops = self._metrics()

        idle_brush = color(p["white"], 20 if p["is_dark"] else 12)
        idle_pen = QPen(color(p["white"], p["border_alpha"]), 1)

        for block in BLOCKS:
            for row_index, row in enumerate(block.rows):
                offset = 0.0
                absolute_row = block.start_row + row_index
                for entry in row:
                    if not isinstance(entry, KeyCap):
                        offset += float(entry)
                        continue
                    x = PAD + (block.x + offset) * unit
                    rect = self._cap_rect(entry, x, absolute_row, unit, row_h, tops)
                    pressed = entry.key_id in self._pressed
                    if pressed:
                        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
                        gradient.setColorAt(0.0, color(accent["primary"], 235))
                        gradient.setColorAt(1.0, color(accent["secondary"], 210))
                        painter.setBrush(gradient)
                        painter.setPen(QPen(color(accent["primary"]), 1))
                    else:
                        painter.setBrush(idle_brush)
                        painter.setPen(idle_pen)
                    painter.drawRoundedRect(rect, 6, 6)

                    font = QFont(self.font())
                    font.setWeight(QFont.DemiBold)
                    size = 8.4
                    font.setPointSizeF(size)
                    while size > 5.8 and QFontMetrics(font).horizontalAdvance(entry.label) > rect.width() - 6:
                        size -= 0.4
                        font.setPointSizeF(size)
                    painter.setFont(font)
                    painter.setPen(color(p["accent_text"] if pressed else p["muted"]))
                    painter.drawText(rect, Qt.AlignCenter, entry.label)
                    offset += entry.width
        painter.end()


class _TesterBridge(QObject):
    """Marshals hook-thread key events onto the UI thread."""

    event = Signal(object)


class KeyTesterPage(BasePage):
    title = "Key Tester"
    subtitle = "Every key the keyboard hook receives"

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self.tester = KeyboardTester()
        self._bridge = _TesterBridge()
        self._bridge.event.connect(self._on_event, Qt.QueuedConnection)
        self._outside: list[tuple[tuple[int, int], QWidget]] = []
        self._simulated: set[str] = set()
        self._index: dict[str, Mapping] = {}
        self._mods: set[str] = set()
        self.tester.add_listener(self._on_tester_event)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 8, 28, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        self.status_pill = Pill("Starting…", "muted")
        header.addWidget(self.status_pill)
        hint = QLabel("Press any key — media, browser and vendor keys appear below the layout.")
        hint.setProperty("muted", True)
        header.addWidget(hint)
        header.addStretch(1)
        self.reset_button = make_button("Reset", "ghost")
        self.reset_button.clicked.connect(self.reset)
        header.addWidget(self.reset_button)
        layout.addLayout(header)

        keyboard_card = GlassCard(radius=18)
        keyboard_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout = QVBoxLayout(keyboard_card)
        card_layout.setContentsMargins(16, 14, 16, 10)
        card_layout.setSpacing(6)
        self.keyboard = KeyboardMap()
        card_layout.addWidget(self.keyboard, 1)
        note = QLabel("Keys pass through to other apps while testing.")
        note.setProperty("muted", True)
        note.setAlignment(Qt.AlignRight)
        card_layout.addWidget(note)
        layout.addWidget(keyboard_card, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        bottom.addWidget(self._build_last_card(), 1)
        bottom.addWidget(self._build_mapping_card(), 1)
        bottom.addWidget(self._build_outside_card(), 1)
        layout.addLayout(bottom)
        self._load_mappings()

    # -- cards -------------------------------------------------------------
    def _build_last_card(self) -> QWidget:
        card = GlassCard(radius=18)
        card.setMinimumHeight(212)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)

        title = QLabel("LAST KEY")
        title.setObjectName("SectionTitle")
        box.addWidget(title)
        self.last_name = QLabel("—")
        font = self.last_name.font()
        font.setPointSizeF(22)
        font.setWeight(QFont.Bold)
        self.last_name.setFont(font)
        self.last_name.setWordWrap(True)
        box.addWidget(self.last_name)
        box.addStretch(1)
        self._vk_row = KeyValueRow("Virtual key", "—")
        self._scan_row = KeyValueRow("Scan code", "—")
        self._ext_row = KeyValueRow("Extended", "—")
        for row in (self._vk_row, self._scan_row, self._ext_row):
            box.addWidget(row)
        return card

    def _build_mapping_card(self) -> QWidget:
        card = GlassCard(radius=18)
        card.setMinimumHeight(212)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(5)

        title = QLabel("ACTIVE PROFILE")
        title.setObjectName("SectionTitle")
        box.addWidget(title)
        self.mapping_profile = QLabel("—")
        self.mapping_profile.setProperty("muted", True)
        self.mapping_profile.setWordWrap(True)
        box.addWidget(self.mapping_profile)

        self.mapping_chord = QLabel("Press a key to test")
        chord_font = self.mapping_chord.font()
        chord_font.setPointSizeF(13)
        chord_font.setWeight(QFont.Bold)
        self.mapping_chord.setFont(chord_font)
        self.mapping_chord.setWordWrap(True)
        box.addWidget(self.mapping_chord)

        self.mapping_name = QLabel("")
        name_font = self.mapping_name.font()
        name_font.setPointSizeF(10.2)
        name_font.setWeight(QFont.DemiBold)
        self.mapping_name.setFont(name_font)
        self.mapping_name.setWordWrap(True)
        box.addWidget(self.mapping_name)

        self.mapping_output = QLabel("")
        self.mapping_output.setProperty("muted", True)
        self.mapping_output.setWordWrap(True)
        box.addWidget(self.mapping_output)
        box.addStretch(1)

        self.mapping_pill = Pill("WAITING", "muted")
        box.addWidget(self.mapping_pill)
        self.mapping_hint = QLabel("Mappings from the profile that is active right now.")
        self.mapping_hint.setProperty("muted", True)
        self.mapping_hint.setWordWrap(True)
        hint_font = self.mapping_hint.font()
        hint_font.setPointSizeF(8.6)
        self.mapping_hint.setFont(hint_font)
        box.addWidget(self.mapping_hint)
        return card

    def _build_outside_card(self) -> QWidget:
        card = GlassCard(radius=18)
        card.setMinimumHeight(212)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 12)
        box.setSpacing(6)

        title = QLabel("OUTSIDE THE LAYOUT")
        title.setObjectName("SectionTitle")
        box.addWidget(title)
        subtitle = QLabel("Media, browser, OEM, IME and vendor keys")
        subtitle.setProperty("muted", True)
        box.addWidget(subtitle)

        self.outside_hint = QLabel("Nothing yet — press a key that is not on a standard keyboard.")
        self.outside_hint.setProperty("muted", True)
        self.outside_hint.setWordWrap(True)
        box.addWidget(self.outside_hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.outside_host = QWidget()
        self.outside_host.setAttribute(Qt.WA_StyledBackground, False)
        self.outside_layout = QVBoxLayout(self.outside_host)
        self.outside_layout.setContentsMargins(0, 0, 6, 0)
        self.outside_layout.setSpacing(6)
        self.outside_layout.addStretch(1)
        self.scroll.setWidget(self.outside_host)
        box.addWidget(self.scroll, 1)
        return card

    # -- lifecycle ---------------------------------------------------------
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._start()

    def hideEvent(self, event):  # noqa: N802
        self._stop()
        super().hideEvent(event)

    def _start(self) -> None:
        if self.tester.start():
            self.status_pill.set_text("Listening")
            self.status_pill.set_tone("success")
            self.status_pill.setToolTip("")
        else:
            self.status_pill.set_text("Hook unavailable")
            self.status_pill.set_tone("danger")
            self.status_pill.setToolTip(self.tester.last_error or "The keyboard hook could not be installed.")

    def _stop(self) -> None:
        self.tester.stop()
        self._mods.clear()
        self.keyboard.set_pressed(set())

    def _load_mappings(self) -> None:
        """Snapshot the active profile's mappings for chord lookups."""
        profile = self.controller.profiles.active
        mappings = self.controller.profiles.active_mappings()
        self._index, _ = build_mapping_index(mappings)
        enabled = sum(1 for mapping in mappings if mapping.is_enabled)
        self.mapping_profile.setText(f"{profile.name} · {enabled} active mapping(s)")

    def refresh(self) -> None:
        self._load_mappings()
        if self.isVisible():
            self._start()

    # -- events ------------------------------------------------------------
    def _on_tester_event(self, event, key_id) -> None:
        self._bridge.event.emit(
            {
                "vk": int(event.vk),
                "scan": int(event.scan_code),
                "extended": bool(event.extended),
                "down": bool(event.key_down),
                "key_id": key_id,
            }
        )

    def _on_event(self, payload: dict) -> None:
        vk = int(payload.get("vk", 0))
        scan = int(payload.get("scan", 0))
        extended = bool(payload.get("extended", False))
        key_id = payload.get("key_id")
        down = bool(payload.get("down", False))
        self.keyboard.set_pressed(set(self.tester.pressed) | self._simulated)
        mod = VK_TO_MODIFIER.get(vk)
        if mod:
            if down:
                self._mods.add(mod[0])
            else:
                self._mods.discard(mod[0])
        if not down:
            return
        os_name = None if key_id else windows_key_name(vk)
        name = describe_key(vk, scan, extended, os_name)
        self._show_last(name, vk, scan, extended)
        if key_id is None:
            self._add_outside(name, vk, scan, extended)
        self._show_mapping(name, vk)

    def _show_last(self, name: str, vk: int, scan: int, extended: bool) -> None:
        self.last_name.setText(name)
        self._vk_row.set_value(f"0x{vk:02X}")
        self._scan_row.set_value(f"0x{scan:02X}")
        self._ext_row.set_value("yes" if extended else "no")

    def _show_mapping(self, name: str, vk: int) -> None:
        """Show the mapping the active profile resolves this key chord to."""
        key_name = VK_TO_KEY.get(vk)
        if key_name:
            self.mapping_chord.setText(chord_display({"mods": list(self._mods), "key": key_name}))
        else:
            self.mapping_chord.setText(name)
        mapping = mapping_for_chord(self._index, key_name or "", self._mods)
        if mapping is None:
            self.mapping_name.setText("No mapping for this key")
            self.mapping_output.setText("")
            self.mapping_pill.set_text("UNMAPPED")
            self.mapping_pill.set_tone("muted")
            self.mapping_hint.setText("Add a mapping for it on the Key Mapper page.")
            return
        self.mapping_name.setText(mapping.name or mapping.input_display)
        self.mapping_output.setText(f"{mapping.trigger_behavior.title()} · {mapping.output_display}")
        text, tone, hint = self._engine_state()
        self.mapping_pill.set_text(text)
        self.mapping_pill.set_tone(tone)
        self.mapping_hint.setText(hint)

    def _engine_state(self) -> tuple[str, str, str]:
        status = self.controller.engine.status()
        if status["emergency"]:
            return "ENGINE STOPPED", "danger", "Emergency stop is active — this mapping will not fire."
        if not status["running"]:
            return "ENGINE OFF", "warning", "The keyboard hook is not running — this mapping will not fire."
        if status["paused"]:
            return "PAUSED", "warning", "Mappings are paused — this mapping will not fire."
        if not status["enabled"]:
            return "DISABLED", "warning", "Mappings are disabled — this mapping will not fire."
        return "FIRES NOW", "success", "This is the output the engine sends for this chord."

    def _add_outside(self, name: str, vk: int, scan: int, extended: bool) -> None:
        identity = (vk, scan)
        if any(existing == identity for existing, _ in self._outside):
            return
        row = QWidget()
        box = QVBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        name_label = QLabel(name)
        name_font = name_label.font()
        name_font.setWeight(QFont.DemiBold)
        name_label.setFont(name_font)
        box.addWidget(name_label)
        codes = QLabel(f"VK 0x{vk:02X} · scan 0x{scan:02X}" + (" · extended" if extended else ""))
        codes.setProperty("muted", True)
        codes_font = codes.font()
        codes_font.setPointSizeF(8.6)
        codes.setFont(codes_font)
        box.addWidget(codes)

        self.outside_layout.insertWidget(0, row)
        self._outside.insert(0, (identity, row))
        self.outside_hint.hide()
        while len(self._outside) > 40:
            _, old = self._outside.pop()
            old.deleteLater()

    # -- actions -----------------------------------------------------------
    def reset(self) -> None:
        self.tester.reset()
        self._simulated.clear()
        self._mods.clear()
        self.keyboard.set_pressed(set())
        self.last_name.setText("—")
        for row in (self._vk_row, self._scan_row, self._ext_row):
            row.set_value("—")
        self.mapping_chord.setText("Press a key to test")
        self.mapping_name.setText("")
        self.mapping_output.setText("")
        self.mapping_pill.set_text("WAITING")
        self.mapping_pill.set_tone("muted")
        self.mapping_hint.setText("Mappings from the profile that is active right now.")
        for _, widget in self._outside:
            widget.deleteLater()
        self._outside.clear()
        self.outside_hint.show()

    def simulate(self, vk: int, scan_code: int = 0, extended: bool = False, key_id: str | None = None) -> None:
        """Feed a synthetic key press (used by the UI smoke test)."""
        if key_id is None:
            key_id = key_id_for_event(vk, scan_code, extended)
        self._on_event(
            {"vk": vk, "scan": scan_code, "extended": extended, "down": True, "key_id": key_id}
        )
        if key_id:
            self._simulated.add(key_id)
