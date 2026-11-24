"""Tests for the key tester's layout data and raw key identification."""

from __future__ import annotations

from app.engine.key_layout import (
    BLOCKS,
    LAYOUT_IDS,
    KeyCap,
    describe_key,
    is_layout_key,
    key_id_for_event,
)
from app.engine.keycodes import key_label


def _row_width(rows) -> list[float]:
    widths = []
    for row in rows:
        widths.append(sum(entry.width if isinstance(entry, KeyCap) else float(entry) for entry in row))
    return widths


def test_layout_geometry_is_consistent():
    main = BLOCKS[0]
    assert _row_width(main.rows[1:]) == [15.0] * 5
    assert _row_width(BLOCKS[1].rows) == [3.0]  # print screen cluster
    assert _row_width(BLOCKS[2].rows) == [3.0] * 4  # navigation cluster
    assert _row_width(BLOCKS[3].rows) == [4.0] * 5  # numpad


def test_layout_ids_are_unique_and_labelled():
    assert len(LAYOUT_IDS) == len({key for key in LAYOUT_IDS})
    for key_id in ("a", "space", "numpadenter", "rshift", "printscreen"):
        assert key_id in LAYOUT_IDS


def test_letters_numbers_and_function_keys_land_on_the_layout():
    assert key_id_for_event(0x41) == "a"
    assert key_id_for_event(0x30) == "0"
    assert key_id_for_event(0x70) == "f1"
    assert key_id_for_event(0x7B) == "f12"
    assert key_id_for_event(0x20) == "space"


def test_shift_sides_use_the_scan_code():
    assert key_id_for_event(0x10, 0x2A) == "lshift"
    assert key_id_for_event(0x10, 0x36) == "rshift"
    assert key_id_for_event(0xA0, 0x2A) == "lshift"
    assert key_id_for_event(0xA1, 0x36) == "rshift"


def test_ctrl_and_alt_sides_use_the_extended_flag():
    assert key_id_for_event(0x11, 0x1D, False) == "lctrl"
    assert key_id_for_event(0x11, 0x1D, True) == "rctrl"
    assert key_id_for_event(0x12, 0x38, False) == "lalt"
    assert key_id_for_event(0x12, 0x38, True) == "ralt"


def test_enter_and_numpad_enter_are_distinguished():
    assert key_id_for_event(0x0D, 0x1C, False) == "enter"
    assert key_id_for_event(0x0D, 0x1C, True) == "numpadenter"


def test_numpad_keys_are_not_reported_as_navigation():
    assert key_id_for_event(0x26, 0x48, True) == "up"
    assert key_id_for_event(0x26, 0x48, False) == "numpad8"
    assert key_id_for_event(0x2E, 0x53, True) == "delete"
    assert key_id_for_event(0x2E, 0x53, False) == "numpaddecimal"
    assert key_id_for_event(0x60) == "numpad0"


def test_keys_outside_the_layout_are_reported_separately():
    assert key_id_for_event(0x7C) is None  # F13
    assert is_layout_key(key_id_for_event(0x7C)) is False
    assert key_id_for_event(0xAF) is None  # Volume up
    assert key_id_for_event(0xB5) is None  # Browser forward
    assert describe_key(0x7C) == "F13"
    assert describe_key(0xAF) == "VOL UP"


def test_unknown_keys_prefer_the_windows_name_and_fall_back_to_raw_codes():
    assert describe_key(0x8A, os_name="Vendor Key") == "Vendor Key"
    assert describe_key(0x8A) == "VK 0x8A"
    assert describe_key(0x8A, 0x36) == "VK 0x8A · scan 0x36"


def test_single_character_os_names_are_scan_position_artifacts():
    # GetKeyNameText names a position: a media key can resolve to a letter.
    assert describe_key(0xB5, 0x69, True, "B") == "VK 0xB5 · scan 0x69"


def test_known_keys_keep_their_friendly_label():
    assert describe_key(0xA0) == "LEFT SHIFT"
    assert describe_key(0x41) == key_label("a")
