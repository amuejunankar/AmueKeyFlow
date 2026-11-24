"""Profile persistence and switching tests."""

from __future__ import annotations

import sqlite3

import pytest

from app.database import migrations
from app.database.database import Database
from app.database.models import Mapping, new_id, normalize_executable
from app.services.profile_manager import ProfileManager
from app.services.settings_manager import SettingsManager


@pytest.fixture()
def env(tmp_path):
    db = Database(path=tmp_path / "test.db", backup_dir=tmp_path / "backups")
    db.connect()
    settings = SettingsManager(db)
    manager = ProfileManager(db, settings)
    yield db, settings, manager
    db.close()


def add_mapping(db, profile_id, key="capslock"):
    mapping = Mapping(
        id=new_id(),
        profile_id=profile_id,
        name=f"{key} mapping",
        input_config={"mods": [], "key": key},
        output_config={"key": "home"},
        mapping_type="key",
    )
    return db.save_mapping(mapping)


def test_default_profile_is_created(env):
    _, _, manager = env
    profiles = manager.profiles()
    assert len(profiles) == 1
    assert profiles[0].name == "Default"
    assert manager.active.name == "Default"


def test_create_and_switch_profile(env):
    db, settings, manager = env
    profile = manager.create("Gaming", "For games")
    assert manager.active.name == "Default"
    manager.switch(profile.id)
    assert manager.active.id == profile.id
    assert settings.get("active_profile_id") == profile.id
    # Persisted state is restored by a new manager instance.
    reloaded = ProfileManager(db, settings)
    assert reloaded.active.id == profile.id


def test_duplicate_profile_copies_mappings(env):
    db, _, manager = env
    source = manager.active
    add_mapping(db, source.id, "capslock")
    add_mapping(db, source.id, "pageup")
    copy = manager.duplicate(source.id)
    assert copy.name != source.name
    assert len(db.list_mappings(copy.id)) == 2
    assert len({m.id for m in db.list_mappings(copy.id)}) == 2


def test_delete_profile_rules(env):
    db, _, manager = env
    extra = manager.create("Productivity")
    manager.delete(extra.id)
    assert manager.profiles()[0].name == "Default"
    with pytest.raises(ValueError):
        manager.delete(manager.active_id)


def test_rename_rejects_duplicate_names(env):
    _, _, manager = env
    manager.create("Gaming")
    productivity = manager.create("Productivity")
    with pytest.raises(ValueError):
        manager.rename(productivity.id, "gaming")


def test_profile_scoped_mappings(env):
    db, _, manager = env
    first = manager.active
    second = manager.create("Gaming")
    add_mapping(db, first.id, "capslock")
    add_mapping(db, second.id, "pageup")
    add_mapping(db, second.id, "pagedown")
    assert len(manager.active_mappings()) == 1
    manager.switch(second.id)
    assert len(manager.active_mappings()) == 2
    counts = manager.mapping_counts()
    assert counts[second.id] == 2


def test_app_rules_route_to_profiles(env):
    _, _, manager = env
    browsing = manager.create("Browsing")
    manager.add_app_rule(browsing.id, "Chrome.exe")
    assert manager.profile_for_app("chrome.EXE") == browsing
    assert manager.profile_for_app("path/to/chrome.exe").id == browsing.id
    assert manager.profile_for_app("notepad.exe") is None
    assert manager.rule_counts()[browsing.id] == 1
    with pytest.raises(ValueError):
        manager.add_app_rule(manager.active_id, "chrome.exe")
    rule = manager.app_rules(browsing.id)[0]
    manager.remove_app_rule(rule.id)
    assert manager.profile_for_app("chrome.exe") is None


def test_app_rules_are_validated(env):
    _, _, manager = env
    with pytest.raises(ValueError):
        manager.add_app_rule(manager.active_id, "")
    with pytest.raises(ValueError):
        normalize_executable("bad|name")
    assert normalize_executable(" C:\\Apps\\Game.EXE ") == "game.exe"


def test_deleting_profile_removes_app_rules(env):
    db, _, manager = env
    gaming = manager.create("Gaming")
    manager.add_app_rule(gaming.id, "steam.exe")
    manager.delete(gaming.id)
    assert db.list_app_rules(gaming.id) == []


def test_migration_from_v1_keeps_existing_data(tmp_path):
    path = tmp_path / "v1.db"
    con = sqlite3.connect(path)
    con.executescript(migrations.SCHEMA_V1)
    con.execute("PRAGMA user_version = 1")
    con.execute(
        "INSERT INTO profiles (id, name, description, created_at, updated_at, is_active)"
        " VALUES ('p1', 'Work', 'existing', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1)"
    )
    con.execute(
        "INSERT INTO mappings (id, profile_id, name, description, input_configuration,"
        " output_configuration, mapping_type, trigger_behavior, delay, is_enabled, created_at, updated_at)"
        " VALUES ('m1', 'p1', 'Copy', '', '{\"mods\": [], \"key\": \"f14\"}',"
        " '{\"mods\": [\"ctrl\"], \"key\": \"c\"}', 'shortcut', 'press', 0, 1,"
        " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    con.commit()
    con.close()

    db = Database(path=path, backup_dir=tmp_path / "backups")
    db.connect()
    try:
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.list_profiles()[0].name == "Work"
        stored = db.list_mappings("p1")
        assert len(stored) == 1 and stored[0].name == "Copy"
        assert stored[0].output_config == {"mods": ["ctrl"], "key": "c"}
        assert db.list_app_rules() == []
    finally:
        db.close()


def test_mapping_updates_persist(env):
    db, _, manager = env
    mapping = add_mapping(db, manager.active_id)
    mapping.output_config = {"key": "end"}
    mapping.is_enabled = False
    db.save_mapping(mapping)
    stored = db.get_mapping(mapping.id)
    assert stored.output_config["key"] == "end"
    assert stored.is_enabled is False
