"""Versioned JSON import/export for profiles and mappings.

Imported files are treated strictly as data: every field is validated, nothing
is evaluated, and oversized files are rejected before parsing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.constants import MAPPING_TYPES, TRIGGER_BEHAVIORS
from app.database.models import (
    AppOverride,
    AppRule,
    Mapping,
    Profile,
    new_id,
    normalize_executable,
    utc_now,
)
from app.database.database import Database
from app.engine.keycodes import chord_key, validate_chord
from app.engine.output_spec import validate_output

log = logging.getLogger(__name__)

SCHEMA_ID = "amue-keyflow-config"
SCHEMA_VERSION = 2
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_PROFILES = 64
MAX_MAPPINGS_PER_PROFILE = 500
MAX_APP_RULES_PER_PROFILE = 64
MAX_APP_OVERRIDES = 64


class ImportValidationError(ValueError):
    """Raised when an import file is malformed or unsafe."""


@dataclass
class ImportSummary:
    profiles_created: int = 0
    mappings_imported: int = 0
    mappings_skipped: int = 0
    rules_imported: int = 0
    overrides_created: int = 0
    replaced: bool = False

    @property
    def message(self) -> str:
        parts = []
        if self.replaced:
            parts.append("Configuration replaced.")
        parts.append(f"{self.profiles_created} profile(s) imported")
        parts.append(f"{self.mappings_imported} mapping(s) imported")
        if self.rules_imported:
            parts.append(f"{self.rules_imported} app rule(s) imported")
        if self.overrides_created:
            parts.append(f"{self.overrides_created} app override(s) imported")
        if self.mappings_skipped:
            parts.append(f"{self.mappings_skipped} duplicate(s) skipped")
        return ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------
def mapping_to_payload(mapping: Mapping) -> dict[str, Any]:
    return {
        "name": mapping.name,
        "description": mapping.description,
        "input": mapping.input_config,
        "output": mapping.output_config,
        "type": mapping.mapping_type,
        "trigger": mapping.trigger_behavior,
        "delay": mapping.delay,
        "enabled": mapping.is_enabled,
    }


def profile_to_payload(
    profile: Profile,
    mappings: list[Mapping],
    app_rules: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": profile.name,
        "description": profile.description,
        "app_rules": list(app_rules or []),
        "mappings": [mapping_to_payload(m) for m in mappings],
    }


def override_to_payload(override: AppOverride, mappings: list[Mapping]) -> dict[str, Any]:
    return {
        "name": override.name or override.executable,
        "executable": override.executable,
        "enabled": override.is_enabled,
        "mappings": [mapping_to_payload(m) for m in mappings],
    }


def build_payload(
    entries: list[tuple[Profile, list[Mapping]]],
    rules_by_profile: dict[str, list[str]] | None = None,
    overrides: list[tuple[AppOverride, list[Mapping]]] | None = None,
) -> dict[str, Any]:
    rules_by_profile = rules_by_profile or {}
    return {
        "app": "Amue KeyFlow",
        "schema": SCHEMA_ID,
        "version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profiles": [
            profile_to_payload(profile, mappings, rules_by_profile.get(profile.id))
            for profile, mappings in entries
        ],
        "app_overrides": [override_to_payload(override, mappings) for override, mappings in (overrides or [])],
    }


def write_export(
    path: str | Path,
    entries: list[tuple[Profile, list[Mapping]]],
    rules_by_profile: dict[str, list[str]] | None = None,
    overrides: list[tuple[AppOverride, list[Mapping]]] | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(entries, rules_by_profile, overrides)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _require_str(value: Any, field: str, max_len: int = 200) -> str:
    if not isinstance(value, str):
        raise ImportValidationError(f"{field} must be a string.")
    value = value.strip()
    if len(value) > max_len:
        raise ImportValidationError(f"{field} is too long (max {max_len} characters).")
    return value


def _parse_mapping(
    data: Any, profile_id: str | None, index: int, override_id: str | None = None
) -> Mapping:
    if not isinstance(data, dict):
        raise ImportValidationError(f"Mapping {index}: expected an object.")
    name = _require_str(data.get("name", ""), f"Mapping {index}: name")
    description = _require_str(data.get("description", ""), f"Mapping {index}: description", 1000)
    mapping_type = data.get("type")
    if mapping_type not in MAPPING_TYPES:
        raise ImportValidationError(f"Mapping {index}: unknown type {mapping_type!r}.")
    trigger = data.get("trigger", "press")
    if trigger not in TRIGGER_BEHAVIORS:
        raise ImportValidationError(f"Mapping {index}: unknown trigger behaviour {trigger!r}.")
    input_config = data.get("input")
    ok, message = validate_chord(input_config)
    if not ok:
        raise ImportValidationError(f"Mapping {index}: {message}")
    output_config = data.get("output")
    ok, message = validate_output(mapping_type, output_config)
    if not ok:
        raise ImportValidationError(f"Mapping {index}: {message}")
    delay = data.get("delay", 0)
    if not isinstance(delay, int) or isinstance(delay, bool) or not 0 <= delay <= 60_000:
        raise ImportValidationError(f"Mapping {index}: delay must be 0-60000 ms.")
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ImportValidationError(f"Mapping {index}: enabled must be true or false.")
    now = utc_now()
    return Mapping(
        id=new_id(),
        profile_id=None if override_id else profile_id,
        override_id=override_id,
        name=name or _default_name(input_config),
        description=description,
        input_config=dict(input_config),
        output_config=dict(output_config),
        mapping_type=mapping_type,
        trigger_behavior=trigger,
        delay=delay,
        is_enabled=enabled,
        created_at=now,
        updated_at=now,
    )


def _default_name(input_config: dict) -> str:
    from app.engine.keycodes import chord_display

    return f"{chord_display(input_config)} mapping"


def _validate_header(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ImportValidationError("The file must contain a JSON object.")
    if payload.get("schema") != SCHEMA_ID:
        raise ImportValidationError("This is not an Amue KeyFlow configuration file.")
    version = payload.get("version")
    if not isinstance(version, int) or version < 1:
        raise ImportValidationError("Missing or invalid configuration version.")
    if version > SCHEMA_VERSION:
        raise ImportValidationError(
            f"This file uses configuration version {version}; this build supports up to {SCHEMA_VERSION}."
        )


def parse_overrides(payload: Any) -> list[dict[str, Any]]:
    """Validate the optional per-app overrides of a payload.

    Version 1 files have no overrides, so a missing key means “none”.
    """
    _validate_header(payload)
    raw = payload.get("app_overrides", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ImportValidationError("app_overrides must be a list.")
    if len(raw) > MAX_APP_OVERRIDES:
        raise ImportValidationError(f"Too many app overrides (max {MAX_APP_OVERRIDES}).")
    overrides: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ImportValidationError(f"App override {index}: expected an object.")
        try:
            executable = normalize_executable(item.get("executable", ""))
        except (TypeError, ValueError) as exc:
            raise ImportValidationError(f"App override {index}: {exc}") from exc
        if executable in seen:
            raise ImportValidationError(f"App override {index}: “{executable}” appears twice.")
        seen.add(executable)
        name = _require_str(item.get("name", "") or executable, f"App override {index}: name", 80)
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ImportValidationError(f"App override {index}: enabled must be true or false.")
        mappings = item.get("mappings", [])
        if not isinstance(mappings, list):
            raise ImportValidationError(f"App override {index}: mappings must be a list.")
        if len(mappings) > MAX_MAPPINGS_PER_PROFILE:
            raise ImportValidationError(f"App override {index}: too many mappings.")
        seen_inputs: set[str] = set()
        for m_index, mapping in enumerate(mappings, start=1):
            if not isinstance(mapping, dict):
                raise ImportValidationError(
                    f"App override “{executable}” mapping {m_index}: expected an object."
                )
            try:
                _parse_mapping(mapping, None, m_index, override_id="validation")
            except ImportValidationError as exc:
                raise ImportValidationError(f"App override “{executable}”: {exc}") from exc
            key = chord_key(mapping["input"], family_only=True)
            if key in seen_inputs:
                raise ImportValidationError(
                    f"App override “{executable}” contains two mappings for the same input."
                )
            seen_inputs.add(key)
        overrides.append(
            {"name": name, "executable": executable, "enabled": enabled, "mappings": list(mappings)}
        )
    return overrides


def parse_payload(payload: Any) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Validate a payload, returning raw ``(profile, mappings)`` dict pairs."""
    _validate_header(payload)
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ImportValidationError("The file does not contain any profiles.")
    if len(profiles) > MAX_PROFILES:
        raise ImportValidationError(f"Too many profiles (max {MAX_PROFILES}).")

    parsed: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    seen_names: set[str] = set()
    seen_apps: set[str] = set()
    for p_index, profile in enumerate(profiles, start=1):
        if not isinstance(profile, dict):
            raise ImportValidationError(f"Profile {p_index}: expected an object.")
        name = _require_str(profile.get("name", ""), f"Profile {p_index}: name", 80)
        if not name:
            raise ImportValidationError(f"Profile {p_index}: name cannot be empty.")
        if name.lower() in seen_names:
            raise ImportValidationError(f"Profile {p_index}: duplicate profile name “{name}”.")
        seen_names.add(name.lower())
        description = _require_str(profile.get("description", ""), f"Profile {p_index}: description", 500)
        raw_apps = profile.get("app_rules", [])
        if raw_apps is None:
            raw_apps = []
        if not isinstance(raw_apps, list):
            raise ImportValidationError(f"Profile {p_index}: app_rules must be a list.")
        if len(raw_apps) > MAX_APP_RULES_PER_PROFILE:
            raise ImportValidationError(
                f"Profile {p_index}: too many app rules (max {MAX_APP_RULES_PER_PROFILE})."
            )
        app_rules: list[str] = []
        for item in raw_apps:
            try:
                executable = normalize_executable(item)
            except (TypeError, ValueError) as exc:
                raise ImportValidationError(f"Profile “{name}”: {exc}") from exc
            if executable in seen_apps:
                continue
            seen_apps.add(executable)
            app_rules.append(executable)
        mappings = profile.get("mappings", [])
        if not isinstance(mappings, list):
            raise ImportValidationError(f"Profile {p_index}: mappings must be a list.")
        if len(mappings) > MAX_MAPPINGS_PER_PROFILE:
            raise ImportValidationError(f"Profile {p_index}: too many mappings.")
        seen_inputs: set[str] = set()
        for m_index, item in enumerate(mappings, start=1):
            if not isinstance(item, dict):
                raise ImportValidationError(f"Profile {p_index} mapping {m_index}: expected an object.")
            try:
                # Full validation (trigger, type, output, delay) before anything is stored.
                _parse_mapping(item, "validation", m_index)
            except ImportValidationError as exc:
                raise ImportValidationError(f"Profile “{name}”: {exc}") from exc
            key = chord_key(item["input"], family_only=True)
            if key in seen_inputs:
                raise ImportValidationError(
                    f"Profile “{name}” contains two mappings for the same input."
                )
            seen_inputs.add(key)
        parsed.append(
            ({"name": name, "description": description, "app_rules": app_rules}, list(mappings))
        )
    return parsed


