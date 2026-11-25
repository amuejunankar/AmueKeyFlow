"""Application-wide constants and default configuration for Amue KeyFlow."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Amue KeyFlow"
APP_SLUG = "AmueKeyFlow"
APP_VERSION = "1.6.0"
APP_PUBLISHER = "Amue"
APP_DESCRIPTION = "Windows keyboard mapper and shortcut automation"

#: Marker placed in the ``dwExtraInfo`` field of every input this application
#: injects.  The low level hook ignores events carrying it, which is the core
#: recursion protection of the engine.
INJECTION_TAG = 0x4B464C57  # "KFLW"

CONFIG_SCHEMA_VERSION = 3

#: Keys that Windows never delivers to user-mode low level hooks.  Used only for
#: documentation/warnings inside the UI.
SECURE_SEQUENCES = "Ctrl+Alt+Del, Ctrl+Shift+Esc (when pressed on the secure desktop)"

DEFAULT_EMERGENCY_HOTKEY = {"mods": ["ctrl", "alt", "shift"], "key": "f12"}


def _default_data_dir() -> Path:
    override = os.environ.get("AMUE_KEYFLOW_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / APP_SLUG
    return Path.home() / ".amue-keyflow"


DATA_DIR = _default_data_dir()
DB_PATH = DATA_DIR / "keyflow.db"
LOG_DIR = DATA_DIR / "logs"
BACKUP_DIR = DATA_DIR / "backups"
EXPORT_DIR = DATA_DIR / "exports"
RECORDINGS_DIR = DATA_DIR / "recordings"


def _resource_dir() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "app" / "resources"
    return Path(__file__).resolve().parent / "resources"


RESOURCE_DIR = _resource_dir()

#: ``sys.frozen`` is set by PyInstaller; used by the startup manager and for
#: locating bundled resources.
IS_FROZEN = bool(getattr(sys, "frozen", False))

DEFAULT_SETTINGS: dict[str, object] = {
    # General
    "start_with_windows": False,
    "startup_behavior": "window",  # "tray" | "window"
    "minimize_to_tray": True,
    "launch_minimized": False,
    "auto_switch_profiles": True,
    "confirm_exit": False,
    "caffeine_enabled": False,
    # Appearance
    "theme": "dark",  # "dark" | "light" | "system"
    "accent": "violet",  # "violet" | "blue" | "cyan" | "magenta"
    # Keyboard engine
    "engine_enabled": True,
    "mappings_enabled": True,
    "key_repeat_policy": "block",  # "block" | "allow" | "throttle"
    "repeat_throttle_ms": 150,
    "recording_timeout_s": 8,
    "mapping_delay_ms": 0,
    "conflict_warnings": True,
    # Voice FX (all values are safe defaults: the microphone stays off)
    "voice_fx_enabled": False,
    "voice_preset": "off",
    "voice_pitch": 0,
    "voice_wet": 100,
    "voice_gain": 0.0,
    "voice_input": "",
    "voice_output": "",
    "voice_monitor": False,
    "voice_monitor_device": "",
    "voice_monitor_gain": -6.0,
    # Safety
    "emergency_hotkey_enabled": True,
    "confirm_delete": True,
    # Activity
    "activity_logging": True,
    "activity_max_entries": 1000,
    # Advanced
    "logging_level": "INFO",
    "debug_mode": False,
    # Internal
    "active_profile_id": "",
}

#: Accent palette families.  ``primary``/``secondary`` are used for gradients.
ACCENTS: dict[str, dict[str, str]] = {
    "violet": {"primary": "#7C6AF7", "secondary": "#A78BFA", "glow": "#8B7CFF"},
    "blue": {"primary": "#4D7CFE", "secondary": "#60A5FA", "glow": "#5B8CFF"},
    "cyan": {"primary": "#2DD4BF", "secondary": "#38BDF8", "glow": "#22D3EE"},
    "magenta": {"primary": "#D946EF", "secondary": "#F472B6", "glow": "#E879F9"},
}

TRIGGER_BEHAVIORS: dict[str, str] = {
    "press": "On key press",
    "release": "On key release",
    "hold": "While key is held",
    "toggle": "Toggle (latch output)",
}

MAPPING_TYPES: dict[str, str] = {
    "key": "Key",
    "shortcut": "Shortcut",
    "action": "Windows Action",
    "text": "Text",
    "macro": "Macro",
}

WINDOWS_ACTIONS: dict[str, str] = {
    "volumeup": "Volume Up",
    "volumedown": "Volume Down",
    "mute": "Mute",
    "playpause": "Play / Pause",
    "nexttrack": "Next Track",
    "prevtrack": "Previous Track",
    "lock": "Lock Workstation",
    "taskview": "Open Task View",
    "showdesktop": "Show Desktop",
}

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
