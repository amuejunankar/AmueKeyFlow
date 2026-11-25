"""Per-app override tests: layering, scoping, migration and import/export."""

from __future__ import annotations

import sqlite3

import pytest

from app.constants import CONFIG_SCHEMA_VERSION
from app.database import migrations
from app.database.database import Database
from app.database.models import Mapping, new_id
from app.engine.conflict_detector import conflicts_by_mapping, has_conflict
from app.engine.keycodes import chord_key
from app.engine.mapping_processor import HookEvent, MappingProcessor, build_mapping_index
from app.services.import_export import (
    SCHEMA_ID,
    ImportValidationError,
    import_payload,
    load_payload,
    parse_overrides,
    write_export,
)


def profile_mapping(profile_id, mods, key, name="Map", output=None, mapping_type="key"):
    return Mapping(
        id=new_id(),
        profile_id=profile_id,
        name=name,
        input_config={"mods": list(mods), "key": key},
        output_config=output or {"key": "home"},
        mapping_type=mapping_type,
    )


def override_mapping(override_id, mods, key, name="Map", output=None, mapping_type="key"):
    return Mapping(
        id=new_id(),
        override_id=override_id,
        name=name,
        input_config={"mods": list(mods), "key": key},
        output_config=output or {"key": "home"},
        mapping_type=mapping_type,
    )


@pytest.fixture()
def db(tmp_path):
    database = Database(path=tmp_path / "overrides.db", backup_dir=tmp_path / "backups")
    database.connect()
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Engine layering
# ---------------------------------------------------------------------------
def _press(processor, fired, keys):
    for vk, down in keys:
        processor.handle(HookEvent(vk=vk, key_down=down))


def test_override_chord_wins_and_other_chords_fall_through():
    profile_map = profile_mapping("p", ["ctrl"], "s", "Save", {"mods": ["ctrl"], "key": "s"}, "shortcut")
    override_map = override_mapping(
        "o", ["ctrl"], "s", "Save in Figma", {"mods": ["ctrl", "shift"], "key": "s"}, "shortcut"
    )
    extra = override_mapping("o", [], "f5", "Refresh", {"mods": ["ctrl"], "key": "r"}, "shortcut")
    untouched = profile_mapping("p", [], "f9", "Profile only")

    fired: list[str] = []
    processor = MappingProcessor(on_trigger=lambda mapping, kind: fired.append(mapping.name))
    # Override mappings are indexed first, so the first match wins.
    processor.set_mappings([override_map, extra, profile_map, untouched])

    _press(processor, fired, [(0x11, True), (0x53, True), (0x53, False), (0x11, False)])
    assert fired == ["Save in Figma"]

    fired.clear()
    _press(processor, fired, [(0x74, True), (0x74, False)])  # F5
    assert fired == ["Refresh"]

    fired.clear()
    _press(processor, fired, [(0x78, True), (0x78, False)])  # F9
    assert fired == ["Profile only"]


def test_profile_index_without_override_keeps_the_profile_chord():
    profile_map = profile_mapping("p", ["ctrl"], "s", "Save")
    index, _ = build_mapping_index([profile_map])
    assert index[chord_key({"mods": ["ctrl"], "key": "s"})] is profile_map


def test_overrides_only_resolve_for_their_own_app(db):
    override = db.create_app_override("figma.exe")
    assert db.app_override_for_executable("figma.exe").id == override.id
    assert db.app_override_for_executable("C:\\Program Files\\Figma\\Figma.EXE").id == override.id
    assert db.app_override_for_executable("chrome.exe") is None


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------
def test_profile_and_override_chords_are_not_a_conflict():
    profile_map = profile_mapping("p", ["ctrl"], "s")
    override_map = override_mapping("o", ["ctrl"], "s")
    assert conflicts_by_mapping([profile_map, override_map]) == {}
    assert has_conflict(override_map, [profile_map]) is None


def test_duplicates_inside_one_override_are_still_conflicts():
    first = override_mapping("o", ["ctrl"], "s", "One")
    second = override_mapping("o", ["ctrl"], "s", "Two")
    result = conflicts_by_mapping([first, second])
    assert set(result) == {first.id, second.id}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def test_app_override_crud_cascades_to_its_mappings(db):
    override = db.create_app_override("C:\\Apps\\Figma.exe", "Figma")
    assert override.executable == "figma.exe"
    assert override.is_enabled is True
    with pytest.raises(ValueError):
        db.create_app_override("FIGMA.EXE")

    saved = db.save_mapping(override_mapping(override.id, ["ctrl"], "s"))
    assert saved.profile_id is None
    assert [m.id for m in db.list_override_mappings(override.id)] == [saved.id]
    assert db.list_app_overrides()[0].mapping_count == 1

    override.is_enabled = False
    override.name = "Figma edits"
    db.update_app_override(override)
    reloaded = db.get_app_override(override.id)
    assert reloaded.is_enabled is False
    assert reloaded.name == "Figma edits"

    db.delete_app_override(override.id)
    assert db.list_app_overrides() == []
    assert db.conn.execute("SELECT COUNT(*) FROM mappings").fetchone()[0] == 0


def test_mapping_needs_exactly_one_scope(db):
    profile = db.active_profile()
    orphan = Mapping(
        id=new_id(),
        name="Orphan",
        input_config={"mods": [], "key": "a"},
        output_config={"key": "b"},
        mapping_type="key",
    )
    with pytest.raises(ValueError):
        db.save_mapping(orphan)

    both = Mapping(
        id=new_id(),
        profile_id=profile.id,
        override_id="some-override",
        name="Both",
        input_config={"mods": [], "key": "a"},
        output_config={"key": "b"},
        mapping_type="key",
    )
    with pytest.raises(ValueError):
        db.save_mapping(both)


