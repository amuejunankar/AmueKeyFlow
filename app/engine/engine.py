"""Keyboard engine facade: hook + processor + simulation + worker threads."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Iterable

from app.constants import DEFAULT_EMERGENCY_HOTKEY
from app.database.models import Mapping
from app.engine.key_recorder import KeyRecorder
from app.engine.keyboard_hook import LowLevelKeyboardHook
from app.engine.keyboard_simulator import KeyboardSimulator, SendInputError, vk_for_key
from app.engine.mapping_processor import HookEvent, MappingProcessor
from app.services.activity_logger import ActivityLogger
from app.services.settings_manager import SettingsManager

log = logging.getLogger(__name__)

Notifier = Callable[[str, dict], None]


class MappingEngine:
    """Own the global hook and execute mapping outputs off the hook thread."""

    def __init__(
        self,
        settings: SettingsManager,
        activity: ActivityLogger,
        notify: Notifier | None = None,
    ) -> None:
        self.settings = settings
        self.activity = activity
        self._notify_cb = notify
        self.processor = MappingProcessor(on_trigger=self._on_trigger)
        self.simulator = KeyboardSimulator()
        self.hook = LowLevelKeyboardHook(self._handle_event)
        self.recorder = KeyRecorder(self.hook)

        self.processor.on_hold_start = self._on_hold_start
        self.processor.on_hold_stop = self._on_hold_stop
        self.processor.on_emergency = lambda: self.emergency_stop("Emergency hotkey pressed")

        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop_worker = threading.Event()
        self._desired_running = False
        self._emergency = False
        self._watchdog: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._hold_events: dict[str, threading.Event] = {}
        self._held_outputs: dict[str, list[int]] = {}
        self._last_error = ""
        self._started_at = 0.0
        self._lock = threading.RLock()

    # -- notifications -----------------------------------------------------
    def _notify(self, event: str, payload: dict) -> None:
        if self._notify_cb:
            try:
                self._notify_cb(event, payload)
            except Exception:  # pragma: no cover
                log.exception("Engine notification failed")

    # -- public API --------------------------------------------------------
    def configure(self) -> None:
        s = self.settings
        self.processor.set_repeat_policy(
            str(s.get("key_repeat_policy", "block")), s.get_int("repeat_throttle_ms", 150)
        )
        emergency_enabled = s.get_bool("emergency_hotkey_enabled", True)
        self.processor.set_emergency_hotkey(DEFAULT_EMERGENCY_HOTKEY if emergency_enabled else None)
        # An emergency stop must never be undone by an unrelated settings change.
        if not self._emergency:
            self.processor.set_enabled(s.get_bool("mappings_enabled", True))

    def set_mappings(self, mappings: Iterable[Mapping]) -> None:
        items = list(mappings)
        self.processor.set_mappings(items)
        # A latched (toggle) mapping that disappeared or was disabled must not
        # leave its output keys held down.
        active_ids = {m.id for m in items if m.is_enabled}
        for mapping_id in list(self._held_outputs):
            if mapping_id not in active_ids:
                self._release_output(mapping_id)
        self._notify("mappings_changed", {"count": self.processor.active_mapping_count})

    def set_mappings_enabled(self, enabled: bool) -> None:
        self.processor.set_enabled(enabled)

    def set_paused(self, paused: bool) -> None:
        self.processor.set_paused(paused)

    @property
    def paused(self) -> bool:
        return self.processor.paused

    @property
    def mappings_enabled(self) -> bool:
        return self.processor.enabled

    @property
    def emergency_stopped(self) -> bool:
        return self._emergency

    @property
    def running(self) -> bool:
        return self.hook.is_running

    @property
    def last_error(self) -> str:
        return self._last_error or self.hook.last_error

    def status(self) -> dict:
        return {
            "running": self.hook.is_running,
            "enabled": self.processor.enabled,
            "paused": self.processor.paused,
            "emergency": self._emergency,
            "mapped": self.processor.active_mapping_count,
            "error": self.last_error,
        }

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        self.configure()
        self._start_worker()
        if not self.hook.start():
            self._last_error = self.hook.last_error or "The keyboard hook could not be installed."
            log.error(self._last_error)
            self._notify("engine_failed", {"error": self._last_error})
            return False
        self.hook.seed_modifiers(self.processor)
        self.processor.reset_state()
        self.processor.set_paused(False)
        self._desired_running = True
        self._emergency = False
        self._started_at = time.monotonic()
        self._start_watchdog()
        log.info(
            "Keyboard engine started (%s active mapping(s), enabled=%s)",
            self.processor.active_mapping_count,
            self.processor.enabled,
        )
        self._notify("engine_started", self.status())
        return True

    def stop(self, release: bool = True) -> None:
        self._desired_running = False
        self._watchdog_stop.set()
        try:
            self.recorder.stop()
        except Exception:  # pragma: no cover
            pass
        self.hook.stop()
        self._release_latches()
        if release:
            try:
                self.simulator.release_all()
            except Exception:  # pragma: no cover
                log.exception("Releasing simulated keys failed")
        self.processor.reset_state()
        log.info("Keyboard engine stopped; all simulated keys released")
        self._notify("engine_stopped", self.status())

    def shutdown(self) -> None:
        """Full teardown used when the application exits."""
        self.stop(release=True)
        self._stop_worker.set()
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(2.0)
            self._worker = None

    def restart_interception(self) -> bool:
        self._emergency = False
        self._desired_running = False
        return self.hook.restart() and self.start()

    def emergency_stop(self, reason: str = "Emergency stop") -> None:
        """Disable interception immediately and restore a normal keyboard."""
        log.warning("Emergency stop: %s", reason)
        self._emergency = True
        self._desired_running = False
        self.processor.paused = True
        self.processor.set_enabled(False)
        self._release_latches()
        try:
            self.hook.stop()
        finally:
            try:
                self.simulator.release_all()
            except Exception:  # pragma: no cover
                log.exception("Could not release simulated keys during emergency stop")
        self._notify("emergency_stop", {"reason": reason, **self.status()})

    # -- hook callback -----------------------------------------------------
    def _handle_event(self, event: HookEvent) -> bool:
        if event.injected:
            return False
        return self.processor.handle(event)

    # -- output execution --------------------------------------------------
    def _on_trigger(self, mapping: Mapping, kind: str) -> None:
        held_mods = sorted(self.processor.state.mods)
        if kind == "toggle_on":
            if mapping.mapping_type in {"key", "shortcut"}:
                self._enqueue(mapping, held_mods, mode="hold_on")
            else:
                self._enqueue(mapping, held_mods, mode="press")
            return
        if kind == "toggle_off":
            self._release_output(mapping.id)
            return
        self._enqueue(mapping, held_mods, mode="press")

    def _enqueue(self, mapping: Mapping, held_mods: list[str], mode: str = "press") -> None:
        delay = int(mapping.delay or self.settings.get_int("mapping_delay_ms", 0) or 0)
        self._queue.put((mapping, held_mods, mode, delay))

    def _start_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop_worker.clear()
        self._worker = threading.Thread(target=self._worker_loop, name="KeyFlowExecutor", daemon=True)
        self._worker.start()

    def _worker_loop(self) -> None:
        while not self._stop_worker.is_set():
            item = self._queue.get()
            if item is None:
                break
            mapping, held_mods, mode, delay = item
            try:
                if delay:
                    time.sleep(min(delay, 60_000) / 1000.0)
                self._perform(mapping, held_mods, mode)
                if mode != "hold_on":
                    self.activity.log(mapping, "success")
                self._notify(
                    "mapping_triggered",
                    {
                        "mapping_id": mapping.id,
                        "name": mapping.name,
                        "input": mapping.input_display,
                        "output": mapping.output_display,
                        "status": "success",
                    },
                )
            except Exception as exc:
                log.exception("Mapping execution failed: %s", mapping.id)
                self.activity.log(mapping, "error", str(exc))
                self._notify(
                    "mapping_failed",
                    {"mapping_id": mapping.id, "name": mapping.name, "error": str(exc)},
                )

    def _perform(self, mapping: Mapping, held_mods: list[str], mode: str = "press") -> None:
        simulator = self.simulator
        output = mapping.output_config
        if mapping.mapping_type == "key":
            key = str(output.get("key", ""))
            vk = vk_for_key(key)
            if vk is None:
                raise SendInputError(f"Unknown output key: {key!r}")
            if mode == "hold_on":
                simulator.key_down(vk)
                self._held_outputs.setdefault(mapping.id, []).append(vk)
            else:
                simulator.tap_key(key)
            return
        if mapping.mapping_type == "shortcut":
            mods = [str(m) for m in output.get("mods", [])]
            key = str(output.get("key", ""))
            if mode == "hold_on":
                simulator.hold_chord(mods, key)
                held: list[int] = []
                for token in mods:
                    vk = vk_for_key(token)
                    if vk:
                        held.append(vk)
                key_vk = vk_for_key(key)
                if key_vk:
                    held.append(key_vk)
                self._held_outputs.setdefault(mapping.id, []).extend(held)
            else:
                simulator.send_chord(mods, key, held_mods)
            return
        if mapping.mapping_type == "action":
            simulator.perform_action(str(output.get("action", "")))
            return
        if mapping.mapping_type == "text":
            simulator.send_text(str(output.get("text", "")))
            return
        if mapping.mapping_type == "macro":
            for step in output.get("steps", []):
                kind = step.get("type")
                if kind == "wait":
                    time.sleep(min(int(step.get("ms", 0)), 60_000) / 1000.0)
                elif kind == "key":
                    simulator.tap_key(str(step.get("key", "")))
                elif kind == "shortcut":
                    simulator.send_chord(
                        [str(m) for m in step.get("mods", [])], str(step.get("key", "")), held_mods
                    )
                elif kind == "text":
                    simulator.send_text(str(step.get("text", "")))
            return
        raise SendInputError(f"Unsupported mapping type: {mapping.mapping_type}")

    # -- hold mode ---------------------------------------------------------
    def _on_hold_start(self, mapping: Mapping) -> None:
        self._on_hold_stop(mapping.id)
        stop_event = threading.Event()
        self._hold_events[mapping.id] = stop_event
        interval = max(60, self.settings.get_int("repeat_throttle_ms", 150)) / 1000.0

        def loop() -> None:
            while not stop_event.is_set():
                self._on_trigger(mapping, "press")
                if stop_event.wait(interval):
                    break

        thread = threading.Thread(target=loop, name=f"KeyFlowHold-{mapping.id[:6]}", daemon=True)
        thread.start()

    def _on_hold_stop(self, mapping_id: str) -> None:
        event = self._hold_events.pop(mapping_id, None)
        if event is not None:
            event.set()

    # -- helpers -----------------------------------------------------------
    def _release_output(self, mapping_id: str) -> None:
        vks = self._held_outputs.pop(mapping_id, [])
        if vks:
            self.simulator.release_keys(vks)

    def _release_latches(self) -> None:
        for mapping_id in list(self._held_outputs):
            self._release_output(mapping_id)
        for mapping_id in list(self._hold_events):
            self._on_hold_stop(mapping_id)

    def _start_watchdog(self) -> None:
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog = threading.Thread(target=self._watchdog_loop, name="KeyFlowWatchdog", daemon=True)
        self._watchdog.start()

    def _watchdog_loop(self) -> None:
        failures = 0
        while not self._watchdog_stop.wait(2.0):
            if not self._desired_running:
                continue
            if self.hook.is_running:
                failures = 0
                continue
            failures += 1
            log.warning("Keyboard hook is not running; attempting recovery (%s/3)", failures)
            if failures > 3:
                self._last_error = "The keyboard hook stopped unexpectedly. Mappings are disabled."
                self._desired_running = False
                self._notify("engine_failed", {"error": self._last_error})
                continue
            try:
                if self.hook.start():
                    self.hook.seed_modifiers(self.processor)
                    self.processor.reset_state()
                    self._notify("engine_recovered", self.status())
                    failures = 0
            except Exception:  # pragma: no cover
                log.exception("Hook recovery failed")

    def record_capture(self, on_captured, on_timeout=None, on_progress=None) -> bool:
        if not self.hook.is_running:
            return False
        timeout = max(3, self.settings.get_int("recording_timeout_s", 8))
        return self.recorder.start(timeout, on_captured, on_timeout, on_progress)

    def cancel_recording(self) -> None:
        self.recorder.stop()
