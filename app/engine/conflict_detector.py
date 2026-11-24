"""Detection of duplicate and overlapping input mappings."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from app.database.models import Mapping
from app.engine.keycodes import chord_display, chord_key


@dataclass
class Conflict:
    input_display: str
    mapping_ids: list[str]
    names: list[str]

    @property
    def message(self) -> str:
        joined = "”, “".join(self.names)
        return f"“{joined}” all trigger on {self.input_display}."


def conflicts_by_mapping(mappings: Iterable[Mapping]) -> dict[str, list[str]]:
    """Return ``mapping_id -> conflicting mapping ids``.

    Mappings are compared on their family-normalised input, so ``CTRL+B`` and
    ``LEFT CTRL+B`` are reported as an overlap.
    """
    groups: dict[str, list[Mapping]] = defaultdict(list)
    for mapping in mappings:
        try:
            groups[chord_key(mapping.input_config, family_only=True)].append(mapping)
        except (ValueError, TypeError):
            continue
    result: dict[str, list[str]] = {}
    for items in groups.values():
        if len(items) < 2:
            continue
        ids = [m.id for m in items]
        for mapping in items:
            result[mapping.id] = [other for other in ids if other != mapping.id]
    return result


def find_conflicts(mappings: Iterable[Mapping]) -> list[Conflict]:
    groups: dict[str, list[Mapping]] = defaultdict(list)
    for mapping in mappings:
        try:
            groups[chord_key(mapping.input_config, family_only=True)].append(mapping)
        except (ValueError, TypeError):
            continue
    conflicts: list[Conflict] = []
    for items in groups.values():
        if len(items) < 2:
            continue
        conflicts.append(
            Conflict(
                input_display=chord_display(items[0].input_config),
                mapping_ids=[m.id for m in items],
                names=[m.name or chord_display(m.input_config) for m in items],
            )
        )
    return conflicts


def has_conflict(candidate: Mapping, mappings: Iterable[Mapping]) -> Mapping | None:
    target = chord_key(candidate.input_config, family_only=True)
    for mapping in mappings:
        if mapping.id == candidate.id:
            continue
        try:
            if chord_key(mapping.input_config, family_only=True) == target:
                return mapping
        except (ValueError, TypeError):
            continue
    return None
