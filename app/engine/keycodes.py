"""Canonical key tables, chord parsing and formatting.

A *chord* is represented as ``{"mods": ["ctrl", "shift"], "key": "b"}`` where
``mods`` holds canonical modifier tokens (``ctrl``, ``alt``, ``shift``, ``win``
or the left/right specific ``lctrl``/``rctrl``/... variants) and ``key`` holds
one canonical base key name such as ``"b"``, ``"f14"`` or ``"pageup"``.

The module is deliberately free of Qt and Windows imports so it can be unit
tested anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

# ---------------------------------------------------------------------------
# Modifiers
# ---------------------------------------------------------------------------

MODIFIER_FAMILIES: dict[str, str] = {
    "ctrl": "ctrl",
    "lctrl": "ctrl",
    "rctrl": "ctrl",
    "alt": "alt",
    "lalt": "alt",
    "ralt": "alt",
    "shift": "shift",
    "lshift": "shift",
    "rshift": "shift",
    "win": "win",
    "lwin": "win",
    "rwin": "win",
}

MODIFIER_LABELS: dict[str, str] = {
    "ctrl": "CTRL",
    "lctrl": "LEFT CTRL",
    "rctrl": "RIGHT CTRL",
    "alt": "ALT",
    "lalt": "LEFT ALT",
    "ralt": "RIGHT ALT",
    "shift": "SHIFT",
    "lshift": "LEFT SHIFT",
    "rshift": "RIGHT SHIFT",
    "win": "WIN",
    "lwin": "LEFT WIN",
    "rwin": "RIGHT WIN",
}

#: Generic virtual key codes used when injecting a *family* modifier.
MODIFIER_VK: dict[str, int] = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}

#: Side specific virtual key codes.
MODIFIER_SPECIFIC_VK: dict[str, int] = {
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "lalt": 0xA4,
    "ralt": 0xA5,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "lwin": 0x5B,
    "rwin": 0x5C,
}

#: vk -> (token used for the pressed state, family)
VK_TO_MODIFIER: dict[int, tuple[str, str]] = {
    0x11: ("ctrl", "ctrl"),
    0x12: ("alt", "alt"),
    0x10: ("shift", "shift"),
    0xA2: ("lctrl", "ctrl"),
    0xA3: ("rctrl", "ctrl"),
    0xA0: ("lshift", "shift"),
    0xA1: ("rshift", "shift"),
    0xA4: ("lalt", "alt"),
    0xA5: ("ralt", "alt"),
    0x5B: ("lwin", "win"),
    0x5C: ("rwin", "win"),
}

#: Identifiers reported by ``GetAsyncKeyState`` for generic modifier state.
GENERIC_MODIFIER_VK: dict[str, int] = {
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
}

MODIFIER_ORDER = ["ctrl", "lctrl", "rctrl", "alt", "lalt", "ralt", "shift", "lshift", "rshift", "win", "lwin", "rwin"]


@dataclass(frozen=True)
class KeyInfo:
    name: str
    vk: int
    label: str
    category: str
    extended: bool = False


_LETTERS = [(chr(c), 0x41 + (c - ord("a")), chr(c).upper(), "letters") for c in range(ord("a"), ord("z") + 1)]
_NUMBERS = [(str(d), 0x30 + d, str(d), "numbers") for d in range(10)]
_FUNCTION = [(f"f{i}", 0x6F + i, f"F{i}", "function") for i in range(1, 25)]

_NAVIGATION = [
    ("escape", 0x1B, "ESC", "navigation", False),
    ("tab", 0x09, "TAB", "navigation", False),
    ("capslock", 0x14, "CAPS LOCK", "navigation", False),
    ("enter", 0x0D, "ENTER", "navigation", False),
    ("backspace", 0x08, "BACKSPACE", "navigation", False),
    ("space", 0x20, "SPACE", "navigation", False),
    ("insert", 0x2D, "INSERT", "navigation", True),
    ("delete", 0x2E, "DELETE", "navigation", True),
    ("home", 0x24, "HOME", "navigation", True),
    ("end", 0x23, "END", "navigation", True),
    ("pageup", 0x21, "PAGE UP", "navigation", True),
    ("pagedown", 0x22, "PAGE DOWN", "navigation", True),
    ("up", 0x26, "UP", "navigation", True),
    ("down", 0x28, "DOWN", "navigation", True),
    ("left", 0x25, "LEFT", "navigation", True),
    ("right", 0x27, "RIGHT", "navigation", True),
]

_NUMPAD = [
    ("numlock", 0x90, "NUM LOCK", "numpad", True),
    ("numpad0", 0x60, "NUM 0", "numpad", False),
    ("numpad1", 0x61, "NUM 1", "numpad", False),
    ("numpad2", 0x62, "NUM 2", "numpad", False),
    ("numpad3", 0x63, "NUM 3", "numpad", False),
    ("numpad4", 0x64, "NUM 4", "numpad", False),
    ("numpad5", 0x65, "NUM 5", "numpad", False),
    ("numpad6", 0x66, "NUM 6", "numpad", False),
    ("numpad7", 0x67, "NUM 7", "numpad", False),
    ("numpad8", 0x68, "NUM 8", "numpad", False),
    ("numpad9", 0x69, "NUM 9", "numpad", False),
    ("numpadmultiply", 0x6A, "NUM *", "numpad", False),
    ("numpadadd", 0x6B, "NUM +", "numpad", False),
    ("numpadsubtract", 0x6D, "NUM -", "numpad", False),
    ("numpaddecimal", 0x6E, "NUM .", "numpad", False),
    ("numpaddivide", 0x6F, "NUM /", "numpad", True),
]

_SYMBOLS = [
    ("semicolon", 0xBA, ";", "symbols", False),
    ("equal", 0xBB, "=", "symbols", False),
    ("comma", 0xBC, ",", "symbols", False),
    ("minus", 0xBD, "-", "symbols", False),
    ("period", 0xBE, ".", "symbols", False),
    ("slash", 0xBF, "/", "symbols", False),
    ("grave", 0xC0, "`", "symbols", False),
    ("bracketleft", 0xDB, "[", "symbols", False),
    ("backslash", 0xDC, "\\", "symbols", False),
    ("bracketright", 0xDD, "]", "symbols", False),
    ("quote", 0xDE, "'", "symbols", False),
    ("oem102", 0xE2, "\\ (ISO)", "symbols", False),
]

_MEDIA = [
    ("mute", 0xAD, "MUTE", "media", True),
    ("volumedown", 0xAE, "VOL DOWN", "media", True),
    ("volumeup", 0xAF, "VOL UP", "media", True),
    ("nexttrack", 0xB0, "NEXT TRACK", "media", True),
    ("prevtrack", 0xB1, "PREV TRACK", "media", True),
    ("mediastop", 0xB2, "STOP MEDIA", "media", True),
    ("playpause", 0xB3, "PLAY / PAUSE", "media", True),
    ("launchmail", 0xB4, "LAUNCH MAIL", "media", True),
    ("browserhome", 0xAC, "BROWSER HOME", "media", True),
]

_SYSTEM = [
    ("printscreen", 0x2C, "PRINT SCREEN", "system", True),
    ("scrolllock", 0x91, "SCROLL LOCK", "system", False),
    ("pause", 0x13, "PAUSE", "system", False),
    ("apps", 0x5D, "MENU / APPS", "system", True),
    ("sleep", 0x5F, "SLEEP", "system", True),
]

KEY_LIST: list[KeyInfo] = [
    *[KeyInfo(n, vk, label, cat) for (n, vk, label, cat) in _LETTERS],
    *[KeyInfo(n, vk, label, cat) for (n, vk, label, cat) in _NUMBERS],
    *[KeyInfo(n, vk, label, cat) for (n, vk, label, cat) in _FUNCTION],
    *[KeyInfo(n, vk, label, cat, ext) for (n, vk, label, cat, ext) in _NAVIGATION],
    *[KeyInfo(n, vk, label, cat, ext) for (n, vk, label, cat, ext) in _NUMPAD],
    *[KeyInfo(n, vk, label, cat, ext) for (n, vk, label, cat, ext) in _SYMBOLS],
    *[KeyInfo(n, vk, label, cat, ext) for (n, vk, label, cat, ext) in _MEDIA],
    *[KeyInfo(n, vk, label, cat, ext) for (n, vk, label, cat, ext) in _SYSTEM],
]

KEY_INFO: dict[str, KeyInfo] = {k.name: k for k in KEY_LIST}
VK_TO_KEY: dict[int, str] = {}
for _info in KEY_LIST:
    VK_TO_KEY.setdefault(_info.vk, _info.name)

CATEGORY_LABELS: dict[str, str] = {
    "letters": "Letters",
    "numbers": "Numbers",
    "function": "Function keys",
    "navigation": "Navigation",
    "numpad": "Numpad",
    "symbols": "Symbols",
    "media": "Media",
    "system": "System",
}

#: Virtual keys that require ``KEYEVENTF_EXTENDEDKEY`` when injected even when
#: they are not flagged in the table above (handled for completeness).
EXTENDED_VK: set[int] = {k.vk for k in KEY_LIST if k.extended}


def key_label(name: str) -> str:
    info = KEY_INFO.get(name)
    if info:
        return info.label
    mod = MODIFIER_LABELS.get(name)
    if mod:
        return mod
    return name.upper()


def is_modifier(token: str) -> bool:
    return token.lower() in MODIFIER_FAMILIES


def modifier_family(token: str) -> str:
    return MODIFIER_FAMILIES.get(token.lower(), token.lower())


def normalize_mods(mods: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for token in mods:
        low = str(token).lower().strip()
        if low not in MODIFIER_FAMILIES:
            raise ValueError(f"Unknown modifier: {token!r}")
        if low not in seen:
            seen.append(low)
    return sorted(seen, key=lambda t: MODIFIER_ORDER.index(t))


def validate_chord(chord: Mapping[str, object]) -> tuple[bool, str]:
    """Return ``(ok, message)`` for a chord structure."""
    if not isinstance(chord, Mapping):
        return False, "Input must be an object with 'mods' and 'key'."
    key = chord.get("key")
    if not isinstance(key, str) or not key:
        return False, "A trigger key is required."
    if key not in KEY_INFO:
        return False, f"Unsupported trigger key: {key!r}"
    mods = chord.get("mods", [])
    if not isinstance(mods, (list, tuple)):
        return False, "'mods' must be a list."
    try:
        normalize_mods([str(m) for m in mods])
    except ValueError as exc:
        return False, str(exc)
    if len({modifier_family(str(m)) for m in mods}) != len(mods):
        return False, "Duplicate modifier families are not allowed."
    return True, ""


def uses_specific_modifiers(chord: Mapping[str, object]) -> bool:
    """True when the chord pins a modifier to its left/right physical side."""
    return any(str(m).lower() in {"lctrl", "rctrl", "lalt", "ralt", "lshift", "rshift", "lwin", "rwin"} for m in (chord.get("mods") or []))


def chord_key(chord: Mapping[str, object], family_only: bool = False) -> str:
    """Return a stable lookup key for a chord, e.g. ``"ctrl+alt|b"``."""
    mods = [str(m).lower() for m in (chord.get("mods") or [])]
    if family_only:
        mods = sorted({modifier_family(m) for m in mods})
    else:
        mods = normalize_mods(mods)
    key = str(chord.get("key", "")).lower()
    return "+".join(mods) + "|" + key


def make_chord(mods: Iterable[str], key: str) -> dict[str, object]:
    chord = {"mods": normalize_mods(mods), "key": key.lower()}
    ok, message = validate_chord(chord)
    if not ok:
        raise ValueError(message)
    return chord


def chord_display(chord: Mapping[str, object]) -> str:
    if not isinstance(chord, Mapping):
        return "—"
    mods = [str(m).lower() for m in (chord.get("mods") or [])]
    parts = [MODIFIER_LABELS.get(m, m.upper()) for m in normalize_mods_safe(mods)]
    key = str(chord.get("key", ""))
    parts.append(key_label(key))
    return " + ".join(parts)


def normalize_mods_safe(mods: Iterable[str]) -> list[str]:
    try:
        return normalize_mods(mods)
    except ValueError:
        return [str(m).lower() for m in mods]


def key_name_from_vk(vk: int) -> str | None:
    return VK_TO_KEY.get(vk)


def vk_for_key(name: str) -> int | None:
    info = KEY_INFO.get(name.lower())
    if info:
        return info.vk
    token = name.lower()
    if token in MODIFIER_SPECIFIC_VK:
        return MODIFIER_SPECIFIC_VK[token]
    return MODIFIER_VK.get(token)


def keys_by_category() -> dict[str, list[KeyInfo]]:
    grouped: dict[str, list[KeyInfo]] = {}
    for info in KEY_LIST:
        grouped.setdefault(info.category, []).append(info)
    return grouped


def search_keys(query: str) -> list[KeyInfo]:
    query = query.strip().lower()
    if not query:
        return list(KEY_LIST)
    results = []
    for info in KEY_LIST:
        if query in info.name or query in info.label.lower() or query in info.category:
            results.append(info)
    return results