def load_payload(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ImportValidationError("The selected file does not exist.")
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ImportValidationError("The file is too large to be a KeyFlow configuration (max 2 MB).")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ImportValidationError("The file is not valid UTF-8 text.") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImportValidationError(f"The file is not valid JSON (line {exc.lineno}).") from exc
    return payload


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def import_payload(
    database: Database,
    payload: dict[str, Any],
    mode: str = "merge",
) -> ImportSummary:
    """Import validated data, either replacing everything or merging by profile."""
    parsed = parse_payload(payload)
    parsed_overrides = parse_overrides(payload)
    summary = ImportSummary()

    if mode not in {"merge", "replace"}:
        raise ImportValidationError("Unknown import mode.")

    if mode == "replace":
        profiles: list[Profile] = []
        mappings: list[Mapping] = []
        app_rules: list[AppRule] = []
        now = utc_now()
        for index, (profile_data, raw_mappings) in enumerate(parsed):
            profile = Profile(
                id=new_id(),
                name=profile_data["name"],
                description=profile_data["description"],
                created_at=now,
                updated_at=now,
                is_active=index == 0,
            )
            profiles.append(profile)
            for executable in profile_data.get("app_rules", []):
                app_rules.append(
                    AppRule(id=new_id(), profile_id=profile.id, executable=executable, created_at=now)
                )
            for m_index, item in enumerate(raw_mappings, start=1):
                mappings.append(_parse_mapping(item, profile.id, m_index))
        overrides: list[AppOverride] = []
        for spec in parsed_overrides:
            override = AppOverride(
                id=new_id(),
                executable=spec["executable"],
                name=spec["name"],
                is_enabled=spec["enabled"],
                created_at=now,
                updated_at=now,
            )
            overrides.append(override)
            for m_index, item in enumerate(spec["mappings"], start=1):
                mappings.append(_parse_mapping(item, None, m_index, override_id=override.id))
        summary.profiles_created = len(profiles)
        summary.mappings_imported = len(mappings)
        summary.rules_imported = len(app_rules)
        summary.overrides_created = len(overrides)
        summary.replaced = True
        database.replace_all(profiles, mappings, profiles[0].id, app_rules, overrides)
        return summary

    now = utc_now()
    for profile_data, raw_mappings in parsed:
        existing = database.get_profile_by_name(profile_data["name"])
        if existing is None:
            profile = Profile(
                id=new_id(),
                name=profile_data["name"],
                description=profile_data["description"],
                created_at=now,
                updated_at=now,
            )
            with database._lock:  # single insert, keeps the unique name check atomic
                database.conn.execute(
                    "INSERT INTO profiles (id, name, description, created_at, updated_at, is_active)"
                    " VALUES (?, ?, ?, ?, ?, 0)",
                    (profile.id, profile.name, profile.description, profile.created_at, profile.updated_at),
                )
                database.conn.commit()
            summary.profiles_created += 1
        else:
            profile = existing

        existing_inputs = {
            chord_key(m.input_config, family_only=True) for m in database.list_mappings(profile.id)
        }
        for index, item in enumerate(raw_mappings, start=1):
            candidate = _parse_mapping(item, profile.id, index)
            key = chord_key(candidate.input_config, family_only=True)
            if key in existing_inputs:
                summary.mappings_skipped += 1
                continue
            existing_inputs.add(key)
            database.save_mapping(candidate)
            summary.mappings_imported += 1

        for executable in profile_data.get("app_rules", []):
            try:
                database.add_app_rule(profile.id, executable)
            except ValueError:
                continue
            summary.rules_imported += 1

    for spec in parsed_overrides:
        override = database.app_override_for_executable(spec["executable"])
        if override is None:
            try:
                override = database.create_app_override(spec["executable"], spec["name"])
            except ValueError:
                override = database.app_override_for_executable(spec["executable"])
            if override is None:
                continue
            summary.overrides_created += 1
        if not spec["enabled"] and override.is_enabled:
            override.is_enabled = False
            database.update_app_override(override)
        existing_inputs = {
            chord_key(m.input_config, family_only=True)
            for m in database.list_override_mappings(override.id)
        }
        for index, item in enumerate(spec["mappings"], start=1):
            candidate = _parse_mapping(item, None, index, override_id=override.id)
            key = chord_key(candidate.input_config, family_only=True)
            if key in existing_inputs:
                summary.mappings_skipped += 1
                continue
            existing_inputs.add(key)
            database.save_mapping(candidate)
            summary.mappings_imported += 1

    return summary
