"""Validation and formatting for mapping outputs (key, shortcut, action, text, macro)."""

from __future__ import annotations

from typing import Any, Mapping

from app.constants import WINDOWS_ACTIONS
from app.engine.keycodes import (
    KEY_INFO,
    MODIFIER_LABELS,
    chord_display,
    normalize_mods,
    validate_chord,
)

MACRO_STEP_TYPES = {
    "key": "Key press",
    "shortcut": "Shortcut",
    "text": "Type text",
    "wait": "Wait",
}

MAX_MACRO_STEPS = 64
MAX_TEXT_LENGTH = 2000


def _validate_key_name(name: Any) -> tuple[bool, str]:
    if not isinstance(name, str) or name.lower() not in KEY_INFO:
        return False, f"Unknown key: {name!r}"
    return True, ""


def validate_macro_step(step: Mapping[str, Any]) -> tuple[bool, str]:
    if not isinstance(step, Mapping):
        return False, "Each macro step must be an object."
    kind = step.get("type")
    if kind == "key":
        return _validate_key_name(step.get("key"))
    if kind == "shortcut":
        ok, message = validate_chord({"mods": step.get("mods", []), "key": step.get("key")})
        return ok, message
    if kind == "text":
        text = step.get("text")
        if not isinstance(text, str) or not text:
            return False, "Text steps require non-empty text."
        if len(text) > MAX_TEXT_LENGTH:
            return False, f"Text steps are limited to {MAX_TEXT_LENGTH} characters."
        return True, ""
    if kind == "wait":
        ms = step.get("ms")
        if not isinstance(ms, int) or isinstance(ms, bool) or not 0 <= ms <= 60_000:
            return False, "Wait steps require an integer duration between 0 and 60000 ms."
        return True, ""
    return False, f"Unknown macro step type: {kind!r}"


def validate_output(mapping_type: str, config: Mapping[str, Any]) -> tuple[bool, str]:
    """Validate an output configuration for the given mapping type."""
    if not isinstance(config, Mapping):
        return False, "Output configuration must be an object."
    if mapping_type == "key":
        return _validate_key_name(config.get("key"))
    if mapping_type == "shortcut":
        return validate_chord({"mods": config.get("mods", []), "key": config.get("key")})
    if mapping_type == "action":
        action = config.get("action")
        if action not in WINDOWS_ACTIONS:
            return False, f"Unknown Windows action: {action!r}"
        return True, ""
    if mapping_type == "text":
        text = config.get("text")
        if not isinstance(text, str) or not text:
            return False, "Enter the text that should be typed."
        if len(text) > MAX_TEXT_LENGTH:
            return False, f"Text is limited to {MAX_TEXT_LENGTH} characters."
        return True, ""
    if mapping_type == "macro":
        steps = config.get("steps")
        if not isinstance(steps, list) or not steps:
            return False, "A macro needs at least one step."
        if len(steps) > MAX_MACRO_STEPS:
            return False, f"A macro is limited to {MAX_MACRO_STEPS} steps."
        for index, step in enumerate(steps, start=1):
            ok, message = validate_macro_step(step)
            if not ok:
                return False, f"Step {index}: {message}"
        return True, ""
    return False, f"Unknown mapping type: {mapping_type!r}"


def describe_output(mapping_type: str, config: Mapping[str, Any]) -> str:
    """Return a short human readable description used in tables and the tray."""
    if not isinstance(config, Mapping):
        return "—"
    if mapping_type == "key":
        key = config.get("key", "")
        return KEY_INFO[key].label if key in KEY_INFO else str(key)
    if mapping_type == "shortcut":
        return chord_display({"mods": config.get("mods", []), "key": config.get("key", "")})
    if mapping_type == "action":
        return WINDOWS_ACTIONS.get(str(config.get("action")), str(config.get("action")))
    if mapping_type == "text":
        text = str(config.get("text", "")).replace("\n", " ")
        return f'"{text[:42]}{"…" if len(text) > 42 else ""}"'
    if mapping_type == "macro":
        steps = config.get("steps") or []
        return f"Macro · {len(steps)} step{'s' if len(steps) != 1 else ''}"
    return "—"


def describe_macro_step(step: Mapping[str, Any]) -> str:
    kind = step.get("type")
    if kind == "key":
        key = str(step.get("key", ""))
        return KEY_INFO[key].label if key in KEY_INFO else key
    if kind == "shortcut":
        return chord_display({"mods": step.get("mods", []), "key": step.get("key", "")})
    if kind == "text":
        text = str(step.get("text", ""))
        return f'Type "{text[:30]}"'
    if kind == "wait":
        return f"Wait {step.get('ms', 0)} ms"
    return "—"


def output_modifiers(config: Mapping[str, Any]) -> list[str]:
    try:
        return normalize_mods([str(m) for m in config.get("mods", [])])
    except ValueError:
        return []


def modifier_labels_for(mods: list[str]) -> list[str]:
    return [MODIFIER_LABELS.get(m, m.upper()) for m in mods]
