"""Tests for trigger resolution, suppression and repeat policies."""

from __future__ import annotations

import pytest

from app.database.models import Mapping, new_id
from app.engine.mapping_processor import (
    HookEvent,
    MappingProcessor,
    build_mapping_index,
    mapping_for_chord,
)

CTRL, SHIFT, ALT = 0x11, 0x10, 0x12
LCTRL, RCTRL = 0xA2, 0xA3
B, CAPS, F14 = 0x42, 0x14, 0x7D


def mapping(mods, key, trigger="press", enabled=True, output=None, mapping_id=None):
    return Mapping(
        id=mapping_id or new_id(),
        profile_id="profile",
        name=f"{key} mapping",
        input_config={"mods": mods, "key": key},
        output_config=output or {"key": "home"},
        mapping_type="key",
        trigger_behavior=trigger,
        is_enabled=enabled,
    )


def event(vk, down=True, t=0.0):
    return HookEvent(vk=vk, key_down=down, time=t)


def build(mappings, triggered=None):
    fired = triggered if triggered is not None else []
    processor = MappingProcessor(on_trigger=lambda m, kind: fired.append((m.input_display, kind)))
    processor.set_mappings(mappings)
    return processor, fired


def press(processor, *vks):
    results = []
    for vk in vks:
        results.append(processor.handle(event(vk, True)))
    return results


def release(processor, *vks):
    return [processor.handle(event(vk, False)) for vk in vks]


def test_combination_is_suppressed_and_fires_once():
    processor, fired = build([mapping(["ctrl", "shift"], "b")])
    assert press(processor, CTRL, SHIFT) == [False, False]
    assert processor.handle(event(B, True)) is True
    assert len(fired) == 1
    # Auto-repeat of the held key is blocked by the default policy.
    processor.handle(event(B, True, t=0.05))
    assert len(fired) == 1
    assert processor.handle(event(B, False)) is True
    assert release(processor, SHIFT, CTRL) == [False, False]
    # Modifiers are released so nothing stays stuck.
    assert processor.state.mods == set()


def test_unmapped_key_passes_through():
    processor, fired = build([mapping([], "capslock")])
    assert processor.handle(event(F14, True)) is False
    assert fired == []
    assert processor.handle(event(F14, False)) is False


def test_disabled_mapping_does_not_intercept():
    processor, fired = build([mapping([], "capslock", enabled=False)])
    assert processor.handle(event(CAPS, True)) is False
    assert fired == []


def test_global_disable_restores_passthrough():
    processor, fired = build([mapping(["ctrl"], "b")])
    processor.set_enabled(False)
    press(processor, CTRL)
    assert processor.handle(event(B, True)) is False
    assert fired == []


def test_release_trigger_fires_on_keyup():
    processor, fired = build([mapping(["alt"], "q", trigger="release")])
    press(processor, ALT)
    assert processor.handle(event(0x51, True)) is True
    assert fired == []
    assert processor.handle(event(0x51, False)) is True
    assert fired and fired[0][1] == "press"


def test_repeat_policy_allow_and_throttle():
    processor, fired = build([mapping([], "capslock")])
    processor.set_repeat_policy("allow")
    processor.handle(event(CAPS, True, t=1.0))
    processor.handle(event(CAPS, True, t=1.03))
    assert len(fired) == 2

    processor, fired = build([mapping([], "capslock")])
    processor.set_repeat_policy("throttle", 150)
    processor.handle(event(CAPS, True, t=2.0))
    processor.handle(event(CAPS, True, t=2.05))
    assert len(fired) == 1
    processor.handle(event(CAPS, True, t=2.30))
    assert len(fired) == 2


def test_toggle_mode_latches_and_unlatches():
    processor, fired = build([mapping([], "capslock", trigger="toggle")])
    processor.handle(event(CAPS, True))
    processor.handle(event(CAPS, False))
    processor.handle(event(CAPS, True))
    processor.handle(event(CAPS, False))
    assert [kind for _, kind in fired] == ["toggle_on", "toggle_off"]


def test_specific_modifier_matching():
    processor, fired = build([mapping(["lctrl"], "b")])
    press(processor, LCTRL)
    assert processor.handle(event(B, True)) is True
    assert len(fired) == 1

    processor, fired = build([mapping(["ctrl"], "b")])
    press(processor, RCTRL)
    assert processor.handle(event(B, True)) is True
    assert len(fired) == 1


def test_left_specific_mapping_ignores_right_modifier():
    processor, fired = build([mapping(["lctrl"], "b")])
    press(processor, RCTRL)
    assert processor.handle(event(B, True)) is False
    assert fired == []


def test_emergency_hotkey_suppressed_and_reported():
    calls = []
    processor = MappingProcessor()
    processor.on_emergency = lambda: calls.append("stop")
    processor.set_emergency_hotkey({"mods": ["ctrl", "alt", "shift"], "key": "f12"})
    press(processor, CTRL, ALT, SHIFT)
    assert processor.handle(event(0x7B, True)) is True
    assert calls == ["stop"]


def test_pause_blocks_mappings():
    processor, fired = build([mapping([], "capslock")])
    processor.set_paused(True)
    assert processor.handle(event(CAPS, True)) is False
    assert processor.handle(event(CAPS, False)) is False
    processor.set_paused(False)
    assert processor.handle(event(CAPS, True)) is True
    assert len(fired) == 1


def test_hold_mode_start_and_stop():
    started, stopped = [], []
    processor, fired = build([mapping([], "capslock", trigger="hold")])
    processor.on_hold_start = lambda m: started.append(m.id)
    processor.on_hold_stop = lambda mid: stopped.append(mid)
    processor.handle(event(CAPS, True))
    processor.handle(event(CAPS, False))
    assert len(started) == 1
    assert stopped == started
    assert len(fired) == 1


def test_shared_lookup_matches_engine_resolution():
    caps = mapping([], "capslock")
    ctrl_b = mapping(["ctrl"], "b")
    left_b = mapping(["lctrl"], "b", mapping_id="left-b")
    disabled = mapping(["shift"], "f14", enabled=False)
    index, by_id = build_mapping_index([caps, ctrl_b, left_b, disabled])

    assert mapping_for_chord(index, "capslock", []) is caps
    assert mapping_for_chord(index, "b", ["ctrl"]) is ctrl_b
    assert mapping_for_chord(index, "b", ["rctrl"]) is ctrl_b
    assert mapping_for_chord(index, "b", ["lctrl"]) is left_b
    assert mapping_for_chord(index, "b", []) is None
    assert mapping_for_chord(index, "f14", ["shift"]) is None
    assert mapping_for_chord(index, "", []) is None
    assert set(by_id) == {caps.id, ctrl_b.id, left_b.id}


def test_every_key_up_is_safe_without_state():
    processor, _ = build([mapping([], "capslock")])
    assert processor.handle(event(CAPS, False)) is False
