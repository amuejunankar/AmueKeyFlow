"""Static 104-key layout data and raw key identification.

Pure module (no Qt, no Windows imports) so the key tester's geometry and the
virtual-key/scan-code disambiguation can be unit tested anywhere.

The layout is expressed in key units: ``1.0`` is a standard single keycap. A
:class:`Block` is a group of rows placed at a horizontal offset, which keeps the
main typing area, the navigation cluster and the numpad independently aligned.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.keycodes import MODIFIER_LABELS, VK_TO_KEY, key_label


@dataclass(frozen=True)
class KeyCap:
    key_id: str
    label: str
    width: float = 1.0
    height: float = 1.0


@dataclass(frozen=True)
class Block:
    """Rows of keycaps; a bare float is a horizontal spacer in key units."""

    x: float
    start_row: int
    rows: tuple[tuple[KeyCap | float, ...], ...]


def _cap(key_id: str, label: str | None = None, width: float = 1.0, height: float = 1.0) -> KeyCap:
    return KeyCap(key_id, label if label is not None else key_label(key_id).upper(), width, height)


# Row indices: 0 = function row, 1 = number row, 2 = QWERTY, 3 = ASDF, 4 = ZXCV, 5 = bottom.
FUNCTION_ROW = (
    _cap("escape", "ESC"),
    0.5,
    _cap("f1"), _cap("f2"), _cap("f3"), _cap("f4"),
    0.5,
    _cap("f5"), _cap("f6"), _cap("f7"), _cap("f8"),
    0.5,
    _cap("f9"), _cap("f10"), _cap("f11"), _cap("f12"),
)
NUMBER_ROW = (
    _cap("grave", "`"),
    _cap("1"), _cap("2"), _cap("3"), _cap("4"), _cap("5"),
    _cap("6"), _cap("7"), _cap("8"), _cap("9"), _cap("0"),
    _cap("minus", "-"), _cap("equal", "="),
    _cap("backspace", "BACKSPACE", 2.0),
)
ROW_Q = (
    _cap("tab", "TAB", 1.5),
    _cap("q"), _cap("w"), _cap("e"), _cap("r"), _cap("t"),
    _cap("y"), _cap("u"), _cap("i"), _cap("o"), _cap("p"),
    _cap("bracketleft", "["), _cap("bracketright", "]"),
    _cap("backslash", "\\", 1.5),
)
ROW_A = (
    _cap("capslock", "CAPS", 1.75),
    _cap("a"), _cap("s"), _cap("d"), _cap("f"), _cap("g"),
    _cap("h"), _cap("j"), _cap("k"), _cap("l"),
    _cap("semicolon", ";"),
    _cap("quote", "'"),
    _cap("enter", "ENTER", 2.25),
)
ROW_Z = (
    _cap("lshift", "SHIFT", 2.25),
    _cap("z"), _cap("x"), _cap("c"), _cap("v"), _cap("b"), _cap("n"), _cap("m"),
    _cap("comma", ","), _cap("period", "."), _cap("slash", "/"),
    _cap("rshift", "SHIFT", 2.75),
)
BOTTOM_ROW = (
    _cap("lctrl", "CTRL", 1.25),
    _cap("lwin", "WIN", 1.25),
    _cap("lalt", "ALT", 1.25),
    _cap("space", "SPACE", 6.25),
    _cap("ralt", "ALT", 1.25),
    _cap("rwin", "WIN", 1.25),
    _cap("apps", "MENU", 1.25),
    _cap("rctrl", "CTRL", 1.25),
)

MAIN_BLOCK = Block(0.0, 0, (FUNCTION_ROW, NUMBER_ROW, ROW_Q, ROW_A, ROW_Z, BOTTOM_ROW))

SYSTEM_BLOCK = Block(
    15.7,
    0,
    ((_cap("printscreen", "PRTSC"), _cap("scrolllock", "SCRLK"), _cap("pause", "PAUSE")),),
)

NAV_BLOCK = Block(
    15.7,
    2,
    (
        (_cap("insert", "INS"), _cap("home", "HOME"), _cap("pageup", "PGUP")),
        (_cap("delete", "DEL"), _cap("end", "END"), _cap("pagedown", "PGDN")),
        (1.0, _cap("up", "\u2191"), 1.0),
        (_cap("left", "\u2190"), _cap("down", "\u2193"), _cap("right", "\u2192")),
    ),
)

NUMPAD_BLOCK = Block(
    19.4,
    1,
    (
        (_cap("numlock", "NUM"), _cap("numpaddivide", "/"), _cap("numpadmultiply", "*"), _cap("numpadsubtract", "-")),
        (_cap("numpad7", "7"), _cap("numpad8", "8"), _cap("numpad9", "9"), _cap("numpadadd", "+", 1.0, 2.0)),
        (_cap("numpad4", "4"), _cap("numpad5", "5"), _cap("numpad6", "6"), 1.0),
        (_cap("numpad1", "1"), _cap("numpad2", "2"), _cap("numpad3", "3"), _cap("numpadenter", "ENTER", 1.0, 2.0)),
        (_cap("numpad0", "0", 2.0), _cap("numpaddecimal", "."), 1.0),
    ),
)

BLOCKS: tuple[Block, ...] = (MAIN_BLOCK, SYSTEM_BLOCK, NAV_BLOCK, NUMPAD_BLOCK)

#: Total layout width in key units, including the gaps between blocks.
TOTAL_UNITS = 23.4

#: Ids of every key drawn on the standard layout.
LAYOUT_IDS: frozenset[str] = frozenset(
    entry.key_id
    for block in BLOCKS
    for row in block.rows
    for entry in row
    if isinstance(entry, KeyCap)
)

#: Side specific modifier virtual keys reported by the low-level hook.
_SPECIFIC_MODIFIERS: dict[int, str] = {
    0xA0: "lshift",
    0xA1: "rshift",
    0xA2: "lctrl",
    0xA3: "rctrl",
    0xA4: "lalt",
    0xA5: "ralt",
    0x5B: "lwin",
    0x5C: "rwin",
}

#: Keys whose meaning depends on the extended flag (numpad vs. navigation).
_EXTENDED_PAIRS: dict[int, tuple[str, str]] = {
    0x0D: ("numpadenter", "enter"),  # (extended, plain)
    0x2D: ("insert", "numpad0"),
    0x2E: ("delete", "numpaddecimal"),
    0x24: ("home", "numpad7"),
    0x23: ("end", "numpad1"),
    0x21: ("pageup", "numpad9"),
    0x22: ("pagedown", "numpad3"),
    0x26: ("up", "numpad8"),
    0x28: ("down", "numpad2"),
    0x25: ("left", "numpad4"),
    0x27: ("right", "numpad6"),
}

_NUMPAD_DIGITS = {0x60 + digit: f"numpad{digit}" for digit in range(10)}


def is_layout_key(key_id: str | None) -> bool:
    return bool(key_id) and key_id in LAYOUT_IDS


def key_id_for_event(vk: int, scan_code: int = 0, extended: bool = False) -> str | None:
    """Return the layout key id a raw hook event belongs to, or ``None``.

    ``None`` means the key is not part of the standard layout (media keys,
    F13-F24, OEM, IME or vendor keys), which the tester lists separately.
    """
    specific = _SPECIFIC_MODIFIERS.get(vk)
    if specific:
        return specific

    if vk == 0x10:  # generic SHIFT: scan code 0x36 is the right hand key
        return "rshift" if scan_code == 0x36 else "lshift"
    if vk == 0x11:  # generic CTRL: E0 prefix marks the right hand key
        return "rctrl" if extended else "lctrl"
    if vk == 0x12:  # generic ALT
        return "ralt" if extended else "lalt"

    pair = _EXTENDED_PAIRS.get(vk)
    if pair:
        return pair[0] if extended else pair[1]

    digit = _NUMPAD_DIGITS.get(vk)
    if digit:
        return digit

    name = VK_TO_KEY.get(vk)
    if name and name in LAYOUT_IDS:
        return name
    return None


def describe_key(vk: int, scan_code: int = 0, extended: bool = False, os_name: str | None = None) -> str:
    """Human readable label for any raw key event.

    Prefers the layout/key table name, then the name Windows reports for the
    key, then a raw ``VK``/scan-code description so nothing is dropped.
    """
    key_id = key_id_for_event(vk, scan_code, extended)
    if key_id:
        return MODIFIER_LABELS.get(key_id) or key_label(key_id)
    name = VK_TO_KEY.get(vk)
    if name:
        return key_label(name)
    # A single character is a scan-position artifact ("B" for a media key), not
    # a key name, so it is ignored in favour of the raw codes.
    if os_name and (len(os_name) > 1 or not os_name.isalnum()):
        return os_name
    if scan_code:
        return f"VK 0x{vk:02X} \u00b7 scan 0x{scan_code:02X}"
    return f"VK 0x{vk:02X}"
