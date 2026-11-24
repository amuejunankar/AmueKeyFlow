"""Conflict detection tests."""

from __future__ import annotations

from app.database.models import Mapping, new_id
from app.engine.conflict_detector import conflicts_by_mapping, find_conflicts, has_conflict
from app.engine.keycodes import chord_key


def make(mods, key, name="mapping", mapping_id=None):
    return Mapping(
        id=mapping_id or new_id(),
        profile_id="p",
        name=name,
        input_config={"mods": mods, "key": key},
        output_config={"key": "home"},
        mapping_type="key",
    )


def test_duplicate_inputs_are_detected():
    a = make(["ctrl"], "b", "Copy")
    b = make(["ctrl"], "b", "Paste")
    c = make(["ctrl"], "v", "Other")
    result = conflicts_by_mapping([a, b, c])
    assert set(result) == {a.id, b.id}
    assert result[a.id] == [b.id]


def test_family_normalisation_matches_left_and_right():
    a = make(["lctrl"], "b", "Left")
    b = make(["ctrl"], "b", "Generic")
    assert has_conflict(a, [b]) is b
    assert has_conflict(a, [a]) is None
    conflicts = find_conflicts([a, b])
    assert len(conflicts) == 1
    assert "CTRL + B" in conflicts[0].input_display


def test_unique_inputs_have_no_conflicts():
    a = make([], "capslock")
    b = make(["alt"], "tab")
    assert conflicts_by_mapping([a, b]) == {}
    assert find_conflicts([a, b]) == []


def test_chord_key_is_order_independent():
    assert chord_key({"mods": ["shift", "ctrl"], "key": "b"}) == chord_key({"mods": ["ctrl", "shift"], "key": "b"})
