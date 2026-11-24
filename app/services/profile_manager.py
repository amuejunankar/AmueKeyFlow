"""Profile lifecycle management."""

from __future__ import annotations

import logging
from typing import Callable

from app.database.database import Database
from app.database.models import AppRule, Mapping, Profile, new_id, utc_now
from app.services.settings_manager import SettingsManager

log = logging.getLogger(__name__)


class ProfileManager:
    """Owns profile CRUD, the active profile and the notification fan-out."""

    def __init__(self, database: Database, settings: SettingsManager) -> None:
        self._db = database
        self._settings = settings
        self._listeners: list[Callable[[], None]] = []
        self._active: Profile | None = None
        self._restore_active()

    # -- state -------------------------------------------------------------
    def _restore_active(self) -> None:
        profiles = self._db.list_profiles()
        if not profiles:
            self._db.create_profile("Default", "Your starting profile")
            profiles = self._db.list_profiles()
        saved_id = str(self._settings.get("active_profile_id", "") or "")
        active = next((p for p in profiles if p.id == saved_id), None)
        if active is None:
            active = next((p for p in profiles if p.is_active), profiles[0])
        self._active = active
        self._db.set_active_profile(active.id)
        self._settings.set("active_profile_id", active.id)

    def reload(self) -> None:
        """Re-read the active profile after the database was replaced by an import."""
        self._active = None
        self._restore_active()
        self._notify()

    def add_listener(self, listener: Callable[[], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # pragma: no cover
                log.exception("Profile listener failed")

    # -- queries -----------------------------------------------------------
    def profiles(self) -> list[Profile]:
        return self._db.list_profiles()

    @property
    def active(self) -> Profile:
        if self._active is None:
            self._restore_active()
        assert self._active is not None
        return self._active

    @property
    def active_id(self) -> str:
        return self.active.id

    def mappings(self, profile_id: str | None = None) -> list[Mapping]:
        return self._db.list_mappings(profile_id or self.active_id)

    def active_mappings(self) -> list[Mapping]:
        return self._db.list_mappings(self.active_id)

    def mapping_counts(self) -> dict[str, int]:
        counts = {profile.id: 0 for profile in self.profiles()}
        for mapping in self._db.list_mappings():
            counts[mapping.profile_id] = counts.get(mapping.profile_id, 0) + 1
        return counts

    # -- app rules ---------------------------------------------------------
    def app_rules(self, profile_id: str | None = None) -> list[AppRule]:
        return self._db.list_app_rules(profile_id)

    def rule_counts(self) -> dict[str, int]:
        counts = {profile.id: 0 for profile in self.profiles()}
        for rule in self._db.list_app_rules():
            counts[rule.profile_id] = counts.get(rule.profile_id, 0) + 1
        return counts

    def add_app_rule(self, profile_id: str, executable: str) -> AppRule:
        rule = self._db.add_app_rule(profile_id, executable)
        self._notify()
        return rule

    def remove_app_rule(self, rule_id: str) -> None:
        self._db.delete_app_rule(rule_id)
        self._notify()

    def profile_for_app(self, executable: str) -> Profile | None:
        return self._db.profile_for_executable(executable)

    # -- mutations ---------------------------------------------------------
    def create(self, name: str, description: str = "") -> Profile:
        profile = self._db.create_profile(name, description)
        self._notify()
        return profile

    def duplicate(self, profile_id: str, new_name: str | None = None) -> Profile:
        source = self._db.get_profile(profile_id)
        if source is None:
            raise ValueError("Profile not found.")
        name = (new_name or f"{source.name} copy").strip()
        base = name
        counter = 2
        while self._db.get_profile_by_name(name):
            name = f"{base} {counter}"
            counter += 1
        profile = self._db.create_profile(name, source.description)
        for mapping in self._db.list_mappings(source.id):
            copy = mapping.clone(profile_id=profile.id)
            self._db.save_mapping(copy)
        self._notify()
        return profile

    def rename(self, profile_id: str, name: str, description: str | None = None) -> None:
        profile = self._db.get_profile(profile_id)
        if profile is None:
            raise ValueError("Profile not found.")
        profile.name = name
        if description is not None:
            profile.description = description
        self._db.update_profile(profile)
        if self._active and self._active.id == profile.id:
            self._active = profile
        self._notify()

    def delete(self, profile_id: str) -> None:
        if profile_id == self.active_id:
            raise ValueError("Switch to another profile before deleting this one.")
        self._db.delete_profile(profile_id)
        self._notify()

    def switch(self, profile_id: str) -> Profile:
        profile = self._db.get_profile(profile_id)
        if profile is None:
            raise ValueError("Profile not found.")
        self._db.set_active_profile(profile_id)
        self._settings.set("active_profile_id", profile_id)
        self._active = profile
        self._notify()
        return profile

    def create_from_import(self, name: str, description: str, mappings: list[Mapping]) -> Profile:
        profile = self._db.create_profile(name, description)
        for mapping in mappings:
            clone = Mapping(
                id=new_id(),
                profile_id=profile.id,
                name=mapping.name,
                description=mapping.description,
                input_config=mapping.input_config,
                output_config=mapping.output_config,
                mapping_type=mapping.mapping_type,
                trigger_behavior=mapping.trigger_behavior,
                delay=mapping.delay,
                is_enabled=mapping.is_enabled,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self._db.save_mapping(clone)
        self._notify()
        return profile
