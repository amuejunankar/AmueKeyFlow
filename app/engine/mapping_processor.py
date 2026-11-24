"""Pure, testable mapping resolution logic.

The processor is deliberately free of Windows and Qt imports: the hook feeds it
key events, it decides whether the event must be swallowed and which mapping
fires.  Everything that touches the OS (suppression, injection) lives in
:mod:`app.engine.keyboard_hook` and :mod:`app.engine.keyboard_simulator`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from app.database.models import Mapping
from app.engine.keycodes import (
    MODIFIER_FAMILIES,
    VK_TO_KEY,
    VK_TO_MODIFIER,
    chord_key,
    modifier_family,
    normalize_mods_safe,
    uses_specific_modifiers,
)

log = logging.getLogger(__name__)

TriggerCallback = Callable[[Mapping, str], None]


@dataclass
class HookEvent:
    vk: int
    key_down: bool
    injected: bool = False
    time: float = 0.0
    extended: bool = False
    scan_code: int = 0


def build_mapping_index(mappings: Iterable[Mapping]) -> tuple[dict[str, Mapping], dict[str, Mapping]]:
    """Index enabled mappings for chord lookup.

    Returns ``(by_chord, by_id)``. A chord that pins LEFT/RIGHT is only indexed
    under that side; family chords also match either physical modifier.
    """
    index: dict[str, Mapping] = {}
    by_id: dict[str, Mapping] = {}
    for mapping in mappings:
        if not mapping.is_enabled:
            continue
        try:
            specific = chord_key(mapping.input_config)
            family = chord_key(mapping.input_config, family_only=True)
        except (ValueError, TypeError):
            log.warning("Skipping mapping with invalid input: %s", mapping.id)
            continue
        index.setdefault(specific, mapping)
        if not uses_specific_modifiers(mapping.input_config):
            index.setdefault(family, mapping)
        by_id[mapping.id] = mapping
    return index, by_id


def mapping_for_chord(
    index: dict[str, Mapping], key_name: str, mods: Iterable[str]
) -> Mapping | None:
    """Resolve a key plus the active modifier tokens against a mapping index.

    Uses the same specific-then-family lookup as :class:`MappingProcessor`, so
    a preview (the Key Tester) cannot disagree with what the engine fires.
    """
    key = str(key_name or "").lower()
    if not key:
        return None
    specific = normalize_mods_safe(mods)
    if specific:
        mapping = index.get("+".join(specific) + "|" + key)
        if mapping is not None:
            return mapping
    family = sorted({modifier_family(m) for m in specific})
    return index.get("+".join(family) + "|" + key)


@dataclass
class ProcessorState:
    mods: set[str] = field(default_factory=set)
    down_keys: set[int] = field(default_factory=set)
    suppressed: dict[int, Mapping] = field(default_factory=dict)
    latched: set[str] = field(default_factory=set)
    last_fire: dict[str, float] = field(default_factory=dict)
    last_event_time: float = 0.0


class MappingProcessor:
    """Resolve physical key events against the active profile's mappings."""

    def __init__(self, on_trigger: TriggerCallback | None = None) -> None:
        self._on_trigger = on_trigger
        self._mappings: dict[str, Mapping] = {}
        self._by_id: dict[str, Mapping] = {}
        self.enabled = True
        self.paused = False
        self.repeat_policy = "block"
        self.repeat_throttle_ms = 150
        self.emergency_hotkey: dict | None = None
        self.on_emergency: Callable[[], None] | None = None
        self.on_hold_start: Callable[[Mapping], None] | None = None
        self.on_hold_stop: Callable[[str], None] | None = None
        self.state = ProcessorState()

    # -- configuration -----------------------------------------------------
    def set_mappings(self, mappings: Iterable[Mapping]) -> None:
        self._mappings, self._by_id = build_mapping_index(mappings)
        for mapping_id in list(self.state.latched):
            if mapping_id not in by_id:
                self.state.latched.discard(mapping_id)
                if self.on_hold_stop:
                    self.on_hold_stop(mapping_id)

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.release_latches()
        self.enabled = bool(enabled)

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.release_latches()
        self.paused = bool(paused)

    def set_repeat_policy(self, policy: str, throttle_ms: int = 150) -> None:
        self.repeat_policy = policy if policy in {"block", "allow", "throttle"} else "block"
        self.repeat_throttle_ms = max(0, int(throttle_ms))

    def set_emergency_hotkey(self, hotkey: dict | None) -> None:
        self.emergency_hotkey = hotkey or None

    def sync_modifiers(self, tokens: Iterable[str]) -> None:
        """Seed modifier state (used when the hook starts while keys are held)."""
        self.state.mods = {str(t).lower() for t in tokens if str(t).lower() in MODIFIER_FAMILIES}

    def reset_state(self) -> None:
        self.state = ProcessorState()

    def release_latches(self) -> None:
        for mapping_id in list(self.state.latched):
            self.state.latched.discard(mapping_id)
            if self.on_hold_stop:
                self.on_hold_stop(mapping_id)

    # -- queries -----------------------------------------------------------
    @property
    def active_mapping_count(self) -> int:
        return len(self._by_id)

    @property
    def latched_ids(self) -> set[str]:
        return set(self.state.latched)

    def mapping_for_input(self, chord: dict) -> Mapping | None:
        try:
            return self._mappings.get(chord_key(chord)) or self._mappings.get(chord_key(chord, family_only=True))
        except (ValueError, TypeError):
            return None

    # -- event handling ----------------------------------------------------
    def handle(self, event: HookEvent) -> bool:
        """Return ``True`` when the event must be swallowed."""
        try:
            return self._handle(event)
        except Exception:  # pragma: no cover - never break the hook
            log.exception("Mapping processor failed for vk=%s", event.vk)
            return False

    def _handle(self, event: HookEvent) -> bool:
        vk = event.vk
        self.state.last_event_time = event.time or time.monotonic()

        if event.key_down:
            if self._is_emergency(event):
                if self.on_emergency:
                    self.on_emergency()
                return True

            mod = VK_TO_MODIFIER.get(vk)
            if mod:
                self.state.mods.add(mod[0])
                self.state.down_keys.add(vk)
                return False

            already_down = vk in self.state.down_keys
            self.state.down_keys.add(vk)

            key_name = VK_TO_KEY.get(vk)
            if key_name is None:
                return False
            if not self.enabled or self.paused or not self._mappings:
                return False

            mapping = self._resolve(key_name)
            if mapping is None:
                return False

            self.state.suppressed[vk] = mapping
            if mapping.trigger_behavior == "release":
                return True

            if already_down and not self._allow_repeat(mapping):
                return True

            self._fire(mapping)
            if mapping.trigger_behavior == "hold" and self.on_hold_start and not already_down:
                self.on_hold_start(mapping)
            return True

        # ---- key up ------------------------------------------------------
        was_down = vk in self.state.down_keys
        self.state.down_keys.discard(vk)
        mod = VK_TO_MODIFIER.get(vk)
        if mod:
            self.state.mods.discard(mod[0])
        else:
            mapping = self.state.suppressed.pop(vk, None)
            if mapping is not None and was_down:
                if mapping.trigger_behavior == "release":
                    self._fire(mapping)
                elif mapping.trigger_behavior == "hold" and self.on_hold_stop:
                    self.on_hold_stop(mapping.id)
                return True
        if vk in self.state.suppressed:
            mapping = self.state.suppressed.pop(vk)
            if mapping is not None:
                if mapping.trigger_behavior == "release":
                    self._fire(mapping)
                elif mapping.trigger_behavior == "hold" and self.on_hold_stop:
                    self.on_hold_stop(mapping.id)
            return True
        return False

    # -- internals ---------------------------------------------------------
    def _resolve(self, key_name: str) -> Mapping | None:
        return mapping_for_chord(self._mappings, key_name, self.state.mods)

    def _allow_repeat(self, mapping: Mapping) -> bool:
        if self.repeat_policy == "block":
            return False
        if self.repeat_policy == "allow":
            return True
        now = self.state.last_event_time
        last = self.state.last_fire.get(mapping.id, 0.0)
        if (now - last) * 1000.0 >= self.repeat_throttle_ms:
            self.state.last_fire[mapping.id] = now
            return True
        return False

    def _fire(self, mapping: Mapping) -> None:
        now = self.state.last_event_time or time.monotonic()
        if mapping.trigger_behavior == "toggle":
            if mapping.id in self.state.latched:
                self.state.latched.discard(mapping.id)
                kind = "toggle_off"
            else:
                self.state.latched.add(mapping.id)
                kind = "toggle_on"
            self.state.last_fire[mapping.id] = now
            if self._on_trigger:
                self._on_trigger(mapping, kind)
            return
        self.state.last_fire[mapping.id] = now
        if self._on_trigger:
            self._on_trigger(mapping, "press")

    def _is_emergency(self, event: HookEvent) -> bool:
        if not self.emergency_hotkey or not self.on_emergency:
            return False
        key = str(self.emergency_hotkey.get("key", ""))
        if VK_TO_KEY.get(event.vk) != key:
            return False
        wanted = {modifier_family(str(m)) for m in self.emergency_hotkey.get("mods", [])}
        active = {modifier_family(m) for m in self.state.mods}
        return wanted.issubset(active)