def test_clone_keeps_or_moves_the_scope():
    override_map = override_mapping("o", [], "f5")
    assert override_map.clone().override_id == "o"
    assert override_map.clone().profile_id is None
    moved = override_map.clone(profile_id="p")
    assert moved.override_id is None and moved.profile_id == "p"


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------
def test_migration_from_v2_preserves_data_and_allows_overrides(tmp_path):
    legacy = tmp_path / "legacy.db"
    now = "2026-01-01T00:00:00+00:00"
    connection = sqlite3.connect(legacy)
    connection.executescript(migrations.SCHEMA_V1)
    connection.executescript(migrations.SCHEMA_V2)
    connection.execute(
        "INSERT INTO profiles (id, name, description, created_at, updated_at, is_active)"
        " VALUES ('p1', 'Default', '', ?, ?, 1)",
        (now, now),
    )
    connection.execute(
        "INSERT INTO mappings (id, profile_id, name, description, input_configuration,"
        " output_configuration, mapping_type, trigger_behavior, delay, is_enabled, created_at, updated_at)"
        " VALUES ('m1', 'p1', 'Copy', '', ?, ?, 'key', 'press', 0, 1, ?, ?)",
        ('{"mods": [], "key": "a"}', '{"key": "b"}', now, now),
    )
    connection.execute(
        "INSERT INTO settings (key, value) VALUES ('theme', '\"light\"')"
    )
    connection.execute(
        "INSERT INTO app_rules (id, profile_id, executable, created_at) VALUES ('r1', 'p1', 'code.exe', ?)",
        (now,),
    )
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()

    database = Database(path=legacy, backup_dir=tmp_path / "backups")
    database.connect()
    try:
        assert database.conn.execute("PRAGMA user_version").fetchone()[0] == CONFIG_SCHEMA_VERSION
        mappings = database.list_mappings("p1")
        assert [m.id for m in mappings] == ["m1"]
        assert mappings[0].override_id is None
        assert database.all_settings()["theme"] == "light"
        assert [r.executable for r in database.list_app_rules()] == ["code.exe"]

        override = database.create_app_override("figma.exe")
        database.save_mapping(override_mapping(override.id, [], "f5"))
        assert len(database.list_override_mappings(override.id)) == 1
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------
def test_overrides_roundtrip_and_v1_files_still_import(db, tmp_path):
    profile = db.active_profile()
    db.save_mapping(profile_mapping(profile.id, [], "capslock"))
    override = db.create_app_override("figma.exe", "Figma")
    db.save_mapping(override_mapping(override.id, ["ctrl"], "s"))

    path = write_export(
        tmp_path / "export.json",
        [(profile, db.list_mappings(profile.id))],
        {profile.id: []},
        [(override, db.list_override_mappings(override.id))],
    )
    payload = load_payload(path)
    assert payload["version"] == 2
    parsed = parse_overrides(payload)
    assert [item["executable"] for item in parsed] == ["figma.exe"]
    assert parsed[0]["name"] == "Figma"

    target = Database(path=tmp_path / "target.db", backup_dir=tmp_path / "b2")
    target.connect()
    try:
        summary = import_payload(target, payload, mode="replace")
        assert summary.overrides_created == 1
        imported = target.app_override_for_executable("figma.exe")
        assert imported is not None
        assert [m.input_display for m in target.list_override_mappings(imported.id)] == ["CTRL + S"]

        legacy = {"schema": SCHEMA_ID, "version": 1, "profiles": [{"name": "Legacy", "mappings": []}]}
        assert parse_overrides(legacy) == []
        summary = import_payload(target, legacy, mode="merge")
        assert summary.profiles_created == 1
        # A version 1 import leaves existing overrides untouched.
        assert len(target.list_app_overrides()) == 1
    finally:
        target.close()


def test_invalid_override_payloads_are_rejected():
    base = {"schema": SCHEMA_ID, "version": 2, "profiles": [{"name": "Default", "mappings": []}]}

    with pytest.raises(ImportValidationError):
        parse_overrides({**base, "app_overrides": "nope"})

    with pytest.raises(ImportValidationError):
        parse_overrides({**base, "app_overrides": [{"executable": "", "mappings": []}]})

    with pytest.raises(ImportValidationError):
        parse_overrides(
            {
                **base,
                "app_overrides": [
                    {"executable": "a.exe", "mappings": []},
                    {"executable": "A.EXE", "mappings": []},
                ],
            }
        )

    with pytest.raises(ImportValidationError):
        parse_overrides(
            {
                **base,
                "app_overrides": [
                    {
                        "executable": "a.exe",
                        "mappings": [
                            {"input": {"mods": [], "key": "a"}, "output": {"key": "b"}, "type": "key"},
                            {"input": {"mods": [], "key": "a"}, "output": {"key": "c"}, "type": "key"},
                        ],
                    }
                ],
            }
        )

    with pytest.raises(ImportValidationError):
        parse_overrides(
            {
                **base,
                "app_overrides": [
                    {
                        "executable": "a.exe",
                        "mappings": [
                            {"input": {"mods": [], "key": "a"}, "output": {"action": "nope"}, "type": "action"}
                        ],
                    }
                ],
            }
        )
