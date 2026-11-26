"""Voice FX page — real-time microphone presets, routing and recording."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.audio import devices as audio_devices
from app.audio.presets import (
    MAX_GAIN_DB,
    MAX_PITCH,
    MIN_GAIN_DB,
    MIN_PITCH,
    PRESET_ORDER,
    PRESETS,
    VoicePreset,
    clamp_gain,
    clamp_pitch,
    clamp_wet,
)
from app.audio.voice_engine import NO_OUTPUT
from app.constants import RECORDINGS_DIR
from app.ui.base_page import ScrollPage
from app.ui.components.buttons import make_button
from app.ui.components.cards import Banner, SectionCard
from app.ui.components.chips import Pill
from app.ui.components.dialogs import Toast
from app.ui.components.toggle import ToggleSwitch
from app.ui.settings import SettingRow
from app.ui.theme import color, palette

VB_CABLE_URL = "https://vb-audio.com/Cable/"

INSTRUCTIONS = (
    "1. Install VB-Cable (free, one reboot).   "
    "2. Choose “CABLE Input” as the output below.   "
    "3. In Discord / Zoom / your game choose “CABLE Output” as the microphone."
)


def _short(text: str, limit: int = 34) -> str:
    """Device names are long; keep the status line readable."""
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class _Meter(QWidget):
    """Input and output level in dBFS, with a peak-hold marker.

    A square-root scale used to make a quiet microphone look half full; this is a
    real level scale from -60 dBFS to 0 dBFS, so what you see matches the number.
    """

    MIN_DB = -60.0
    RELEASE_DB = 1.6  # per poll (~80 ms)
    HOLD_DB = 0.35

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._in_db = self.MIN_DB
        self._out_db = self.MIN_DB
        self._in_hold = self.MIN_DB
        self._out_hold = self.MIN_DB
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    @classmethod
    def db_from_peak(cls, peak: float) -> float:
        try:
            peak = float(peak)
        except (TypeError, ValueError):
            return cls.MIN_DB
        if peak <= 1e-5:
            return cls.MIN_DB
        return max(cls.MIN_DB, min(0.0, 20.0 * math.log10(peak)))

    def set_levels(self, input_peak: float, output_peak: float) -> None:
        self._in_db, self._in_hold = self._advance(
            self.db_from_peak(input_peak), self._in_db, self._in_hold
        )
        self._out_db, self._out_hold = self._advance(
            self.db_from_peak(output_peak), self._out_db, self._out_hold
        )
        self.update()

    def _advance(self, target: float, shown: float, hold: float) -> tuple[float, float]:
        if target >= shown:
            shown = target
        else:
            shown = max(target, shown - self.RELEASE_DB)
        return shown, max(target, hold - self.HOLD_DB)

    def reset(self) -> None:
        self._in_db = self._out_db = self._in_hold = self._out_hold = self.MIN_DB
        self.update()

    def _ratio(self, db: float) -> float:
        return max(0.0, min(1.0, (db - self.MIN_DB) / (0.0 - self.MIN_DB)))

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(self.font())
        font.setPointSizeF(8.2)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)

        rows = (
            ("IN", self._in_db, self._in_hold),
            ("OUT", self._out_db, self._out_hold),
        )
        for index, (label, db, hold) in enumerate(rows):
            y = 8 + index * 28
            painter.setPen(color(p["faint"] if db <= self.MIN_DB else p["muted"]))
            painter.drawText(QRectF(0, y, 30, 14), Qt.AlignVCenter | Qt.AlignLeft, label)

            track = QRectF(36, y + 3, max(10.0, self.width() - 36 - 74), 9)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color(p["white"], 22 if p["is_dark"] else 26))
            painter.drawRoundedRect(track, 4.5, 4.5)

            ratio = self._ratio(db)
            if ratio > 0.002:
                filled = QRectF(track.left(), track.top(), max(3.0, track.width() * ratio), track.height())
                # Colour the fill by the actual level, not by how full the bar is:
                # a fixed red tip made ordinary speech look like clipping.
                if db > -3.0:
                    tint = p["danger"]
                elif db > -9.0:
                    tint = p["warning"]
                else:
                    tint = p["success"]
                gradient = QLinearGradient(filled.topLeft(), filled.topRight())
                gradient.setColorAt(0.0, color(tint, 140))
                gradient.setColorAt(1.0, color(tint, 235))
                painter.setBrush(gradient)
                painter.drawRoundedRect(filled, 4.5, 4.5)

            hold_ratio = self._ratio(hold)
            if hold_ratio > 0.01:
                x = track.left() + track.width() * hold_ratio
                painter.setPen(QPen(color(p["text"], 150), 2))
                painter.drawLine(x, track.top() - 2, x, track.bottom() + 2)

            value = "—" if db <= self.MIN_DB else f"{db:.0f} dB"
            painter.setPen(color(p["danger"] if db > -3 else (p["faint"] if db <= self.MIN_DB else p["muted"])))
            painter.drawText(
                QRectF(track.right() + 8, y, max(20.0, self.width() - track.right() - 10), 14),
                Qt.AlignVCenter | Qt.AlignRight,
                value,
            )
        painter.end()


class _RecordDot(QWidget):
    """Pulsing red dot shown while a WAV is being written."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._active = False
        self._phase = 0.0
        self.setFixedSize(12, 12)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self._phase = 0.0
        self.update()

    def tick(self) -> None:
        self._phase = (self._phase + 0.12) % 1.0
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if not self._active:
            painter.setBrush(color(p["faint"], 90))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(4, 4, 4, 4))
            painter.end()
            return
        pulse = 0.5 + 0.5 * math.cos(2.0 * math.pi * self._phase)
        painter.setBrush(color(p["danger"], int(50 + 110 * pulse)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(0, 0, 12, 12))
        painter.setBrush(color(p["danger"]))
        painter.drawEllipse(QRectF(3, 3, 6, 6))
        painter.end()


class _PresetTile(QWidget):
    clicked = Signal(str)

    def __init__(self, preset: VoicePreset, parent: QWidget | None = None):
        super().__init__(parent)
        self.preset = preset
        self.selected = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(78)
        self.setMinimumWidth(108)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(preset.hint)

    def set_selected(self, selected: bool) -> None:
        if self.selected == selected:
            return
        self.selected = selected
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.preset.key)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        accent = p["accent"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self.selected:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, color(accent["primary"], 120))
            gradient.setColorAt(1.0, color(accent["secondary"], 26))
            painter.setBrush(gradient)
            painter.setPen(QPen(color(accent["secondary"], 180), 1.2))
        else:
            painter.setBrush(color(p["white"], 20 if self._hover else 12))
            painter.setPen(QPen(color(p["white"], p["border_alpha"]), 1))
        painter.drawRoundedRect(rect, 14, 14)

        title_font = QFont(self.font())
        title_font.setPointSizeF(10.4)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(color("#FFFFFF") if self.selected and p["is_dark"] else color(p["text"]))
        painter.drawText(
            QRectF(rect.left() + 14, rect.top() + 12, rect.width() - 28, 20),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.preset.label,
        )

        hint_font = QFont(self.font())
        hint_font.setPointSizeF(8.4)
        painter.setFont(hint_font)
        painter.setPen(color(p["muted"] if not self.selected else p["text"]))
        painter.drawText(
            QRectF(rect.left() + 14, rect.top() + 34, rect.width() - 28, rect.height() - 42),
            int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap),
            self.preset.hint,
        )
        painter.end()


