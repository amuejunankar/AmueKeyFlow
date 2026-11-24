"""Database, settings, migration and import/export tests."""

from __future__ import annotations

import json

import pytest

from app.constants import CONFIG_SCHEMA_VERSION
from app.database.database import Database
from app.database.models import Mapping, new_id
from app.engine.keycodes import chord_display
from app.engine.output_spec import validate_output
from app.services.import_export import (
    SCHEMA_ID,
    ImportValidationError,
    build_payload,
    import_payload,
    load_payload,
    parse_payload,
    write_export,
)
from app.services.settings_manager import SettingsManager


@pytest.fixture()
def db(tmp_path):
    database = Database(path=tmp_path / "config.db", backup_dir=tmp_path / "backups")
    database.connect()
    yield database
    database.close()


def make_mapping(profile_id, mods=(), key="capslock", output=None, mapping_type="key", name="Map"):
    return Mapping(
        id=new_id(),
        profile_id=profile_id,
        name=name,
        input_config={"mods": list(mods), "key": key},
        output_config=output or {"key": "home"},
        mapping_type=mapping_type,
    )


def test_shortcut_output_allows_no_modifiers():
    ok, message = validate_output("shortcut", {"mods": [], "key": "pageup"})
    assert ok, message
    ok, message = validate_output("macro", {"steps": [{"type": "shortcut", "mods": [], "key": "f13"}]})
    assert ok, message


def test_schema_version_is_current(db):
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == CONFIG_SCHEMA_VERSION


def test_settings_defaults_and_persistence(tmp_path):
    database = Database(path=tmp_path / "s.db", backup_dir=tmp_path / "b")
    database.connect()
    settings = SettingsManager(database)
    assert settings.get_bool("minimize_to_tray") is True
    assert settings.get_bool("start_with_windows") is False
    settings.set("theme", "light")
    settings.set("mapping_delay_ms", 120)
    database.close()

    reopened = Database(path=tmp_path / "s.db", backup_dir=tmp_path / "b")
    reopened.connect()
    again = SettingsManager(reopened)
    assert again.get("theme") == "light"
    assert again.get_int("mapping_delay_ms") == 120
    again.reset()
    assert again.get("theme") == "dark"
    reopened.close()


def test_settings_listener_fires(db):
    settings = SettingsManager(db)
    seen = []
    settings.add_listener(lambda key, value: seen.append((key, value)))
    settings.set("accent", "cyan")
    assert ("accent", "cyan") in seen


def test_export_and_import_roundtrip(db, tmp_path):
    profile = db.active_profile()
    db.save_mapping(make_mapping(profile.id, ["ctrl"], "b", {"mods": ["ctrl"], "key": "c"}, "shortcut", "Copy"))
    path = write_export(tmp_path / "export.json", [(profile, db.list_mappings(profile.id))])
    payload = load_payload(path)
    parsed = parse_payload(payload)
    assert parsed[0][0]["name"] == profile.name
    assert len(parsed[0][1]) == 1

    target = Database(path=tmp_path / "target.db", backup_dir=tmp_path / "b2")
    target.connect()
    summary = import_payload(target, payload, mode="replace")
    assert summary.mappings_imported == 1
    imported = target.list_mappings(target.active_profile().id)
    assert imported[0].name == "Copy"
    assert imported[0].output_config == {"mods": ["ctrl"], "key": "c"}
    target.close()


def test_export_and_import_roundtrip_includes_app_rules(db, tmp_path):
    profile = db.active_profile()
    db.add_app_rule(profile.id, "code.exe")
    rules = {profile.id: [rule.executable for rule in db.list_app_rules(profile.id)]}
    path = write_export(tmp_path / "rules.json", [(profile, [])], rules)
    payload = load_payload(path)
    assert parse_payload(payload)[0][0]["app_rules"] == ["code.exe"]

    target = Database(path=tmp_path / "target-rules.db", backup_dir=tmp_path / "b3")
    target.connect()
    try:
        summary = import_payload(target, payload, mode="replace")
        assert summary.rules_imported == 1
        assert [r.executable for r in target.list_app_rules()] == ["code.exe"]
    finally:
        target.close()


def test_merge_skips_duplicate_inputs(db):
    profile = db.active_profile()
    db.save_mapping(make_mapping(profile.id, [], "capslock"))
    payload = build_payload([(profile, db.list_mappings(profile.id))])
    summary = import_payload(db, payload, mode="merge")
    assert summary.mappings_skipped == 1
    assert summary.mappings_imported == 0


def test_malformed_files_are_rejected(db, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ImportValidationError):
        load_payload(bad)

    with pytest.raises(ImportValidationError):
        parse_payload({"schema": "other-app", "version": 1, "profiles": []})

    with pytest.raises(ImportValidationError):
        parse_payload({"schema": SCHEMA_ID, "version": 99, "profiles": [{"name": "x", "mappings": []}]})

    duplicate_inputs = {
        "schema": SCHEMA_ID,
        "version": 1,
        "profiles": [
            {
                "name": "Dup",
                "mappings": [
                    {"input": {"mods": [], "key": "a"}, "output": {"key": "b"}, "type": "key"},
                    {"input": {"mods": [], "key": "a"}, "output": {"key": "c"}, "type": "key"},
                ],
            }
        ],
    }
    with pytest.raises(ImportValidationError):
        parse_payload(duplicate_inputs)

    invalid_key = {
        "schema": SCHEMA_ID,
        "version": 1,
        "profiles": [
            {
                "name": "Bad",
                "mappings": [{"input": {"mods": [], "key": "not-a-key"}, "output": {"key": "b"}, "type": "key"}],
            }
        ],
    }
    with pytest.raises(ImportValidationError):
        parse_payload(invalid_key)


def test_oversized_files_are_rejected(tmp_path):
    path = tmp_path / "huge.json"
    path.write_text(json.dumps({"schema": SCHEMA_ID, "version": 1, "profiles": [], "pad": "x" * 3_000_000}))
    with pytest.raises(ImportValidationError):
        load_payload(path)


def test_invalid_outputs_are_rejected():
    payload = {
        "schema": SCHEMA_ID,
        "version": 1,
        "profiles": [
            {
                "name": "Bad output",
                "mappings": [
                    {"input": {"mods": [], "key": "a"}, "output": {"action": "format-disk"}, "type": "action"}
                ],
            }
        ],
    }
    with pytest.raises(ImportValidationError):
        parse_payload(payload)


def test_activity_logging_and_pruning(db):
    settings = SettingsManager(db)
    from app.services.activity_logger import ActivityLogger

    logger = ActivityLogger(db, settings)
    profile = db.active_profile()
    mapping = db.save_mapping(make_mapping(profile.id))
    logger.log(mapping, "success")
    logger.log(mapping, "error", "injection blocked")
    entries = logger.entries()
    assert len(entries) == 2
    assert entries[0].status == "error"
    db.clear_activity()
    assert logger.entries() == []


def test_chord_display_formatting():
    assert chord_display({"mods": ["ctrl", "shift"], "key": "b"}) == "CTRL + SHIFT + B"
    assert chord_display({"mods": [], "key": "pageup"}) == "PAGE UP"
