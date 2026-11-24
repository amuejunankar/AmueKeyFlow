"""Dataclasses describing persisted entities."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from app.engine.keycodes import chord_display
from app.engine.output_spec import describe_output


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Profile:
    id: str
    name: str
    description: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    is_active: bool = False
    mapping_count: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Profile":
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_active=bool(row["is_active"]),
            mapping_count=int(row["mapping_count"]) if "mapping_count" in row.keys() else 0,
        )


@dataclass
class Mapping:
    id: str
    profile_id: str
    name: str
    input_config: dict[str, Any]
    output_config: dict[str, Any]
    mapping_type: str
    description: str = ""
    trigger_behavior: str = "press"
    delay: int = 0
    is_enabled: bool = True
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @property
    def input_display(self) -> str:
        return chord_display(self.input_config)

    @property
    def output_display(self) -> str:
        return describe_output(self.mapping_type, self.output_config)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "name": self.name,
            "description": self.description,
            "input_configuration": json.dumps(self.input_config, separators=(",", ":")),
            "output_configuration": json.dumps(self.output_config, separators=(",", ":")),
            "mapping_type": self.mapping_type,
            "trigger_behavior": self.trigger_behavior,
            "delay": int(self.delay),
            "is_enabled": 1 if self.is_enabled else 0,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Mapping":
        return cls(
            id=row["id"],
            profile_id=row["profile_id"],
            name=row["name"] or "",
            description=row["description"] or "",
            input_config=json.loads(row["input_configuration"]),
            output_config=json.loads(row["output_configuration"]),
            mapping_type=row["mapping_type"],
            trigger_behavior=row["trigger_behavior"] or "press",
            delay=int(row["delay"] or 0),
            is_enabled=bool(row["is_enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def clone(self, profile_id: str | None = None) -> "Mapping":
        now = utc_now()
        return Mapping(
            id=new_id(),
            profile_id=profile_id or self.profile_id,
            name=self.name,
            description=self.description,
            input_config=json.loads(json.dumps(self.input_config)),
            output_config=json.loads(json.dumps(self.output_config)),
            mapping_type=self.mapping_type,
            trigger_behavior=self.trigger_behavior,
            delay=self.delay,
            is_enabled=self.is_enabled,
            created_at=now,
            updated_at=now,
        )


@dataclass
class AppRule:
    """Binds one executable to the profile it should activate."""

    id: str
    profile_id: str
    executable: str
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "AppRule":
        return cls(
            id=row["id"],
            profile_id=row["profile_id"],
            executable=row["executable"],
            created_at=row["created_at"],
        )


def normalize_executable(value: str) -> str:
    """Return a canonical ``app.exe`` name for an executable path, name or title."""
    name = str(value or "").strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not name:
        raise ValueError("Choose an application.")
    if not name.endswith(".exe"):
        name += ".exe"
    if not re.fullmatch(r"[a-z0-9][a-z0-9 ._+\-()]{0,118}\.exe", name):
        raise ValueError(f"“{value}” is not a valid Windows application name.")
    return name


@dataclass
class ActivityEntry:
    id: int
    mapping_id: str
    mapping_name: str
    input_text: str
    output_text: str
    profile_id: str
    timestamp: str
    status: str
    detail: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ActivityEntry":
        return cls(
            id=int(row["id"]),
            mapping_id=row["mapping_id"] or "",
            mapping_name=row["mapping_name"] or "",
            input_text=row["input_text"] or "",
            output_text=row["output_text"] or "",
            profile_id=row["profile_id"] or "",
            timestamp=row["timestamp"],
            status=row["status"],
            detail=row["detail"] or "",
        )