class _Slider(QWidget):
    """Flat painted slider (the QSS theme has no QSlider rules)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = max(int(maximum), self._min + 1)
        self._value = int(value)
        self._hover = False
        self._dragging = False
        self.setMinimumHeight(24)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    # -- api ---------------------------------------------------------------
    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802
        value = max(self._min, min(self._max, int(value)))
        if value == self._value:
            return
        self._value = value
        self.update()
        self.valueChanged.emit(value)

    def setValueSilently(self, value: int) -> None:
        self._value = max(self._min, min(self._max, int(value)))
        self.update()

    # -- interaction -------------------------------------------------------
    def _value_at(self, x: float) -> int:
        track = self._track_rect()
        ratio = (x - track.left()) / max(1.0, track.width())
        return int(round(self._min + ratio * (self._max - self._min)))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.setValue(self._value_at(event.position().x()))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging:
            self.setValue(self._value_at(event.position().x()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._dragging = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        self.setValue(self._value + (1 if event.angleDelta().y() > 0 else -1))
        event.accept()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    # -- painting ----------------------------------------------------------
    def _track_rect(self) -> QRectF:
        return QRectF(9, self.height() / 2 - 3, max(10.0, self.width() - 18), 6)

    def paintEvent(self, event):  # noqa: N802
        p = palette()
        accent = p["accent"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        track = self._track_rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(color(p["white"], 24 if p["is_dark"] else 28))
        painter.drawRoundedRect(track, 3, 3)

        ratio = (self._value - self._min) / max(1, self._max - self._min)
        knob_x = track.left() + track.width() * ratio
        accent_alpha = 255 if (self._hover or self._dragging) else 220
        gradient = QLinearGradient(track.topLeft(), track.topRight())
        gradient.setColorAt(0.0, color(accent["primary"], accent_alpha))
        gradient.setColorAt(1.0, color(accent["secondary"], accent_alpha))
        filled = QRectF(track.left(), track.top(), max(0.0, knob_x - track.left()), track.height())
        if filled.width() > 1:
            painter.setBrush(gradient)
            painter.drawRoundedRect(filled, 3, 3)

        painter.setBrush(QColor(255, 255, 255, 245))
        painter.setPen(QPen(color(accent["primary"], 130), 1))
        painter.drawEllipse(QRectF(knob_x - 7, track.center().y() - 7, 14, 14))
        painter.end()


class _SliderRow(QWidget):
    def __init__(
        self,
        label: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.suffix = suffix
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.label = QLabel(label)
        self.label.setProperty("muted", True)
        self.label.setFixedWidth(62)
        layout.addWidget(self.label)
        self.slider = _Slider(minimum, maximum, value)
        layout.addWidget(self.slider, 1)
        self.value_label = QLabel("")
        self.value_label.setFixedWidth(58)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        font = self.value_label.font()
        font.setWeight(QFont.DemiBold)
        self.value_label.setFont(font)
        layout.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._update_text)
        self._update_text()

    def _update_text(self, *_args) -> None:
        self.value_label.setText(f"{self.slider.value()}{self.suffix}")

    def set_value(self, value: int) -> None:
        self.slider.setValueSilently(value)
        self._update_text()


class VoiceFxPage(ScrollPage):
    title = "Voice FX"
    subtitle = "Real-time microphone presets"

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(controller, parent)
        self._building = True
        self._device_error = ""
        self._shown_error = ""
        self._silent_polls = 0
        self._build_devices()
        self._build_live()
        self._build_presets()
        self.layout_main.addStretch(1)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(140)
        self._apply_timer.timeout.connect(self._apply_audio_settings)

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._building = False

    # -- builders ----------------------------------------------------------
    def _section(self, title: str, subtitle: str) -> SectionCard:
        card = SectionCard(title, subtitle)
        self.layout_main.addWidget(card)
        return card

    def _build_live(self) -> None:
        card = self._section("Live voice", "Microphone processing")

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        self.status_pill = Pill("Idle", "muted")
        row_layout.addWidget(self.status_pill)
        self.status_text = QLabel("Microphone is not being accessed.")
        self.status_text.setProperty("muted", True)
        row_layout.addWidget(self.status_text, 1)

        self.start_button = make_button("Start listening", "primary", "play")
        self.start_button.clicked.connect(self._toggle_listening)
        row_layout.addWidget(self.start_button)

        self.record_button = make_button("Record", "default", "record")
        self.record_button.clicked.connect(self._toggle_recording)
        row_layout.addWidget(self.record_button)

        folder_button = make_button("Recordings", "ghost", "external")
        folder_button.setToolTip("Open the recordings folder")
        folder_button.clicked.connect(self._open_recordings)
        row_layout.addWidget(folder_button)
        card.body.addWidget(row)

        self.meter = _Meter()
        card.body.addWidget(self.meter)

        # Recording progress: shown only while a WAV is being written.
        self.rec_panel = QWidget()
        rec_layout = QHBoxLayout(self.rec_panel)
        rec_layout.setContentsMargins(0, 0, 0, 0)
        rec_layout.setSpacing(9)
        self.rec_dot = _RecordDot()
        rec_layout.addWidget(self.rec_dot)
        self.rec_time = QLabel("0:00")
        rec_font = self.rec_time.font()
        rec_font.setPointSizeF(10.4)
        rec_font.setWeight(QFont.DemiBold)
        self.rec_time.setFont(rec_font)
        self.rec_time.setFixedWidth(46)
        rec_layout.addWidget(self.rec_time)
        self.rec_text = QLabel("")
        self.rec_text.setProperty("muted", True)
        rec_layout.addWidget(self.rec_text, 1)
        self.rec_panel.hide()
        card.body.addWidget(self.rec_panel)

        self.alert = Banner("", "warn")
        self.alert.hide()
        card.body.addWidget(self.alert)

    def _build_presets(self) -> None:
        card = self._section("Preset", "Pitch and tone")
        tiles_widget = QWidget()
        tiles = QHBoxLayout(tiles_widget)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(10)
        self.tiles: dict[str, _PresetTile] = {}
        for key in PRESET_ORDER:
            tile = _PresetTile(PRESETS[key])
            tile.clicked.connect(self._on_preset_selected)
            self.tiles[key] = tile
            tiles.addWidget(tile)
        card.body.addWidget(tiles_widget)

        self.pitch_slider = _SliderRow("Pitch", MIN_PITCH, MAX_PITCH, 0, " st")
        self.pitch_slider.slider.valueChanged.connect(self._on_slider_changed)
        card.body.addWidget(self.pitch_slider)

        self.mix_slider = _SliderRow("Mix", 0, 100, 100, " %")
        self.mix_slider.slider.valueChanged.connect(self._on_slider_changed)
        card.body.addWidget(self.mix_slider)

        self.volume_slider = _SliderRow("Volume", int(MIN_GAIN_DB), int(MAX_GAIN_DB), 0, " dB")
        self.volume_slider.slider.valueChanged.connect(self._on_slider_changed)
        card.body.addWidget(self.volume_slider)

        note = QLabel(
            "These are DSP presets: pitch and tone shaping, not AI voice conversion. "
            "They are convincing on calls, but still sound like a processed version of you."
        )
        note.setProperty("muted", True)
        note.setWordWrap(True)
        card.body.addWidget(note)

    def _build_devices(self) -> None:
        card = self._section("Microphone & output", "Where the voice comes from and goes")

        self.input_combo = QComboBox()
        self.input_combo.setFixedWidth(340)
        self.input_combo.currentIndexChanged.connect(self._on_input_changed)
        card.body.addWidget(
            SettingRow("Microphone", "The device that is processed.", self.input_combo)
        )

        self.output_combo = QComboBox()
        self.output_combo.setFixedWidth(340)
        self.output_combo.currentIndexChanged.connect(self._on_output_changed)
        card.body.addWidget(
            SettingRow(
                "Send to",
                "Virtual cable input when one is installed; otherwise record only.",
                self.output_combo,
            )
        )

        self.monitor_toggle = ToggleSwitch(False)
        self.monitor_toggle.toggled.connect(self._on_monitor_changed)
        card.body.addWidget(
            SettingRow(
                "Monitor in headphones",
                "Hear the processed voice yourself. Use headphones — speakers will feed back.",
                self.monitor_toggle,
            )
        )

        self.cable_banner = Banner("", "info")
        cable_button = make_button("vb-cable.com", "ghost", "external")
        cable_button.clicked.connect(self._open_cable_site)
        self.cable_banner.add_action(cable_button)
        card.body.addWidget(self.cable_banner)

        self.detail_label = QLabel("")
        self.detail_label.setProperty("muted", True)
        self.detail_label.setWordWrap(True)
        card.body.addWidget(self.detail_label)

    # -- settings ----------------------------------------------------------
    def _settings(self):
        return self.controller.settings

    def _on_preset_selected(self, key: str) -> None:
        self._settings().set("voice_preset", key)
        for tile_key, tile in self.tiles.items():
            tile.set_selected(tile_key == key)
        self._apply_timer.start()

    def _on_slider_changed(self, _value: int) -> None:
        if self._building:
            return
        s = self._settings()
        s.set("voice_pitch", clamp_pitch(self.pitch_slider.slider.value()))
        s.set("voice_wet", clamp_wet(self.mix_slider.slider.value()))
        s.set("voice_gain", clamp_gain(self.volume_slider.slider.value()))
        self._apply_timer.start()

    def _apply_audio_settings(self) -> None:
        voice = self.controller.voice
        voice.reload()
        if voice.state == "error" and voice.error_message():
            self._show_alert(voice.error_message(), "error")

    def _on_input_changed(self, _index: int) -> None:
        if self._building:
            return
        self._settings().set("voice_input", self.input_combo.currentData() or "")
        self._apply_audio_settings()

    def _on_output_changed(self, _index: int) -> None:
        if self._building:
            return
        self._settings().set("voice_output", self.output_combo.currentData() or "")
        self._apply_audio_settings()

    def _on_monitor_changed(self, checked: bool) -> None:
        if self._building:
            return
        self._settings().set("voice_monitor", checked)
        self._apply_audio_settings()
        if checked:
            self._show_alert(
                "Monitoring is on. Use headphones: playing the processed voice through "
                "speakers next to your microphone causes feedback.",
                "warn",
            )
        elif self.alert.text_label.text().startswith("Monitoring is on"):
            self.alert.hide()

    # -- actions -----------------------------------------------------------
    def _toggle_listening(self) -> None:
        voice = self.controller.voice
        if voice.is_running():
            voice.stop()
            self._settings().set("voice_fx_enabled", False)
            self._show_alert("", "info", hide=True)
            self.refresh()
            return
        ok, message = voice.start()
        self._settings().set("voice_fx_enabled", ok)
        if not ok:
            self._show_alert(message, "error")
        else:
            if voice.output_device() is not None:
                target = voice.output_device().name
            elif voice.monitor_device() is not None:
                target = f"headphones ({voice.monitor_device().name})"
            else:
                target = "no output (record only)"
            Toast.show_message(
                self.window(),
                f"Voice FX on — sending to {target}. {self._describe_current()}",
                "success",
            )
            self._show_alert("", "info", hide=True)
        self.refresh()

    def _describe_current(self) -> str:
        spec = self.controller.voice.spec()
        label = spec.get("label", "Off")
        pitch = float(spec.get("pitch_semitones", 0))
        return f"{label} ({pitch:+.1f} st)" if abs(pitch) >= 0.01 else str(label)

    def _toggle_recording(self) -> None:
        voice = self.controller.voice
        if voice.is_recording():
            path = voice.stop_recording()
            Toast.show_message(
                self.window(),
                f"Recording saved: {path.name}" if path else "Recording stopped.",
                "success",
            )
            self.refresh()
            return
        if not voice.is_running():
            ok, message = voice.start()
            self._settings().set("voice_fx_enabled", ok)
            if not ok:
                self._show_alert(message, "error")
                self.refresh()
                return
        ok, message = voice.start_recording()
        if not ok:
            self._show_alert(message, "error")
        else:
            Toast.show_message(self.window(), f"Recording to {message}", "info")
        self.refresh()

    def _open_recordings(self) -> None:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(RECORDINGS_DIR)))

    def _open_cable_site(self) -> None:
        QDesktopServices.openUrl(QUrl(VB_CABLE_URL))

    # -- alerts ------------------------------------------------------------
    def _show_alert(self, text: str, tone: str = "warn", hide: bool = False) -> None:
        if hide or not text:
            self.alert.hide()
            return
        self.alert.set_text(text)
        self.alert.show()

    # -- polling -----------------------------------------------------------
    def _poll(self) -> None:
        voice = self.controller.voice

        # The stream died while recording: close the file so it stays playable.
        if voice.state == "error" and voice.is_recording():
            path = voice.stop_recording()
            message = voice.error_message()
            if path is not None:
                message = f"{message} The recording was saved as {path.name}."
            self._shown_error = message
            self._show_alert(message, "error")

        levels = voice.levels()
        self.meter.set_levels(levels["input_peak"], levels["output_peak"])

        running = voice.is_running()
        recording = voice.is_recording()

        if recording:
            self.status_pill.set_text("Recording")
            self.status_pill.set_tone("danger")
        elif running:
            self.status_pill.set_text("Listening")
            self.status_pill.set_tone("success")
        elif voice.state == "error":
            self.status_pill.set_text("Not running")
            self.status_pill.set_tone("danger")
        else:
            self.status_pill.set_text("Idle")
            self.status_pill.set_tone("muted")

        if running:
            source = _short(voice.input_device().name, 32) if voice.input_device() else "microphone"
            if voice.output_device() is not None:
                target = _short(voice.output_device().name, 26)
            elif voice.monitor_device() is not None:
                target = "headphones"
            else:
                target = "record only"
            self.status_text.setText(
                f"{source} → {target} · {voice.spec().get('label', 'Off')} · "
                f"~{levels['latency_ms']:.0f} ms"
            )
        elif voice.state == "error":
            self.status_text.setText("The microphone could not be started.")
        else:
            self.status_text.setText("Microphone is not being accessed.")

        # -- recording progress -------------------------------------------
        self.rec_panel.setVisible(recording)
        self.rec_dot.set_active(recording)
        if recording:
            self.rec_dot.tick()
            seconds = int(voice.recording_seconds())
            self.rec_time.setText(f"{seconds // 60}:{seconds % 60:02d}")
            size_kb = voice.recording_bytes() / 1024.0
            size_text = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            self.rec_text.setText(f"{voice.recording_name()} · {size_text}")
            if levels["input_peak"] < 0.0008:
                self._silent_polls += 1
                if self._silent_polls == 32:  # ~2.5 s of digital silence
                    self._show_alert(
                        "No audio is reaching Voice FX. Check that the microphone is not "
                        "muted and that its Windows input level is turned up.",
                        "warn",
                    )
            else:
                self._silent_polls = 0
        else:
            self._silent_polls = 0

        self.start_button.setText("Stop listening" if running else "Start listening")
        self.record_button.setText("Stop recording" if recording else "Record")

        # Surface failures that happen while the page is open (device unplugged,
        # privacy settings changed) once per message instead of every poll.
        message = voice.error_message()
        if voice.state == "error" and message and message != self._shown_error:
            self._shown_error = message
            self._show_alert(message, "error")
        elif running and self._shown_error:
            self._shown_error = ""
            self.alert.hide()

    # -- refresh -----------------------------------------------------------
    def refresh(self) -> None:
        self._building = True
        s = self._settings()
        preset_key = str(s.get("voice_preset", "off"))
        for key, tile in self.tiles.items():
            tile.set_selected(key == preset_key)
        self.pitch_slider.set_value(clamp_pitch(s.get("voice_pitch", 0)))
        self.mix_slider.set_value(clamp_wet(s.get("voice_wet", 100)))
        self.volume_slider.set_value(int(clamp_gain(s.get("voice_gain", 0))))
        self.monitor_toggle.setChecked(s.get_bool("voice_monitor", False), animate=False)

        # Re-enumerating PortAudio while a stream is open aborts it (and used to
        # kill recordings the moment this page refreshed). Use the cached list.
        use_cache = self.controller.voice.is_running()
        self._reload_device_combos(
            self.input_combo, saved=str(s.get("voice_input", "")), inputs=True, use_cache=use_cache
        )
        self._reload_device_combos(
            self.output_combo, saved=str(s.get("voice_output", "")), inputs=False, use_cache=use_cache
        )
        self._refresh_cable_banner()
        self._building = False

    def _reload_device_combos(
        self, combo: QComboBox, saved: str, inputs: bool, use_cache: bool = False
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        try:
            found = audio_devices.list_devices(use_cache=use_cache)
        except audio_devices.AudioUnavailable as exc:
            combo.addItem("Audio backend unavailable", "")
            combo.setEnabled(False)
            self._device_error = str(exc)
            combo.blockSignals(False)
            return
        combo.setEnabled(True)
        options = audio_devices.pick_devices(found, prefer_input=inputs)
        auto_label = "Windows default microphone" if inputs else "Automatic (virtual microphone)"
        combo.addItem(auto_label, "")
        if not inputs:
            combo.addItem("No output (record only)", NO_OUTPUT)
        # Only the endpoints a person would actually pick, one entry per name.
        for device in options:
            combo.addItem(device.label, device.name)
            combo.setItemData(combo.count() - 1, f"{device.name}  ·  {device.host_api}", Qt.ToolTipRole)
        # Resolve the automatic choice inside the visible list, so the combo shows
        # the microphone that will actually be opened instead of falling back to
        # its first row.
        current = saved
        if not current and inputs:
            resolved = audio_devices.find_device(options, "", prefer_input=True)
            current = resolved.name if resolved is not None else ""
        elif not current:
            cable = audio_devices.virtual_cable_output(options)
            current = cable.name if cable is not None else NO_OUTPUT
        index = combo.findData(current)
        if index < 0 and current:
            # A saved WDM-KS Bluetooth stub is listed under its MME/WASAPI name;
            # resolve it as the same endpoint so the combo shows the real choice.
            for position in range(combo.count()):
                if audio_devices.same_device(str(combo.itemData(position) or ""), current):
                    index = position
                    break
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _refresh_cable_banner(self) -> None:
        try:
            installed, message = audio_devices.cable_status()
        except audio_devices.AudioUnavailable as exc:
            installed, message = False, str(exc)
        self.cable_banner.set_tone("success" if installed else "warn")
        self.cable_banner.set_text(message + ("  " + INSTRUCTIONS if not installed else ""))

        voice = self.controller.voice
        spec = voice.spec()
        bits = [f"Preset: {spec.get('label', 'Off')}"]
        if voice.is_running():
            bits.append(f"{voice.levels()['sample_rate']} Hz mono")
        if self._device_error:
            bits.append(self._device_error)
        self.detail_label.setText(" · ".join(bits))
